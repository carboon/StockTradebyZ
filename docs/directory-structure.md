# StockTrader 目录结构

## 当前结构

```
StockTradebyZ/
├── agent/                   # LLM 审核脚本
├── backend/                 # 后端 API
│   ├── app/                # FastAPI 应用
│   ├── tests/              # 测试
│   └── requirements*.txt   # Python 依赖
├── config/                  # 配置文件
├── dashboard/               # Streamlit 仪表板
├── data/                    # 数据目录 (运行时生成)
├── deploy/                  # 部署相关 ✨
│   ├── docker/             # Docker 镜像
│   │   ├── Dockerfile.dev
│   │   ├── Dockerfile.prod
│   │   ├── Dockerfile.frontend
│   │   ├── Dockerfile.frontend-dev
│   │   └── Dockerfile.nginx
│   ├── docker-compose.yml  # Docker Compose 配置
│   └── scripts/            # 部署脚本
│       ├── start.sh        # 启动脚本
│       └── stop.sh         # 停止脚本
├── docs/                    # 项目文档
├── frontend/                # Vue 前端
├── nginx/                   # Nginx 配置
├── pipeline/                # 数据处理脚本
├── scripts/                 # 工具脚本
│   ├── migrate/            # 数据迁移脚本
│   ├── backup/             # 备份脚本
│   └── utils/              # 工具脚本
│       ├── localctl.py     # 本地控制器
│       ├── backup.sh
│       └── restore.sh
├── tests/                   # 根级测试
├── .env.example             # 环境变量模板
├── README.md                # 项目说明
├── start.sh                 # 快捷启动脚本
└── stop.sh                  # 快捷停止脚本
```

## 快速开始

### 使用 Docker (推荐)

```bash
# 开发环境
./start.sh dev

# 生产环境
./start.sh prod

# 停止服务
./stop.sh
```

### 本地开发

```bash
# 使用 scripts/utils/localctl.py
python scripts/utils/localctl.py start
```

## 目录说明

| 目录 | 说明 |
|------|------|
| `agent/` | LLM 图表审核脚本 |
| `backend/` | FastAPI 后端服务 |
| `config/` | 配置文件 (YAML) |
| `dashboard/` | Streamlit 数据仪表板 |
| `deploy/` | Docker 部署配置和脚本 |
| `docs/` | 项目文档 |
| `frontend/` | Vue 3 前端应用 |
| `nginx/` | Nginx 配置 (生产用) |
| `pipeline/` | 数据处理和选股脚本 |
| `scripts/` | 工具和迁移脚本 |
| `tests/` | 集成测试 |

## 环境变量

在 `.env` 文件中配置：

```bash
# Tushare 配置
TUSHARE_TOKEN=your_token_here

# 数据库
DATABASE_URL=sqlite:///data/db/stocktrade.db

# 后端配置
BACKEND_PORT=8000
BACKEND_HOST=0.0.0.0

# LLM 配置 (可选)
ZHIPUAI_API_KEY=
DASHSCOPE_API_KEY=
GEMINI_API_KEY=
```

## 开发工作流

1. **克隆项目**
   ```bash
   git clone <repo-url>
   cd StockTradebyZ
   ```

2. **配置环境**
   ```bash
   cp .env.example .env
   # 编辑 .env 文件
   ```

3. **启动服务**
   ```bash
   ./start.sh dev
   ```

4. **访问应用**
   - 前端: http://localhost:5173
   - 后端: http://localhost:8000
   - API 文档: http://localhost:8000/docs

## 生产部署

参见 [DEPLOYMENT.md](../deploy/DEPLOYMENT.md)
