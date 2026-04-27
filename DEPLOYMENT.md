# StockTrader 2.0 部署运行指南

## 📝 最近更新 (2024-04-27)

### 新增功能
- ✅ **自动端口分配**: 启动时自动检测端口占用，智能分配可用端口
- ✅ **Windows 完整支持**: 提供 PowerShell 脚本，一键安装和启动
- ✅ **编码问题修复**: 解决 Windows 下中文乱码和 emoji 字符问题
- ✅ **配置文件模板**: 新增 `.env.example` 便于快速配置

### 改进
- 🚀 优化启动流程，无需手动处理端口冲突
- 🔧 增强错误提示，更友好的用户指引
- 📦 完善依赖管理，支持国内镜像源加速

---

## 项目结构

```
StockTradebyZ/
├── backend/                 # FastAPI 后端
│   ├── app/
│   │   ├── api/            # API 路由
│   │   ├── models/         # 数据模型
│   │   ├── schemas/        # Pydantic 模式
│   │   ├── services/       # 业务逻辑
│   │   ├── websocket/      # WebSocket 工具
│   │   ├── config.py       # 配置
│   │   ├── database.py     # 数据库
│   │   └── main.py         # 入口
│   └── requirements.txt
│
├── frontend/               # Vue 3 前端
│   ├── src/
│   │   ├── api/           # API 调用
│   │   ├── components/    # 组件
│   │   ├── stores/        # Pinia 状态
│   │   ├── views/         # 页面
│   │   └── main.ts
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
│
├── data/                   # 数据目录 (本地开发)
├── pipeline/              # 选股流程
├── agent/                 # AI 代理
├── config/                # 配置文件
├── docker-compose.yml     # Docker 编排
├── Dockerfile             # 后端镜像
├── Dockerfile.frontend    # 前端镜像
├── .env.example           # 环境变量模板
└── run_all.py            # 主流程脚本
```

---

## 一、非 Docker 一键部署（推荐给 macOS / Linux 用户）

项目根目录已经提供了一组脚本，适合单机部署：

```bash
# 0. 最简一键方式
./bootstrap-local.sh

# 1. 如需分步执行：安装依赖（自动创建 .venv，默认使用国内镜像）
./install-local.sh

# 如需连系统依赖一起自动安装
AUTO_INSTALL_SYSTEM_DEPS=1 ./install-local.sh

# 2. 编辑 .env，至少填入 TUSHARE_TOKEN
vi .env

# 3. 启动前预检（推荐）
./preflight-local.sh

# 4. 首次初始化数据
./init-data.sh

# 5. 启动前后端
./start-local.sh

# 6. 查看状态
./status-local.sh

# 7. 停止服务
./stop-local.sh

# 8. 完整卸载本地部署
./uninstall-local.sh

# 9. 生成系统守护配置（可选）
./generate-service.sh
```

`bootstrap-local.sh` 的行为：

- 首次执行时自动安装依赖
- 若 `TUSHARE_TOKEN` 未配置，仍会启动前后端，并在页面中强提示先完成配置
- 已配置 Token 时自动执行预检、初始化数据、启动前后端

### 1.1 完整卸载

如需彻底移除本地部署，可直接执行：

```bash
./uninstall-local.sh
```

会清理以下内容：

- 停止 `start-local.sh` 启动的前后端进程
- 卸载用户级 `systemd` / `LaunchAgent` 服务（如已安装）
- 删除数据库和本地业务数据：`data/`
- 删除本地配置：`.env`、`frontend/.env.local`
- 删除本地依赖与构建产物：`.venv`、`frontend/node_modules`、`frontend/dist`
- 删除守护模板目录：`deploy/`

### 1.2 国内环境优化

脚本默认内置以下加速源：

- pip: `https://pypi.tuna.tsinghua.edu.cn/simple`
- npm: `https://registry.npmmirror.com`

