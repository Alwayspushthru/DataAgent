#!/usr/bin/env bash

# Copyright 2026 the original author or authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
mysql_container="${1:-dataagent-local-mysql}"
backend_script=".vscode/local-run/start-backend.sh"
frontend_script=".vscode/local-run/start-frontend.sh"

for script in "$backend_script" "$frontend_script"; do
    if [[ ! -x "$script" ]]; then
        echo "缺少可执行的本机启动脚本：${script}。请参考 README 的首次配置与手动启动步骤。" >&2
        exit 1
    fi
done
if [[ ! -x data-agent-frontend-nuxt/node_modules/.bin/pnpm ]]; then
    echo "请先安装前端依赖：cd data-agent-frontend-nuxt && npx --yes pnpm@11.9.0 install" >&2
    exit 1
fi
if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    echo "无法连接 Docker，请先启动 Docker Desktop 并确认当前终端可使用 docker。" >&2
    exit 1
fi
if ! docker container inspect "$mysql_container" >/dev/null 2>&1; then
    echo "找不到已有 MySQL 容器 ${mysql_container}，请先按 README 完成本机初始化。" >&2
    exit 1
fi

echo "启动 MySQL：$mysql_container"
docker start "$mysql_container" >/dev/null
echo "等待 MySQL 就绪（最多尝试 30 次，每次间隔 2 秒）……"
mysql_ready=false
for ((attempt = 0; attempt < 30; attempt++)); do
    if docker exec "$mysql_container" mysqladmin ping --host=127.0.0.1 --silent --connect-timeout=1 >/dev/null 2>&1; then
        mysql_ready=true
        break
    fi
    sleep 2
done
if [[ "$mysql_ready" != true ]]; then
    echo "MySQL 未就绪，请检查：docker logs $mysql_container" >&2
    exit 1
fi

# Separate process groups let cleanup stop Maven/Java and pnpm/Nuxt descendants too.
# Job control works with the Bash 3.2 shipped on macOS; wait -n is not required.
set -m
service_pids=()
cleanup() {
    trap '' INT TERM
    if [[ ${#service_pids[@]} -gt 0 ]]; then
        echo "正在停止前后端；MySQL 保持运行。停止数据库请执行 make db-stop。"
        for pid in "${service_pids[@]}"; do
            kill -TERM -- "-$pid" 2>/dev/null || true
        done
        for ((attempt = 0; attempt < 50; attempt++)); do
            alive=false
            for pid in "${service_pids[@]}"; do
                if kill -0 -- "-$pid" 2>/dev/null; then alive=true; fi
            done
            if [[ "$alive" == false ]]; then break; fi
            sleep 0.2
        done
        for pid in "${service_pids[@]}"; do
            kill -KILL -- "-$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        done
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "启动前后端，日志输出到当前终端。按 Ctrl+C 统一停止。"
"$backend_script" &
service_pids+=("$!")
"$frontend_script" &
service_pids+=("$!")
echo "启动完成后访问 http://localhost:3000（后端端口 8065）。"

while true; do
    for pid in "${service_pids[@]}"; do
        if ! kill -0 "$pid" 2>/dev/null; then
            status=0
            wait "$pid" || status=$?
            echo "前后端进程之一已退出（状态码 ${status}），正在关闭另一进程。" >&2
            exit "$status"
        fi
    done
    sleep 1
done
