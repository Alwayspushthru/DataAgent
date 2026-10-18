"""Local development-only OFF/ON runner. Never reads formal answers or invokes gold SQL."""
import argparse
from collections import Counter
import concurrent.futures
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

from benchmark import OUT,ROOT,check_freeze
from grade_benchmark import load_jsonl,score
from knowledge import load_contract,export
from pipeline import file_sha256

def api(base,path,body=None,method=None,timeout=510):
    data=None if body is None else json.dumps(body,ensure_ascii=False).encode()
    request=urllib.request.Request(base+path,data=data,method=method or ('POST' if body is not None else 'GET'),headers={'Content-Type':'application/json'})
    # Local endpoints must not be routed through a system HTTP proxy.
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request,timeout=timeout) as response:result=json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'Local API {path} failed with HTTP {error.code}') from None
    if isinstance(result,dict) and result.get('success') is False:
        raise RuntimeError('Local API failed: '+str(result.get('message')))
    return result

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temp.replace(path)

def verify_isolation(base,agent_id):
    semantic=api(base,f'/api/semantic-model?agentId={agent_id}')['data']
    documents=api(base,'/api/agent-knowledge/query/page',dict(agentId=int(agent_id),pageNum=1,pageSize=1))
    if semantic or documents.get('data') or documents.get('total',0):
        raise ValueError('Evaluation agent contains extra semantic models or document knowledge')
    return dict(semantic_models=0,other_knowledge_documents=0,checked_at=datetime.now().isoformat())

def setup(args):
    check_freeze()
    con=json.loads(args.credentials.read_text())
    if con['database']!='retail_eval_v1':raise ValueError('Expected frozen retail database')
    state=json.loads(args.setup.read_text()) if args.setup.exists() else {}
    name='retail_eval_v1_knowledge_development'
    agents=api(args.base,'/api/agent/list')
    matches=[x for x in agents if x['name']==name]
    if len(matches)>1:raise ValueError('Ambiguous evaluation agent name')
    agent=matches[0] if matches else api(args.base,'/api/agent',dict(name=name,status='draft',description='Frozen retail development evaluation; isolated read-only datasource; no answer material.'))
    state['agentId']=agent['id'];write(args.setup,state)
    sources=api(args.base,'/api/datasource')
    matches=[x for x in sources if x['name']==name]
    if len(matches)>1:raise ValueError('Ambiguous datasource name')
    datasource=matches[0] if matches else api(args.base,'/api/datasource',dict(name=name,type='mysql',host=con['host'],port=con['port'],databaseName=con['database'],username=con['username'],password=con['password'],connectionUrl=con['jdbc_url'],status='active',description='Independent evaluation snapshot; read-only user.'))
    if datasource['databaseName']!=con['database'] or datasource['username']!=con['username']:raise ValueError('Existing evaluation datasource differs')
    state['datasourceId']=datasource['id'];write(args.setup,state)
    a=state['agentId'];d=state['datasourceId']
    api(args.base,f'/api/datasource/{d}/test',{})
    api(args.base,f'/api/agent/{a}/datasources/{d}',{})
    api(args.base,f'/api/agent/{a}/datasources/tables',dict(datasourceId=d,tables=['transaction_lines']))
    api(args.base,f'/api/agent/{a}/datasources/init',{})
    existing=api(args.base,f'/api/business-knowledge?agentId={a}')['data']
    by_name={x['businessTerm']:x for x in existing}
    mapping={}
    for doc,origin in zip(export(load_contract(),a),export(load_contract())):
        old=by_name.get(doc['businessTerm'])
        if old:
            if old['description']!=doc['description'] or old.get('synonyms','')!=doc['synonyms']:raise ValueError('Existing knowledge differs from frozen definition')
            created=old
        else:created=api(args.base,'/api/business-knowledge',doc)['data']
        mapping[origin['knowledgeId']]=created['id'];state['knowledgeIds']=mapping;write(args.setup,state)
        if created.get('embeddingStatus')=='FAILED':raise RuntimeError('Embedding failed; inspect local knowledge status, no batch run started.')
        print('Knowledge prepared',origin['knowledgeId'],flush=True)
    # The simple vector store is memory-based: refresh after each service restart.
    api(args.base,f'/api/business-knowledge/refresh-vector-store?agentId={a}',{})
    actual=api(args.base,f'/api/business-knowledge?agentId={a}')['data']
    if len(actual)!=24:raise ValueError('Evaluation agent must contain exactly 24 frozen business documents')
    if any(x.get('embeddingStatus')!='COMPLETED' for x in actual):raise ValueError('Not all business documents embedded')
    state.update(knowledge_version='1.0.0',knowledge_sha256=file_sha256(ROOT/'knowledge/contract-v1.json'),
                 business_documents=24,schema_tables=['transaction_lines'],prepared_at=datetime.now().isoformat())
    state['isolation_check']=verify_isolation(args.base,a)
    write(args.setup,state);print('Evaluation agent and 24 knowledge documents ready.',flush=True)

