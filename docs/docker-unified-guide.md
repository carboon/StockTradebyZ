# 统一 Docker 配置使用说明

## 概述

本项目现在使用统一的 Docker 配置，确保开发和生产环境完全一致。

## 快速开始

### 开发环境

```bash
# 方式 1: 使用启动脚本 (推荐)
./start-unified.sh dev

# 方式 2: 直接使用 docker compose
docker compose -f docker-compose.unified.yml up
```

### 生产环境

```bash
# 方式 1: 使用启动脚本 (推荐)
./start-unified.sh prod

# 方式 2: 直接使用 docker compose
MODE=prod docker compose -f docker-compose.unified.yml up
```

## 启动脚本命令

| 命令 | 说明 |
|------|------|
| `./start-unified.sh dev` | 启动开发环境 (默认) |
| `./start-unified.sh prod` | 启动生产环境 |
| `./start-unified.sh build` | 重新构建镜像 |
| `./start-unified.sh down` | 停止并删除容器 |
| `./start-unified.sh logs [service]` | 查看日志 |
| `./start-unified.sh shell` | 进入后端容器 |
| `./start-unified.sh test` | 运行测试 |
| `./start-unified.sh status` | 查看服务状态 |

## 环境差异

| 项目 | 开发环境 (dev) | 生产环境 (prod) |
|------|----------------|----------------|
| 后端命令 | `uvicorn ... --reload` | `uvicorn ... --workers 1` |
| 前端 | Vite dev server (5173) | Nginx 静态文件 (80) |
| 代码挂载 | ✅ 热更新 | ❌ 只读 |
| 重启策略 | unless-stopped | always |
| 环境变量 | ENVIRONMENT=dev | ENVIRONMENT=prod |

## 端口配置

| 服务 | 开发环境 | 生产环境 |
|------|----------|----------|
| 后端 API | 8000 | 80 (通过 Nginx) |
| 前端 | 5173 (HMR) | 80 (Nginx) |
| API 文档 | 8000/docs | 80/api/docs |

## 文件结构

```
StockTradebyZ/
├── docker-compose.unified.yml  # 统一配置
├── Dockerfile.dev              # 开发环境后端
├── Dockerfile.prod             # 生产环境后端
├── Dockerfile.frontend-dev     # 开发环境前端
├── Dockerfile.frontend         # 生产环境前端
├── Dockerfile.nginx            # Nginx 配置
└── start-unified.sh            # 统一启动脚本
```

## 环境变量

在 `.env` 文件中配置：

```bash
# 后端配置
BACKEND_PORT=8000
BACKEND_HOST=0.0.0.0

# 前端配置 (开发)
FRONTEND_PORT=5173

# Nginx 配置 (生产)
NGINX_PORT=80

# 模式 (dev/prod)
MODE=dev
```

## 开发体验

### 热更新

开发环境支持代码热更新：
- 后端: 修改 `backend/` 下代码自动重载
- 前端: 修改 `frontend/` 下代码自动刷新

### 查看日志

```bash
# 查看所有日志
./start-unified.sh logs

# 查看后端日志
./start-unified.sh logs backend

# 查看 dev 前端日志
./start-unified.sh logs frontend-dev
```

### 进入容器调试

```bash
./start-unified.sh shell
```

## 生产部署

1. 构建镜像
```bash
./start-unified.sh build
```

2. 启动生产环境
```bash
./start-unified.sh prod
```

3. 查看状态
```bash
./start-unified.sh status
```

## 故障排查

### 端口被占用

修改 `.env` 文件中的端口配置：
```bash
BACKEND_PORT=8001
NGINX_PORT=8080
```

### 容器无法启动

查看详细日志：
```bash
docker compose -f docker-compose.unified.yml logs
```

### 重新构建

如果遇到缓存问题：
```bash
./start-unified.sh build --no-cache
```
