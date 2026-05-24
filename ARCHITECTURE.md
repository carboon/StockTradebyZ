# StockTrader 2.0 架构说明

## 当前运行模型

系统当前收敛为 `PostgreSQL + Redis + Docker`。

统一入口/生产链路：

```text
Browser
  -> Nginx
  -> FastAPI backend
  -> PostgreSQL
```

后端同时连接：

```text
FastAPI backend
  -> Redis cache
  -> data/ snapshots, logs, exports
  -> pipeline/ and agent/ offline logic
```

开发链路：

```text
Browser
  -> Vite frontend-dev
  -> FastAPI backend
  -> PostgreSQL
```

说明：

- 生产/统一入口使用 `nginx` 托管前端静态资源，并代理 `/api/`、`/ws/`、`/data/`
- 开发模式使用 `frontend-dev` 提供 Vite HMR，后端独立暴露 `8000`
- `backend` 负责 API、认证、任务编排、读缓存、结果拼装和后台调度
- `pipeline/` 和 `agent/` 保留离线候选构建、量化复核、AI reviewer 和研究辅助逻辑
- PostgreSQL 是正式主库；SQLite 仅允许在测试隔离中出现
- Redis 是读缓存和部分预热结果的加速层，不可用时后端会降级到内存缓存

## 模块职责

- `frontend/`
  Vue 3 + Vite 前端，包含全盘分析、板块分析、单股诊断、重点观察、任务中心、配置、用户和系统说明页面。
- `backend/`
  FastAPI 服务，包含 API 路由、认证授权、数据库模型、任务管理、自动更新、数据服务、缓存和启动迁移。
- `pipeline/`
  行情抓取、候选筛选、回测、批量重建和离线策略流程。
- `agent/`
  量化 reviewer、AI reviewer、单股分析和持仓/观察辅助报告。
- `deploy/`
  Docker Compose、Dockerfile、启动脚本、发布脚本、备份脚本和 systemd service。
- `config/`
  dashboard、reviewer、预筛选、退出计划和行情抓取配置。
- `data/`
  运行期目录，存放原始日线分片、分时快照、缓存、导出和日志。

## API 分层

主要 API 前缀：

- `/api/v1/auth`：登录、注册验证、用户资料、密码、API Key、用量和管理员用户管理
- `/api/v1/config`：系统配置、Tushare 验证、环境变量保存和运行时配置重载
- `/api/v1/stock`：股票搜索、股票基础信息和 K 线数据
- `/api/v1/analysis`：明日之星、当前热盘、板块分析、中盘分析、单股诊断、概念板块和信号收益
- `/api/v1/watchlist`：重点观察列表、观察项分析和图表
- `/api/v1/tasks`：任务中心、数据更新、完整性检查、日志、恢复、增量补齐和管理员摘要

WebSocket：

- `/ws/tasks/{task_id}`：单任务进度与日志
- `/ws/ops`：任务中心统一事件流

## 在线与离线边界

在线接口：

- 以查询、拼装、缓存和任务编排为主
- 优先读取 PostgreSQL、Redis 和已生成快照
- 不在普通页面请求里触发全市场重算
- 更新进行中时，关键读页面返回“更新数据中”状态

离线任务：

- 由任务中心、后台调度或 `./update-data.sh` 触发
- 负责抓数、补数、重建明日之星、当前热盘、板块分析和中盘快照
- 完成后预热读路径，页面只消费已生成结果

## 数据流

日线：

```text
Tushare daily/daily_basic/moneyflow
  -> data/raw_daily/{trade_date}.jsonl
  -> stock_daily
  -> candidates, analysis_results, current_hot, sector_analysis
```

盘中：

```text
Eastmoney -> Tencent -> Tushare rt_min
  -> data/raw_intraday/
  -> intraday snapshots
  -> 全盘分析/当前热盘中盘视图
```

诊断：

```text
stock_daily + K 线 + B1 + quant reviewer
  -> diagnosis history cache
  -> 单股诊断/重点观察
```

## 核心业务流程

`明日之星`：

```text
流动性池 Top 2000
  -> B1 四项检查
  -> ST/次新/解禁/行业强度/市场环境前置过滤
  -> 趋势结构/价格位置/量价行为/历史异动四维复核
  -> PASS / WATCH / FAIL
```

`当前热盘`：

```text
活跃股票池
  -> 热度与强弱计算
  -> 候选和结果生成
  -> 板块强弱与轮动聚合
```

`中盘分析`：

```text
09:30~11:30 分时数据
  -> 大盘中盘总览
  -> 个股上午强弱、关键价位、执行参考
```

`重点观察`：

```text
用户观察/持仓记录
  -> 单股诊断和图表
  -> 执行层建议
```

## 更新模型

- `daily`：更新指定交易日或最新交易日的日线，并重建当日结果
- `generate`：检查近 120 日窗口缺口，补齐缺失数据和市场指标，再重建派生结果
- `intraday`：11:30 后生成中盘快照，默认截止 `11:30:00`
- `repair daily`：修复 `stock_daily` 缺失或样本不足
- `repair scores`：修复历史候选、评分、结果和运行记录不一致

自动更新由后端应用内调度器负责，默认配置入口在任务中心；不再依赖宿主机 systemd timer。

## 数据边界

- 正式主库只有 PostgreSQL
- Redis 只作为缓存层，不作为唯一数据来源
- 文件系统只保留快照、缓存、导出和日志
- `data/`、`.env`、`deploy/.env` 和真实密钥不得提交

## 官方入口

- 本地统一入口：`./start.sh`
- 开发 HMR：`./deploy/scripts/start.sh dev --build`
- 停止：`./stop.sh`
- 生产启动：`./deploy/scripts/start.sh prod --build`
- 发布：`./deploy/scripts/release.sh`
- 数据更新：`./update-data.sh`
- 备份：`./deploy/scripts/backup.sh`
