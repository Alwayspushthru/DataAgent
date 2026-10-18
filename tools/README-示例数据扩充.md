# 示例数据扩充：用开源数据集喂饱 product_db

当前 `product_db` 只有 10 条订单（`order_date` 集中在 2025-06-01 ~ 2025-06-07），
所以"上月各产品的增长情况"这类问题要么返回空、要么无法做环比。
下面是可直接落地的开源数据集方案，以及配套的导入脚本。

## 一、推荐数据集

| 数据集 | 规模 / 时间跨度 | 许可 | 适合本项目的点 | 不足 |
|---|---|---|---|---|
| **UCI Online Retail II**（首选） | 1,067,371 行，2009-12-01 ~ 2011-12-09 | CC BY 4.0 | 单表就含 发票号/商品码/商品名/数量/单价/时间/客户ID，**天然可拆成 users/products/orders/order_items**；25 个月数据，能算真实的月度环比 | 无商品分类、无用户注册时间；英国礼品批发场景 |
| Olist Brazilian E-Commerce | 约 10 万订单，2016-09 ~ 2018-10 | Kaggle CC BY-NC-SA 4.0（**禁商用**） | 9 张表（订单/明细/商品/客户/卖家/支付/评价/分类），最接近真实多表电商库 | 商品名与分类是葡萄牙语，需翻译；许可限制商用 |
| Kaggle Store Sales - Time Series | 约 300 万行，2013-01-01 ~ 2017-08-15 | 竞赛数据，CC0 / 公有领域 | 按 门店×商品族×日期 的销售额与促销，做"商品族月度走势"很规整 | 是聚合后的销售事实表，不是订单明细，无法拆出 users/orders |

