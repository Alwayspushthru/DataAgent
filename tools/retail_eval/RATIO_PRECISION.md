# 比率计算精度改进：2026-10-19

已把比率计算精度要求接入SQL生成、错误修复和语义审计三个入口。共用资源为`data-agent-management/src/main/resources/prompts/sql-numeric-precision.txt`，由PromptHelper注入，不依赖业务知识Evidence是否开启，因此OFF/ON都会收到相同工程约束。

## 当前行为

- 整数计数或低scale表达式的除法，优先在操作数上显式保证足够的小数精度。MySQL计数比率参考写法为`CAST(分子聚合表达式 AS DECIMAL(30,12)) / NULLIF(分母聚合表达式,0)`。
- 金额和其他大数必须结合Schema及聚合范围保留足够整数位，不盲目把所有表达式缩窄成固定DECIMAL类型。
- 不以仅乘1.0作为精度充分的证明；分母零或NULL保持NULL，不用COALESCE补零，不擅自改变百分比单位或指标范围。
- 中间计算、过滤、排序不按展示位数提前舍入；明确要求展示精度时才在最终展示表达式处理。
- 语义审计检查数值类型和运算顺序；空区间结果正确不能独自证明非空计算精度充分。已有充分精度的等价表达式不要求机械增加CAST。

这次改动为生成/修复提示及模型语义审计约束，没有加入自动SQL重写器或确定性的精度执行拦截。提示下发测试与数据库算术测试分别验证；不能据此声称所有未来模型输出都已得到保证。

## MySQL实机回归

使用用户已有Docker容器中的MySQL 8.0.46及只读账户，测试9个场景：1/3、2/3、1/30000、2/7、零复购、全部复购、空区间、NULL分子、NULL分母。用Python Decimal的50位精度作独立数值参考，容差1e-6。

9个新表达式数值/空值检查、3个旧行为负例和1个阈值判断检查，共13项通过。只执行SELECT及`SET SESSION div_precision_increment=4`，不写表、不改全局参数，不调用项目模型。

| 表达式 | 1/3场景 | 1/30000场景 |
|---|---:|---:|
| 直接相除 | 0.3333 | 0.0000 |
| 乘1.0再除 | 0.33333 | 0.00003 |
| 外层CAST到DECIMAL(30,12) | 0.333333333000 | 0.000033333000 |
| 先显式量化到4位再扩大CAST | 0.333300000000 | 0.000000000000 |
| 除法前CAST到DECIMAL(30,12) | 0.3333333333333333 | 0.0000333333333333 |

### 对此前解释的更正

不能断言MySQL的`CAST(1/3 AS DECIMAL(30,12))`必然等于`0.333300000000`。本机实测外层CAST仍保留了更多中间计算位，本次该表达式满足1e-6容差。初次回归把它当成必然失败的负例，因此只通过12/13项；这是测试假设错误，不是已证实的修复失败。

已保留初次测试脚本和结果，修正为稳定负例：先用内层`CAST(... AS DECIMAL(20,4))`明确量化，再扩大类型，已丢失的小数位不会恢复。外层CAST继续作为观测项保留，不从测试中移除。工程提示也相应改成不只依赖外层CAST的外观推断精度，优先在除法前明确操作数精度。

## Java验证与运行状态

相关Java回归包括PromptConstantTest、PromptHelperTest、PromptLoaderTest、NumericPrecisionPromptFlowTest、Nl2SqlServiceImplTest、SemanticConsistencyNodeTest。调用链测试覆盖生成、修复、审计在有/无业务Evidence两种情况下收到同一份精度规则。

首次受限执行中，54项提示相关测试通过，另22项受Mockito JVM attach限制；用户随后打开Docker并授权重跑。同一组测试加6项无插桩调用链检查后共82项通过。未建立替代运行环境，均使用现有JDK与Docker。

本次没有重启现有后端或重跑50/500题。提示通过classpath及PromptLoader缓存读取，运行服务需在下次正常启动/部署时加载新版本；后续实跑必须使用新目录，不能覆盖v2记录。本轮已采纳的OFF0/40、ON32/40口径成绩及16%/84%查询结果成绩保持不变，四题用户裁定不撤销。

## 复现

需要Docker/沙箱外权限时，先说明资源和原因，再请求权限执行；不要另建环境规避限制。

```bash
# 用户已有的Docker容器运行后，执行只读数据库算术回归
python3 tools/retail_eval/check_ratio_precision.py

# 使用项目现有JDK运行相关Java测试；Mockito需要JVM attach权限
JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home \
  ./mvnw -o -pl data-agent-management \
  -Dtest=PromptConstantTest,PromptHelperTest,PromptLoaderTest,NumericPrecisionPromptFlowTest,Nl2SqlServiceImplTest,SemanticConsistencyNodeTest \
  -DfailIfNoTests=false test
```

本地证据位于`.vscode/retail-eval/ratio-precision-2026-10-19/`：mysql-regression.json为最终数据库结果；mysql-regression-initial.json和check_ratio_precision-initial.py保留最初假设及失败结果；java-tests-final.log为最终Java测试日志。已有JaCoCo历史执行数据存在类版本不一致提示，因此不使用该覆盖率报告作本次覆盖率证据。

## 2026-10-20实际开发集回归

后续已按用户授权用现有JDK和Docker重启精度改进版，完成50道开发题OFF/ON各50次全新任务。查询正确率OFF 12%、ON 72%，业务口径正确率OFF 0%、ON 67.5%，均保留固定分母；相较v2整体回退，详见[v3回归摘要](reports/development-full-v3-summary-2026-10-20.md)。

本轮成功执行的9份比率SQL均在除法前显式转换Decimal。实际复购SQL在非空1/3合成场景得到0.3333333333333333，通过1e-6容差，旧v2同题曾得到0.3333。本轮仅1道复购题执行成功，其余4道仍受澄清或规划失败阻断，不能把部分精度验证写成整条Agent链路成功率提升。

本轮另行复跑的9场景13项独立算术检查全部通过。新证据保存在`.vscode/retail-eval/development-full-v3/`，v2原始采集、评分和四项历史裁定均未改变。
