# StockTrader 2.0

一个面向个人电脑本地部署的 A 股量化选股与复核工具。当前默认工作流是：

`Tushare 行情采集 -> B1 初选 -> Quant 程序化复核 -> Web 任务中心与结果查看`

项目已经从“脚本为主”演进为“本地脚本 + FastAPI + Vue”混合架构，但真正的选股逻辑仍主要在 `pipeline/` 和 `agent/` 中，Web 层负责部署、配置、任务编排、进度展示和新人引导。

## 文档导航

- [ARCHITECTURE.md](ARCHITECTURE.md): 当前真实架构、运行模式、任务与恢复机制
- [DEPLOYMENT.md](DEPLOYMENT.md): macOS / Linux 本地部署与 Docker 部署
- [WINDOWS_DEPLOYMENT.md](WINDOWS_DEPLOYMENT.md): Windows 本地部署
- [README.dev.md](README.dev.md): 开发者入口、调试与常用命令

## 当前系统形态

- 本地优先，默认使用 SQLite 和本地 `data/` 目录
- 推荐部署入口是 `bootstrap-local.sh` / `bootstrap-local.bat`
- 本地部署模式下，前端生产资源由 FastAPI 统一提供，默认只访问 `http://127.0.0.1:8000`
- 直接打开 `/update`、`/tomorrow-star`、`/diagnosis` 等前端路由时，后端会做 SPA 回退，不需要单独的 Nginx 规则
- 第 1 步 Tushare 抓取是最耗时阶段，界面右上角和任务中心都会显示 `当前/总数/ETA/当前代码`
- 真正具备断点恢复的是远端数据抓取和增量更新；后续步骤如果中断，重新发起任务会基于已抓取的本地数据重新生成

## 快速开始

### macOS / Linux

```bash
./bootstrap-local.sh
```

### Windows

```powershell
.\bootstrap-local.bat
```

完成后默认访问：

- 应用首页: `http://127.0.0.1:8000`
- API 文档: `http://127.0.0.1:8000/docs`

如果 `TUSHARE_TOKEN` 尚未配置，系统仍可先启动；首次进入后可在“配置管理”页面填写并验证 Token，再从“运维管理”页面启动首次初始化。

## 首次初始化与日常更新

首次初始化会通过后端任务中心执行，而不是要求用户手工拼命令。当前行为如下：

- 初始化任务由 `POST /api/v1/tasks/start` 发起
- CLI 包装脚本 `init-data.sh` / `tools/localctl.py init-data` 本质上也是调用同一套 API
- 抓取原始数据阶段会显示股票级进度、预计剩余时间、当前代码、失败数量和已恢复数量
- 如果抓取阶段中断，再次发起初始化时会优先从 `data/run/` 里的断点继续
- 如果只是后续步骤中断，重新发起初始化会复用已抓好的 `data/raw/`，重新生成候选和分析结果

日常更新一般有两种：

- 全量初始化 / 全量重跑：`/api/v1/tasks/start`
- 最新交易日增量更新：`/api/v1/tasks/start-incremental`

两类任务互斥，避免同时占用 Tushare 配额和本地数据目录。

## 核心功能

- 配置管理：保存 `TUSHARE_TOKEN`，做首次启动自检
- 运维管理：启动初始化、查看任务日志、查看本机诊断、发起增量更新
- 明日之星：查看候选股与 `PASS / WATCH / FAIL` 结果
- 单股诊断：查看单只股票的 B1 检查、量化评分和 K 线数据
- 重点观察：维护自选跟踪与观察建议
- 系统说明：给非开发用户解释当前默认口径和使用方式

## 关键目录

```text
backend/           FastAPI 后端
frontend/          Vue 3 前端
pipeline/          第 1~2 步选股流程
agent/             第 4 步复核与单票分析
dashboard/         图表导出与 Streamlit 看盘工具
config/            YAML 策略与流程配置
data/              SQLite、CSV、候选结果、日志、断点文件
tools/localctl.py  本地部署控制器
run_all.py         全量流程总入口
```

## 路由与 API 约定

浏览器页面路由和后端 API 不是一回事：

- 页面路由：`/config`、`/update`、`/tomorrow-star`、`/diagnosis`、`/watchlist`
- API 路由：统一在 `/api/v1/*` 下

例如：

- 页面地址：`http://127.0.0.1:8000/update`
- API 地址：`http://127.0.0.1:8000/api/v1/tasks/overview`

如果你用 `curl` 调试后端，请优先访问 `/api/v1/...`，不要把页面路由当成 JSON 接口。

## 开发模式

如果你需要前后端分开调试，可使用：

```bash
./start-dev.sh
```

这会启动：

- FastAPI: `http://127.0.0.1:8000`
- Vite: `http://127.0.0.1:5173`

本地开发模式和本地部署模式的区别、目录职责和服务边界，请直接看 [ARCHITECTURE.md](ARCHITECTURE.md)。
