<div align="center">
  <p>中文 | <a href="./README-en.md">English</a></p>
  <h1>Spring AI Alibaba DataAgent</h1>
  <p>用自然语言查询业务数据，从分析计划到图表报告，在一个工作台中完成。</p>
  <p>自然语言问数 · SQL 与 Python 分析 · 可视化报告 · 业务知识配置</p>

  <p>
    <a href="https://github.com/alibaba/spring-ai-alibaba"><img src="https://img.shields.io/badge/Spring%20AI%20Alibaba-1.1.2.2-blue" alt="Spring AI Alibaba"></a>
    <img src="https://img.shields.io/badge/Spring%20Boot-3.4.8+-green" alt="Spring Boot">
    <img src="https://img.shields.io/badge/Java-17+-orange" alt="Java">
    <img src="https://img.shields.io/badge/License-Apache%202.0-red" alt="License">
    <a href="https://deepwiki.com/spring-ai-alibaba/DataAgent"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"></a>
  </p>

  <p>
    <a href="#项目介绍">项目介绍</a> ·
    <a href="#产品预览">产品预览</a> ·
    <a href="#核心功能">核心功能</a> ·
    <a href="#完成第一次数据分析">使用流程</a> ·
    <a href="#快速开始">快速开始</a> ·
    <a href="#集成与进阶使用">文档导航</a>
  </p>
  <img src="img/LOGO.png" alt="DataAgent" width="960">
</div>

## 项目介绍

DataAgent 是一个面向业务数据的 AI 分析助手，基于 Spring AI Alibaba 构建。连接数据库后，你可以直接用自然语言提出问题，让智能体查询数据、执行计算，并生成包含图表和文字结论的分析报告。

从日常问数到专题分析，DataAgent 将提问、计划确认、SQL 查询、Python 分析和报告查看集中在同一个工作台中。你可以查看执行过程和中间结果，也可以补充业务术语、指标口径和知识文档，让分析结合实际业务背景展开。

对于业务人员，它提供对话式的数据查询与报告入口；对于分析人员，它支持查看 SQL、核对数据和调整分析计划；对于开发者，它提供模型配置、API 和 MCP 接入能力，便于集成到已有应用中。

## 产品预览

以下截图展示智能体管理、数据问答和报告的使用形态，取自仓库已有版本；当前版本的布局和部分按钮名称有所调整，操作流程以下文说明为准。

### 管理不同业务场景的分析助手

为销售、订单、库存等业务场景创建智能体，维护名称、描述和分类，并按名称或状态查找。

![智能体管理界面示意](img/homepage-agents.png)

### 在对话中提出问题并查看执行过程

进入数据问答，选择数据库和模型后发送问题。工作台展示分析过程，左侧历史会话便于回看先前的提问和结果。

![数据问答与执行过程示意](img/analyze-question.png)

### 将分析结果整理成报告

查看指标、图表和文字结论，并通过报告卡片预览或下载报告，供后续整理与分享。

![订单分析报告示例](img/analyze-result.png)

## 核心功能

### 用自然语言查询数据

输入“按订单状态统计订单数和总金额”或“查询销量最高的商品”，智能体结合数据表结构和业务知识生成 SQL，完成查询。涉及多个表的问题可以通过表关系组织关联查询。

在数据问答输入区开启“仅NL2SQL”，可以聚焦 SQL 查询；开启“显示SQL结果”，可以在执行过程中查看返回的数据，核对筛选条件和统计口径。

<details>
<summary>查看 SQL 和查询结果示例</summary>

![SQL 与查询结果表格](img/show-sql-result.png)

</details>

### 从数据查询到深入分析

对于趋势、分组对比和统计计算等需求，智能体先制定分析计划，再按计划执行 SQL 查询，并在需要时使用 Python 处理数据。你可以在工作流时间线中查看计划、SQL 生成与执行、Python 分析和报告生成等步骤。

例如，提问“查询订单数据，使用 Python 按日期汇总订单金额并分析变化”，可以将数据提取与后续计算串联起来。包含 Python 步骤的分析需要可用的 Docker 环境，配置方法见[快速开始](docs/QUICK_START.md)。

### 查看和导出分析报告

分析完成后，报告将查询与计算结果整理为文字结论、数据表格和可视化图表。报告卡片支持 Markdown 与 HTML 预览切换、全屏查看，以及 MD、HTML 文件下载，方便保存分析结果。

### 在执行前确认分析计划

发送问题前开启“人工反馈”，智能体生成计划后会等待确认。你可以点击“接受计划”继续执行，也可以填写修改意见后点击“拒绝重规划”，让智能体重新组织分析步骤。

