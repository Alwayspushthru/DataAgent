# 开发题OFF/ON链路

本阶段使用已冻结的开发题，不运行正式500题，也不把开发成绩填入正式简历指标。

已完成完整50题/100份真实记录，结果和未解决问题见[开发集 v2 脱敏验收摘要](reports/development-full-v2-summary-2026-10-18.md)。另保留本地历史 10 题先导报告（未纳入版本管理）。

## 接口

评测接口默认不存在，仅在 `data-agent.evaluation.enabled=true` 时注册。接口要求请求来自回环地址，建议服务只绑定127.0.0.1。当前独立服务地址为 `http://127.0.0.1:18065`。

`POST /api/evaluation/run`：

```json
{"agentId":"5","query":"这里放问题及相同的输出列约定","businessKnowledgeEnabled":false}
```

businessKnowledgeEnabled默认true；false时仍执行查询重写，但不访问业务/文档Evidence检索并显式写入空Evidence，避免旧证据残留。两组保持物理Schema与字段处理、模型、工具、重试预算一致。当前独立评测Agent只包含24条冻结业务知识，没有其他文档知识或指标定义型语义模型。

执行路径包含意图识别、知识检索、问题增强、Schema召回、关系选择、可行性评估、真实Planner、计划校验、SQL生成、语义校验、执行与修复。评测模式跳过图表和末尾报告，采集查询结果；不会使用跳过真实规划的nl2sqlOnly快捷模式。

响应包含：threadId、conversationId、业务知识开关、节点输入输出/尝试次数/耗时、实际SQL执行记录与结果、模型名称及配置、检索阈值/SQL重试限制。没有API密钥或数据库连接密码。只统计模型已上报的streaming Token；内部advisor调用可能缺少用量，因此不能当作完整账单成本。

`POST /api/evaluation/retrieval?threshold=0.0`：同样提供agentId和query，返回最多8条业务知识的相似度、元数据和预览，用于排查零召回。它只用于开发诊断，不将每题gold知识ID作为召回条件。

## 本次工程修正

- 请求级开关进入图状态，OFF清空Evidence；默认业务行为仍为ON。
- 节点采集独立于Langfuse开关，直接在SQL执行节点保存结果，不从自然语言报告反推。
- SQL NULL保留为JSON null，避免与空字符串混淆。
- 返回行数达到1000上限时标记possiblyTruncated，评分端拒绝声称结果完整。
- 真实内存向量库回归复现：Long业务知识ID的IN集合与转换后的Integer字面量不匹配。使用数值EQ的OR组合保留允许ID语义，并验证禁用知识及其他Agent仍不可见。不改写业务定义和正式题。

## 启动

在项目根目录执行（先启动Docker MySQL）：

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
SERVER_ADDRESS=127.0.0.1 SERVER_PORT=18065 LANGFUSE_ENABLED=false \
  ./mvnw -o -pl data-agent-management spring-boot:run \
  '-Dspring-boot.run.arguments=--data-agent.evaluation.enabled=true --spring.ai.alibaba.data-agent.checkpoint.type=memory --spring.ai.alibaba.data-agent.max-sql-retry-count=3 --spring.ai.alibaba.data-agent.vector-store.default-similarity-threshold=0.2'
```

聊天与Embedding使用本地已启用模型；上述命令不修改模型表。该开发配置为检索topK=8、相似度阈值0.2、SQL最多生成3次。阈值是开发配置，不能看正式题成绩后静默调整。OFF/ON使用同一配置。

## 准备评测Agent

```bash
python3 tools/retail_eval/run_development.py setup
```

此命令会建立/复用独立的 `retail_eval_v1_knowledge_development` Agent和只读数据源，只初始化transaction_lines物理表，并逐条导入24条冻结知识。setup及run启动前检查没有额外文档或语义模型定义，避免实验变量混入其他业务上下文。内存向量库重启后需重新setup。所有修改限于新建评测Agent，数据快照不写入。知识生成会调用已配置Embedding服务。

本地状态文件：`.vscode/retail-eval/development-setup.json`，包含Agent ID、数据源ID、知识ID映射与知识版本，不含密钥。

## 运行与复核

```bash
# 每类2题，共10题；每题OFF和ON，总20次真实任务
python3 tools/retail_eval/run_development.py run --limit 10 --workers 2 \
  --run-dir .vscode/retail-eval/development-pilot-v3

# 完整开发集；本地v1已完成，复用该目录会读取原记录；新一轮请使用新目录
python3 tools/retail_eval/run_development.py run --limit 50 --workers 2 \
  --run-dir .vscode/retail-eval/development-full-v1
