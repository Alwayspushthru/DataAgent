"""Read-only MySQL regression for ratio precision; no Agent/model calls."""
import argparse
from datetime import datetime,timezone
from decimal import Decimal,localcontext
import json
import os
from pathlib import Path
from types import SimpleNamespace

from pipeline import command,file_sha256

CASES=[('one_third',1,3),('two_thirds',2,3),('tiny_ratio',1,30000),
       ('two_sevenths',2,7),('no_repeat',0,3),('all_repeat',3,3),
       ('empty',0,0),('null_numerator',None,3),('null_denominator',1,None)]
EXPRESSIONS={
    'integer_division':'repeat_customers / NULLIF(buyers, 0)',
    'times_1_0':'repeat_customers * 1.0 / NULLIF(buyers, 0)',
    'cast_after_division':'CAST(repeat_customers / NULLIF(buyers, 0) AS DECIMAL(30,12))',
    'quantized_then_cast':'CAST(CAST(repeat_customers / NULLIF(buyers, 0) AS DECIMAL(20,4)) AS DECIMAL(30,12))',
    'cast_before_division':'CAST(repeat_customers AS DECIMAL(30,12)) / NULLIF(buyers, 0)',
}
TOLERANCE=Decimal('0.000001')

def expected_ratio(numerator,denominator):
    if numerator is None or denominator in [None,0]:return None
    with localcontext() as context:
        context.prec=50
        return Decimal(numerator)/Decimal(denominator)

def matches(expected,actual):
    if expected is None or actual is None:return expected is None and actual is None
    return abs(expected-actual)<=TOLERANCE

def queries():
    statements=['SELECT VERSION(), @@SESSION.div_precision_increment;',
                'SET SESSION div_precision_increment=4;']
    for name,numerator,denominator in CASES:
        n='NULL' if numerator is None else str(numerator)
        d='NULL' if denominator is None else str(denominator)
        expressions=', '.join(expression+' AS '+label for label,expression in EXPRESSIONS.items())
        statements.append(f"WITH counts AS (SELECT CAST({n} AS SIGNED) AS repeat_customers, CAST({d} AS SIGNED) AS buyers) SELECT '{name}', {expressions} FROM counts;")
    return '\n'.join(statements)

def run(args):
    credentials=json.loads(args.credentials.read_text())
    if credentials['database']!='retail_eval_v1':raise ValueError('Expected the isolated retail evaluation connection')
    os.environ['RETAIL_MYSQL_PASSWORD']=credentials['password']
    connection=SimpleNamespace(container=args.container,user=credentials['username'])
    output=command(connection,queries()).splitlines()
    version,original_increment=output[0].split('\t')
    if len(output)!=len(CASES)+1:raise ValueError('Unexpected MySQL result count')
    results=[];index={}
    for (name,numerator,denominator),line in zip(CASES,output[1:]):
        fields=line.split('\t')
        if fields[0]!=name or len(fields)!=len(EXPRESSIONS)+1:raise ValueError('Unexpected MySQL result shape')
        expected=expected_ratio(numerator,denominator)
        actual={key:None if value=='NULL' else Decimal(value) for key,value in zip(EXPRESSIONS,fields[1:])}
        result=dict(scenario=name,numerator=numerator,denominator=denominator,expected=expected,
            actual=actual,within_tolerance={key:matches(expected,value) for key,value in actual.items()})
        results.append(result);index[name]=result
    checks={name+'_cast_before_matches':result['within_tolerance']['cast_before_division'] for name,result in index.items()}
    for key in ['integer_division','times_1_0','quantized_then_cast']:
        checks['one_third_reproduces_'+key+'_error']=not index['one_third']['within_tolerance'][key]
    threshold=Decimal('0.33332');one=index['one_third']
    checks['threshold_decision_preserved']=one['expected']>=threshold and one['actual']['cast_before_division']>=threshold and one['actual']['integer_division']<threshold
    prompt=Path('data-agent-management/src/main/resources/prompts/sql-numeric-precision.txt')
    report=dict(kind='mysql_ratio_precision_regression',passed=all(checks.values()),
        executed_at_utc=datetime.now(timezone.utc).isoformat(),mysql_version=version,
        observed_initial_div_precision_increment=int(original_increment),tested_session_div_precision_increment=4,
        database_writes=False,model_calls=0,actual_agent_output_validated=False,
        note='Tests proposed SQL arithmetic and prompt transport separately; not a new Agent accuracy measurement.',
        outer_cast_note='Outer CAST is recorded as an observation, not assumed to fail: MySQL can retain extra intermediate digits. Explicit quantization to four decimals is the stable negative control.',
        tolerance=str(TOLERANCE),numeric_reference='Python Decimal with precision=50',
        count_scenarios=len(CASES),checks=checks,results=results,
        mysql_session_sql=queries(),precision_policy_sha256=file_sha256(prompt),script_sha256=file_sha256(Path(__file__)))
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
    print(json.dumps(dict(passed=report['passed'],scenarios=len(CASES),checks_passed=sum(checks.values()),
        checks_total=len(checks),mysql_version=version,out=str(args.out)),ensure_ascii=False))
    if not report['passed']:raise SystemExit(1)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--credentials',type=Path,default=Path('.vscode/retail-eval/connection.json'))
    parser.add_argument('--container',default='dataagent-local-mysql')
    parser.add_argument('--out',type=Path,default=Path('.vscode/retail-eval/ratio-precision-2026-10-19/mysql-regression.json'))
    run(parser.parse_args())
