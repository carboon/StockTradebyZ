# StockTrader 2.0 部署运行指南

相关文档：

- [README.md](README.md): 项目入口与快速开始
- [ARCHITECTURE.md](ARCHITECTURE.md): 当前真实架构、任务中心、进度与恢复机制
- [README.dev.md](README.dev.md): 开发者入口
- [WINDOWS_DEPLOYMENT.md](WINDOWS_DEPLOYMENT.md): Windows 详细说明

## 1. 推荐模式

对个人电脑用户，当前推荐只有一个：

- 本地部署模式
- 后端统一提供前端页面
- 单机 SQLite
- 本地 `data/` 目录持久化

默认访问地址：

- 应用首页: `http://127.0.0.1:8000`
- API 文档: `http://127.0.0.1:8000/docs`

## 2. macOS / Linux 本地部署

### 2.1 一键启动

```bash
./bootstrap-local.sh
```

这会调用共享控制器 `tools/localctl.py`，完成：

- 安装 Python 依赖和前端依赖
- 准备 `.venv`
- 生成前端本地环境配置
- 启动后端
- 如果已经配置好 `TUSHARE_TOKEN`，自动发起首次初始化

### 2.2 分步执行

```bash
# 安装依赖
./install-local.sh

# 启动前预检
./preflight-local.sh

# 启动本地服务
./start-local.sh

# 首次初始化
./init-data.sh

# 查看状态
./status-local.sh

# 停止服务
./stop-local.sh

# 卸载本地部署
./uninstall-local.sh
```

### 2.3 首次进入时未配置 Token

如果还没有 `TUSHARE_TOKEN`，系统也允许先启动。

这时推荐路径是：

1. 执行 `./start-local.sh`
2. 打开 `http://127.0.0.1:8000`
3. 进入“配置管理”页面填写并验证 Token
4. 进入“运维管理”页面启动首次初始化

### 2.4 常用入口脚本和真实行为

当前这些脚本本质上都是 `tools/localctl.py` 的薄包装：

- `bootstrap-local.sh`
- `install-local.sh`
- `preflight-local.sh`
- `start-local.sh`
- `init-data.sh`
- `status-local.sh`
- `stop-local.sh`
- `uninstall-local.sh`

这意味着：

- macOS / Linux 和 Windows 的行为已经尽量统一
- CLI 和页面不是两套独立逻辑，而是共用同一套后端 API 和本地控制器

## 3. 初始化、进度与恢复

### 3.1 首次初始化做什么

首次初始化对应全量流程：

1. Tushare 抓取原始日线到 `data/raw/`
2. 量化初选
3. 导出候选图
4. quant 程序化复核
5. 导出 PASS 图表
6. 生成推荐结果

发起方式：

- 页面：运维管理页
- API：`POST /api/v1/tasks/start`
- CLI：`./init-data.sh`

### 3.2 进度展示

当前最重要的进度是第 1 步远端抓数。

系统会在这些位置显示：

- 页面右上角全局进度卡
- 运维管理页任务中心
- `init-data.sh` 的命令行输出

抓数阶段会重点显示：

- `当前/总数`
- `ETA`
- `当前代码`
- `失败数量`
- `已恢复数量`

### 3.3 恢复机制

当前真实恢复能力如下：

- 第 1 步远端抓数支持断点恢复
- 最新交易日增量更新支持断点恢复
- 第 2 步到第 6 步没有再做细粒度任务快照恢复

这意味着：

- 如果抓数中断，再次发起初始化会优先继续抓剩余股票
- 如果后续步骤中断，重新发起任务会基于已抓好的 `data/raw/` 重新生成

### 3.4 任务互斥

系统当前会避免同时跑多套大任务：

- 同一时间只允许一个全量类任务
- 增量更新和全量初始化互斥

这样做是为了：

- 避免重复占用 Tushare 配额
- 避免并发写同一批本地数据文件
- 保证前端进度展示只有一套主状态

