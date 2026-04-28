# StockTrader 2.0 架构说明

本文档描述当前仓库的真实结构、运行模式、核心数据流，以及“本地个人部署 + 首次初始化 + 进度恢复”这条主线是如何落地的。

## 1. 项目定位

这是一个面向个人电脑的本地化选股与复核系统，不是多用户 SaaS，也不是分布式服务。

当前设计目标非常明确：

- 部署尽量简单，适合个人机器直接跑
- 以本地文件和 SQLite 为主，不引入额外基础设施
- 保留既有量化主流程，不为了 Web 化而重写业务逻辑
- 把最耗时的 Tushare 采集过程做成可见、可恢复、可重试
- 对第一次使用的用户尽量友好，先引导配置，再引导初始化

因此，这个项目本质上是：

`既有量化选股 CLI 流程 + FastAPI 编排层 + Vue 可视化界面 + 本地部署控制器`

## 2. 系统总览

```text
用户
├─ 命令行脚本 (*.sh / *.bat / *.ps1)
│  └─ tools/localctl.py
└─ 浏览器
   └─ http://127.0.0.1:8000
      ├─ Vue 前端 (frontend/)
      └─ FastAPI 后端 (backend/)
         ├─ API 路由层
         ├─ 任务编排 / 进度推送
         ├─ 单股分析 / 增量更新服务
         ├─ SQLite (data/db/stocktrade.db)
         └─ 本地文件数据 (data/raw data/review data/run ...)

全量业务主流程
└─ run_all.py
   ├─ pipeline/fetch_kline.py
   ├─ pipeline/cli.py preselect
   ├─ dashboard/export_kline_charts.py
   └─ agent/quant_reviewer.py / 其他 reviewer
```

最关键的一点：

- `pipeline/` 和 `agent/` 仍然是业务核心
- `backend/` 和 `frontend/` 主要是把这些能力包装成更容易使用的本地应用

## 3. 运行模式

### 3.1 本地部署模式（推荐）

入口：

- `bootstrap-local.sh`
- `start-local.sh`
- `init-data.sh`
- Windows 对应 `*.bat` / `*.ps1`

统一控制器：

- `tools/localctl.py`

当前行为：

- `bootstrap-local.*` / `install-local.*` 负责准备 `.venv`、依赖和 `frontend/.env.local`
- `start-local.*` 负责在需要时构建 `frontend/dist` 并启动后端
- 启动 FastAPI
- 由后端直接提供前端页面和 API
- 默认访问地址就是 `http://127.0.0.1:8000`

这是当前最符合“个人电脑简单部署”的模式，也是 README 推荐的主入口。

### 3.2 本地开发模式

入口：

- `start-dev.sh`

当前行为：

- 启动后端 `:8000`
- 启动 Vite `:5173`
- 适合前后端分开调试

因此：

- 本地部署模式：单入口、后端托管前端
- 本地开发模式：双服务、便于热更新

### 3.3 Docker 模式

仓库仍保留：

- `Dockerfile`
- `Dockerfile.frontend`
- `docker-compose.yml`
- `start-docker.sh`

但从当前代码和脚本设计看，主优化方向已经明显转向单机本地部署，而不是容器优先。

## 4. 顶层目录职责

```text
backend/        FastAPI 后端、任务中心、配置与数据接口
frontend/       Vue 3 + TypeScript 前端
pipeline/       抓数、初选、回测等量化流程
agent/          quant/LLM 复核、单票分析、持仓报告
dashboard/      图表导出与 Streamlit 看盘工具
config/         YAML 配置
data/           数据库、CSV、候选结果、图表、日志、断点文件
tools/          本地部署控制器与脚本支撑
run_all.py      全量流程总入口
```

## 5. 核心业务流程

当前全量流程入口是 `run_all.py`，默认 reviewer 已切换为 `quant`。

完整步骤如下：

1. `pipeline/fetch_kline.py`
   从 Tushare 拉取全市场前复权日线到 `data/raw/`
2. `python -m pipeline.cli preselect`
   做量化初选，输出候选结果
3. `dashboard/export_kline_charts.py`
   导出候选 K 线图
4. `agent/quant_reviewer.py`
   做 quant 程序化复核；也保留 GLM/Qwen/Gemini 脚本
5. 导出 PASS 图表
   在 quant 模式下，如有 PASS，会额外导出对应图表
6. 汇总结果
   读取 `data/review/<pick_date>/suggestion.json`

当前默认策略口径：

- 抓取全部板块，不只主板
- 流动性池默认取前 `2000` 只
- 初选默认只跑 `B1`
- 复核默认使用 `quant`

## 6. 后端架构

后端根目录在 `backend/app/`。

### 6.1 应用入口

入口文件：

- `backend/app/main.py`

职责：

- 创建 FastAPI 应用
- 初始化数据库表
- 启动时从数据库回填关键环境变量
- 为旧 SQLite 库补齐兼容字段
- 注册 API 路由
- 挂载 `/data` 静态目录
- 提供 `/ws/tasks/{task_id}` 和 `/ws/ops` WebSocket
- 在本地部署模式下托管前端静态资源