例如，可以要求“只统计已完成订单，按天汇总，并补充平均订单金额”。这一操作适合需要先明确筛选范围和分析口径的任务；选择“仅NL2SQL”时，人工反馈会关闭。

<details>
<summary>查看计划确认与反馈示例</summary>

![人工反馈与计划确认示意](img/feedback-mode.png)

</details>

### 创建专属业务智能体

在“智能体管理”中新建智能体，填写名称、分类、描述和 Prompt，为不同业务任务设置分析背景。通过侧边栏选择当前智能体后，可以继续配置其数据源、语义模型、业务知识和知识库。

数据问答支持新建、重命名和切换历史会话，便于围绕不同分析主题分别记录问题与结果。“提示词配置”还提供增强提示词的维护入口，可以按需要调整分析指令。

### 让分析理解业务口径

数据表结构之外，DataAgent 提供三类知识配置，用于补充字段含义、指标定义和分析背景。

| 配置入口 | 用途 | 配置示例 |
| :--- | :--- | :--- |
| 语义模型配置 | 建立业务名称与数据库字段的对应关系，补充同义词和字段说明 | 将 `orders.total_amount` 对应为“订单金额”，补充“交易金额”等同义词 |
| 业务知识配置 | 定义指标公式、过滤条件和业务术语 | 定义“已完成订单金额”为 `status = 'completed'` 的订单金额之和 |
| 智能体知识库 | 通过文档和问答提供背景、分析流程与参考案例 | 上传订单状态说明，或添加常见问题及对应 SQL 示例 |

在侧边栏选择目标智能体，再进入相应配置页面添加内容。具体配置方式见[知识配置最佳实践](docs/KNOWLEDGE_USAGE.md)。

<details>
<summary>查看语义模型配置示例</summary>

![语义模型字段配置示意](img/semantic-models.png)

</details>

### 管理数据源和模型

在“通用设置 → 数据连接”中添加数据库连接、测试连通性，并为当前智能体选择数据表。对于未定义物理外键的数据库，可以通过“逻辑外键”补充表间关系，帮助智能体理解关联方式。

在“通用设置 → 模型配置”中分别添加对话模型和嵌入模型，测试连接并设置默认模型。系统提供多个模型供应商选项，也支持通过自定义地址接入兼容 OpenAI 接口的服务。数据问答输入区支持选择当前使用的数据库和对话模型。

<details>
<summary>查看数据表选择示例</summary>

![数据源与数据表选择示意](img/datasource-tables.png)

</details>

## 完成第一次数据分析

启动系统后，可以用仓库提供的订单、商品和用户示例数据完成一次分析。示例数据导入方法见[快速开始](docs/QUICK_START.md)，以下步骤从进入页面开始。

### 1. 配置模型

打开“通用设置 → 模型配置”，分别添加对话模型和嵌入模型，填写模型名称、API Key 及服务地址，测试连接并设为默认。对话模型用于理解问题与生成分析内容，嵌入模型用于知识和数据表结构检索。

### 2. 创建分析智能体

进入“智能体管理”，点击“新建智能体”，填写名称、分类和标签等信息。例如，将其命名为“订单分析助手”，在描述或 Prompt 中说明它负责订单查询和销售分析。创建后，通过侧边栏确认当前选中的智能体。

### 3. 连接业务数据并初始化

进入“数据连接”，添加示例业务库的连接信息，启用并测试连接。为目标数据源点击“设为当前”，展开表列表，勾选 `orders`、`order_items`、`products`、`users` 等分析需要的表，点击“更新数据表”，再点击“初始化当前智能体数据源”。

这一步读取已选业务表的结构，供后续检索和查询使用；业务表及示例数据需要事先导入数据库。

### 4. 按需补充业务知识

如果问题涉及专有术语或统计口径，在知识配置中补充定义。例如，说明订单状态 `completed` 表示已完成，并明确销售额是否只统计该状态的订单。字段注释已能充分表达含义时，可以先体验基础查询，再逐步补充知识。

### 5. 提交问题并确认计划

进入“数据问答”，新建分析会话，确认数据库和模型，关闭“仅NL2SQL”，按需开启“人工反馈”和“显示SQL结果”，然后发送：

```text
分析示例库中全部订单：按状态统计订单数和订单金额，
按日期展示已完成订单的金额变化，并生成包含图表的分析报告。
```

如果开启人工反馈，查看计划中的时间范围、订单状态和统计维度，接受计划或提交修改意见。

### 6. 查看结果并保存报告

在时间线中查看执行进度和 SQL 查询结果。报告生成后，查看图表与结论，使用报告卡片中的 MD 或 HTML 按钮下载。

