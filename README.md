# StockTrader 2.0

当前仓库只保留 PostgreSQL + Docker 的运行方案。

## 快速开始

开发环境：

```bash
./start.sh
```

停止：

```bash
./stop.sh
```

生产环境：

```bash
./deploy/scripts/start.sh prod --build
```

底层等价命令：

```bash
docker compose -f deploy/docker-compose.yml --profile postgres --profile dev up -d --build
docker compose -f deploy/docker-compose.yml --profile postgres --profile prod up -d --build
```

访问地址：

- 开发主入口：`http://127.0.0.1:8080`
- 前端直连：`http://127.0.0.1:5173`
- 后端 API：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`

## 仓库结构

- `frontend/`
  Vue 页面层
- `backend/`
  FastAPI、任务编排、数据接口
- `pipeline/` / `agent/`
  离线量化流程与复核逻辑
- `deploy/`
  Docker Compose、Dockerfile、运行脚本
- `data/`
  快照、缓存、导出和运行期文件

## 文档

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [README.dev.md](README.dev.md)
- [docs/README.md](docs/README.md)

## 当前原则

- 只支持 PostgreSQL
- 只保留 Docker 运行入口
- 不再保留 SQLite 运行、迁移和兼容逻辑