一个很重要的当前事实：

- `SPAStaticFiles` 已支持 Vue Router history 模式回退
- 因此直接访问 `/update`、`/tomorrow-star` 等页面路由时，后端会回退到 `index.html`

### 6.2 API 路由层

当前后端主要路由如下：

- `backend/app/api/config.py`
  - 配置读取、保存 `.env`、验证 Tushare
- `backend/app/api/tasks.py`
  - 任务中心、全量初始化、增量更新、任务日志、本机诊断
- `backend/app/api/analysis.py`
  - 明日之星、候选结果、单股诊断历史与分析
- `backend/app/api/stock.py`
  - 股票基本信息、K 线数据
- `backend/app/api/watchlist.py`
  - 重点观察与观察分析

所有后端 API 都挂在：

- `/api/v1/config/*`
- `/api/v1/tasks/*`
- `/api/v1/analysis/*`
- `/api/v1/stock/*`
- `/api/v1/watchlist/*`

页面路由 `/update` 不是 API 接口，这两套路径不要混用。

### 6.3 服务层

### `TaskService`

文件：

- `backend/app/services/task_service.py`

职责：

- 创建和持久化后台任务
- 通过子进程执行 `run_all.py`
- 解析标准输出中的结构化进度
- 将进度写入 `tasks.progress_meta_json`
- 保存任务日志到 `task_logs`
- 通过 WebSocket 向前端推送日志

当前阶段模型分为 6 段：

- `fetch_data`
- `build_pool`
- `build_candidates`
- `pre_filter`
- `score_review`
- `finalize`

同时：

- 只允许一个活跃的全量类任务（`full_update` / `tomorrow_star`）
- 如果已有运行中的全量任务，新请求会返回已有任务信息，便于前端恢复查看

### `MarketService`

文件：

- `backend/app/services/market_service.py`

职责：

- 获取最新交易日
- 判断本地数据是否需要更新
- 执行最新交易日增量更新
- 维护增量更新状态
- 持久化增量断点文件

它维护两层状态：

- 内存中的 `_update_state`
- `data/run/` 下的断点文件

### `AnalysisService`

文件：

- `backend/app/services/analysis_service.py`

职责：

- 单股分析
- 读取本地 CSV
- 计算 B1 检查结果
- 调用 quant 评分
- 读取候选历史、分析历史

### `TushareService`

文件：

- `backend/app/services/tushare_service.py`

职责：

- Token 校验
- 数据状态检查
- 股票基础信息同步

### 6.4 持久化

数据库默认是：

- `data/db/stocktrade.db`

SQLAlchemy 位于：

- `backend/app/database.py`
- `backend/app/models.py`

当前是单机 SQLite，并开启了：

- `WAL`
- `busy_timeout`
- `check_same_thread=False`

主要表如下：

- `configs`
- `stocks`
- `candidates`
- `analysis_results`
- `daily_b1_checks`
- `watchlist`
- `watchlist_analysis`
- `tasks`
- `task_logs`
- `data_update_log`

## 7. 前端架构

前端位于 `frontend/src/`，当前采用：

- Vue 3
- TypeScript
- Pinia
- Vue Router
- Element Plus

### 7.1 路由

当前页面路由：

- `/config`
- `/update`
- `/tomorrow-star`
- `/diagnosis`
- `/watchlist`
- `/system-info`
- `/` -> `/tomorrow-star`

### 7.2 页面职责

- `Config.vue`
  - 配置 Token
  - 保存 `.env`
  - 首次启动自检
  - 引导用户去任务中心初始化
- `Update.vue`
  - 任务中心
  - 运行中任务
  - 历史任务
  - 增量更新
  - 本机诊断
  - 失败恢复入口
- `TomorrowStar.vue`
  - 查看候选与分析结果
- `Diagnosis.vue`
  - 单股诊断
- `Watchlist.vue`
  - 重点观察
- `SystemInfo.vue`
  - 面向非开发用户的系统说明

### 7.3 全局布局与新人体验

核心布局组件：

- `frontend/src/components/common/PageLayout.vue`

当前已经承担这些全局职责：

- 右上角任务进度卡
- Tushare 就绪状态徽标
- 首次初始化完成状态徽标
- 全局状态横幅
- 跳转到配置页 / 任务中心的快捷入口

也就是说，“新人第一次打开系统后应该先做什么”并不只靠 README，而是已经下沉到前端全局壳层和配置页、任务中心页中。

### 7.4 状态管理

当前主要 store：

- `frontend/src/store/config.ts`
  - 配置状态、Tushare 状态、初始化状态
- `frontend/src/store/task.ts`
  - 任务列表和当前任务
- `frontend/src/store/stock.ts`
  - 股票相关状态
- `frontend/src/store/notice.ts`
  - 全局通知

前端还维护了初始化任务视图恢复状态：

- `frontend/src/utils/initTaskViewState.ts`

它会把当前查看的任务页签和任务 ID 持久化到浏览器存储中，刷新页面后尽量恢复到之前的任务视图。

当前 Web UI 的主路径已经围绕 `quant` 打通：

