# 固定问数题集 v1.0.0

本题集用于零售业务知识Evidence的OFF/ON对照。绑定已验收的retail_eval_v1与业务定义v1.0.0，是基于公开数据自建的中文模板题集，不是BIRD官方成绩。

## 组成

| 类别 | 开发题 | 正式题 | 正式题内容 |
|---|---:|---:|---|
| 业务范围与取消口径 scope | 10 | 100 | 销售额、销售数量、有效明细数、取消发票数、取消有符号金额 |
| 指标分母与比率 denominator | 10 | 100 | 平均订单金额、每购买客户平均销售额、期间复购客户占比、加权销售单价、已识别客户销售额占比 |
| 时间边界与月度比较 time | 10 | 100 | 跨月日期按日统计、两月销售额/发票/客户统计、完整自然月环比 |
| 去重与分组粒度 grain | 10 | 100 | 发票去重、客户去重、期间复购客户数、商品编码去重、国家Top10金额与全局份额 |
| 基础查询控制组 basic | 10 | 100 | 原始行数、有符号金额、国家去重数、原始数量合计、原始商品编码去重数；问题显式说明不加业务过滤 |
| 合计 | 50 | 500 | 前四类共400道口径题，全部500道用于结果正确率 |

正式集25个模板族，每族20个日期/国家参数变体；开发集10个不同结构的模板族，每族5个变体。开发题采用联合指标、国家分组诊断、精确时间与空期间等结构。两集不复用题目文本和模板族ID，但共享指标、数据快照和业务概念，不能声称未见指标或未见行业泛化。

国家过滤按题目显式条件执行；客户金额可归属率题使用包含匿名交易的全国家范围，避免全部客户已识别的国家导致长期恒为100%。当前题集不包含相对日期、未定义GMV、模糊客单价、不可回答需求或多轮对话；澄清能力应另建专门测试，不混入500/400分母。

## 在哪里查看

- `dev-题目-v1.md`：按五类阅读全部50道开发题。
- `test-题目-v1.md`：按五类阅读全部500道正式题。
- `dev-questions-v1.jsonl` / `test-questions-v1.jsonl`：机器可读题目与返回列约定。
- `inventory-v1.json`：数量、模板族、数据快照与知识定义哈希。
- `scoring-rules-v1.json`：固定评分标准。
- `freeze-v1.json`：题集、私有标准答案和工具的哈希，检查版本变化。
- `../reports/benchmark-acceptance-2026-10-18.json`：本次题集验收结果。

以下文件位于Git忽略的本地私有目录 `.vscode/retail-eval/benchmark-v1/`：

- `dev-answers-v1.jsonl` / `test-answers-v1.jsonl`：每题reference_sql、expected_rows、required_rules及知识ID。
- `dev-参考与评分-v1.md` / `test-参考与评分-v1.md`：可直接阅读的逐题SQL、标准结果和R01..Rn评分清单。
- `dev-review-template-v1.jsonl` / `test-review-template-v1.jsonl`：空白评审表；复制后填写实际SQL证据和逐规则判断，不要直接覆盖模板。
- `mysql-validation.json`：参考SQL实际执行与独立源端答案的逐题比较。
- `source.sqlite`：由冻结源明细产生的参考计算缓存，金额用整数微英镑。
- 后续Agent运行记录、人工口径评审及评分报告也放在该本地目录。

源端参考答案来自冻结TSV：标量业务指标使用Python Decimal与独立公式；分组与去重使用源端SQLite整数金额聚合，再用Decimal求比率。MySQL参考SQL另行编写，并在真实数据库逐题执行比较。没有使用同一个LLM生成答案再给自己评分。SQL和题目仍由程序模板生成，不能把自动核验冒称专家逐题人工审阅。

## 评分原则

1. **结果与口径分开**：结果相同不代表口径正确。口径根据实际执行SQL/Trace逐规则核验。
2. **固定分母**：OFF与ON的口径分母都是400；ON结果分母500。报错、超时、漏答、错误拒答都不从分母删除。
3. **数值比较**：计数和金额精确比较；除法容差1e-6。NULL与0区分，保留重复行，时间序列与排名检查行序。不得按展示两位金额提前舍入。
4. **完整规则通过**：私有答案的required_rules按顺序编号R01、R02等，全部满足才口径通过；不使用“满足大部分规则”作为正确。
5. **评审证据**：每条规则填写passed和实际SQL证据，记录评审者。未完成评审则business_accuracy=null，不伪造已验证成绩。LLM Judge可初筛，单独使用时标为provisional。
6. **输出契约**：两组都收到相同question和answer_schema。允许通过列名重排列顺序；不通过自动猜指标映射来修正错误。组别、类别、规则和标准答案不作为模型提示。

每道正式题均执行一个“忽略题目时间范围”的源端错误变体检查，要求结果与正确答案不同。这只能证明该时间错误可被本数据发现，不能保证每个业务规则错误都会改变数值；所以仍需语义口径评审。简单结果相等不能替代审计。

## 开发、冻结与正式实验

开发集用于连接调试、输出协议、提示词和评分器调试。正式集冻结后不用于反复调参；若修正题目、知识或评分，需要发布新版本并重新跑OFF和ON。审阅者可以看私有答案，但Agent运行时只能看到公开问题与返回列约定。

生成器默认不覆盖已冻结题集。生成/验证工具：

```bash
# 已冻结后build会拒绝覆盖，重建需明确创建新版本。
python3 tools/retail_eval/benchmark.py build

# 使用现有只读账号，重新执行550条参考SQL核验
python3 tools/retail_eval/benchmark.py verify-mysql

# 检查公开题目、私有答案、规则与工具是否仍与冻结版本一致
python3 tools/retail_eval/benchmark.py check-freeze

python3 -m unittest discover -s tools/retail_eval -p 'test_*.py' -v
```

## 后续Agent输出与口径评审格式

预测文件每行一题，例如：

```json
{"id":"test_scope_sales_amount_01","status":"success","columns":["value"],"rows":[["模型实际查到的数字"]]}
```

status为timeout/error/refused等非success时均判执行失败。示例文本不是可提交的数值。

人工评审每行一题，rules必须与该题required_rules一一对应：

```json
{"id":"test_scope_sales_amount_01","reviewer_type":"human","reviewer":"评审者标识","executed_sql_evidence":"实际SQL或Trace定位","rules":{"R01":{"passed":true,"evidence":"对应SQL子句与判断依据"}}}
```

以上仅演示字段结构，一条R01不能代替所有规则。标准答案中的SQL不可作为模型实际SQL提交评审。

```bash
python3 tools/retail_eval/grade_benchmark.py \
  --group on \
  --predictions .vscode/retail-eval/benchmark-v1/on-predictions.jsonl \
  --reviews .vscode/retail-eval/benchmark-v1/on-human-reviews.jsonl \
  --out .vscode/retail-eval/benchmark-v1/on-score.json
```

同样方式生成off-score。`--allow-judge`仅用于明确标注的初筛，不能把它当人工确认成绩。题集验收不是Agent成绩；本次不会运行1000次OFF/ON模型调用。
