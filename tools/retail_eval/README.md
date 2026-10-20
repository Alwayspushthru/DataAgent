# 独立零售测试库与对账

当前评审采纳遵循[业务口径评审规则 v2](REVIEW_POLICY.md)：AI明确通过/失败直接采纳，仅明确标注的例外项需要人工裁定。保留AI审核来源，历史冻结评分器和原始成绩不覆盖。

2026-10-20使用精度改进版完成新一轮开发集回归：查询正确率OFF 12%、ON 72%；业务口径OFF 0%、ON 67.5%，没有待人工裁定项。相比v2整体成绩回退，精度修正已有实际SQL证据，剩余问题集中在知识覆盖、规划及结构化输出。详见[最新v3回归摘要](reports/development-full-v3-summary-2026-10-20.md)。

历史v2的四项例外于2026-10-19由用户裁定通过，v2口径结果为OFF 0/40、ON 32/40；完整本地报告位于`tools/retail_eval/reports/development-full-v2-business-final-2026-10-19.md`（Git忽略）。该历史结果及例外不外推至v3。

比率精度改进已接入SQL生成、修复及审计提示，验证方法与边界见[比率计算精度说明](RATIO_PRECISION.md)。

本目录已完成数据层、[业务知识定义 v1.0.0](knowledge/README.md)和[50道开发题、500道正式题及评分规则](benchmark/README.md)。知识开关、执行采集、开发题评分与复核操作见[开发评测说明](DEVELOPMENT_RUN.md)。开发试跑与正式500题成绩严格区分，业务口径正确率需完成实际SQL的逐规则评审。

开发集v2和v3均分别跑完50道题的OFF/ON对照，每轮100份记录。历史情况见[开发集v2脱敏验收摘要](reports/development-full-v2-summary-2026-10-18.md)，最新情况见上方v3入口。

## 数据与语义边界

- 来源：UCI Online Retail II，https://doi.org/10.24432/C5CG6D ，CC BY 4.0。
- 保留两张工作表全部可解析记录，不去重、不平移日期、不生成完成/待付款状态。
- `is_cancelled` 仅来自发票号 C 前缀；负数量和零/负价格保留。
- `line_amount` 是有符号的原始数量乘单价，并非自动定义为“成交额”或“净收入”。
- 金额使用 DECIMAL 和 Python Decimal，保留 6 位小数，不用浮点平均单价。
- 每行保存 source_sheet/source_row，可在原始 Excel 和 raw.jsonl 中追溯。
- 无法解析的行写 quarantine.jsonl；客户/描述缺失保留 NULL，不伪造客户。
- customers.first_observed_at 是本数据中的首次出现时间，不是注册时间。
- invoices 按原始发票号汇总，customer_id_count 提示同发票多个客户，不武断选一个客户。
- products 不强制选择所谓“最新商品名/当前价格”，名称与价格留在明细。

## 表接口

| 表/视图 | 粒度与连接键 |
|---|---|
| transaction_lines | 每条源记录一行，主键 line_id；来源位置唯一 |
| invoices | 每个 invoice_no 一行，含明细数、有符号金额、时间范围 |
| customers | 每个非空 customer_id 一行 |
| products | 每个 stock_code 一行，含名称变体数 |

逻辑关系：transaction_lines.invoice_no → invoices.invoice_no；customer_id → customers.customer_id（允许缺失）；stock_code → products.stock_code。后三张是从事实表派生的视图，可能需要在 DataAgent 中核验视图发现支持；直接查询事实表不依赖视图支持。

没有新增 HTTP API。接口是 MySQL SQL 与命令行。

## 本次交付的连接与测试入口

- 地址：127.0.0.1:3306；库：retail_eval_v1；账号：retail_eval_reader。
- 密码和 JDBC URL：`.vscode/retail-eval/connection.json`（0600，只读账号，仅授权本测试库）。
- 本次正式清单与对账报告：`.vscode/retail-eval/frozen/`。
- 原始数据实际从公开 GitHub 镜像下载，清单记录 URL 与 SHA256；尚未与官方文件做全量哈希比对。
- SQL 快照：`.vscode/retail-eval/retail_eval_v1.sql.gz`，校验值在 snapshot.json。
- `v1/` 是最初导入材料，`frozen/` 是修正 Decimal 负零规范化后的正式清单，两者入库 TSV 完全相同。应以 frozen/verification.json 为最终结论。
- `retail_eval_smoke_v1` 是独立边界测试库，不用于业务问数。

