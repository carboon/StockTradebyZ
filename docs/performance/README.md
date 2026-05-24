# 性能测试基线

本目录记录 StockTrade 在真实运行服务上的压测方式。当前基线优先覆盖 Mac mini M4 上多人在线查询的读路径，不触发数据初始化、日更、补数、生成候选等写入或破坏性任务。

## 启动服务

从仓库根目录启动 Docker 生产链路：

```bash
cp .env.example deploy/.env
./start.sh
./deploy/scripts/start.sh ps
```

默认入口通常是 `http://127.0.0.1:80`，如果 `deploy/.env` 设置了 `NGINX_PORT=127.0.0.1:8080`，则入口是 `http://127.0.0.1:8080`。

## 运行 HTTP 压测

脚本位于：

```bash
scripts/perf/http_api_load_test.py
```

它只使用 Python 标准库，对运行中的服务发起真实 HTTP 请求，登录后使用 Bearer token 访问接口。敏感信息不要写入命令历史或提交到 Git，建议用环境变量传入：

```bash
export STOCKTRADE_PERF_BASE_URL="http://127.0.0.1:8080"
export STOCKTRADE_PERF_USERNAME="admin"
export STOCKTRADE_PERF_PASSWORD="替换为 deploy/.env 中的密码"
export STOCKTRADE_PERF_CODES="600000,000001,600036,600519,000858"

.venv/bin/python scripts/perf/http_api_load_test.py \
  --concurrency 8 \
  --duration 60 \
  --json-output data/perf/mac-mini-m4-baseline.json
```

也可以直接传已经获取到的 token，避免在压测开始前再次登录：

```bash
STOCKTRADE_PERF_TOKEN="ey..." \
.venv/bin/python scripts/perf/http_api_load_test.py \
  --base-url http://127.0.0.1:8080 \
  --concurrency 16 \
  --duration 120
```

脚本会同时输出人类可读摘要和完整 JSON。统计项包括：

- `avg_ms`
- `p50_ms`
- `p95_ms`
- `p99_ms`
- `error_rate`
- `rps`
- `status_counts`

当存在 HTTP 4xx/5xx、超时或连接错误时，脚本会把这些请求计入错误率，并以退出码 `2` 结束，方便 CI 或手工巡检识别失败。

## 场景

默认 `--scenario all` 会混合运行以下只读场景：

- `single-diagnosis`：单股诊断热查询，访问 `/api/v1/analysis/diagnosis/{code}/history-status`
- `kline`：K 线查询，访问 `/api/v1/stock/kline`
- `market`：全盘候选/结果，混合访问明日之星和当前热盘候选/结果
- `page-switch`：模拟页面切换，混合访问新鲜度、日期、自选、K 线、诊断、全盘接口
- `update-read`：日更期间读请求基线，只读任务状态、新鲜度、K 线、全盘结果，不主动触发日更

只压单个场景：

```bash
.venv/bin/python scripts/perf/http_api_load_test.py \
  --base-url http://127.0.0.1:8080 \
  --username "$STOCKTRADE_PERF_USERNAME" \
  --password "$STOCKTRADE_PERF_PASSWORD" \
  --scenario kline \
  --concurrency 20 \
  --duration 180
```

组合多个场景：

```bash
.venv/bin/python scripts/perf/http_api_load_test.py \
  --scenario market \
  --scenario page-switch \
  --concurrency 12 \
  --duration 120
```

## 建议基线流程

1. 启动 Docker 服务并确认首页、登录、单股诊断、全盘分析页面可正常打开。
2. 先用 `--concurrency 1 --duration 10` 做连通性冒烟。
3. 使用 `--concurrency 8 --duration 60` 记录轻量多人查询基线。
4. 使用 `--concurrency 16`、`32` 逐步增加压力，观察 p95/p99 和错误率。
5. 如需日更期间基线，先由任务中心或运维流程启动日更，再单独运行 `--scenario update-read`；脚本本身不会启动日更。

结果文件建议写到 `data/perf/`，该目录属于运行期数据，不应提交到 Git。
