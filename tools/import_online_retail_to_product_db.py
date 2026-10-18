#!/usr/bin/env python3
"""把 UCI Online Retail II 数据集转换成本项目 product_db 示例库可用的 SQL。

数据来源 (CC BY 4.0):
    Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning Repository.
    https://doi.org/10.24432/C5CG6D

用法:
    # 1) 下载数据集: https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip
    #    解压得到 online_retail_II.xlsx (43.5MB, 1,067,371 行, 2009-12-01 ~ 2011-12-09)
    # 2) 生成 SQL（--shift-to-recent 会把时间平移到"上个月"结尾，方便问"上月"）
    python3 tools/import_online_retail_to_product_db.py \
        --excel ~/Downloads/online_retail_II.xlsx \
        --out .vscode/local-run/product_db_retail_II.sql \
        --start-month 2010-12 --shift-to-recent
    # 3) 导入 (注意 utf8mb4)
    mysql -h 127.0.0.1 -P 3306 -uroot -proot --default-character-set=utf8mb4 product_db \
        < .vscode/local-run/product_db_retail_II.sql

映射关系 (源单表 -> 目标五表):
    InvoiceNo+StockCode+Quantity+UnitPrice+InvoiceDate+CustomerID
      -> users(id=CustomerID)              每位客户一条
      -> products(id+1000, name=Description, price=最近一次 UnitPrice)
      -> orders(id, user_id, order_date=该发票最早行时间, total_amount=Σ行金额, status)
      -> order_items(id, order_id, product_id, quantity=Σ数量, unit_price)
    目标库里已有的 products(1..10) 会被保留，新商品从 id=1000 起编号。

状态口径 (与示例库 pending/completed/cancelled 对齐):
    InvoiceNo 以 'C' 开头            -> cancelled (退货/取消)
    时间落在数据集最后一个完整月之后 -> pending   (最近一个月视为未完成)
    其余                             -> completed

注意: 脚本只生成 SQL 文本，不直连数据库，因此不依赖任何 MySQL 驱动。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PRODUCT_ID_OFFSET = 1000
DEFAULT_BATCH = 500


def log(msg: str) -> None:
    print(f"[import] {msg}", flush=True)


def sql_str(value) -> str:
    """把 Python 值转成 SQL 字面量。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "NULL"
    if isinstance(value, (int,)) and not isinstance(value, bool):
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.2f}"
    text = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{text}'"


def shift_to_recent(raw: pd.DataFrame) -> pd.DataFrame:
    """把整体时间平移到"上个月收尾"，让"上月/近三个月"这类相对时间提问有数据可查。

    年月的相对关系保持不变，只按月平移。
    """
    max_date = raw["InvoiceDate"].max()
    now = pd.Timestamp.now()
    target_last_month_end = now.replace(day=1) - pd.Timedelta(days=1)
    months = (target_last_month_end.year - max_date.year) * 12 + (target_last_month_end.month - max_date.month)
    if months == 0:
        return raw
    shifted = raw.copy()
    shifted["InvoiceDate"] = shifted["InvoiceDate"] + pd.DateOffset(months=months)
    log(f"时间平移 {months} 个月: {max_date} -> {shifted['InvoiceDate'].max()} (便于用'上月'提问)")
    return shifted


def load_frame(excel: Path, sheet: str | None, start_month: str | None) -> pd.DataFrame:
    log(f"读取 {excel.name} ...")
    if excel.suffix.lower() in {".xlsx", ".xlsm"}:
        book = pd.ExcelFile(excel, engine="openpyxl")
        sheets = [sheet] if sheet else list(book.sheet_names)
        frames = []
        for name in sheets:
            log(f"  - sheet: {name}")
            frames.append(book.parse(name))
        raw = pd.concat(frames, ignore_index=True)
    else:
        raw = pd.read_csv(excel, encoding="utf-8", encoding_errors="replace")

    raw.columns = [str(c).strip() for c in raw.columns]
    # 兼容不同版本的表头写法
    rename = {}
    for col in raw.columns:
        low = col.lower().replace(" ", "")
        if low == "invoiceno":
            rename[col] = "InvoiceNo"
        elif low == "stockcode":
            rename[col] = "StockCode"
        elif low == "description":
            rename[col] = "Description"
        elif low == "quantity":
            rename[col] = "Quantity"
        elif low == "invoicedate":
            rename[col] = "InvoiceDate"
        elif low == "unitprice":
            rename[col] = "UnitPrice"
        elif low in {"customerid", "customer"}:
            rename[col] = "CustomerID"
    raw = raw.rename(columns=rename)

    need = {"InvoiceNo", "StockCode", "Quantity", "InvoiceDate", "UnitPrice", "CustomerID"}
    missing = need - set(raw.columns)
    if missing:
        raise SystemExit(f"缺少列: {sorted(missing)}；实际列: {list(raw.columns)}")

    raw["InvoiceNo"] = raw["InvoiceNo"].astype(str).str.strip()
    raw["StockCode"] = raw["StockCode"].astype(str).str.strip()
    raw["InvoiceDate"] = pd.to_datetime(raw["InvoiceDate"], errors="coerce")
    raw["Quantity"] = pd.to_numeric(raw["Quantity"], errors="coerce")
    raw["UnitPrice"] = pd.to_numeric(raw["UnitPrice"], errors="coerce")
    raw["CustomerID"] = pd.to_numeric(raw["CustomerID"], errors="coerce")
    if "Description" not in raw.columns:
        raw["Description"] = None

    before = len(raw)
    raw = raw.dropna(subset=["InvoiceDate", "Quantity", "UnitPrice"])
    raw = raw[(raw["Quantity"] > 0) & (raw["UnitPrice"] > 0)]
    raw["Description"] = raw["Description"].fillna("").astype(str).str.strip()
    raw = raw[raw["Description"] != ""]
    log(f"清洗: {before} -> {len(raw)} 行 (去掉缺失/退货/0价/无描述)")

    if start_month:
        start = pd.Timestamp(start_month + "-01")
        raw = raw[raw["InvoiceDate"] >= start]
        log(f"按起始月过滤 {start_month}: 剩余 {len(raw)} 行")

    if raw.empty:
        raise SystemExit("过滤后没有数据，请检查 --start-month")
    return raw


