"""Score execution results and independently reviewed business rules.

This consumes results, never executes submitted SQL. No Agent/LLM calls.
"""
import argparse
import json
from pathlib import Path
from benchmark import compare, OUT, check_freeze
from pipeline import file_sha256

def load_jsonl(path):
    rows=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('Duplicate IDs: '+str(path))
    return {r['id']:r for r in rows}

def result_score(case,prediction):
    if prediction is None:return False,'missing_prediction'
    if prediction.get('status')!='success':return False,'execution_failure'
    required=[c['name'] for c in case['answer_schema']]
    provided=prediction.get('columns',[])
    if len(set(provided))!=len(provided) or set(provided)!=set(required):return False,'column_names_mismatch'
    try:
        rows=prediction['rows']
        if any(len(r)!=len(provided) for r in rows):return False,'column_count_mismatch'
        normalized=[[r[provided.index(k)] for k in required] for r in rows]
    except Exception:return False,'invalid_rows'
    return compare(case['expected_rows'],normalized,case['answer_schema'],case['order_sensitive'])

def business_score(case,prediction,review,allow_judge=False):
    if not prediction or prediction.get('status')!='success':return False,'execution_failure'
    if not review:return None,'review_missing'
    if review.get('reviewer_type')!='human' and not allow_judge:return None,'human_review_required'
    if not review.get('reviewer') or not review.get('executed_sql_evidence'):
        return None,'review_provenance_missing'
    results=review.get('rules',{})
    expected={f'R{i:02}' for i in range(1,len(case['required_rules'])+1)}
    if set(results)!=expected:return None,'rule_reviews_incomplete'
    if any(type(v.get('passed')) is not bool or not v.get('evidence') for v in results.values()):
        return None,'rule_evidence_incomplete'
    return all(v['passed'] for v in results.values()),'rules_reviewed'

def score(cases,predictions,reviews,allow_judge=False):
    if set(predictions)-set(cases):raise ValueError('Unknown prediction IDs')
    if set(reviews)-set(cases):raise ValueError('Unknown review IDs')
    records=[]
    for ident,case in cases.items():
        p=predictions.get(ident);ok,reason=result_score(case,p)
        business,review_reason=(None,'not_in_business_subset') if case['category']=='basic' else business_score(case,p,reviews.get(ident),allow_judge)
        records.append(dict(id=ident,category=case['category'],result_correct=ok,result_reason=reason,
                            business_correct=business,business_reason=review_reason))
    b=[r for r in records if r['category']!='basic']
    complete=all(r['business_correct'] is not None for r in b)
    summary={'total':len(records),'result_correct':sum(r['result_correct'] for r in records),
        'query_result_accuracy':sum(r['result_correct'] for r in records)/len(records),
        'business_total':len(b),'business_scored':sum(r['business_correct'] is not None for r in b),
        'business_correct':sum(r['business_correct'] is True for r in b),
        'business_accuracy':sum(r['business_correct'] is True for r in b)/len(b) if b and complete else None,
        'business_review_complete':complete,'rating_mode':'judge_provisional' if allow_judge else 'human_verified',
        'missing_predictions':len(set(cases)-set(predictions))}
    return dict(summary=summary,records=records)

def main():
    p=argparse.ArgumentParser();p.add_argument('--predictions',type=Path,required=True)
    p.add_argument('--reviews',type=Path);p.add_argument('--group',choices=['off','on'],required=True)
    p.add_argument('--answers',type=Path,default=Path('.vscode/retail-eval/benchmark-v1/test-answers-v1.jsonl'))
    p.add_argument('--out',type=Path,required=True);p.add_argument('--allow-judge',action='store_true')
    args=p.parse_args()
    check_freeze()
    frozen=json.loads((OUT/'freeze-v1.json').read_text())
    answer_key='.vscode/retail-eval/benchmark-v1/test-answers-v1.jsonl'
    if file_sha256(args.answers)!=frozen['files_sha256'][answer_key]:raise ValueError('Answers differ from frozen test set')
    cases=load_jsonl(args.answers);predictions=load_jsonl(args.predictions)
    reviews=load_jsonl(args.reviews) if args.reviews else {}
    if len(cases)!=500 or sum(c['category']!='basic' for c in cases.values())!=400:raise ValueError('Expected frozen 500/400 test set')
    report=score(cases,predictions,reviews,args.allow_judge)
    report.update(group=args.group,answers_sha256=file_sha256(args.answers),predictions_sha256=file_sha256(args.predictions))
    if args.reviews:report['reviews_sha256']=file_sha256(args.reviews)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report['summary'],ensure_ascii=False,indent=2))

if __name__=='__main__':main()