如需覆盖，可在执行时自行指定：

```bash
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple \
NPM_REGISTRY=https://registry.npmmirror.com \
./install-local.sh
```

如机器尚未安装 `python/node/npm/pip/venv/lsof`，`install-local.sh` 会先检查系统依赖：

- 默认模式：给出当前系统对应的安装命令，不直接改系统环境
- 自动安装模式：执行 `AUTO_INSTALL_SYSTEM_DEPS=1 ./install-local.sh`

当前已内置的系统包管理器识别：

- macOS: `brew`
- Debian / Ubuntu: `apt-get`
- Fedora / Rocky / AlmaLinux: `dnf`
- CentOS: `yum`

### 1.3 预检脚本

`preflight-local.sh` 会检查：

- Python / Node / npm 是否可用
- `.env` 是否存在
- `TUSHARE_TOKEN` 是否已配置（未配置时给出警告，不阻止启动）
- 数据目录是否就绪
- 前后端端口是否被占用
- `tushare.pro`、pip 镜像、npm 镜像是否可访问

推荐在首次启动前执行：

```bash
./preflight-local.sh
```

### 1.4 守护服务配置

如果希望用户登录后长期运行，可生成本机守护模板：

```bash
./generate-service.sh
```

- Linux: 生成 `systemd --user` 服务文件
- macOS: 生成 `LaunchAgent` plist
- 会自动读取当前 `.env` 中的端口和 `VITE_API_BASE_URL`

生成文件位于：

- `deploy/systemd/`
- `deploy/launchd/`

### 1.5 默认端口

- 后端: `8000`
- 前端: `5173`

可在 `.env` 中修改：

```bash
BACKEND_PORT=8000
FRONTEND_PORT=5173
VITE_API_BASE_URL=http://127.0.0.1:8000/api
```

---

## 一点五、Windows 本地一键部署

Windows 不复用 `*.sh` 脚本，改用 `PowerShell + Python CLI` 入口。

推荐直接执行：

```powershell
.\bootstrap-local.bat
```

常用命令：

```powershell
.\install-local.bat
.\preflight-local.bat
.\init-data.bat
.\start-local.bat
.\status-local.bat
.\stop-local.bat
.\uninstall-local.bat
```

说明：

- `*.bat` 会自动调用同名 `*.ps1`
- `*.ps1` 再调用共享控制器 `tools/localctl.py`
- 现有 macOS / Linux 的 `*.sh` 入口保持不变

详细说明请看 [WINDOWS_DEPLOYMENT.md](WINDOWS_DEPLOYMENT.md)。

---

## 二、本地开发模式

### 2.0 本地数据库说明

当前默认使用 SQLite，本地数据库文件为：

- `data/db/stocktrade.db`

特点：

- 无需单独安装数据库服务，适合单机部署
- 备份方式直接复制该文件即可
- 若迁移到另一台机器，连同 `data/` 目录一起迁移最稳妥

常用管理方式：

```bash
# 查看表
sqlite3 data/db/stocktrade.db ".tables"

# 进入数据库
sqlite3 data/db/stocktrade.db
```

### 2.1 环境准备

```bash
# Python 3.12+
python --version

# Node.js 18+
node --version
npm --version
```

### 2.2 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，填入必要配置
# 至少需要配置 TUSHARE_TOKEN
```

**必需配置**:
```bash
# Tushare Token (必需)
TUSHARE_TOKEN=你的token

# 可选 LLM API Key
ZHIPUAI_API_KEY=
DASHSCOPE_API_KEY=
GEMINI_API_KEY=
```

### 2.3 启动后端

```bash
# 方式一: 使用虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate  # Windows

pip install -r requirements.txt
pip install -r backend/requirements.txt

# 启动后端
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

```bash
# 方式二: 直接安装
pip install -r requirements.txt
pip install -r backend/requirements.txt

cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

后端启动后访问: http://localhost:8000/docs

### 2.4 启动前端

```bash
cd frontend

