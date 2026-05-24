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
├── update-data.sh
└── stop.sh
```

## 当前关键目录

- `backend/`
  FastAPI、API、认证、任务编排、结果拼装、缓存与自动更新
- `frontend/`
  Vue 3 + Vite 前端
- `pipeline/`
  行情抓取、初选、候选构建
- `agent/`
  quant 复核、单股诊断
- `deploy/`
  Docker Compose、Dockerfile、运行脚本
- `nginx/`
  生产统一入口反向代理配置
- `config/`
  dashboard、reviewer、预筛选、退出计划和行情抓取配置
- `data/`
  快照、缓存、导出与运行期数据

## 当前保留脚本

- `start.sh`
- `stop.sh`
- `update-data.sh`
- `deploy/scripts/start.sh`
- `deploy/scripts/release.sh`
- `deploy/scripts/backup.sh`

当前仓库不再保留 SQLite 运行能力和本机直启控制器。

补充说明：

- `backend/migrations/` 目录仍保留 PostgreSQL 初始化 SQL
- 测试代码中仍可使用内存 SQLite 作为隔离数据库，这不属于部署分支