def prompt(case):
    labels=', '.join(c['name'] for c in case['answer_schema'])
    return case['question']+'\n\n结果接口约定：最终查询使用以下输出列名（按此顺序）：'+labels+'。请尽量在一条最终SELECT中返回全部所需列，保留计算精度；比率返回比值而非百分数字符串。不要因为接口约定更改业务统计定义。'

def prediction(case,capture):
    base=dict(id=case['id'],threadId=capture.get('threadId'),columns=[],rows=[])
    if capture.get('status')!='completed':return dict(base,status=capture.get('status','error'))
    nodes=capture.get('nodes',[])
    if any(n.get('node')=='PYTHON_EXECUTE_NODE' for n in nodes):return dict(base,status='unsupported_python_output')
    executions=capture.get('sqlExecutions',[])
    if not executions:return dict(base,status='no_execution')
    last=executions[-1]
    if last.get('status')!='success':return dict(base,status='execution_error')
    if last.get('possiblyTruncated'):return dict(base,status='possibly_truncated')
    columns=last['columns'];rows=last['data']
    if len(set(columns))!=len(columns):return dict(base,status='duplicate_columns')
    if any(any(c not in row for c in columns) for row in rows):return dict(base,status='incomplete_row')
    return dict(base,status='success',columns=columns,rows=[[row[c] for c in columns] for row in rows])

def choose_cases(limit):
    public=load_jsonl(OUT/'dev-questions-v1.jsonl')
    categories=list(dict.fromkeys(c['category'] for c in public.values()))
    groups={k:[c for c in public.values() if c['category']==k] for k in categories}
    # Round-robin across category and family to make small pilots representative.
    for k,rows in groups.items():
        families=list(dict.fromkeys(c['template_family'] for c in rows))
        groups[k]=[rows[i] for j in range(5) for i in range(len(rows)) if i%5==j]
    return [groups[k][i] for i in range(10) for k in categories][:limit]

def summarize(args,run):
    private=load_jsonl(Path('.vscode/retail-eval/benchmark-v1/dev-answers-v1.jsonl'))
    selected={c['id']:private[c['id']] for c in choose_cases(args.limit)}
    scores={}
    for group in ['off','on']:
        path=run/(group+'-predictions.jsonl')
        if not path.exists():continue
        predictions=load_jsonl(path)
        reviews_path=args.reviews_dir/(group+'-reviews.jsonl') if args.reviews_dir else None
        reviews=load_jsonl(reviews_path) if reviews_path and reviews_path.exists() else {}
        report=score(selected,predictions,reviews)
        report.update(group=group,split='development',not_formal_test_accuracy=True)
        report['predictions_sha256']=file_sha256(path)
        if reviews_path and reviews_path.exists():report['reviews_sha256']=file_sha256(reviews_path)
        write(run/(group+'-score.json'),report);scores[group]=report['summary']
    write(run/'summary.json',dict(split='development',selected=len(selected),scores=scores,
         note='Result scoring only. Business accuracy remains pending actual SQL rule review. Not the frozen 500-question result.'))
    return scores

def grade(args):
    """Regrade captured development predictions without calling a model or gold SQL."""
    check_freeze()
    config=json.loads((args.run_dir/'config.json').read_text())
    if config.get('split')!='development':raise ValueError('Development run required')
    args.limit=config['limit']
    cases=choose_cases(args.limit)
    if config['cases']!=[c['id'] for c in cases]:raise ValueError('Selected development cases changed')
    private=load_jsonl(Path('.vscode/retail-eval/benchmark-v1/dev-answers-v1.jsonl'))
    for group in ['off','on']:
        records=[]
        for case in cases:
            if case['category']=='basic':continue
            capture_path=args.run_dir/'captures'/(case['id']+'-'+group+'.json')
            capture=json.loads(capture_path.read_text())
            sqls=[e['sql'] for e in capture.get('sqlExecutions',[]) if e.get('sql')]
            records.append(dict(id=case['id'],reviewer_type='human',reviewer='',
                executed_sql_evidence='',capture_file=str(capture_path),
                capture_sha256=file_sha256(capture_path),executed_sql=sqls,
                rules={f'R{i:02}':dict(definition=rule,passed=None,evidence='')
                       for i,rule in enumerate(private[case['id']]['required_rules'],1)}))
        target=args.run_dir/(group+'-review-template.jsonl')
        # Templates are regenerated; actual reviewer files are never overwritten.
        target.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in records))
    print(json.dumps(summarize(args,args.run_dir),ensure_ascii=False,indent=2))