示例数据包含固定日期，首次体验使用“全部订单”可避免相对时间筛选导致空结果。需要体验 Python 时，可以在问题中明确要求使用 Python 汇总或计算，并先准备好 Docker 环境。

## 典型使用场景

| 场景 | 可以这样提问 | 查看内容 |
| :--- | :--- | :--- |
| 日常问数 | 按订单状态统计订单数和订单总金额 | SQL、统计结果表 |
| 趋势分析 | 按日期分析已完成订单的金额变化，并生成图表 | 趋势图、文字结论与报告 |
| 商品对比 | 按商品汇总已完成订单的销量与明细金额，列出前五名 | 多表查询结果、排名与对比图表 |
| 用户分析 | 按用户统计已完成订单数和订单金额，比较消费情况 | 用户汇总数据、对比分析 |

以上为提问示例，具体输出取决于已接入的数据、业务配置和模型能力。

## 快速开始

### 准备环境与数据库

需要 JDK 17+、MySQL 5.7+、Node.js 22+ 和 pnpm 11+。执行 Python 分析时还需要 Docker；项目自带 Maven Wrapper，无需单独安装 Maven。

首次运行先按[快速开始文档](docs/QUICK_START.md)创建管理库、导入管理表及业务示例数据，并配置数据库连接。默认关闭 SQL 自动初始化，启动服务不会自动建表或导入示例数据。管理库的默认连接为 `127.0.0.1:3306/saa_data_agent`，连接地址、用户名和密码可通过 `DATA_AGENT_DATASOURCE_URL`、`DATA_AGENT_DATASOURCE_USERNAME`、`DATA_AGENT_DATASOURCE_PASSWORD` 设置。

### 启动服务

在项目根目录打开终端，启动后端：

```bash
./mvnw -pl data-agent-management spring-boot:run
```

另开一个终端，在前端目录安装依赖并启动：

```bash
cd data-agent-frontend-nuxt
npx --yes pnpm@11.9.0 install
./node_modules/.bin/pnpm dev --host 127.0.0.1
```

打开 <http://localhost:3000>，按[完成第一次数据分析](#完成第一次数据分析)配置模型和智能体。

已完成本机初始化、且具备 `.vscode/local-run/` 辅助脚本的环境可以使用 `make start`。本机日常启停、首次手动配置和 macOS 环境说明见[本地开发与启动](docs/LOCAL_DEVELOPMENT.md)。

## 集成与进阶使用

DataAgent 提供 API 接口，支持将会话与消息操作接入已有应用；也可以作为 MCP 服务器，为支持 MCP 的客户端提供自然语言转 SQL 和智能体查询工具。流式分析接口支持在启用智能体 API Key 后，通过 `X-API-Key` 或 Bearer Token 校验请求凭证。更多接入方式见[高级功能](docs/ADVANCED_FEATURES.md)。

需要理解实现或扩展能力时，可以继续阅读架构与开发文档。

| 文档 | 内容 |
| :--- | :--- |
| [快速开始](docs/QUICK_START.md) | 环境要求、数据库准备、基础配置与启动 |
| [本地开发与启动](docs/LOCAL_DEVELOPMENT.md) | 本机启停、首次手动配置、macOS 环境说明 |
| [知识配置最佳实践](docs/KNOWLEDGE_USAGE.md) | 语义模型、业务知识、文档与问答的配置方式 |
| [高级功能](docs/ADVANCED_FEATURES.md) | API、MCP、逻辑外键、检索策略与 Python 沙盒配置 |
| [架构设计](docs/ARCHITECTURE.md) | 系统架构、分析工作流、核心模块与时序图 |
| [开发者指南](docs/DEVELOPER_GUIDE.md) | 开发环境、配置说明、模型与向量库扩展 |

## 社区与贡献

- 钉钉交流群：`154405001431`（DataAgent 用户 1 群）。部分用户可能因账号安全问题无法加入，条件允许时可换账号申请。
- 参与开发：阅读[开发者指南](docs/DEVELOPER_GUIDE.md)，了解开发与扩展方式。
- 提交贡献：参考[中文贡献说明](CONTRIBUTING-zh.md)或 [English contribution guide](CONTRIBUTING-en.md)。

### 许可证

本项目采用 Apache License 2.0 许可证。

### Star 历史

[![Star History Chart](https://star-history.dera.page/svg?repos=spring-ai-alibaba/DataAgent&type=Date)](https://star-history.dera.page/#spring-ai-alibaba/DataAgent&Date)

### 贡献者

<a href="https://github.com/spring-ai-alibaba/DataAgent/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=spring-ai-alibaba/DataAgent" alt="项目贡献者">
</a>

---

<div align="center">
  Made with ❤️ by Spring AI Alibaba DataAgent Team
</div>
