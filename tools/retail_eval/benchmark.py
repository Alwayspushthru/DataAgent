"""Build fixed questions and independent, source-derived answer oracle.

Agent input is only public.question and public.answer_schema. Never inject private
answers, required rules, metric IDs or mutation probes into retrieval/context.
"""
import argparse
import calendar
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from knowledge import ROOT, CONTRACT, load_contract
from pipeline import canonical, command, file_sha256, unescape
from validate_knowledge import reference, read_lines

OUT=ROOT/'benchmark'
PROJECT=ROOT.parent.parent
DB='retail_eval_v1'
VALID='is_cancelled=0 AND quantity>0 AND unit_price>0'
KNOWN="customer_id IS NOT NULL AND TRIM(customer_id)<>''"
CATEGORIES={'scope':'业务范围与取消口径','denominator':'指标分母与比率',
            'time':'时间边界与月度比较','grain':'去重与分组粒度','basic':'基础查询控制组'}
_REFERENCES={}
_ANSWERS={}
_CACHE_PATH=None
_CACHE_META=None

def month(index):
    return datetime(2010+index//12,index%12+1,1)

def fmt(d):return d.strftime('%Y-%m-%d %H:%M:%S')
def literal(s):return "'"+s.replace("'","''")+"'"
def decimal_text(v):
    if v is None:return None
    return format(Decimal(str(v)),'f')

def prepare_source(work,dbfile):
    c=load_contract(); manifest=json.loads((work/'manifest.json').read_text())
    if manifest['canonical_sha256']!=c['snapshot_canonical_sha256']:raise ValueError('Wrong source snapshot')
    existing=dbfile.exists()
    db=sqlite3.connect('file:'+str(dbfile)+'?mode=ro',uri=True) if existing else sqlite3.connect(dbfile)
    if not existing:db.executescript('''CREATE TABLE transaction_lines(line_id INTEGER,invoice_no TEXT,stock_code TEXT,
    description TEXT,quantity INTEGER,invoice_date TEXT,unit_price INTEGER,customer_id TEXT,
    country TEXT,is_cancelled INTEGER,line_amount INTEGER);''')
    old=db.execute('SELECT * FROM transaction_lines ORDER BY line_id') if existing else None
    h=hashlib.sha256();batch=[];count=0
    for r in read_lines(work/'lines.tsv'):
        h.update(canonical(r).encode());count+=1
        row=(int(r[0]),r[3],r[4],r[5],int(r[6]),r[7],int(Decimal(r[8])*1000000),
                      r[9],r[10],int(r[11]),int(Decimal(r[12])*1000000))
        if existing:
            if next(old,None)!=row:raise ValueError('Cached source differs from verified TSV')
            continue
        batch.append(row)
        if len(batch)>=5000:
            db.executemany('INSERT INTO transaction_lines VALUES (?,?,?,?,?,?,?,?,?,?,?)',batch);batch=[]
    if batch:db.executemany('INSERT INTO transaction_lines VALUES (?,?,?,?,?,?,?,?,?,?,?)',batch)
    if h.hexdigest()!=c['snapshot_canonical_sha256']:raise ValueError('Source TSV digest mismatch')
    if existing:
        if next(old,None) is not None:raise ValueError('Extra cached source rows')
    else:
        db.execute('CREATE INDEX period_idx ON transaction_lines(invoice_date)')
        db.commit()
    return db,count

def expr_sql(metric,valid=VALID,known=KNOWN,source=False):
    # SQL implementation and Python reference() are separate oracles. Source-side
    # grouping uses integer micro-GBP and Python Decimal, never float SQL division.
    v=valid;k=known
    expressions={
    'M01':'COUNT(*)','M02':'SUM(line_amount)',
    'M03':f'COUNT(CASE WHEN {v} THEN 1 END)',
    'M04':f'SUM(CASE WHEN {v} THEN line_amount END)',
    'M05':f'SUM(CASE WHEN {v} THEN quantity END)',
    'M06':f'COUNT(DISTINCT CASE WHEN {v} THEN invoice_no END)',
    'M07':f'COUNT(DISTINCT CASE WHEN {v} AND {k} THEN customer_id END)',
    'M08':f'SUM(CASE WHEN {v} AND {k} THEN line_amount END)',
    'M13':f'COUNT(DISTINCT CASE WHEN {v} THEN stock_code END)',
    'M15':'COUNT(DISTINCT CASE WHEN is_cancelled=1 THEN invoice_no END)',
    'M16':'SUM(CASE WHEN is_cancelled=1 THEN line_amount END)',
    'M17':f'SUM(CASE WHEN {v} AND NOT ({k}) THEN line_amount END)',
    'B_COUNTRY':'COUNT(DISTINCT country)','B_QUANTITY':'SUM(quantity)',
    'B_SKU':'COUNT(DISTINCT stock_code)',
    }
    def ratio(a,b):return f'({a})/NULLIF(({b}),0)'
    for target,a,b in [('M09','M04','M06'),('M10','M08','M07'),('M14','M04','M05')]:
        expressions[target]=ratio(expressions[a],expressions[b])
    expressions['M18']=ratio('COALESCE('+expressions['M08']+',0)',expressions['M04'])
    if metric=='M11' or metric=='M12':
        repeats=f'(SELECT COUNT(*) FROM (SELECT customer_id FROM p WHERE {v} AND {k} GROUP BY customer_id HAVING COUNT(DISTINCT invoice_no)>=2) z)'
        return 'COALESCE(MAX('+repeats+'),0)' if metric=='M11' else ratio('CAST('+repeats+' AS DECIMAL(30,12))',expressions['M07'])
    return expressions[metric]

def where(spec,ignore_time=False):
    terms=[] if ignore_time else [f"invoice_date>={literal(spec['start'])}",f"invoice_date<{literal(spec['end'])}"]
    if spec.get('country'):terms.append('country='+literal(spec['country']))
    return ' AND '.join(terms) or '1=1'

def target_sql(spec):
    mode=spec['mode'];metrics=spec['metrics'];p=f'WITH p AS (SELECT * FROM transaction_lines WHERE {where(spec)}) '
    if mode=='scalar':
        return p+'SELECT '+', '.join(expr_sql(m)+' AS '+a for m,a in zip(metrics,spec['columns']))+' FROM p;'
    if mode in ('daily','monthly'):
        group="DATE_FORMAT(invoice_date,'%Y-%m-%d')" if mode=='daily' else "DATE_FORMAT(invoice_date,'%Y-%m')"
        return p+f'SELECT {group} AS period, '+expr_sql(metrics[0])+f' AS {spec["columns"][1]} FROM p GROUP BY period ORDER BY period;'
    if mode=='country_share':
        return p+f''' ,g AS (SELECT country,SUM(line_amount) sales_amount FROM p WHERE {VALID} GROUP BY country),
        t AS (SELECT SUM(line_amount) total FROM p WHERE {VALID})
        SELECT country,sales_amount,sales_amount/NULLIF(total,0) sales_share FROM g CROSS JOIN t
        ORDER BY sales_amount DESC,country COLLATE utf8mb4_bin ASC LIMIT 10;'''
    if mode=='mom':
        ps=literal(spec['previous_start']);start=literal(spec['start']);end=literal(spec['end'])
        # Include both months; CASE sums remain NULL for a missing month.
        return f'''WITH a AS (SELECT SUM(CASE WHEN invoice_date>={start} THEN line_amount END) current_amount,
        SUM(CASE WHEN invoice_date<{start} THEN line_amount END) previous_amount
        FROM transaction_lines WHERE invoice_date>={ps} AND invoice_date<{end} AND {VALID})
        SELECT current_amount,previous_amount,(current_amount-previous_amount)/NULLIF(previous_amount,0) mom FROM a;'''
    if mode=='country_metrics':
        return p+'SELECT country,'+', '.join(expr_sql(m)+' AS '+a for m,a in zip(metrics,spec['columns'][1:]))+' FROM p GROUP BY country ORDER BY country COLLATE utf8mb4_bin ASC;'
    raise ValueError(mode)

def source_rows(db,spec):
    # Rehydrate the source integer representation for independent Python formulas.
    q='SELECT line_id,invoice_no,stock_code,description,quantity,invoice_date,unit_price,customer_id,country,is_cancelled,line_amount FROM transaction_lines WHERE '+where(spec)
    for r in db.execute(q):
        yield [str(r[0]),'source','0',r[1],r[2],r[3],str(r[4]),r[5],str(Decimal(r[6])/1000000),r[7],r[8],str(r[9]),str(Decimal(r[10])/1000000)]

def source_answer(db,spec):
    key=json.dumps(spec,sort_keys=True)
    if key not in _ANSWERS:_ANSWERS[key]=_source_answer(db,spec)
    return _ANSWERS[key]

def _source_answer(db,spec):
    mode=spec['mode'];metrics=spec['metrics']
    if mode=='scalar':
        key=(spec['start'],spec['end'],spec.get('country'))
        if key not in _REFERENCES:
            values=reference(source_rows(db,spec),spec['start'],spec['end'])
            basic=db.execute(f'SELECT COUNT(DISTINCT country),SUM(quantity),COUNT(DISTINCT stock_code) FROM transaction_lines WHERE {where(spec)}').fetchone()
            values.update(zip(['B_COUNTRY','B_QUANTITY','B_SKU'],basic));_REFERENCES[key]=values
            if _CACHE_PATH:
                _CACHE_PATH.write_text(json.dumps({'meta':_CACHE_META,'values':{
                    json.dumps(k):v for k,v in _REFERENCES.items()}},default=str)+'\n')
        values=_REFERENCES[key]
        return [[decimal_text(values[m]) for m in metrics]]
    if mode in ('daily','monthly'):
        n=10 if mode=='daily' else 7;m=metrics[0]
        # Counts and sums directly over source rows, using integer micro currency.
        expression=expr_sql(m)
        rows=db.execute(f'SELECT SUBSTR(invoice_date,1,{n}),{expression} FROM transaction_lines WHERE {where(spec)} GROUP BY 1 ORDER BY 1').fetchall()
        return [[key,decimal_text(Decimal(value)/1000000) if value is not None and m in ['M02','M04','M08','M16','M17'] else decimal_text(value)] for key,value in rows]
    if mode=='country_share':
        rows=db.execute(f'SELECT country,SUM(line_amount) FROM transaction_lines WHERE {where(spec)} AND {VALID} GROUP BY country ORDER BY SUM(line_amount) DESC,country COLLATE BINARY ASC').fetchall()
        total=sum(r[1] for r in rows)
        return [[country,decimal_text(Decimal(amount)/1000000),decimal_text(Decimal(amount)/total) if total else None] for country,amount in rows[:10]]
    if mode=='mom':
        previous=dict(spec,start=spec['previous_start'],end=spec['start'],mode='scalar',metrics=['M04'])
        current=dict(spec,mode='scalar',metrics=['M04'])
        a=source_answer(db,current)[0][0];b=source_answer(db,previous)[0][0]
        return [[a,b,None if a is None or b is None or Decimal(b)==0 else decimal_text((Decimal(a)-Decimal(b))/Decimal(b))]]
    if mode=='country_metrics':
        result=[]
        keys=[r[0] for r in db.execute(f'SELECT DISTINCT country FROM transaction_lines WHERE {where(spec)} ORDER BY country COLLATE BINARY ASC')]
        for country in keys:
            # No NULL countries in this frozen source; fail rather than silently mis-scope future data.
            if country is None:raise ValueError('NULL country grouping requires explicit source implementation')
            part=dict(spec,country=country,mode='scalar',columns=spec['columns'][1:])
            result.append([country]+source_answer(db,part)[0])
        return result
    raise ValueError(mode)

def schema(spec):
    kinds=[]
    for col in spec['columns']:
        kind='text' if col in ['period','country'] else 'decimal'
        division={'M09','M10','M12','M14','M18'}
        tolerance='0.000001' if ((col=='value' and spec['metrics'][0] in division) or col in ['sales_share','mom'] or col in {'metric_'+m.lower() for m in division}) else '0'
        kinds.append(dict(name=col,type=kind,absolute_tolerance=tolerance,nullable=True))
    return kinds

def make_questions():
    c=load_contract();names={m['id']:m['name'] for m in c['metrics']}
    defs={m['id']:m for m in c['metrics']}
    formal={
      'scope':[('sales_amount','M04'),('sales_units','M05'),('sales_lines','M03'),('cancel_invoices','M15'),('cancel_signed','M16')],
      'denominator':[('average_invoice','M09'),('per_buyer','M10'),('repeat_rate','M12'),('weighted_price','M14'),('known_share','M18')],
      'grain':[('distinct_invoice','M06'),('distinct_buyer','M07'),('repeat_buyer','M11'),('distinct_sku','M13'),('country_share','M04')],
      'time':[('daily_sales','M04'),('monthly_sales','M04'),('monthly_invoice','M06'),('monthly_buyer','M07'),('monthly_mom','M04')],
      'basic':[('raw_count','M01'),('raw_sum','M02'),('raw_countries','B_COUNTRY'),('raw_quantity','B_QUANTITY'),('raw_codes','B_SKU')]}
    items=[]
    for cat,families in formal.items():
        for family,m in families:
            for i in range(20):
                start,end=month(i),month(i+1)
                spec=dict(mode='scalar',metrics=[m],columns=['value'],start=fmt(start),end=fmt(end),country=None)
                prefix=f'{start:%Y年%m月}'
                country=[None,'United Kingdom','Germany','France',None][i%5] if cat in ['scope','denominator','grain'] and family!='country_share' and m!='M18' else None
                spec['country']=country
                if country:prefix+='、国家为'+country
                question=f'请统计{prefix}的{names.get(m,m)}。返回一个数值。'
                if cat=='basic':
                    prompts={'M01':'原始交易明细行数，不添加取消、数量、价格或客户过滤',
                    'M02':'全部原始明细的有符号金额之和，不排除任何记录',
                    'B_COUNTRY':'原始记录中非空country的去重数量，不增加业务过滤',
                    'B_QUANTITY':'全部原始记录quantity之和，保留负数和零，不增加业务过滤',
                    'B_SKU':'原始记录stock_code的去重数量，不增加业务过滤'}
                    question=f'请查询{prefix}的{prompts[m]}。返回一个数值。'
                if family=='country_share':
                    spec.update(mode='country_share',columns=['country','sales_amount','sales_share'])
                    question=f'请列出{prefix}销售额最高的10个国家，并给出各自销售额和占同月全部国家销售额的比值。并列按country二进制升序，输出恰好10行，不足则全部。'
                if cat=='time':
                    if family=='daily_sales':
                        start=end-timedelta(days=2);end=end+timedelta(days=2)
                        spec.update(mode='daily',start=fmt(start),end=fmt(end),columns=['period','sales_amount'])
                        question=f'请按日统计{start:%Y-%m-%d}至{end-timedelta(days=1):%Y-%m-%d}（含结束日）的销售额，只返回有原始记录的日期，按日期升序。'
                    elif family=='monthly_mom':
                        spec.update(mode='mom',previous_start=fmt(month(i-1)),columns=['current_amount','previous_amount','mom'])
                        question=f'请计算{prefix}销售额相对于上一个完整自然月的环比，返回本月金额、上月金额和环比比值。'
                    else:
                        end=month(i+2)
                        spec.update(mode='monthly',end=fmt(end),columns=['period',{'M04':'sales_amount','M06':'invoice_count','M07':'buyer_count'}[m]])
                        question=f'请按月统计{start:%Y-%m-%d}至{end-timedelta(days=1):%Y-%m-%d}（含结束日）的{names[m]}，只返回有原始记录的月份，按月份升序。'
                metric_ids=[m] if m in defs else []
                required=['P01','P06']+metric_ids
                if spec['mode']=='mom':required+=['P02']
                if spec['mode']=='country_share':required+=['P03']
                rules=['严格遵守题目时间及国家范围','只读执行，使用原始明细而非报告猜值']
                if m in defs:
                    rules+=[c['scopes'][defs[m]['scope']], '指标公式：'+defs[m]['formula']]+defs[m]['rules']
                rules+=['分组与输出列匹配，不能通过LIMIT截断遗漏答案']
                items.append(dict(id=f'test_{cat}_{family}_{i+1:02}',split='test',category=cat,
                    template_family='test_'+cat+'_'+family,question=question,spec=spec,
                    answer_schema=schema(spec),required_knowledge_ids=required,required_rules=rules,
                    order_sensitive=spec['mode']!='scalar'))
    # Development families use combined metrics and grouped diagnostics rather
    # than repeating the formal single-metric query templates. Metric concepts
    # are shared intentionally: this is not unseen-industry generalization.
    dev={
      'scope':[('sales_vs_raw',['M01','M03','M02','M04']),('cancel_vs_positive',['M15','M16','M05'])],
      'denominator':[('customer_attribution',['M04','M08','M17','M07']),('invoice_vs_customer',['M06','M07','M09','M10'])],
      'grain':[('country_invoice_buyer',['M06','M07']),('country_units_codes',['M05','M13'])],
      'time':[('boundary_counts',['M01','M03']),('empty_period',['M01','M04','M06','M12'])],
      'basic':[('raw_overview',['M01','M02','B_QUANTITY']),('raw_cardinality',['B_COUNTRY','B_SKU'])]}
    for cat,families in dev.items():
        for family,metrics in families:
            for i in range(5):
                start,end=month(i*3),month(i*3+2)
                if family=='empty_period':start,end=datetime(2012,1+i,1),datetime(2012,2+i,1)
                if family=='boundary_counts':start,end=month(i+1)-timedelta(hours=12),month(i+1)+timedelta(hours=12)
                cols=['metric_'+m.lower() for m in metrics]
                mode='country_metrics' if cat=='grain' else 'scalar'
                spec=dict(mode=mode,metrics=metrics,columns=(['country']+cols if mode=='country_metrics' else cols),start=fmt(start),end=fmt(end),country=None)
                labels=[names.get(m,{'B_COUNTRY':'原始country非空去重数','B_SKU':'原始stock_code去重数','B_QUANTITY':'原始quantity有符号合计'}.get(m,m)) for m in metrics]
                question=f'请查询从{fmt(start)}起至{fmt(end)}之前的'+('各country的' if mode=='country_metrics' else '')+'、'.join(labels)+'。'
                if mode=='country_metrics':question+='保留有原始记录的国家，按country二进制升序。'
                rules=['时间范围左闭右开','每个指标分别遵守自身范围，不能把销售过滤施加到原始指标上']
                items.append(dict(id=f'dev_{cat}_{family}_{i+1:02}',split='dev',category=cat,
                    template_family='dev_'+cat+'_'+family,question=question,spec=spec,answer_schema=schema(spec),
                    required_knowledge_ids=['P01','P06']+[m for m in metrics if m in defs],required_rules=rules,
                    order_sensitive=mode!='scalar'))
    for item in items:
        s=item['spec']
        rules=[f"明细时间满足 invoice_date >= '{s['start']}' AND invoice_date < '{s['end']}'；月环比另读取紧邻上月。"]
        if s.get('country'):rules.append('国家过滤严格为 country='+s['country'])
        for m in s['metrics']:
            if m in defs:
                d=defs[m]
                rules += [d['name']+'：范围 '+c['scopes'][d['scope']],d['name']+'：公式 '+d['formula']]+d['rules']
            else:rules.append('原始指标不增加销售/取消/数量/客户过滤，按题目指定字段执行聚合。')
        rules.append('COUNT无匹配为0；SUM无匹配为NULL；分母零或NULL返回NULL；比值不自动乘100，中间值不按展示精度舍入。')
        if s['mode']=='mom':rules.append(c['policies']['P02']['definition'])
        if s['mode']=='country_share':rules.append(c['policies']['P03']['definition'])
        if s['mode'] in ['monthly','daily']:rules.append('按明细日期的日/月分桶，仅返回有原始记录的桶，按period升序；每个桶单独使用指标范围和去重粒度。')
        if s['mode']=='country_metrics':rules.append('每个国家分别聚合，包含有原始记录但有效销售为空的国家；国家按二进制升序。')
        rules.append('结果粒度和列符合answer_schema；不得通过未要求的LIMIT截断或报告猜值替代执行。')
        item['required_rules']=list(dict.fromkeys(rules))
    return items

def build(args):
    global _CACHE_PATH,_CACHE_META
    OUT.mkdir(exist_ok=True)
    if (OUT/'freeze-v1.json').exists():raise SystemExit('Benchmark frozen; do not overwrite. Publish a new version.')
    args.output.mkdir(parents=True,exist_ok=True)
    db,count=prepare_source(args.work,args.output/'source.sqlite')
    _CACHE_PATH=args.output/'reference-cache.json'
    _CACHE_META={'snapshot':load_contract()['snapshot_canonical_sha256'],
                 'oracle_sha256':file_sha256(ROOT/'validate_knowledge.py'),
                 'builder_sha256':file_sha256(Path(__file__))}
    if _CACHE_PATH.exists():
        saved=json.loads(_CACHE_PATH.read_text())
        if saved['meta']==_CACHE_META:
            _REFERENCES.update({tuple(json.loads(k)):{m:Decimal(v) if isinstance(v,str) else v for m,v in values.items()}
                                for k,values in saved['values'].items()})
    items=make_questions();private=[];public=[]
    for n,item in enumerate(items,1):
        result=source_answer(db,item['spec'])
        if len(result)>1000:raise ValueError('Result exceeds execution row cap')
        # Detect at least one realistic date-scope error per non-empty formal task.
        wrong=dict(item['spec'],start='2009-12-01 00:00:00',end='2011-12-10 00:00:00')
        if wrong['mode']=='mom':wrong['previous_start']='2009-11-01 00:00:00'
        mutation_result=source_answer(db,wrong) if item['split']=='test' else None
        if item['split']=='test' and mutation_result==result:raise ValueError('Date mutation indistinguishable: '+item['id'])
        private.append(dict(item,reference_sql=target_sql(item['spec']),expected_rows=result,
                            mutation_probe={'type':'ignore_requested_time_scope','distinguishable':mutation_result!=result} if item['split']=='test' else None))
        public.append({k:item[k] for k in ['id','split','category','template_family','question','answer_schema']})
        if n%50==0:print('Built',n,'questions',flush=True)
    for split in ['dev','test']:
        (OUT/(split+'-questions-v1.jsonl')).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in public if x['split']==split))
        # Standard answers are local private artifacts, not part of the RAG pack.
        (args.output/(split+'-answers-v1.jsonl')).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in private if x['split']==split))
    inventory=dict(version='1.0.0',source_rows=count,contract_sha256=file_sha256(CONTRACT),
        sizes=dict(Counter(x['split'] for x in items)),
        categories={s:dict(Counter(x['category'] for x in items if x['split']==s)) for s in ['dev','test']},
        template_families={s:len({x['template_family'] for x in items if x['split']==s}) for s in ['dev','test']},
        mutation_probes_passed=500,description='Template-derived custom commerce set; not 500 independent business scenarios. Not a BIRD score.')
    (OUT/'inventory-v1.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n')
    # Human browseable copies deliberately omit SQL and numeric standard answers.
    for split in ['dev','test']:
        lines=[f'# {"开发集" if split=="dev" else "正式集"} v1.0.0','', '固定模板生成题，ID与JSONL一致。参考答案保存在本地私有目录。','']
        for cat,label in CATEGORIES.items():
            lines+=['','## '+label,'']
            for x in public:
                if x['split']==split and x['category']==cat:lines+=[f"- `{x['id']}`：{x['question']}"]
        (OUT/(split+'-题目-v1.md')).write_text('\n'.join(lines)+'\n')
    db.close();print(json.dumps(inventory,ensure_ascii=False,indent=2))