仅做用户行为分析（不适合"订单/商品"口径）：天池 [淘宝用户购物行为数据集](https://tianchi.aliyun.com/dataset/649)（UserBehavior，约 1 亿条 PV/加购/收藏/购买日志）。

## 二、字段映射（Online Retail II → product_db）

源表一行 = 发票中的一行商品：

```
InvoiceNo, StockCode, Description, Quantity, InvoiceDate, UnitPrice, CustomerID, Country
```

转换成：

| 目标表 | 来源与口径 |
|---|---|
| `users` | `CustomerID` 去重，`username = customer_<id>`，`created_at` = 该客户最早一次下单时间 |
| `products` | `StockCode` 去重（取最近一次出现的描述与单价作主数据），`id` 从 **1000** 起编号，避免撞上原有 1~10 |
| `orders` | 按 `InvoiceNo` 分组：`order_date` = 该发票最早行时间，`total_amount` = Σ(`Quantity`×`UnitPrice`) |
| `order_items` | 按 (`InvoiceNo`,`StockCode`) 聚合：`quantity` = Σ数量，`unit_price` = 平均单价 |
| `orders.status` | `InvoiceNo` 以 `C` 开头 → `cancelled`；落在数据集最后一个完整月之后 → `pending`；其余 → `completed` |
| `product_categories` | 源数据无分类信息，保持为空（如需演示分类，可另接 Olist 或手工补几条映射） |

清洗规则：丢弃 `InvoiceDate/Quantity/UnitPrice` 缺失、`Quantity <= 0`（退货）、`UnitPrice <= 0`、`Description` 为空的行。

## 三、导入步骤

```bash
# 1) 下载并解压（43.5MB xlsx）
#    https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip

# 2) 生成 SQL（约 1~2 分钟）
#    --start-month 控制导入量；--shift-to-recent 把时间平移到"上个月"结尾，
#    这样"上月/近三个月"这类相对时间提问才有数据
python3 tools/import_online_retail_to_product_db.py \
    --excel ~/Downloads/online_retail_II.xlsx \
    --out .vscode/local-run/product_db_retail_II.sql \
    --start-month 2010-12 --shift-to-recent

# 3) 导入（本机演示库：127.0.0.1:3306 root/root，库 product_db）
mysql -h 127.0.0.1 -P 3306 -uroot -proot --default-character-set=utf8mb4 product_db \
    < .vscode/local-run/product_db_retail_II.sql
```

脚本只生成 SQL 文本、不直连数据库，所以不依赖任何 MySQL 驱动或第三方包，用系统 Python 即
可运行。SQL 尾部自带自检查询（各表行数 + 按月的成交额分布）。

### 常用参数

| 参数 | 说明 |
|---|---|
| `--excel` | `online_retail_II.xlsx` 或 csv 路径 |
| `--sheet` | 只读某个 sheet（默认两个 sheet 全读） |
| `--start-month` | 只导入该月及之后，如 `2011-01`；留空 = 全部 |
| `--shift-to-recent` | 整体时间平移，使最后一批数据落在上个月 |
| `--batch` | 每条 INSERT 的 VALUES 行数，默认 500 |

## 四、导入之后要做的三件事

1. **重新初始化数据源**：通用设置 → 数据连接 → 右上角「初始化当前智能体数据源」。
   schema 没变时也建议做一次，确保新表/新行进入向量库（表结构若改了则必须做）。
2. **补语义模型**：新商品名是英文长描述（如 `WHITE HANGING HEART T-LIGHT HOLDER`），
   在 `知识库管理 → 语义模型配置` 里给 `products.name` 补业务名称与同义词，NL2SQL 命中率会明显提高。
3. **在业务知识里钉死口径**：例如
   「增长 = 本月成交金额 / 上月成交金额 - 1；成交金额 = orders 中 status='completed' 的
   Σ(order_items.quantity × order_items.unit_price)；商品维度经 order_items.product_id 关联 products」。

## 五、已知取舍

- 时间平移后月度环比真实，但**绝对日期不再是历史真实日期**（仅用于演示）。
- 商品是为批发礼品，单笔 quantity 可能很大；如需更贴近零售场景，可在导入时对 quantity 做截断。
- 许可：UCI 数据需保留出处（CC BY 4.0）。若产品要商用演示，避免使用 Olist 的 NC 数据。

---

## 六、另外三个数据源的适用性判断（Chinook / BIRD Mini-Dev / Spider 2.0）

结论：三者角色完全不同——**Chinook 是"业务演示库"，BIRD Mini-Dev 是"NL2SQL 评测集"，Spider 2.0 是"能力上限基准"，只有第一个适合当数据源**。

### 1. Chinook —— ✅ 强烈推荐，最适合当第二个示例数据源

- 音乐商店示例库，11 张表（`Customer / Invoice / InvoiceLine / Track / Album / Artist / Genre / MediaType / Playlist / PlaylistTrack / Employee`），
  销售数据是**随机生成的四整年**，Media 数据来自真实 iTunes Library（[官方仓库](https://github.com/lerocha/chinook-database)）。
- 官方直接提供各数据库脚本，导入 MySQL 只需两步：
  ```bash
  curl -LO https://raw.githubusercontent.com/lerocha/chinook-database/master/ChinookDatabase/DataSources/Chinook_MySql.sql
  mysql -h 127.0.0.1 -P 3306 -uroot -proot --default-character-set=utf8mb4 -e "CREATE DATABASE chinook DEFAULT CHARACTER SET utf8mb4"
  mysql -h 127.0.0.1 -P 3306 -uroot -proot --default-character-set=utf8mb4 chinook < Chinook_MySql.sql
  ```
- 为什么适合本项目：
  - 有**真实的 4 年月度销售数据**（`Invoice.InvoiceDate` + `InvoiceLine.Quantity/UnitPrice`），"各流派/各媒体类型的销售额环比增长"这类问题天然可答；
  - 表名字段名是标准英文（`Total`、`UnitPrice`、`InvoiceDate`），语义模型/Business Knowledge 好配，NL2SQL 命中率高；
  - 体量很小（入库秒级），反复"重新初始化数据源"几乎没有成本，适合压测 schema 召回；
  - 官方定位就是 demo/testing 工具，稳定性好。
- 需要注意：
  - 它不是电商（无库存、无订单状态、无分类/退货概念），想验证 `status='completed'` 这类口径还得用 product_db；
  - 需要给 DataAgent 的语义模型补英文列的业务名/同义词（例如 `Invoice.Total` → 成交金额、`Track.Name` → 曲目）；
  - 仓库 `license` 字段是 `NOASSERTION`，用前在仓库根目录确认 LICENSE 文本，商用前自行过一遍法务口径。

### 2. BIRD Mini-Dev —— ⚠️ 不要当数据源，但值得当"准确率评测集"

- CC BY-SA 4.0，500 条 text-to-SQL（2025-07 的 V2 扩到 780 条 / 18 个库），来自 **11 个互不相关的库**：
  借记卡、学生社团、血栓预测、欧洲足球、F1、超级英雄、代码社区、卡牌游戏、毒理学、加州学校、金融
  （[官方仓库](https://github.com/bird-bench/mini_dev)、[HuggingFace](https://huggingface.co/datasets/birdsql/bird_mini_dev)）。
- 官方提供 MySQL / PostgreSQL 版 `BIRD_dev.sql`，可以正常入库：
  ```bash
  mysql -h 127.0.0.1 -P 3306 -uroot -proot --default-character-set=utf8mb4 -e "CREATE DATABASE bird DEFAULT CHARACTER SET utf8mb4"
  mysql -h 127.0.0.1 -P 3306 -uroot -proot --default-character-set=utf8mb4 bird < BIRD_dev.sql
  ```
- 为什么不建议当业务数据源：库之间毫无业务连贯性，没有"商品/订单/增长"口径，演示叙事讲不通。
- 真正的价值（这才是它该用的地方）：
  - 把它配成一个独立数据源，**用官方 gold SQL 跑执行准确率（EX）**，用来量化 DataAgent 的 NL2SQL 水平；
  - 每条样本自带 `evidence`（外部知识），正好可以用来检验本项目的**证据召回 / 业务知识召回**是否生效；
  - 它是 CC BY-SA：如果对外分发改造后的数据，派生数据要同样开放，内部评测不受影响。
- 注意：`sql_mode` 需去掉 `ONLY_FULL_GROUP_BY`，官方 README 有说明。

### 3. Spider 2.0 —— ❌ 本阶段不建议接入（成本/收益不划算）

- 632 道企业级 text-to-SQL 工作流题，库来自真实企业应用，**单个库常超 1000 列**，跑在 Snowflake / BigQuery 上，SQL 常常 100 行以上（[官网](https://spider2-sql.github.io/)、[仓库](https://github.com/xlang-ai/Spider2)）。
- 官方明确建议用 `spider-agent-lite` / `spider-agent-snow` 跑 benchmark，**不把它当普通数据源**：
  - Snowflake 账号需申请表单，2025-11 起还有密码/MFA 策略变更，2026-08 官方公告评估账号被暂停，接入链路不稳定；
  - Lite 里只有 135 个 SQLite 库可以离线跑，但要自行搭评测环境；
  - 目标形态是"复杂长上下文 + 多 SQL 工作流 + CSV 结果比对"，DataAgent 当前的 Graph（Planner→NL2SQL→执行→可视化报告）不是为这种"企业级多步工作流"设计的，硬接会产生大量误报，反而看不清真实问题。
- 什么时候再看：等你想给 DataAgent 做**能力上限压测**、并且接受"分数很低是正常的"（GPT-4o 级别在 Spider 2.0 上只有 10% 左右）时，再按官方 `spider-agent-*` 跑一遍，而不是把它塞进"选择数据库"下拉框。

### 落地建议（一句话版）

| 目的 | 用什么 |
|---|---|
| 有连续月份的销售数据、能演示"增长/环比" | **UCI Online Retail II**（见上文脚本） |
| 干净规范的多表业务库、低成本的 schema 召回与 NL2SQL 演示 | **Chinook** |
| 有订单状态/库存/商品分类的电商场景 | 现有 **product_db**（数据可再用 Retail II 或 Olist 补） |
| 量化 NL2SQL 准确率、验证证据召回 | **BIRD Mini-Dev**（当评测集，不当数据源） |
| 能力上限压测 | **Spider 2.0**（用官方 agent，别接进产品） |
