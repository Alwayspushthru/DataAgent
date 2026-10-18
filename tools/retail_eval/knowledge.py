"""Versioned business definitions: validation and RAG export, no API calls."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTRACT = ROOT / 'knowledge' / 'contract-v1.json'

def load_contract():
    return json.loads(CONTRACT.read_text())

def validate(c):
    assert c['version'] == '1.0.0'
    assert c['database'] == 'retail_eval_v1'
    seen=set(); aliases={}
    for m in c['metrics']:
        assert m['id'] not in seen
        seen.add(m['id'])
        assert m['scope'] in c['scopes']
        for key in ['name','definition','formula','unit','empty','required_fields','rules']:
            assert m[key], (m['id'],key)
        assert set(m['required_fields']) <= set(c['fields'])
        for name in [m['name']]+m['aliases']:
            assert name not in aliases, (name,aliases.get(name),m['id'])
            assert name not in c['ambiguous_terms']
            aliases[name]=m['id']
        assert set(m.get('dependencies',[])) <= {x['id'] for x in c['metrics']}
    for key,p in c['policies'].items():
        assert key not in seen
        seen.add(key)
        for name in [p['name']]+p.get('aliases',[]):
            assert name not in aliases
            aliases[name]=key
    assert len(c['metrics'])==18 and len(c['policies'])==6
    return {'metrics':len(c['metrics']),'policies':len(c['policies']),'names_and_aliases':len(aliases),'passed':True}

def documents(c):
    docs=[]
    common='\n'.join(c['global_rules'])
    for m in c['metrics']:
        # Each retrieval chunk is self-contained: definitions of dependencies included.
        dependencies=[x for x in c['metrics'] if x['id'] in m.get('dependencies',[])]
        desc=f"[retail-knowledge {c['version']} / {m['id']}]\n{common}\n"
        desc+=f"指标：{m['name']}。{m['definition']}\n范围：{c['scopes'][m['scope']]}\n公式：{m['formula']}\n单位：{m['unit']}；空输入：{m['empty']}。\n"
        desc+='\n'.join(m['rules'])
        desc+='\n所需字段：'+', '.join('transaction_lines.'+f for f in m['required_fields'])
        for dep in dependencies:
            desc+=f"\n依赖 {dep['name']}：{dep['formula']}；范围：{c['scopes'][dep['scope']]}。"
        docs.append({'knowledgeId':m['id'],'businessTerm':m['name'],'description':desc,
                     'synonyms':','.join(m['aliases']),'isRecall':True})
    for key,value in c['policies'].items():
        docs.append({'knowledgeId':key,'businessTerm':value['name'],
                     'description':f"[retail-knowledge {c['version']} / {key}]\n{value['definition']}",
                     'synonyms':','.join(value.get('aliases',[])),'isRecall':True})
    return docs

def export(c,agent_id=None):
    docs=documents(c)
    if agent_id is not None:
        docs=[dict({k:v for k,v in d.items() if k!='knowledgeId'},agentId=agent_id) for d in docs]
    return docs

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['validate','export'])
    p.add_argument('--agent-id',type=int);p.add_argument('--out',type=Path)
    args=p.parse_args();c=load_contract();result=validate(c)
    frozen=ROOT/'knowledge/freeze-v1.json'
    if frozen.exists():
        lock=json.loads(frozen.read_text())
        for relative,expected in lock['files_sha256'].items():
            actual=hashlib.sha256((frozen.parent/relative).read_bytes()).hexdigest()
            if actual!=expected:raise SystemExit('Frozen artifact changed: '+relative)
        result['freeze_verified']=True
    if args.action=='export':
        if args.agent_id is not None and args.agent_id<=0:p.error('agent id must be positive')
        result=export(c,args.agent_id)
    rendered=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.out:args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(rendered)
    else:print(rendered)

if __name__=='__main__':main()