- `DEFAULT_REVIEWER` 默认是 `quant`
- 配置页中的 LLM Key 输入当前仍处于待完善状态
- 仓库中仍保留 GLM / Qwen / Gemini 脚本，更多是 CLI 能力和后续扩展位

## 8. 数据目录

当前 `data/` 的主要内容：

```text
data/
├─ db/          SQLite 数据库
├─ raw/         原始日线 CSV
├─ candidates/  候选结果
├─ review/      评分结果与 suggestion.json
├─ kline/       导出的 K 线图片
├─ logs/        后端 / 抓数日志
├─ run/         pid 文件、抓数断点、增量更新断点
├─ cache/       市场数据缓存
└─ .market_cache.json
```

这是当前系统的真实持久化核心。对个人部署来说，迁移机器时通常直接带走整个 `data/` 最稳妥。

## 9. 进度展示与恢复机制

这是当前架构里最重要的“易用性”部分。

### 9.1 全量初始化进度

全量初始化由 `TaskService` 执行 `run_all.py`，而 `run_all.py` 与 `pipeline/fetch_kline.py` 会往 stdout 打结构化进度行：

- 前缀：`[PROGRESS_JSON]`

后端会解析这些行，并写入：

- `tasks.progress`
- `tasks.task_stage`
- `tasks.progress_meta_json`

前端再把这些数据显示到：

- `Update` 任务中心
- 页面右上角全局进度卡

当前重点展示字段包括：

- `current`
- `total`
- `current_code`
- `eta_seconds`
- `failed_count`
- `initial_completed`

其中最关键的是第 1 步抓取阶段，因为它最耗时，也最需要告诉用户“现在做到哪了、还要多久”。

### 9.2 抓数断点恢复

第 1 步的真实断点恢复在：

- `pipeline/fetch_kline.py`

机制：

- 按抓取参数生成唯一断点文件名
- 持久化到 `data/run/fetch_kline_<hash>.json`
- 记录已完成代码与失败代码
- 再次发起同一抓取时，优先跳过已完成项，只继续剩余代码

这就是当前“远端 Tushare 采集数据直到完成”的核心恢复能力。

### 9.3 增量更新恢复

最新交易日增量更新由：

- `backend/app/services/market_service.py`

负责，断点文件位于：

- `data/run/incremental_update_<hash>.json`

也支持：

- `current / total`
- `ETA`
- `current_code`
- 失败数量
- 继续恢复

### 9.4 当前恢复边界

需要明确说明，避免文档过度承诺：

- 真正细粒度断点恢复的是“第 1 步远端抓数”和“最新交易日增量更新”
- 第 2 步到第 6 步当前没有再做任务级细粒度快照恢复
- 如果全量任务在后续步骤中断，通常做法是重新发起任务，基于已抓到的 `data/raw/` 重新生成候选和分析结果

这也符合当前产品目标：先把最费时的远端采集做成可恢复，后续步骤允许重跑。

### 9.5 任务互斥

当前系统已经限制：

- 同一时间只能有一个活跃的全量类任务
- 增量更新和全量初始化不能同时运行

目的是避免：

- 重复占用 Tushare 配额
- 同时写入 `data/raw/`
- 前端显示多套冲突进度

## 10. 配置来源

当前配置分两层：

### 10.1 运行配置

主要来自：

- `.env`
- 数据库 `configs` 表

当前后端启动时会：

- 优先使用显式环境变量
- 如果环境变量为空或仍是模板值，再从数据库回填关键配置

这使得用户即使先通过页面保存配置，再重启后端，系统也能恢复关键运行参数。

### 10.2 业务配置

主要来自：

- `config/fetch_kline.yaml`
- `config/rules_preselect.yaml`
- `config/quant_review.yaml`
- 其他 reviewer 的 YAML

判断原则：

- 改服务端口、Token、默认 reviewer：看 `.env` / `configs`
- 改抓数范围、初选规则、评分阈值：看 `config/*.yaml`

## 11. 当前前后端边界

当前有几个容易混淆的点，需要在文档里明确：

### `/update` 是页面，不是 JSON 接口

- 页面：`/update`
- API：`/api/v1/tasks/*`

### 本地部署模式不是双服务

- 用户只需要关心 `:8000`
- `:5173` 只属于开发模式

### 后端不是重写选股算法

- 它主要做任务调度、配置管理、状态聚合和 API 封装
- 结果逻辑仍然主要来自 `pipeline/` 和 `agent/`

## 12. 对新人友好的设计落点

结合当前代码，系统已经把“新用户体验”落在这些地方：

- 启动时允许 `TUSHARE_TOKEN` 暂缺，但页面会强提示配置
- 配置页提供 Token 校验和“保存并初始化”
- 配置页提供“首次启动自检”
- 任务中心提供初始化引导、失败恢复、诊断摘要
- 右上角提供全局进度卡，随时看到远端抓数进度
- 刷新页面后尽量恢复到上一次正在看的任务视图

这套设计已经明显围绕“个人用户第一次在自己电脑上部署并跑通”来组织，而不是围绕多人协作或云端托管。