## 4. 本地数据与迁移

默认数据目录：

```text
data/
├─ db/          SQLite 数据库
├─ raw/         原始 K 线 CSV
├─ candidates/  候选结果
├─ review/      评分结果
├─ kline/       导出的图表
├─ logs/        日志
├─ run/         pid 文件与断点文件
└─ cache/       本地缓存
```

默认数据库文件：

- `data/db/stocktrade.db`

如果你要迁移到另一台个人电脑，最稳妥的做法通常是一起迁移：

- `.env`
- `data/`

## 5. Windows 本地部署

Windows 不走 `*.sh`，而是走：

- `*.bat`
- `*.ps1`
- 共享控制器 `tools/localctl.py`

推荐入口：

```powershell
.\bootstrap-local.bat
```

常用命令：

```powershell
.\install-local.bat
.\preflight-local.bat
.\start-local.bat
.\init-data.bat
.\status-local.bat
.\stop-local.bat
.\uninstall-local.bat
```

详细步骤看 [WINDOWS_DEPLOYMENT.md](WINDOWS_DEPLOYMENT.md)。

## 6. 本地开发模式

如果你是开发者，需要前后端分开调试，可使用：

```bash
./start-dev.sh
```

它会启动：

- 后端: `http://127.0.0.1:8000`
- 前端 Vite: `http://127.0.0.1:5173`

注意：

- 这是开发模式，不是推荐给普通用户的部署模式
- 普通用户只需要关心 `http://127.0.0.1:8000`

## 7. Docker 模式

仓库仍保留 Docker 方案，适合你明确希望用容器运行时使用。

### 7.1 启动

```bash
./start-docker.sh up
```

或者：

```bash
docker compose up -d --build
```

### 7.2 停止和日志

```bash
./start-docker.sh down
./start-docker.sh logs
./start-docker.sh backend
./start-docker.sh frontend
```

### 7.3 Docker 默认地址

- 前端: `http://localhost:3000`
- 后端: `http://localhost:8000`
- API 文档: `http://localhost:8000/docs`

当前 Docker 仍是前后端双容器模式，这和本地部署模式不同。

## 8. 环境变量

至少需要：

```bash
TUSHARE_TOKEN=你的token
```

可选：

```bash
DEFAULT_REVIEWER=quant
MIN_SCORE_THRESHOLD=4.0
BACKEND_PORT=8000
VITE_API_BASE_URL=/api
```

说明：

- Web 当前默认主路径是 `quant`
- LLM 脚本仍在仓库中，但页面配置和主流程默认都围绕 `quant`
- 在本地部署模式下，`VITE_API_BASE_URL=/api` 就够了，不需要手写完整域名

## 9. 故障排查

### 9.1 后端是否启动

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/docs
```

### 9.2 页面路由和 API 混淆

当前要分清：

- 页面路由：`/update`
- API 路由：`/api/v1/tasks/*`

例如：

```bash
curl http://127.0.0.1:8000/api/v1/tasks/overview
```

不要把 `/update` 当作 JSON 接口来调。

### 9.3 初始化失败后怎么看

优先查看：

- 页面“运维管理”里的任务日志
- `data/logs/backend.log`
- `data/run/` 下是否保留了断点文件

### 9.4 端口冲突

```bash
lsof -i :8000
```

如果需要，先停止旧进程，再重新执行：

```bash
./stop-local.sh
./start-local.sh
```

## 10. 当前最适合新人的操作路径

推荐你按这个顺序使用：

1. `./bootstrap-local.sh`
2. 打开 `http://127.0.0.1:8000`
3. 如果未配置 Token，先去“配置管理”
4. 去“运维管理”执行首次初始化
5. 初始化完成后，先看“明日之星”，再看“单股诊断”和“重点观察”

如果只记一件事：

- 个人部署模式下，系统入口就是 `http://127.0.0.1:8000`