复核现有库无需输入管理员密码：

```bash
python3 tools/retail_eval/pipeline.py verify \
  --work .vscode/retail-eval/frozen \
  --credentials .vscode/retail-eval/connection.json
```

在 DataAgent 新增 MySQL 数据源时填写上述地址、库名、用户名和本地文件中的密码，再进行连接测试和元数据初始化。本次未改写应用内的数据源配置，也未发起模型调用。

## 环境

Python 3.9+，openpyxl 3.1.5；Docker Desktop，本地容器 dataagent-local-mysql（MySQL）。
如果系统 Python 缺少依赖，可建立专用虚拟环境安装 `openpyxl==3.1.5`。
数据库默认 retail_eval_v1；仅允许 retail_eval_ 前缀。已经存在的库一律拒绝覆盖。

## 完整流程（在项目根目录执行）

```bash
# 数据下载到被 Git 忽略的本地目录
mkdir -p .vscode/retail-eval/raw
curl -L --fail -o .vscode/retail-eval/raw/online_retail_II.zip \
  'https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip'

# python3 应指向安装了 openpyxl 的 Python 3.9+
python3 tools/retail_eval/pipeline.py prepare \
  --source .vscode/retail-eval/raw/online_retail_II.zip \
  --work .vscode/retail-eval/v1

# 交互输入本机 MySQL 管理员密码，勿写入 Git
read -s RETAIL_MYSQL_PASSWORD
export RETAIL_MYSQL_PASSWORD
python3 tools/retail_eval/pipeline.py import --work .vscode/retail-eval/v1
python3 tools/retail_eval/pipeline.py verify --work .vscode/retail-eval/v1
unset RETAIL_MYSQL_PASSWORD
```

prepare 遇到现有 manifest 拒绝覆盖；重建请用新工作目录和 `--database retail_eval_v2`。import 临时打开 MySQL local_infile 并在 finally 恢复原值，不修改已有业务库。不要对已冻结库执行写操作。

## 如何测试

```bash
python3 -m unittest discover -s tools/retail_eval -p 'test_*.py' -v
# 设置 RETAIL_MYSQL_PASSWORD 后，对完整库重复核验：
python3 tools/retail_eval/pipeline.py verify --work .vscode/retail-eval/v1
```

verify 失败退出码为 1，成功为 0。检查 verification.json 中 passed=true 且 checks 全为 true。
覆盖：记录守恒、逐字段规范化 SHA256、逐发票金额/行数、逐月×取消标记金额/行数、逐行金额等式、客户与商品关联。
相同参数再次 import 应拒绝覆盖；验证真正可复现性应在新目录 prepare、导入新库并比较 canonical_sha256 与对账结果。

```sql
SELECT COUNT(*), MIN(invoice_date), MAX(invoice_date) FROM transaction_lines;
SELECT DATE_FORMAT(invoice_date,'%Y-%m') AS month, is_cancelled,
       COUNT(*) AS line_count, SUM(line_amount) AS signed_amount
FROM transaction_lines GROUP BY month,is_cancelled ORDER BY month,is_cancelled;
SELECT COUNT(*) FROM transaction_lines WHERE line_amount <> quantity*unit_price;
SELECT * FROM invoices WHERE customer_id_count > 1 LIMIT 20;
```

## 本地产物（不提交 Git）

- raw.jsonl：原始单元格记录，日期序列化为文本。
- source.xlsx：从官方 ZIP 提取的工作簿。
- lines.tsv：入库明细。
- quarantine.jsonl：无法规范化的源行及原因。
- manifest.json：源文件哈希、行数、缺失/异常标记及明细哈希。
- invoices.json / months.json：源端 Decimal 汇总参考。
- import_warnings.txt：MySQL 入库警告数，必须为 0。
- verification.json：实际 MySQL 对账结果。

校验保证源数据到数据库的转换一致性，不保证源数据本身无业务问题。原始重复行不自动删除；退款与原销售的匹配、异常价格是否排除，应留给后续明确的业务定义。
