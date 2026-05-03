# 目录结构说明

## 顶层目录

```text
StockTradebyZ/
├── agent/
├── backend/
├── config/
├── data/
├── deploy/
├── docs/
├── frontend/
├── nginx/
├── pipeline/
├── ARCHITECTURE.md
├── DEPLOYMENT.md
├── README.dev.md
├── README.md
├── start.sh
└── stop.sh
```

## 当前关键目录

- `backend/`
  FastAPI、API、任务编排、结果拼装
- `frontend/`
  Vue 前端
- `pipeline/`
  行情抓取、初选、候选构建
- `agent/`
  quant 复核、单股诊断
- `deploy/`
  Docker Compose、Dockerfile、运行脚本
- `data/`
  快照、缓存、导出与运行期数据

## 当前保留脚本

- `start.sh`
- `stop.sh`
- `deploy/scripts/start.sh`
- `deploy/scripts/release.sh`
- `deploy/scripts/backup.sh`

当前仓库不再保留 SQLite、迁移脚本和本机直启控制器。
