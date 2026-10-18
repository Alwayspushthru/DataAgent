import unittest
from collections import Counter
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import run_development as runner
from run_development import prediction,choose_cases,prompt

class DevelopmentRunnerTest(unittest.TestCase):
    def test_pilot_is_balanced_and_includes_two_families_per_category(self):
        cases=choose_cases(10)
        self.assertEqual(set(Counter(c['category'] for c in cases).values()),{2})
        self.assertEqual(len({c['template_family'] for c in cases}),10)
        self.assertTrue(all(c['split']=='dev' for c in cases))

    def test_prompt_does_not_include_private_answers_or_rules(self):
        text=prompt(choose_cases(1)[0])
        self.assertNotIn('reference_sql',text)
        self.assertNotIn('expected_rows',text)
        self.assertNotIn('is_cancelled=0',text)

    def test_sql_null_preserved(self):
        capture={'status':'completed','sqlExecutions':[{'status':'success','columns':['value'],'data':[{'value':None}]}]}
        result=prediction({'id':'a'},capture)
        self.assertEqual(result['rows'],[[None]])

    def test_last_failed_sql_not_replaced_by_previous_success(self):
        capture={'status':'completed','sqlExecutions':[{'status':'success','columns':['value'],'data':[]},{'status':'error'}]}
        self.assertEqual(prediction({'id':'a'},capture)['status'],'execution_error')

    def test_truncated_and_python_outputs_not_claimed_complete(self):
        capture={'status':'completed','sqlExecutions':[{'status':'success','possiblyTruncated':True}]}
        self.assertEqual(prediction({'id':'a'},capture)['status'],'possibly_truncated')
        capture['nodes']=[{'node':'PYTHON_EXECUTE_NODE'}]
        self.assertEqual(prediction({'id':'a'},capture)['status'],'unsupported_python_output')

    def test_regrading_requires_actual_rule_reviews_and_preserves_review_files(self):
        case=dict(id='a',category='scope',required_rules=['scope','time'],expected_rows=[[10]],
            order_sensitive=False,answer_schema=[dict(name='value',type='decimal',absolute_tolerance='0')])
        actual_loader=runner.load_jsonl
        def load(path):
            if path.name=='dev-answers-v1.jsonl':return {'a':case}
            return actual_loader(path)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);reviews=root/'reviews';reviews.mkdir();(root/'captures').mkdir()
            (root/'config.json').write_text(json.dumps(dict(split='development',limit=1,cases=['a'])))
            for group in ['off','on']:
                (root/'captures'/('a-'+group+'.json')).write_text(json.dumps(dict(sqlExecutions=[dict(sql='SELECT 10 AS value')])) )
                (root/(group+'-predictions.jsonl')).write_text(json.dumps(dict(id='a',status='success',columns=['value'],rows=[[10]]))+'\n')
            args=SimpleNamespace(run_dir=root,reviews_dir=None,limit=50)
            with patch.object(runner,'check_freeze'),patch.object(runner,'choose_cases',return_value=[case]),patch.object(runner,'load_jsonl',side_effect=load),redirect_stdout(io.StringIO()):
                runner.grade(args)
                report=json.loads((root/'on-score.json').read_text())
                self.assertIsNone(report['summary']['business_accuracy'])
                template=json.loads((root/'on-review-template.jsonl').read_text())
                self.assertEqual(template['executed_sql'],['SELECT 10 AS value'])
                self.assertIsNone(template['rules']['R01']['passed'])
                template.update(reviewer='human-reviewer',executed_sql_evidence='capture SQL inspected')
                for rule in template['rules'].values():rule.update(passed=True,evidence='SQL verified against rule')
                target=reviews/'on-reviews.jsonl';target.write_text(json.dumps(template)+'\n')
                before=target.read_bytes();args.reviews_dir=reviews
                runner.grade(args)
                self.assertEqual(target.read_bytes(),before)
                report=json.loads((root/'on-score.json').read_text())
                self.assertEqual(report['summary']['business_accuracy'],1)
                self.assertIn('reviews_sha256',report)

    def test_regrading_refuses_formal_run_before_reading_answers(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'config.json').write_text(json.dumps(dict(split='test')))
            with patch.object(runner,'check_freeze'),patch.object(runner,'load_jsonl') as loader:
                with self.assertRaises(ValueError):runner.grade(SimpleNamespace(run_dir=root))
                loader.assert_not_called()

    def test_isolation_refuses_extra_semantic_models_or_documents(self):
        for semantic,documents in [([{'id':1}],{'data':[]}),([] ,{'data':[{'id':2}]})]:
            with self.subTest(semantic=semantic,documents=documents):
                with patch.object(runner,'api',side_effect=[{'data':semantic},documents]):
                    with self.assertRaises(ValueError):runner.verify_isolation('http://localhost',5)

    def test_isolation_allows_empty_agent_context(self):
        with patch.object(runner,'api',side_effect=[{'data':[]},{'data':[],'total':0}]):
            result=runner.verify_isolation('http://localhost',5)
            self.assertEqual(result['semantic_models'],0)
            self.assertEqual(result['other_knowledge_documents'],0)

if __name__=='__main__':unittest.main()
