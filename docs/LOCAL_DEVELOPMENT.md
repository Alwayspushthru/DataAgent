# 本地开发与启动

本文档整理本地环境准备、首次配置与日常启动操作。产品功能和页面使用流程见 [README](../README.md)，完整配置说明见 [快速开始](QUICK_START.md)。

`make start` 适用于已完成初始化、且具备本机辅助脚本的环境。首次克隆项目请从“准备环境”和“新环境：首次配置与手动启动”开始。

## 1. 准备环境

- JDK 17+，并设置 `JAVA_HOME`
- MySQL 5.7+（可使用 Docker 容器运行）
- Node.js 22+
- pnpm 11+（下面的命令无需全局安装 pnpm）
- Docker（使用容器 MySQL 或执行 Python 工作流时必需）

项目自带 Maven Wrapper，使用 `./mvnw`，无需另外安装 Maven。

## 2. 已初始化的本机环境：日常启动

以下日常启动操作适用于已配置 Docker MySQL、本机 Java 后端和 Nuxt 前端的环境。先打开 Docker Desktop，
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

此本机环境约定管理库为 `saa_data_agent`，示例业务库为 `product_db`，数据库监听
`127.0.0.1:3306`。若初始化数据已保存在 Docker 卷中，日常启动不需要重新导入 SQL。
停止前后端时在各自终端按 `Ctrl+C`；停止数据库执行：

```bash
docker stop dataagent-local-mysql
```

## 3. 新环境：首次配置与手动启动

先按[快速开始文档](QUICK_START.md)准备 MySQL，创建管理库并配置数据库连接。
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

## 4. 访问系统

打开浏览器访问 http://localhost:3000 。首次使用时，在“模型配置”中添加聊天模型
和嵌入模型的 API Key，测试连接并设为默认，再配置智能体的数据源。