def verify_mysql(args):
    con=json.loads(args.credentials.read_text());args.user=con['username'];os.environ['RETAIL_MYSQL_PASSWORD']=con['password']
    if con['database']!=DB:raise ValueError('Wrong database')
    checks=[]
    for split in ['dev','test']:
        path=args.output/(split+'-answers-v1.jsonl')
        items=[json.loads(x) for x in path.read_text().splitlines()]
        # Batch statements to avoid hundreds of process launches. Stable markers
        # delimit result sets; every gold query is SELECT-only.
        for offset in range(0,len(items),10):
            batch=items[offset:offset+10]
            query='USE `retail_eval_v1`;\n'+ '\n'.join("SELECT '__CASE__',"+literal(x['id'])+';\n'+x['reference_sql'] for x in batch)
            result=command(args,query);rows={};current=None
            for line in result.splitlines():
                fields=line.split('\t')
                if fields[0]=='__CASE__':current=fields[1];rows[current]=[]
                else:rows[current].append([None if f=='NULL' else unescape(f) for f in fields])
            for item in batch:
                ok,reason=compare(item['expected_rows'],rows[item['id']],item['answer_schema'],item['order_sensitive'])
                checks.append(dict(id=item['id'],passed=ok,reason=reason,rows=len(rows[item['id']])))
            (args.output/'mysql-validation.json').write_text(json.dumps(dict(passed=all(c['passed'] for c in checks),completed=len(checks),checks=checks),ensure_ascii=False,indent=2)+'\n')
            print(split,min(offset+10,len(items)),'/',len(items),'verified',flush=True)
    if not all(x['passed'] for x in checks):raise SystemExit(1)