```

小规模题目轮转覆盖五类及两种开发模板。每题新建会话，两组交错提交。并发2不保证严格的顺序配对，但调用模型和配置一致。同一目录已有capture会复用，不会把已失败题自动重试到成功；新代码/配置应使用新目录。模型名称和检索设置变化会中止一致性检查。

Runner给模型的只有公开question与answer_schema。不读取正式题答案；开发答案仅在调用结束后用于评分。最终执行结果必须拥有要求的输出列名，可按列名重排列；不猜测或补算缺失指标。SQL失败时不选用较早成功SQL冒充最终答案；出现Python结果时标记未支持的最终输出，保留Trace供后续适配。

每个run-dir包含：

| 文件 | 内容 |
|---|---|
| config.json、models.json、server-settings.json | 本轮题目ID、代码哈希、模型与检索配置 |
| captures/ | 每题每组原始执行证据 |
| off/on-predictions.jsonl | 从实际SQL结果提取的预测 |
| off/on-score.json | 逐题结果评分、失败原因与口径待评审状态 |
| summary.json | 开发集汇总；不能视为正式500题成绩 |

口径评审需根据真实执行SQL，使用开发题的R01..Rn规则清单。尚未评审的成功任务保留business_accuracy=null；失败任务计失败。LLM Judge未接入，也不会将数值正确自动转成口径正确。

以下命令不调用模型，也不执行参考SQL，会重新计算结果评分并导出含实际SQL、规则定义和capture哈希的评审模板：

```bash
python3 tools/retail_eval/run_development.py grade \
  --run-dir .vscode/retail-eval/development-pilot-v3
```

将off-review-template.jsonl、on-review-template.jsonl分别复制为新目录下的off-reviews.jsonl、on-reviews.jsonl。评审人阅读capture中的实际执行SQL，填写reviewer、executed_sql_evidence，以及每条规则的passed布尔值和evidence文字。没有SQL执行的题目已计失败，无需补造评审。不要只对照结果数字判断统计口径。

```bash
python3 tools/retail_eval/run_development.py grade \
  --run-dir .vscode/retail-eval/development-pilot-v3 \
  --reviews-dir .vscode/retail-eval/development-reviews-v3
```

未填写的模板不能产生已通过的口径评分；不会将AI分析登记为人工评审。评分保留预测和评审文件哈希，重新评分不会修改原始capture或人工填写的文件。

早期诊断轮存放在development-pilot-v1/v2，记录零召回/快捷规划路径问题，不能与修复后结果混合。最终轮路径及实际完成数量以本阶段验收报告为准。

历史 v1 完整开发集目录为development-full-v1，复用同配置先导轮的20份原始capture并新增80次执行，seed.json记录复用来源及哈希。历史详细报告和口径模板仅在本地保存；当前结果以上述 v2 摘要为准。

## QueryEnhance 稳定性修正（待新一轮真实验证）

QueryEnhance 对空响应、无效 JSON 和缺失 canonical_query 最多重新调用一次，使用原始完整提示及同一 Evidence；OFF/ON 应共同使用此版本。JSON 修复不再脱离业务上下文单独调用模型。两次均失败时明确报错，不返回空节点状态。expanded_queries 缺失或全部为空时使用已有 canonical_query 作为检索查询，并清理空白及重复扩展项。此处理不保证 canonical_query 的业务语义完整，仍需逐题评审。

评测响应新增 queryEnhanceResponses，包含每次完整返回的 attempt、rawResponse 和 finishReasons。模型未报告结束原因时列表可能为空，不能推断为正常完成；传输中断前的部分响应暂不包含在此字段。节点先缓冲并校验完整响应，再输出有效响应，避免重试内容混入最终 JSON。重试最多增加一次模型调用；失败完整响应中已报告的 Token 也计入评测采集。

本次未修改模型预算或冻结题目，也未覆盖旧执行记录。修复后的实际成功率需重启评测服务后使用新的 run-dir 验证，旧版 10%/14% 仍仅代表原开发轮。

## v5增强入口修复验收

见本地修复版 10 题先导报告（未纳入版本管理）。两组均10/10进入Schema；OFF可评分SQL3/10、结果正确1/10；ON可评分SQL及结果正确均9/10。ON有1题检索前改写空响应，Evidence为“无”，因此不将本轮作为纯知识效果结论。业务口径仍待人工复核。

当前增强输出只要求canonical_query，不再要求扩展查询；Dispatcher不依赖expanded_queries。QueryEnhance请求级预算首次4096、校验失败后最多一次8192重试；全局模型预算仍为2000。LENGTH显式记为截断，不接受其正文作为成功输出。每次尝试在queryEnhanceResponses记录maxTokens及终止原因。

新轮代码使用新目录；不要用旧轮目录续跑或覆盖失败记录。后续主要故障是TableRelation/Planner空响应或截断，以及EvidenceRecall检索前改写空输出。

## 完整开发集 v2（已完成）

相同50题OFF/ON共100份全新记录，见[开发集 v2 脱敏验收摘要](reports/development-full-v2-summary-2026-10-18.md)。OFF8/50（16%）、ON42/50（84%）结果正确，Schema入口49/50与50/50。ON49/50实际有Evidence，业务口径仍待人工复核。正式500题未运行。

记录目录为`.vscode/retail-eval/development-full-v2/`；两次ON增强截断均经重试恢复。剩余ON失败为7次口径澄清和1次计划失败，多指标召回缺失M05是首要问题。不要复跑本目录替换失败结果。
