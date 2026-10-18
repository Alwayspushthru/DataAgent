import unittest
from datetime import datetime
from decimal import Decimal
from pipeline import normalize, escape, unescape, canonical

class NormalizationTest(unittest.TestCase):
    def row(self, **kwargs):
        d=dict(invoice='1',stock='A',description='商品',quantity=1,date=datetime(2011,1,1),price=10,customer=None,country='UK')
        d.update(kwargs)
        return normalize(list(d.values()),1,'Year 2010-2011',2)

    def test_cancel_and_negative_retained(self):
        r=self.row(invoice='C1',quantity=-2)
        self.assertEqual(r[11:13],['1','-20.000000'])

    def test_missing_customer_remains_null(self):
        self.assertIsNone(self.row()[9])

    def test_different_prices_preserve_amount(self):
        a,b=self.row(quantity=1,price=10),self.row(quantity=9,price=20)
        self.assertEqual(Decimal(a[12])+Decimal(b[12]),190)

    def test_invalid_values_quarantined(self):
        for changes in [dict(date=None),dict(quantity=1.5),dict(price='NaN'),dict(invoice=None)]:
            with self.assertRaises(ValueError): self.row(**changes)

    def test_roundtrip_special_text(self):
        for v in [None,'NULL',r'\N','a\tb\nc\\d\r','中文']:
            self.assertEqual(unescape(escape(v)),v)

    def test_zero_price_retained(self):
        self.assertEqual(self.row(price=0)[12],'0.000000')

    def test_signed_zero_canonical_equivalence(self):
        a=self.row(quantity=-1,price=0); b=list(a); b[12]='0.000000'
        self.assertEqual(canonical(a),canonical(b))

if __name__=='__main__': unittest.main()
