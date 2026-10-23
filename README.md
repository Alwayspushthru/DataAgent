<div align="center">
  <p>中文 | <a href="./README-en.md">English</a></p>
  <h1>Spring AI Alibaba DataAgent</h1>
  <p>
    <strong>基于 <a href="https://github.com/alibaba/spring-ai-alibaba" target="_blank">Spring AI Alibaba</a> 的企业级智能数据分析师</strong>
  </p>
  <p>
     Text-to-SQL | Python 深度分析 | 智能报告 | MCP 服务器 | RAG 增强
  </p>

  <p>
    <a href="https://github.com/alibaba/spring-ai-alibaba"><img src="https://img.shields.io/badge/Spring%20AI%20Alibaba-1.1.2.2-blue" alt="Spring AI Alibaba"></a>
    <img src="https://img.shields.io/badge/Spring%20Boot-3.4.8+-green" alt="Spring Boot">
    <img src="https://img.shields.io/badge/Java-17+-orange" alt="Java">
    <img src="https://img.shields.io/badge/License-Apache%202.0-red" alt="License">
    <a href="https://deepwiki.com/spring-ai-alibaba/DataAgent"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"></a>
  </p>

   <p>
    <a href="#-项目简介">项目简介</a> • 
    <a href="#-核心特性">核心特性</a> • 
    <a href="#-快速开始">快速开始</a> • 
    <a href="#-文档导航">文档导航</a> • 
    <a href="#-加入社区--贡献">加入社区</a>
  </p>
</div>

<br/>

<div align="center">
    <img src="img/LOGO.png" alt="DataAgent" width="1807" style="border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
</div>

<br/>

## 📖 项目简介

**DataAgent** 是一个基于 **Spring AI Alibaba Graph** 打造的企业级智能数据分析 Agent。它超越了传统的 Text-to-SQL 工具，进化为一个能够执行 **Python 深度分析**、生成 **多维度图表报告** 的 AI 智能数据分析师。

系统采用高度可扩展的架构设计，**全面兼容 OpenAI 接口规范**的对话模型与 Embedding 模型，并支持**灵活挂载任意向量数据库**。无论是私有化部署还是接入主流大模型服务（如 Qwen, Deepseek），都能轻松适配，为企业提供灵活、可控的数据洞察服务。

同时，本项目原生支持 **MCP (Model Context Protocol)**，可作为 MCP 服务器无缝集成到 Claude Desktop 等支持 MCP 的生态工具中。

## ✨ 核心特性

| 特性 | 说明 |
| :--- | :--- |
| **智能数据分析** | 基于 StateGraph 的 Text-to-SQL 转换，支持复杂的多表查询和多轮对话意图理解。 |
| **Python 深度分析** | 基于 Spring AI Alibaba Sandbox 在任务级容器中执行生成代码，支持 PEP 723 动态依赖、资源限制、失败重试与自动清理。 |
| **智能报告生成** | 分析结果自动汇总为包含 ECharts 图表的 HTML/Markdown 报告，所见即所得。 |
| **人工反馈机制** | 独创的 Human-in-the-loop 机制，支持用户在计划生成阶段进行干预和调整。 |
| **RAG 检索增强** | 集成向量数据库，支持对业务元数据、术语库的语义检索，提升 SQL生成准确率。 |
| **多模型调度** | 内置模型注册表，支持运行时动态切换不同的 LLM 和 Embedding 模型。 |
| **MCP 服务器** | 遵循 MCP 协议，支持作为 Tool Server 对外提供 NL2SQL 和 智能体管理能力。 |
| **API Key 管理** | 完善的 API Key 生命周期管理，支持细粒度的权限控制。 |

## 🏗️ 项目结构

![dataagent-structure](img/dataagent-structure.png)


## 🚀 快速开始

> 详细的安装和配置指南请参考 [📑 快速开始文档](docs/QUICK_START.md)。

### 1. 准备环境

- JDK 17+，并设置 `JAVA_HOME`
- MySQL 5.7+（可使用 Docker 容器运行）
- Node.js 22+
- pnpm 11+（下面的命令无需全局安装 pnpm）
- Docker（使用容器 MySQL 或执行 Python 工作流时必需）

项目自带 Maven Wrapper，使用 `./mvnw`，无需另外安装 Maven。

### 2. 已初始化的本机环境：日常启动

本机已配置为 Docker MySQL + 本机 Java 后端 + Nuxt 前端。先打开 Docker Desktop，
然后在项目根目录执行一条命令：

```bash
make start
```

该命令启动已有的 `dataagent-local-mysql` 容器，等待 MySQL 就绪后同时启动后端
（端口 8065）和前端（端口 3000）。日志输出到当前终端，启动完成后访问
http://localhost:3000。保持终端运行，按 `Ctrl+C` 统一停止前后端；若其中一个
进程退出，另一个也会自动关闭。MySQL 保持运行，需要停止时执行：

```bash
make db-stop
```

容器名称不同时，可使用 `make start MYSQL_CONTAINER=你的容器名` 和
`make db-stop MYSQL_CONTAINER=你的容器名`。该命令复用下方两个本机辅助脚本，
要求已完成本机初始化并安装前端依赖。

如需分别查看前后端日志，也可以继续手动启动。先启动已有数据库容器：