def compare(expected,actual,columns,ordered=True):
    if len(actual)!=len(expected):return False,'row_count_mismatch'
    def convert(row):
        if len(row)!=len(columns):raise ValueError('column_count_mismatch')
        return tuple(None if v is None else str(v) if c['type']=='text' else Decimal(str(v)) for v,c in zip(row,columns))
    try:a=[convert(r) for r in actual];e=[convert(r) for r in expected]
    except Exception:return False,'invalid_value_or_columns'
    if not ordered:
        # Unordered comparisons retain multiplicity. Current scalar cases have one row.
        def key(row):return tuple((v is not None,str(v)) for v in row)
        a.sort(key=key);e.sort(key=key)
    for er,ar in zip(e,a):
        for x,y,col in zip(er,ar,columns):
            if x is None or y is None:
                if x is not None or y is not None:return False,'null_mismatch'
            elif col['type']=='text':
                if x!=y:return False,'text_or_order_mismatch'
            elif not x.is_finite() or not y.is_finite() or abs(x-y)>Decimal(col['absolute_tolerance']):
                return False,'numeric_mismatch'
    return True,'matched'

def check_freeze():
    lock=json.loads((OUT/'freeze-v1.json').read_text())
    for relative,expected in lock['files_sha256'].items():
        if file_sha256(PROJECT/relative)!=expected:raise ValueError('Frozen file changed: '+relative)
    print('Benchmark v1.0.0 freeze hashes verified.')

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['build','verify-mysql','check-freeze'])
    p.add_argument('--work',type=Path,default=Path('.vscode/retail-eval/frozen'))
    p.add_argument('--output',type=Path,default=Path('.vscode/retail-eval/benchmark-v1'))
    p.add_argument('--credentials',type=Path,default=Path('.vscode/retail-eval/connection.json'))
    p.add_argument('--container',default='dataagent-local-mysql')
    args=p.parse_args()
    if args.action=='check-freeze':check_freeze()
    else:
        if args.action=='verify-mysql' and (OUT/'freeze-v1.json').exists():check_freeze()
        {'build':build,'verify-mysql':verify_mysql}[args.action](args)

if __name__=='__main__':main()
