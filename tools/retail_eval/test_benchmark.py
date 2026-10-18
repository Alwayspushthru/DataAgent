import unittest
import json
from collections import Counter
from benchmark import make_questions, compare, target_sql, OUT
from grade_benchmark import result_score, business_score, score

class BenchmarkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.items=make_questions()

    def test_counts_and_categories(self):
        self.assertEqual(len(self.items),550)
        for split,n in [('dev',10),('test',100)]:
            counts=Counter(x['category'] for x in self.items if x['split']==split)
            self.assertEqual(len(counts),5)
            self.assertTrue(all(v==n for v in counts.values()))

    def test_unique_questions_and_split_families(self):
        self.assertEqual(len({x['id'] for x in self.items}),550)
        self.assertEqual(len({x['question'] for x in self.items}),550)
        a={x['template_family'] for x in self.items if x['split']=='dev'}
        b={x['template_family'] for x in self.items if x['split']=='test'}
        self.assertEqual((len(a),len(b)),(10,25))
        self.assertFalse(a&b)

    def test_dates_and_schema(self):
        for item in self.items:
            self.assertLess(item['spec']['start'],item['spec']['end'])
            self.assertEqual(len(item['answer_schema']),len(item['spec']['columns']))
            self.assertTrue(target_sql(item['spec']).strip().endswith(';'))

    def test_result_comparison(self):
        cols=[dict(name='x',type='decimal',absolute_tolerance='0.000001')]
        self.assertTrue(compare([['0.333333333']], [['0.333333']],cols)[0])
        self.assertFalse(compare([[None]],[['0']],cols)[0])
        self.assertFalse(compare([['1']],[['NaN']],cols)[0])
        self.assertFalse(compare([['1'],['1']],[['1']],cols,False)[0])

    def test_order_required(self):
        cols=[dict(name='country',type='text',absolute_tolerance='0')]
        self.assertFalse(compare([['UK'],['FR']],[['FR'],['UK']],cols,True)[0])

    def case(self):
        return dict(id='a',category='scope',expected_rows=[['10']],order_sensitive=False,
                    answer_schema=[dict(name='value',type='decimal',absolute_tolerance='0')],required_rules=['scope','time'])

    def pred(self):return dict(id='a',status='success',columns=['value'],rows=[['10']])

    def test_failed_and_missing_count_as_failures(self):
        self.assertFalse(result_score(self.case(),None)[0])
        self.assertFalse(result_score(self.case(),dict(status='timeout'))[0])
        r=score({'a':self.case()},{},{})
        self.assertEqual(r['summary']['query_result_accuracy'],0)
        self.assertEqual(r['summary']['business_accuracy'],0)

    def test_unknown_business_reviews_do_not_make_accuracy(self):
        r=score({'a':self.case()},{'a':self.pred()},{})
        self.assertIsNone(r['summary']['business_accuracy'])
        self.assertFalse(r['summary']['business_review_complete'])

    def test_human_rule_reviews(self):
        review=dict(reviewer_type='human',reviewer='reviewer-1',executed_sql_evidence='trace-1/sql',
                    rules={'R01':dict(passed=True,evidence='where scope checked'),
                           'R02':dict(passed=True,evidence='time checked')})
        self.assertTrue(business_score(self.case(),self.pred(),review)[0])
        review['rules']['R02']['passed']=False
        self.assertFalse(business_score(self.case(),self.pred(),review)[0])
        review['reviewer_type']='llm'
        self.assertIsNone(business_score(self.case(),self.pred(),review)[0])

    def test_renamed_columns_not_silently_accepted(self):
        p=self.pred();p['columns']=['guess']
        self.assertFalse(result_score(self.case(),p)[0])

    def test_duplicate_column_names_rejected(self):
        p=self.pred();p['columns']=['value','value'];p['rows']=[['10','10']]
        self.assertFalse(result_score(self.case(),p)[0])

    def test_generated_public_assets_match_catalog(self):
        for split in ['dev','test']:
            path=OUT/(split+'-questions-v1.jsonl')
            if path.exists():
                saved=[json.loads(x) for x in path.read_text().splitlines()]
                expected=[{k:i[k] for k in ['id','split','category','template_family','question','answer_schema']}
                          for i in self.items if i['split']==split]
                self.assertEqual(saved,expected)

if __name__=='__main__':unittest.main()
