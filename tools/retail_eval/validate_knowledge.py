"""Private validation oracle. Never upload this module/results to Agent knowledge."""
import argparse
import csv
import json
import os
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from knowledge import CONTRACT, load_contract, validate
from pipeline import command, file_sha256, unescape

VALID='is_cancelled=0 AND quantity>0 AND unit_price>0'
KNOWN="customer_id IS NOT NULL AND TRIM(customer_id)<>''"
ZERO=Decimal(0)

def divide(a,b):
    return None if a is None or b is None or b==0 else a/b

def mom(current,previous):
    return None if current is None or previous is None or previous==0 else (current-previous)/previous

def period(start,end):
    a=datetime.fromisoformat(start); b=datetime.fromisoformat(end)
    if a>=b:raise ValueError('start must precede end')
    return a.strftime('%Y-%m-%d %H:%M:%S'),b.strftime('%Y-%m-%d %H:%M:%S')

def reference(lines,start,end):
    start,end=period(start,end)
    count=0; raw_sum=None; sales_sum=None; units=None; known_sum=None; anonymous_sum=None; cancel_sum=None
    sales_count=0; invoices=set();buyers=defaultdict(set);skus=set();cancels=set()
    def add(total,value):return value if total is None else total+value
    for line in lines:
        if not start<=line[7]<end:continue
        count+=1;amount=Decimal(line[12]);q=Decimal(line[6]);p=Decimal(line[8]);cancel=int(line[11])
        raw_sum=add(raw_sum,amount)
        if cancel:
            cancels.add(line[3]);cancel_sum=add(cancel_sum,amount)
        if cancel==0 and q>0 and p>0:
            sales_count+=1;sales_sum=add(sales_sum,amount);units=add(units,q)
            invoices.add(line[3]);skus.add(line[4])
            if line[9] is not None and line[9].strip():
                buyers[line[9]].add(line[3]);known_sum=add(known_sum,amount)
            else:anonymous_sum=add(anonymous_sum,amount)
    repeats=sum(len(v)>=2 for v in buyers.values())
    return dict(zip(['M%02d'%i for i in range(1,19)], [count,raw_sum,sales_count,sales_sum,units,len(invoices),
        len(buyers),known_sum,divide(sales_sum,Decimal(len(invoices))),divide(known_sum,Decimal(len(buyers))),
        repeats,divide(Decimal(repeats),Decimal(len(buyers))),len(skus),divide(sales_sum,units),
        len(cancels),cancel_sum,anonymous_sum,divide(known_sum if known_sum is not None else ZERO,sales_sum)]))

def read_lines(path):
    with Path(path).open() as f:
        for line in f:yield [unescape(v) for v in line.rstrip('\n').split('\t')]

def sql(start,end):
    start,end=period(start,end)
    return f"""WITH p AS (SELECT * FROM transaction_lines WHERE invoice_date>='{start}' AND invoice_date<'{end}'),
    a AS (SELECT COUNT(*) m01,SUM(line_amount) m02,
    SUM(CASE WHEN {VALID} THEN 1 ELSE 0 END) m03,
    SUM(CASE WHEN {VALID} THEN line_amount END) m04,
    SUM(CASE WHEN {VALID} THEN quantity END) m05,
    COUNT(DISTINCT CASE WHEN {VALID} THEN invoice_no END) m06,
    COUNT(DISTINCT CASE WHEN {VALID} AND {KNOWN} THEN customer_id END) m07,
    SUM(CASE WHEN {VALID} AND {KNOWN} THEN line_amount END) m08,
    COUNT(DISTINCT CASE WHEN {VALID} THEN stock_code END) m13,
    COUNT(DISTINCT CASE WHEN is_cancelled=1 THEN invoice_no END) m15,
    SUM(CASE WHEN is_cancelled=1 THEN line_amount END) m16,
    SUM(CASE WHEN {VALID} AND NOT ({KNOWN}) THEN line_amount END) m17 FROM p),
    r AS (SELECT COUNT(*) m11 FROM (SELECT customer_id FROM p WHERE {VALID} AND {KNOWN}
    GROUP BY customer_id HAVING COUNT(DISTINCT invoice_no)>=2) buyers)
    SELECT m01,m02,COALESCE(m03,0),m04,m05,m06,m07,m08,m04/NULLIF(m06,0),m08/NULLIF(m07,0),
    m11,CAST(m11 AS DECIMAL(30,12))/NULLIF(m07,0),m13,m04/NULLIF(m05,0),m15,m16,m17,
    COALESCE(m08,0)/NULLIF(m04,0) FROM a CROSS JOIN r;"""

def evaluate_sql(execute,start,end):
    output=execute(sql(start,end)).strip().split('\t')
    if len(output)!=18:raise ValueError('Expected 18 metrics')
    return {f'M{i:02}':None if v=='NULL' else Decimal(v) for i,v in enumerate(output,1)}

def validate_live(args):
    c=load_contract();validate(c)
    connection=json.loads(args.credentials.read_text());args.user=connection['username']
    os.environ['RETAIL_MYSQL_PASSWORD']=connection['password']
    if connection['database']!=c['database']:raise ValueError('Wrong database')
    manifest=json.loads((args.work/'manifest.json').read_text())
    assert manifest['source_sha256']==c['snapshot_source_sha256']
    assert manifest['canonical_sha256']==c['snapshot_canonical_sha256']
    # Verify reference material matches the source-derived digest before using it.
    import hashlib
    from pipeline import canonical
    h=hashlib.sha256()
    for line in read_lines(args.work/'lines.tsv'):h.update(canonical(line).encode())
    assert h.hexdigest()==c['snapshot_canonical_sha256'],'Reference TSV altered'
    windows=[('full','2009-12-01','2011-12-10'),('complete_month','2011-06-01','2011-07-01'),
             ('empty','2012-01-01','2012-02-01')]
    results=[]
    for name,start,end in windows:
        expected=reference(read_lines(args.work/'lines.tsv'),start,end)
        actual=evaluate_sql(lambda s:command(args,'USE `retail_eval_v1`;'+s),start,end)
        checks={}
        for key in expected:
            e,a=expected[key],actual[key]
            if key in {'M09','M10','M12','M14','M18'} and e is not None and a is not None:
                checks[key]=abs(Decimal(e)-a)<=Decimal('0.000001')
            else:checks[key]=e==a
        results.append(dict(window=name,start=start,end=end,checks=checks,expected=expected,actual=actual))
        print(name, 'PASS' if all(checks.values()) else 'FAIL',flush=True)
    report=dict(contract_version=c['version'],contract_sha256=file_sha256(CONTRACT),
        verified_at=datetime.now().isoformat(),checks=54,passed=all(all(r['checks'].values()) for r in results),
        numeric_tolerance='0.000001 for five division metrics; all sums/counts/nulls exact',results=results)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
    if not report['passed']:raise SystemExit(1)

def main():
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,default=Path('.vscode/retail-eval/frozen'))
    p.add_argument('--credentials',type=Path,default=Path('.vscode/retail-eval/connection.json'))
    p.add_argument('--container',default='dataagent-local-mysql')
    p.add_argument('--out',type=Path,default=Path('.vscode/retail-eval/knowledge-validation.json'))
    validate_live(p.parse_args())

if __name__=='__main__':main()