def pick_products(raw: pd.DataFrame) -> pd.DataFrame:
    """每个 StockCode 取最近一次出现的描述与单价作为主数据。"""
    ordered = raw.sort_values("InvoiceDate")
    latest = ordered.drop_duplicates(subset=["StockCode"], keep="last")
    products = latest[["StockCode", "Description", "UnitPrice"]].copy()
    products["product_id"] = range(PRODUCT_ID_OFFSET, PRODUCT_ID_OFFSET + len(products))
    products["price"] = products["UnitPrice"].round(2)
    products["name"] = products["Description"].str.slice(0, 100)
    return products[["product_id", "StockCode", "name", "price"]]


def build_sql(raw: pd.DataFrame, products: pd.DataFrame, batch: int, note: str) -> str:
    code2id = dict(zip(products["StockCode"], products["product_id"]))
    raw = raw.assign(product_id=raw["StockCode"].map(code2id))
    raw["line_amount"] = (raw["Quantity"] * raw["UnitPrice"]).round(2)

    max_date = raw["InvoiceDate"].max()
    last_full_month = (max_date.replace(day=1) - pd.Timedelta(days=1)).to_period("M")
    log(f"数据时间范围: {raw['InvoiceDate'].min()} ~ {max_date}; 最后一个完整月: {last_full_month}")

    out: list[str] = []
    out.append("-- 由 tools/import_online_retail_to_product_db.py 生成")
    out.append(f"-- {note}")
    out.append(f"-- 生成时间: {datetime.now():%Y-%m-%d %H:%M:%S}")
    out.append(f"-- 数据范围: {raw['InvoiceDate'].min()} ~ {max_date}")
    out.append("SET NAMES utf8mb4;")
    out.append("SET FOREIGN_KEY_CHECKS = 1;")
    out.append("START TRANSACTION;")
    out.append("")

    # 1. users
    customers = raw.dropna(subset=["CustomerID"]).copy()
    customers["CustomerID"] = customers["CustomerID"].astype("int64")
    users = (customers.groupby("CustomerID")["InvoiceDate"].min().reset_index()
             .rename(columns={"InvoiceDate": "created_at"}))
    log(f"users: {len(users)}")
    out.append("-- users")
    for _, row in users.iterrows():
        out.append(
            "INSERT INTO users (id, username, email, created_at) VALUES "
            f"({row['CustomerID']}, 'customer_{row['CustomerID']}', "
            f"'{row['CustomerID']}@example.com', {sql_str(row['created_at'].strftime('%Y-%m-%d %H:%M:%S'))}) "
            "ON DUPLICATE KEY UPDATE created_at = VALUES(created_at);"
        )
    out.append("")

    # 2. products
    log(f"products: {len(products)} (id 从 {PRODUCT_ID_OFFSET} 开始)")
    out.append("-- products")
    for _, row in products.iterrows():
        out.append(
            "INSERT INTO products (id, name, price, stock, created_at) VALUES "
            f"({row['product_id']}, {sql_str(row['name'])}, {row['price']:.2f}, 1000, "
            f"{sql_str(raw['InvoiceDate'].min().strftime('%Y-%m-%d %H:%M:%S'))}) "
            "ON DUPLICATE KEY UPDATE name = VALUES(name), price = VALUES(price);"
        )
    out.append("")

    # 3. orders / 4. order_items
    invoices = raw.groupby("InvoiceNo").agg(
        user_id=("CustomerID", "first"),
        order_date=("InvoiceDate", "min"),
        total_amount=("line_amount", "sum"),
    ).reset_index()

    def status_of(invoice_no: str, when: pd.Timestamp) -> str:
        if invoice_no.upper().startswith("C"):
            return "cancelled"
        if when.to_period("M") > last_full_month:
            return "pending"
        return "completed"

    invoices["status"] = [status_of(i, d) for i, d in zip(invoices["InvoiceNo"], invoices["order_date"])]
    invoices["user_id"] = invoices["user_id"].fillna(0).astype("int64")
    log(f"orders: {len(invoices)}")

    out.append("-- orders")
    order_ids = {inv: idx for idx, inv in enumerate(invoices["InvoiceNo"], start=1)}
    lines: list[str] = []
    for _, row in invoices.iterrows():
        lines.append(
            f"({order_ids[row['InvoiceNo']]}, {row['user_id']}, "
            f"{sql_str(row['order_date'].strftime('%Y-%m-%d %H:%M:%S'))}, "
            f"{row['total_amount']:.2f}, '{row['status']}')"
        )
        if len(lines) >= batch:
            out.append("INSERT INTO orders (id, user_id, order_date, total_amount, status) VALUES\n  "
                       + ",\n  ".join(lines) + "\nON DUPLICATE KEY UPDATE total_amount = VALUES(total_amount), status = VALUES(status);")
            lines = []
    if lines:
        out.append("INSERT INTO orders (id, user_id, order_date, total_amount, status) VALUES\n  "
                   + ",\n  ".join(lines) + "\nON DUPLICATE KEY UPDATE total_amount = VALUES(total_amount), status = VALUES(status);")
    out.append("")

    items = raw.groupby(["InvoiceNo", "product_id"]).agg(
        quantity=("Quantity", "sum"),
        unit_price=("UnitPrice", "mean"),
    ).reset_index()
    items["unit_price"] = items["unit_price"].round(2)
    log(f"order_items: {len(items)}")
    out.append("-- order_items")
    lines = []
    item_id = 1
    for _, row in items.iterrows():
        lines.append(
            f"({item_id}, {order_ids[row['InvoiceNo']]}, {int(row['product_id'])}, "
            f"{int(row['quantity'])}, {row['unit_price']:.2f})"
        )
        item_id += 1
        if len(lines) >= batch:
            out.append("INSERT INTO order_items (id, order_id, product_id, quantity, unit_price) VALUES\n  "
                       + ",\n  ".join(lines) + "\nON DUPLICATE KEY UPDATE quantity = VALUES(quantity), unit_price = VALUES(unit_price);")
            lines = []
    if lines:
        out.append("INSERT INTO order_items (id, order_id, product_id, quantity, unit_price) VALUES\n  "
                   + ",\n  ".join(lines) + "\nON DUPLICATE KEY UPDATE quantity = VALUES(quantity), unit_price = VALUES(unit_price);")

    out.append("")
    out.append("COMMIT;")
    out.append("")
    out.append("-- 导入后自检")
    out.append("SELECT COUNT(*) AS users FROM users;")
    out.append("SELECT COUNT(*) AS products FROM products;")
    out.append("SELECT COUNT(*) AS orders FROM orders;")
    out.append("SELECT DATE_FORMAT(order_date, '%Y-%m') AS ym, COUNT(*) AS orders, ROUND(SUM(total_amount), 2) AS amount")
    out.append("FROM orders WHERE status = 'completed' GROUP BY ym ORDER BY ym;")
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Online Retail II -> product_db SQL")
    parser.add_argument("--excel", required=True, type=Path, help="online_retail_II.xlsx 或 csv 路径")
    parser.add_argument("--sheet", default=None, help="xlsx 中要读取的 sheet（默认全部）")
    parser.add_argument("--out", required=True, type=Path, help="输出的 .sql 文件")
    parser.add_argument("--start-month", default="2011-01", help="只导入该月及之后的数据，如 2011-01；留空导入全部")
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH, help="VALUES 每批行数")
    parser.add_argument("--shift-to-recent", action="store_true",
                        help="把整体时间平移到上个月收尾，便于用'上月/近三个月'这类相对时间提问")
    args = parser.parse_args()

    if not args.excel.exists():
        raise SystemExit(f"找不到文件: {args.excel}")

    raw = load_frame(args.excel, args.sheet, args.start_month or None)
    if args.shift_to_recent:
        raw = shift_to_recent(raw)
    products = pick_products(raw)
    sql = build_sql(raw, products, args.batch, note="UCI Online Retail II (CC BY 4.0)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(sql, encoding="utf-8")
    log(f"已写出 {args.out} ({args.out.stat().st_size / 1024 / 1024:.1f} MB)")
    log("导入命令:")
    log(f"  mysql -h 127.0.0.1 -P 3306 -uroot -proot --default-character-set=utf8mb4 product_db < {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
