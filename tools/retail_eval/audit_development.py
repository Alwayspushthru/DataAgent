"""Audit an existing local development run; no model or database calls."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import statistics

from benchmark import check_freeze
from pipeline import file_sha256
from run_development import backend_hash,write


def audit(run):
    check_freeze()
    config=json.loads((run/'config.json').read_text())
    summary=json.loads((run/'summary.json').read_text())
    assert config['split']=='development'
    assert len(config['cases'])==config['limit']==summary['selected']
    models=json.loads((run/'models.json').read_text())
    settings=json.loads((run/'server-settings.json').read_text())
    threads=[];conversations=[];groups={};files={}
    for group in ['off','on']:
        predictions={r['id']:r for r in map(json.loads,(run/(group+'-predictions.jsonl')).read_text().splitlines())}
        assert set(predictions)==set(config['cases'])
        statuses=Counter();stops=Counter();nonempty=0;recalled=0;sql_runs=0;nodes=0;durations=[]
        attempts=Counter();token_runs=0;prompt_tokens=0;completion_tokens=0;failures=[]
        for ident in config['cases']:
            path=run/'captures'/(ident+'-'+group+'.json')
            capture=json.loads(path.read_text())
            files[str(path.relative_to(run))]=file_sha256(path)
            assert capture['caseId']==ident and capture['group']==group
            assert capture['businessKnowledgeEnabled']==(group=='on')
            assert capture['models']==models and capture['retrievalSettings']==settings
            threads.append(capture['threadId'])
            conversations.append(capture['conversationId'])
            evidence=[n['outputs'].get('EVIDENCE') for n in capture['nodes']
                      if n['node']=='EVIDENCE_RECALL_NODE' and isinstance(n.get('outputs'),dict)]
            assert len(evidence)<=1, 'Unexpected repeated recall terminal record: '+str(path)
            recalled+=bool(evidence)
            if group=='off':
                for node in capture['nodes']:
                    for io in ['inputs','outputs']:
                        values=node.get(io,{})
                        if isinstance(values,dict):assert values.get('EVIDENCE') in [None,'','无'], 'OFF evidence contamination: '+str(path)
            nonempty+=any(v and v!='无' for v in evidence)
            p=predictions[ident];statuses[p['status']]+=1
            sql_runs+=bool(capture['sqlExecutions']);nodes+=len(capture['nodes'])
            durations.append(capture['elapsedMs'])
            attempts.update(e['status'] for e in capture['sqlExecutions'])
            if capture.get('promptTokens') is not None:
                token_runs+=1;prompt_tokens+=capture['promptTokens'];completion_tokens+=capture['completionTokens']
            if p['status']!='success':
                last=capture['nodes'][-1]
                stops[last['node']+':'+last['status']]+=1
                failures.append(dict(id=ident,prediction_status=p['status'],
                    terminal_node=last['node'],terminal_node_status=last['status']))
        score_report=json.loads((run/(group+'-score.json')).read_text())
        categories={}
        for record in score_report.get('records',[]):
            count=categories.setdefault(record['category'],dict(total=0,result_correct=0))
            count['total']+=1;count['result_correct']+=record['result_correct']
        groups[group]=dict(prediction_statuses=dict(statuses),recall_records=recalled,nonempty_evidence_runs=nonempty,
            runs_with_actual_sql=sql_runs,captured_nodes=nodes,failure_terminal_nodes=dict(stops),
            failure_cases=failures,
            incorrect_results=[dict(id=r['id'],reason=r['result_reason'])
                for r in score_report.get('records',[]) if not r['result_correct']],
            result_by_category=categories,
            elapsed_ms_min=min(durations),elapsed_ms_max=max(durations),
            elapsed_ms_p50=statistics.median(durations),
            elapsed_ms_p95=sorted(durations)[math.ceil(.95*len(durations))-1],
            sql_execution_attempts=dict(attempts),
            reported_streaming_usage=dict(runs_with_usage=token_runs,prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,complete_billing_cost=False),
            score=summary['scores'][group])
        for name in [group+'-predictions.jsonl',group+'-score.json']:
            files[name]=file_sha256(run/name)
    assert len(set(threads))==len(threads), 'Conversation contamination: reused thread'
    assert len(set(conversations))==len(conversations), 'Conversation contamination: reused conversation'
    seeded=0
    if (run/'seed.json').exists():
        seed=json.loads((run/'seed.json').read_text())
        seeded=seed['reused_actual_captures']
        assert seeded==len(seed['files_sha256'])
        for name,digest in seed['files_sha256'].items():
            assert file_sha256(run/'captures'/name)==digest, 'Seed capture changed: '+name
        files['seed.json']=file_sha256(run/'seed.json')
    checks=['frozen_knowledge_and_benchmark_hashes_valid','all_selected_predictions_present',
            'off_evidence_empty_on_switch_recorded','model_and_retrieval_settings_consistent',
            'every_run_has_unique_thread','every_run_has_unique_conversation',
            'raw_capture_and_prediction_hashes_recorded']
    current_hash=backend_hash()
    return dict(split='development',selected_questions=config['limit'],actual_runs=len(threads),
        formal_500_not_run=True,backend_code_sha256=config['backend_code_sha256'],models=models,
        reused_actual_capture_count=seeded,new_actual_capture_count=len(threads)-seeded,
        current_backend_code_sha256=current_hash,
        source_matches_current_checkout=config['backend_code_sha256']==current_hash,
        retrieval_settings=settings,checks=checks,groups=groups,files_sha256=files,
        business_review='Only complete human SQL rule reviews can establish business accuracy; see per-group score.',
        note='Small development diagnostic sample, not a claim of general accuracy improvement.')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    result=audit(args.run_dir)
    write(args.out,result)
    print(json.dumps({k:v for k,v in result.items() if k!='files_sha256'},ensure_ascii=False,indent=2))