```bash
docker start dataagent-local-mysql
```

打开两个终端，均进入项目根目录，分别执行以下命令，并保持终端运行。

终端一：启动后端（端口 8065）。

```bash
./.vscode/local-run/start-backend.sh
```

终端二：启动前端（端口 3000）。

```bash
./.vscode/local-run/start-frontend.sh
```

这些脚本是本机初始化时生成的辅助文件，位于 Git 忽略的 `.vscode/local-run/`，
新克隆仓库中不会包含。后端脚本使用 Apple Silicon Mac 上 Homebrew 安装的 JDK 17；
前端脚本使用项目内的 pnpm，因此不要求终端能直接找到 `pnpm`。
其他机器请按下一节配置。

本机管理库为 `saa_data_agent`，示例业务库为 `product_db`，数据库监听
`127.0.0.1:3306`。数据已保存在 Docker 卷中，日常启动不需要重新导入 SQL。
停止前后端时在各自终端按 `Ctrl+C`；停止数据库执行：

```bash
docker stop dataagent-local-mysql
```

### 3. 新环境：首次配置与手动启动

先按[快速开始文档](docs/QUICK_START.md)准备 MySQL，创建管理库并配置数据库连接。
默认连接为 `127.0.0.1:3306/saa_data_agent`，用户名和密码均为本机演示用的 `root`。
使用其他连接信息时，设置 `DATA_AGENT_DATASOURCE_URL`、
`DATA_AGENT_DATASOURCE_USERNAME` 和 `DATA_AGENT_DATASOURCE_PASSWORD`。

在项目根目录首次导入管理表和示例数据，显式指定 UTF-8 字符集，避免中文乱码：

```bash
mysql --default-character-set=utf8mb4 -u root -p saa_data_agent < data-agent-management/src/main/resources/sql/schema.sql
mysql --default-character-set=utf8mb4 -u root -p saa_data_agent < data-agent-management/src/main/resources/sql/data.sql
```

业务示例表和数据的导入方法见快速开始文档。示例数据源中的 Docker 内部主机名
`mysql-data`、`postgres-data` 需要按实际部署地址调整。

终端一：在项目根目录启动后端。

```bash
# Apple Silicon Mac 使用 Homebrew JDK 17 时，可先执行：
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
export PATH="$JAVA_HOME/bin:$PATH"

./mvnw -pl data-agent-management spring-boot:run
```

其他系统将 `JAVA_HOME` 设置为实际 JDK 安装路径。如果 Python 沙盒使用 macOS
Docker Desktop，可额外设置 `DATAAGENT_SANDBOX_DOCKER_HOST=unix://$HOME/.docker/run/docker.sock`。

终端二：进入前端目录安装依赖并启动，无需全局安装 pnpm。

```bash
cd data-agent-frontend-nuxt
npx --yes pnpm@11.9.0 install
./node_modules/.bin/pnpm dev --host 127.0.0.1
```

依赖安装完成后，后续启动只需执行最后一条命令。如果希望直接使用 `pnpm`，
也可以先执行 `npm install -g pnpm@11.9.0`，然后在前端目录运行 `pnpm dev`。

### 4. 访问系统

打开浏览器访问 http://localhost:3000 。首次使用时，在“模型配置”中添加聊天模型
和嵌入模型的 API Key，测试连接并设为默认，再配置智能体的数据源。

## 📚 文档导航

| 文档 | 此文档包含的内容 |
| :--- | :--- |
| [快速开始](docs/QUICK_START.md) | 环境要求、数据库导入、基础配置、系统初体验 |
| [架构设计](docs/ARCHITECTURE.md) | 系统分层架构、StateGraph与工作流设计、核心模块时序图 |
| [开发者指南](docs/DEVELOPER_GUIDE.md) | 开发环境搭建、详细配置手册、代码规范、扩展开发(向量库/模型) |
| [高级功能](docs/ADVANCED_FEATURES.md) | API Key 调用、MCP 服务器配置、自定义混合检索策略、SAA Python 沙盒与动态依赖 |
| [知识配置最佳实践](docs/KNOWLEDGE_USAGE.md) | 语义模型，业务知识，智能体知识的解释和使用 |

## 🤝 加入社区 & 贡献

- **钉钉交流群**: `154405001431` ("DataAgent用户1群") 部分用户可能因为账号安全问题无法加入，条件允许的情况下可换账号申请。
- **贡献指南**: 欢迎社区贡献！请查阅 [开发者文档](docs/DEVELOPER_GUIDE.md) 了解如何提交 PR。
- **贡献规范**: 快速查看 [中文贡献说明](CONTRIBUTING-zh.md) 或 [English contribution guide](CONTRIBUTING-en.md) 了解提交流程与协作要求。

## 📄 许可证

本项目采用 Apache License 2.0 许可证。
## Star 历史

[![Star History Chart](https://star-history.dera.page/svg?repos=spring-ai-alibaba/DataAgent&type=Date)](https://star-history.dera.page/#spring-ai-alibaba/DataAgent&Date)

## 贡献者名单

<a href="https://github.com/spring-ai-alibaba/DataAgent/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=spring-ai-alibaba/DataAgent" />
</a>

---

<div align="center">
    Made with ❤️ by Spring AI Alibaba DataAgent Team
</div>
