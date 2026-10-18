"""Reproducible UCI retail snapshot. Python 3 + openpyxl; Docker MySQL CLI.

No existing database is overwritten. Raw workbook rows are retained as JSONL.
Amounts use Decimal at 6 decimal places; no deduplication or date shifting.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zipfile import ZipFile

SCALE = Decimal('0.000001')
FIELDS = ['line_id','source_sheet','source_row','invoice_no','stock_code','description',
          'quantity','invoice_date','unit_price','customer_id','country','is_cancelled','line_amount']

def file_sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def text(v):
    if v is None: return None
    if isinstance(v, float) and v.is_integer(): return str(int(v))
    return str(v).strip()

def normalize(values, line_id, sheet, row):
    """Return normalized line or an explicit quarantine reason."""
    inv, code, desc, qty, date, price, customer, country = values
    inv, code = text(inv), text(code)
    if not inv or not code: raise ValueError('missing_invoice_or_stock_code')
    if not isinstance(date, datetime): raise ValueError('invalid_date')
    try:
        q, p = Decimal(str(qty)), Decimal(str(price))
        if not q.is_finite() or not p.is_finite(): raise ValueError('nonfinite_numeric')
        if q != q.to_integral_value(): raise ValueError('fractional_quantity')
        if p != p.quantize(SCALE): raise ValueError('price_precision_exceeds_6')
        amount = q * p
        if abs(q) >= 2**63 or abs(p) >= Decimal('1e14') or abs(amount) >= Decimal('1e18'):
            raise ValueError('numeric_out_of_range')
    except (InvalidOperation, TypeError):
        raise ValueError('invalid_numeric')
    return [str(line_id), sheet, str(row), inv, code, text(desc), str(int(q)),
            date.strftime('%Y-%m-%d %H:%M:%S'), format(p.quantize(SCALE),'f'),
            text(customer), text(country), str(int(inv.upper().startswith('C'))),
            format(amount.quantize(SCALE),'f')]

def canonical(row):
    row=list(row)
    # Decimal has signed zero; MySQL DECIMAL does not. Their numeric value is identical.
    for index in (8,12):
        if Decimal(row[index]) == 0: row[index]='0.000000'
    return json.dumps(row, ensure_ascii=False, separators=(',',':')) + '\n'

def escape(v):
    if v is None: return r'\N'
    return str(v).replace('\\','\\\\').replace('\0',r'\0').replace('\t',r'\t').replace('\n',r'\n').replace('\r',r'\r')

def unescape(v):
    if v == r'\N': return None
    return re.sub(r'\\(.)', lambda m: {'n':'\n','r':'\r','t':'\t','0':'\0','\\':'\\'}.get(m[1],m[1]),v)

def prepare(args):
    import openpyxl
    out = args.work
    out.mkdir(parents=True, exist_ok=True)
    if (out/'manifest.json').exists(): raise SystemExit('Manifest exists; use a fresh work directory.')
    source = args.source
    if source.suffix == '.zip':
        with ZipFile(source) as z:
            names = [n for n in z.namelist() if n.endswith('.xlsx')]
            if len(names) != 1: raise ValueError('Expected exactly one workbook')
            workbook = out/'source.xlsx'
            with z.open(names[0]) as src, workbook.open('wb') as dst:
                import shutil
                shutil.copyfileobj(src,dst)
    else: workbook = source
    book = openpyxl.load_workbook(workbook, read_only=True, data_only=True)
    counts = Counter(); flags = Counter(); months = defaultdict(lambda:[0,Decimal(0)])
    invoices = defaultdict(lambda:[0,Decimal(0)])
    digest = hashlib.sha256()
    with (out/'lines.tsv').open('w') as data, (out/'raw.jsonl').open('w') as raw, (out/'quarantine.jsonl').open('w') as bad:
        for sheet in book:
            rows = sheet.iter_rows(values_only=True)
            header = [re.sub(r'\s','',str(c)).lower() for c in next(rows)]
            aliases = [('invoice','invoiceno'),('stockcode',),('description',),('quantity',),
                       ('invoicedate',),('price','unitprice'),('customerid',),('country',)]
            indices = [next((header.index(k) for k in group if k in header),None) for group in aliases]
            if None in indices: raise ValueError(f'Unsupported header: {header}')
            for rowno, values in enumerate(rows,2):
                counts['source_rows'] += 1
                original = {'sheet':sheet.title,'row':rowno,'values':list(values)}
                raw.write(json.dumps(original,ensure_ascii=False,default=str)+'\n')
                try: line = normalize([values[i] for i in indices],counts['source_rows'],sheet.title,rowno)
                except ValueError as ex:
                    counts['quarantined'] += 1
                    bad.write(json.dumps({'sheet':sheet.title,'row':rowno,'reason':str(ex)})+'\n')
                    continue
                counts['accepted'] += 1
                flags['missing_customer'] += int(line[9] is None or line[9]=='')
                flags['missing_description'] += int(not line[5])
                flags['nonpositive_quantity'] += int(int(line[6])<=0)
                flags['nonpositive_price'] += int(Decimal(line[8])<=0)
                flags['cancelled_lines'] += int(line[11])
                data.write('\t'.join(escape(v) for v in line)+'\n')
                digest.update(canonical(line).encode())
                for target,key in [(months,line[7][:7]+'|'+line[11]),(invoices,line[3])]:
                    target[key][0]+=1; target[key][1]+=Decimal(line[12])
            print(f'Prepared {sheet.title}: {counts}',flush=True)
    book.close()
    manifest = {'dataset':'UCI Online Retail II','source_url':'https://doi.org/10.24432/C5CG6D',
        'license':'CC BY 4.0','download_url':args.download_url,'source_file':source.name,
        'source_sha256':file_sha256(source),
        'workbook_sha256':file_sha256(workbook),
        'counts':dict(counts),'flags':dict(flags),'canonical_sha256':digest.hexdigest(),
        'amount_scale':6,'rules':'retain all parseable rows; no deduplication, no status inference, no time shift'}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    for name,obj in [('months',months),('invoices',invoices)]:
        (out/(name+'.json')).write_text(json.dumps({k:[v[0],format(v[1].quantize(SCALE),'f')] for k,v in obj.items()},ensure_ascii=False))
    print(json.dumps(manifest,ensure_ascii=False,indent=2))

def command(args, sql):
    password = os.environ.get('RETAIL_MYSQL_PASSWORD')
    if not password: raise SystemExit('Set RETAIL_MYSQL_PASSWORD for the local MySQL administrator.')
    env = dict(os.environ,MYSQL_PWD=password)
    cmd = ['docker','exec','-i','-e','MYSQL_PWD',args.container,'mysql','--default-character-set=utf8mb4',
           '--local-infile=1','--batch','--skip-column-names','-u'+args.user]
    return subprocess.run(cmd,input=sql,text=True,capture_output=True,env=env,check=True).stdout

def install(args):
    db=args.database
    if command(args,f"SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='{db}';").strip():
        raise SystemExit('Database already exists; verify it or use a fresh database name. No overwrite.')
    staging='/tmp/'+db+'_lines.tsv'
    subprocess.run(['docker','cp',str(args.work/'lines.tsv'),args.container+':'+staging],check=True)
    local=command(args,'SELECT @@GLOBAL.local_infile;').strip()
    try:
        command(args,'SET GLOBAL local_infile=ON;')
        output=command(args,f'''CREATE DATABASE `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
USE `{db}`;
CREATE TABLE transaction_lines (
line_id BIGINT PRIMARY KEY, source_sheet VARCHAR(100) NOT NULL, source_row INT NOT NULL,
invoice_no VARCHAR(100) NOT NULL, stock_code VARCHAR(100) NOT NULL, description TEXT NULL,
quantity BIGINT NOT NULL, invoice_date DATETIME NOT NULL, unit_price DECIMAL(20,6) NOT NULL,
customer_id VARCHAR(100) NULL, country VARCHAR(200) NULL, is_cancelled TINYINT NOT NULL,
line_amount DECIMAL(24,6) NOT NULL,
UNIQUE KEY source_position(source_sheet,source_row), INDEX(invoice_no), INDEX(stock_code),
INDEX(customer_id), INDEX(invoice_date));
LOAD DATA LOCAL INFILE '{staging}' INTO TABLE transaction_lines CHARACTER SET utf8mb4
FIELDS TERMINATED BY '\\t' ESCAPED BY '\\\\' LINES TERMINATED BY '\\n';
SHOW COUNT(*) WARNINGS;
CREATE VIEW invoices AS SELECT invoice_no,MIN(invoice_date) first_line_at,MAX(invoice_date) last_line_at,
COUNT(*) line_count,SUM(line_amount) total_amount,MAX(is_cancelled) is_cancelled,
COUNT(DISTINCT customer_id) customer_id_count FROM transaction_lines GROUP BY invoice_no;
CREATE VIEW customers AS SELECT customer_id,MIN(invoice_date) first_observed_at,
MAX(invoice_date) last_observed_at FROM transaction_lines WHERE customer_id IS NOT NULL AND customer_id<>'' GROUP BY customer_id;
CREATE VIEW products AS SELECT stock_code,COUNT(DISTINCT description) description_variants
FROM transaction_lines GROUP BY stock_code;
''')
        (args.work/'import_warnings.txt').write_text(output)
        if output.strip() != '0': raise RuntimeError('MySQL import warnings detected; inspect import_warnings.txt')
    finally:
        command(args,'SET GLOBAL local_infile='+('ON' if local=='1' else 'OFF')+';')
    print('Imported '+db+'; run verify before use.')

def verify(args):
    manifest=json.loads((args.work/'manifest.json').read_text()); db=args.database
    expressions=[f"IF({f} IS NULL,'N',CONCAT('V',{f}))" for f in FIELDS]
    rows=command(args,f"SELECT {','.join(expressions)} FROM `{db}`.transaction_lines ORDER BY line_id;")
    digest=hashlib.sha256(); count=0
    for row in rows.splitlines():
        fields=[None if v=='N' else unescape(v[1:]) for v in row.split('\t')]
        digest.update(canonical(fields).encode()); count+=1
    checks={'row_count':count==manifest['counts']['accepted'],
            'source_accounting':manifest['counts']['source_rows']==count+manifest['counts'].get('quarantined',0),
            'all_fields_sha256':digest.hexdigest()==manifest['canonical_sha256']}
    for name,query in [('months',"SELECT CONCAT(DATE_FORMAT(invoice_date,'%Y-%m'),'|',is_cancelled),COUNT(*),SUM(line_amount) FROM transaction_lines GROUP BY 1"),
                       ('invoices','SELECT invoice_no,line_count,total_amount FROM invoices')]:
        actual={}
        for line in command(args,f'USE `{db}`;'+query+';').splitlines():
            k,n,amount=line.split('\t'); actual[unescape(k)]=[int(n),format(Decimal(amount).quantize(SCALE),'f')]
        checks[name+'_reconciliation']=actual==json.loads((args.work/(name+'.json')).read_text())
    checks['line_amount_identity']=command(args,f'SELECT COUNT(*) FROM `{db}`.transaction_lines WHERE line_amount<>quantity*unit_price;').strip()=='0'
    checks['customer_references']=command(args,f"SELECT COUNT(*) FROM `{db}`.transaction_lines l LEFT JOIN `{db}`.customers c ON l.customer_id=c.customer_id WHERE l.customer_id IS NOT NULL AND l.customer_id<>'' AND c.customer_id IS NULL;").strip()=='0'
    checks['product_references']=command(args,f'SELECT COUNT(*) FROM `{db}`.transaction_lines l LEFT JOIN `{db}`.products p ON l.stock_code=p.stock_code WHERE p.stock_code IS NULL;').strip()=='0'
    profile=command(args,f'''USE `{db}`;
SELECT 'invoices',COUNT(*) FROM invoices;
SELECT 'customers',COUNT(*) FROM customers;
SELECT 'products',COUNT(*) FROM products;
SELECT 'mixed_customer_invoices',COUNT(*) FROM invoices WHERE customer_id_count>1;
SELECT 'date_min',MIN(invoice_date) FROM transaction_lines;
SELECT 'date_max',MAX(invoice_date) FROM transaction_lines;
SELECT 'signed_total_amount',SUM(line_amount) FROM transaction_lines;
''')
    report={'database':db,'source_sha256':manifest['source_sha256'],'counts':manifest['counts'],
            'profile':dict(line.split('\t',1) for line in profile.splitlines()),
            'checks':checks,'passed':all(checks.values()),'verified_at':datetime.now().isoformat()}
    (args.work/'verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    if not report['passed']: raise SystemExit(1)

def main():
    p=argparse.ArgumentParser(); p.add_argument('action',choices=['prepare','import','verify'])
    p.add_argument('--work',type=Path,default=Path('.vscode/retail-eval/v1'))
    p.add_argument('--source',type=Path); p.add_argument('--database',default='retail_eval_v1')
    p.add_argument('--download-url',default='https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip')
    p.add_argument('--container',default='dataagent-local-mysql'); p.add_argument('--user',default='root')
    p.add_argument('--credentials',type=Path,help='Local JSON credentials for read-only verify')
    args=p.parse_args()
    if args.credentials:
        if args.action!='verify': p.error('--credentials is for verify only')
        c=json.loads(args.credentials.read_text())
        args.user=c['username'];args.database=c['database']
        os.environ['RETAIL_MYSQL_PASSWORD']=c['password']
    if not re.fullmatch(r'retail_eval_[a-zA-Z0-9_]+',args.database): p.error('Database must start with retail_eval_')
    if args.action=='prepare' and not args.source: p.error('--source required')
    {'prepare':prepare,'import':install,'verify':verify}[args.action](args)

if __name__=='__main__': main()