def run(args):
    check_freeze()
    if not 1<=args.limit<=50:raise ValueError('Development limit must be 1..50')
    setup_state=json.loads(args.setup.read_text());cases=choose_cases(args.limit)
    run=args.run_dir;run.mkdir(parents=True,exist_ok=True)
    write(run/'isolation-check.json',verify_isolation(args.base,setup_state['agentId']))
    config=dict(base=args.base,agentId=setup_state['agentId'],limit=args.limit,split='development',
                cases=[c['id'] for c in cases],knowledge_sha256=setup_state['knowledge_sha256'],
                backend_code_sha256=backend_hash(),protocol='query_pipeline_without_report',workers=args.workers)
    if (run/'config.json').exists() and json.loads((run/'config.json').read_text())!=config:raise ValueError('Run configuration changed; choose a fresh directory')
    write(run/'config.json',config)
    tasks=[(case,group) for i,case in enumerate(cases) for group in (['off','on'] if i%2==0 else ['on','off'])]
    def one(task):
        case,group=task;file=run/'captures'/(case['id']+'-'+group+'.json')
        if file.exists():return case,group,json.loads(file.read_text())
        started=time.monotonic()
        try:capture=api(args.base,'/api/evaluation/run',dict(agentId=str(setup_state['agentId']),query=prompt(case),businessKnowledgeEnabled=group=='on'))
        except Exception as ex:capture=dict(status='transport_error',error=str(ex))
        capture.update(caseId=case['id'],group=group,clientElapsedMs=round((time.monotonic()-started)*1000))
        write(file,capture);return case,group,capture
    predictions={'off':{},'on':{}};models=None;settings=None
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(one,t) for t in tasks]
        for future in concurrent.futures.as_completed(futures):
            case,group,capture=future.result()
            if capture.get('models'):
                if models is None:models=capture['models'];write(run/'models.json',models)
                elif models!=capture['models']:raise ValueError('Active models changed during development run')
            if capture.get('retrievalSettings'):
                if settings is None:settings=capture['retrievalSettings'];write(run/'server-settings.json',settings)
                elif settings!=capture['retrievalSettings']:raise ValueError('Retrieval/retry settings changed during run')
            predictions[group][case['id']]=prediction(case,capture)
            for g in ['off','on']:
                ordered=[predictions[g][c['id']] for c in cases if c['id'] in predictions[g]]
                (run/(g+'-predictions.jsonl')).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in ordered))
            print(group,case['id'],predictions[group][case['id']]['status'],flush=True)
    scores=summarize(args,run);print(json.dumps(scores,ensure_ascii=False,indent=2))

def backend_hash():
    project=ROOT.parent.parent
    paths=sorted((project/'data-agent-management/src/main').rglob('*.java'))+sorted((project/'data-agent-management/src/main/resources/prompts').rglob('*'))
    h=hashlib.sha256()
    for p in paths:
        if p.is_file():h.update(str(p.relative_to(project)).encode());h.update(p.read_bytes())
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['setup','run','grade'])
    p.add_argument('--base',default='http://127.0.0.1:18065')
    p.add_argument('--credentials',type=Path,default=Path('.vscode/retail-eval/connection.json'))
    p.add_argument('--setup',type=Path,default=Path('.vscode/retail-eval/development-setup.json'))
    p.add_argument('--run-dir',type=Path,default=Path('.vscode/retail-eval/development-pilot-v3'))
    p.add_argument('--reviews-dir',type=Path,help='Optional directory containing off/on-reviews.jsonl completed by human reviewers')
    p.add_argument('--limit',type=int,default=10);p.add_argument('--workers',type=int,default=2,choices=[1,2])
    args=p.parse_args()
    parsed=urllib.parse.urlparse(args.base)
    if parsed.scheme!='http' or parsed.hostname not in ['127.0.0.1','localhost','::1']:p.error('Local HTTP endpoint required')
    {'setup':setup,'run':run,'grade':grade}[args.action](args)

if __name__=='__main__':main()