# 首次运行需要安装依赖
npm install

# 创建本地环境变量 (可选)
cat > .env << EOF
VITE_API_BASE_URL=http://127.0.0.1:8000/api
EOF

# 启动开发服务器
npm run dev
```

前端启动后访问: http://localhost:5173

---

## 三、Docker 部署模式

### 3.1 配置环境变量

```bash
# 确保项目根目录有 .env 文件
cp .env.example .env
vi .env  # 编辑配置
```

### 3.2 构建并启动

```bash
# 构建镜像并启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f backend
docker-compose logs -f frontend
```

### 3.3 服务地址

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:3000 |
| 后端 API | http://localhost:8000 |
| API 文档 | http://localhost:8000/docs |
| Nginx (生产) | http://localhost:80 |

### 3.4 常用命令

```bash
# 停止服务
docker-compose down

# 重启服务
docker-compose restart

# 重新构建镜像
docker-compose build --no-cache

# 进入后端容器
docker-compose exec backend bash

# 查看数据目录
docker-compose exec backend ls -la /app/data
```

---

## 四、首次运行配置

### 4.1 初始化数据

首次运行需要拉取股票数据：

```bash
# 进入后端容器 (Docker 模式)
docker-compose exec backend bash

# 或本地开发模式
cd /path/to/StockTradebyZ

# 拉取基础数据
python run_all.py --reviewer quant --start-from 1
```

### 4.2 通过 Web UI 操作

1. 访问 http://localhost:3000
2. 进入 **"全量更新"** 页面
3. 选择评分模式（量化评分免费）
4. 点击 **"开始全量更新"**
5. 等待数据抓取和分析完成

---

## 五、数据目录说明

```
data/
├── db/                    # SQLite 数据库
│   └── stocktrade.db
├── raw/                   # 原始 K 线数据
├── candidates/            # 候选股票
├── review/                # 分析结果
├── kline/                 # K 线图表
└── logs/                  # 日志文件
```

---

## 六、故障排查

### 6.1 后端启动失败

```bash
# 检查端口占用
lsof -i :8000

# 检查数据库权限
mkdir -p data/db
chmod 755 data/db
```

### 6.2 前端连接不上后端

检查 `frontend/.env` 或 `.env.local`:
```bash
VITE_API_BASE_URL=http://127.0.0.1:8000/api
```

### 6.3 Docker 日志查看

```bash
# 查看所有容器状态
docker-compose ps

# 查看后端日志
docker-compose logs backend

# 查看前端日志
docker-compose logs frontend
```

### 6.4 WebSocket 连接失败

确保后端 CORS 配置正确，检查 `.env`:
```bash
BACKEND_CORS_ORIGINS=http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173
```

---

## 七、生产环境部署

### 7.1 使用 Nginx 反向代理

```bash
# 启用生产模式 Nginx
docker-compose --profile production up -d
```

### 7.2 环境变量建议

生产环境建议配置:
```bash
# 使用外部数据库 (可选)
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# 配置 CORS 为实际域名
BACKEND_CORS_ORIGINS=https://yourdomain.com

# 使用 Redis 做缓存 (可选)
REDIS_URL=redis://redis:6379/0
```

---

## 八、快速启动脚本

### 本地开发快速启动

```bash
# 完整启动（包含依赖安装）
./start-dev.sh

# 跳过依赖安装（快速启动）
./start-dev.sh --skip-deps
```

启动脚本功能:
- 自动创建虚拟环境
- 自动安装 Python/Node 依赖
- 同时启动后端 (8000) 和前端 (5173)
- Ctrl+C 优雅停止所有服务

### Docker 快速启动

```bash
#!/bin/bash
# start-docker.sh

docker-compose up -d
echo "服务已启动"
echo "前端: http://localhost:3000"
echo "后端: http://localhost:8000"
```
