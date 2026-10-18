import json
import sqlite3
import unittest
from datetime import datetime
from decimal import Decimal

from knowledge import load_contract, validate, export, ROOT
from pipeline import normalize
from validate_knowledge import reference, sql, mom

class KnowledgeTest(unittest.TestCase):
    def setUp(self):
        # Same invoice repeated lines, anonymous sales, cancellations, zero/negative
        # quantities, changed descriptions and prices, exact period boundaries.
        values=[
            ('A','X','first',1,datetime(2011,6,1),10,'U','UK'),
            ('A','X','changed',9,datetime(2011,6,1),20,'U','FR'),
            ('B','Y',None,2,datetime(2011,6,15),5,'U','UK'),
            ('D','Z','anon',1,datetime(2011,6,30,23,59,59),30,None,None),
            ('E','Z','blank',1,datetime(2011,6,10),5,' ','UK'),
            ('C1','X','cancel',-1,datetime(2011,6,2),10,'U','UK'),
            ('F','X','negative',-1,datetime(2011,6,2),20,'U','UK'),
            ('G','X','zero',1,datetime(2011,6,2),0,'U','UK'),
            ('H','X','outside',1,datetime(2011,7,1),100,'V','UK'),
        ]
        self.lines=[normalize(v,i,'fixture',i+1) for i,v in enumerate(values,1)]
        self.result=reference(self.lines,'2011-06-01','2011-07-01')

    def test_schema_and_aliases(self):
        self.assertEqual(validate(load_contract())['metrics'],18)

    def test_sales_excludes_cancel_negative_zero(self):
        self.assertEqual(self.result['M04'],235)
        self.assertEqual(self.result['M03'],5)

    def test_raw_signed_amount_retained(self):
        self.assertEqual(self.result['M02'],205)

    def test_unknown_customer_scope_matches_denominator(self):
        self.assertEqual(self.result['M07'],1)
        self.assertEqual(self.result['M08'],200)
        self.assertEqual(self.result['M10'],200)
        self.assertEqual(self.result['M17'],35)

    def test_repurchase_distinct_invoices(self):
        self.assertEqual(self.result['M06'],4)
        self.assertEqual(self.result['M11'],1)
        only_a=self.lines[:2]
        self.assertEqual(reference(only_a,'2011-06-01','2011-07-01')['M11'],0)

    def test_weighted_price(self):
        self.assertEqual(self.result['M14'],Decimal(235)/14)

    def test_sku_not_description(self):
        self.assertEqual(self.result['M13'],3)

    def test_cancel_not_refund(self):
        self.assertEqual(self.result['M15'],1)
        self.assertEqual(self.result['M16'],-10)

    def test_empty_semantics(self):
        r=reference(self.lines,'2012-01-01','2012-02-01')
        for key in ['M01','M03','M06','M07','M11','M13','M15']:self.assertEqual(r[key],0)
        for key in ['M02','M04','M05','M08','M09','M10','M12','M14','M16','M17','M18']:self.assertIsNone(r[key])

    def test_anonymous_only(self):
        r=reference(self.lines[3:5],'2011-06-01','2011-07-01')
        self.assertEqual(r['M18'],0)
        self.assertIsNone(r['M10'])
        self.assertIsNone(r['M12'])

    def test_half_open_boundary(self):
        self.assertEqual(reference(self.lines,'2011-07-01','2011-08-01')['M04'],100)

    def test_mom_zero_and_null(self):
        self.assertIsNone(mom(Decimal(5),ZERO:=Decimal(0)))
        self.assertIsNone(mom(None,Decimal(5)))
        self.assertEqual(mom(Decimal(15),Decimal(10)),Decimal('.5'))

    def test_sql_matches_hand_checked_fixture(self):
        db=sqlite3.connect(':memory:')
        db.execute('CREATE TABLE transaction_lines (line_id INT, source_sheet TEXT, source_row INT, invoice_no TEXT, stock_code TEXT, description TEXT, quantity INT, invoice_date TEXT, unit_price NUMERIC, customer_id TEXT, country TEXT, is_cancelled INT, line_amount NUMERIC)')
        db.executemany('INSERT INTO transaction_lines VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',self.lines)
        # SQLite integer division differs from MySQL decimal division.
        query=sql('2011-06-01','2011-07-01').replace('m04/','1.0*m04/').replace('m08/','1.0*m08/').replace('COALESCE(m08,0)/','1.0*COALESCE(m08,0)/')
        for i,actual in enumerate(db.execute(query).fetchone(),1):
            expected=self.result[f'M{i:02}']
            if expected is None:self.assertIsNone(actual)
            else:self.assertAlmostEqual(float(expected),float(actual),places=6)
        db.close()

    def test_export_has_no_private_oracle(self):
        rows=export(load_contract(),123)
        self.assertEqual(len(rows),24)
        for row in rows:
            self.assertEqual(set(row),{'businessTerm','description','synonyms','isRecall','agentId'})
            self.assertEqual(row['agentId'],123)
            self.assertNotIn('reference_sql',json.dumps(row))

    def test_checked_in_rag_export_matches_contract(self):
        saved=json.loads((ROOT/'knowledge/rag-documents-v1.json').read_text())
        self.assertEqual(saved,export(load_contract()))

    def test_ambiguous_terms_are_not_automatic_aliases(self):
        c=load_contract()
        names={a for m in c['metrics'] for a in [m['name']]+m['aliases']}
        self.assertTrue(set(c['ambiguous_terms']).isdisjoint(names))

if __name__=='__main__':unittest.main()
