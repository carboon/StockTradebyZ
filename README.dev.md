# StockTrader 2.0 开发说明

本文档面向开发者，记录当前工程的真实结构、核心数据流、主要功能与量化选股逻辑。仓库当前不是纯前后端项目，而是“原有量化选股主流程”与“新增 Web 可视化系统”并存。

## 1. 工程分层总览

### 1.1 顶层模块

- `run_all.py`
  - 全流程主入口。
  - 负责串联抓取数据、量化初选、导出图表、复核评分、输出推荐结果。
- `pipeline/`
  - 第 1~2 步相关逻辑。
  - 包含行情数据处理、流动性股票池构建、B1/砖型图初选、CLI、回测。
- `agent/`
  - 第 4 步复核层。
  - 默认使用 `quant_reviewer.py` 做本地程序化评分，也支持 GLM/Qwen/Gemini 图表复核。
- `dashboard/`
  - 独立于 Web 前后端的 Streamlit 看盘/图表导出工具。
- `backend/`
  - FastAPI 服务层。
  - 对旧有量化流程做 API 封装、任务编排、配置管理和本地 SQLite 持久化。
- `frontend/`
  - Vue 3 + TypeScript 可视化界面。
  - 提供“明日之星 / 全量更新 / 单股诊断 / 重点观察 / 配置管理 / 系统说明”等页面。
- `config/`
  - 主流程与复核策略配置。
- `data/`
  - 运行产物目录，默认不纳入 Git。

### 1.2 当前前后端关系

前后端不是独立重写了一套选股逻辑，而是围绕旧主流程做了一层包装：

- 前端通过 `frontend/src/api/index.ts` 调用后端 API。
- 后端通过 `backend/app/services/*.py` 调用 `run_all.py`、`pipeline` 和 `agent` 中已有逻辑。
- 真正的选股与评分规则，仍然在 `pipeline/` 和 `agent/` 中。

结论：如果要改选股结果，优先看 `pipeline/` 和 `agent/`；如果要改页面行为或任务编排，再看 `backend/` 和 `frontend/`。

## 2. 主流程入口与数据流

### 2.1 主入口：`run_all.py`

`run_all.py` 是当前最重要的业务入口，默认执行以下流程：

1. `pipeline/fetch_kline.py`
   - 根据 `config/fetch_kline.yaml` 拉取 A 股日线数据到 `data/raw/`。
   - 会先判断当前配置下的 CSV 是否已完整存在，已存在则跳过重复下载。
2. `python -m pipeline.cli preselect`
   - 运行第 2 步量化初选。
   - 输出 `data/candidates/candidates_latest.json` 及按日期归档的候选文件。
3. `dashboard/export_kline_charts.py`
   - 为候选股导出 K 线图。
4. `agent/quant_reviewer.py` 或其他 reviewer
   - 对候选股执行第 4 步复核评分。
   - 输出 `data/review/<pick_date>/` 下的单股结果和 `suggestion.json`。
5. 汇总打印推荐结果。

默认 reviewer 已切换为 `quant`，即本地程序化评分，不依赖外部 LLM。

### 2.2 核心产物

- `data/raw/*.csv`
  - 原始日线数据。
- `data/candidates/candidates_latest.json`
  - 最新初选候选。
- `data/review/<date>/*.json`
  - 单股评分结果。
- `data/review/<date>/suggestion.json`
  - 当日汇总推荐结果。
- `data/kline/`
  - 导出的图表资源。

## 3. 第 2 步量化初选

### 3.1 入口

- CLI 入口：`pipeline/cli.py`
- 核心实现：`pipeline/select_stock.py`
- 核心指标/过滤器：`pipeline/Selector.py`
- 通用数据准备：`pipeline/pipeline_core.py`
- 配置文件：`config/rules_preselect.yaml`

### 3.2 当前默认规则

从配置和代码看，当前默认行为如下：

- 先对全市场计算 `43` 日滚动成交额。
- 只保留流动性最强的前 `2000` 只股票。
- 只启用 `B1` 策略。
- `brick` 策略代码仍保留，但默认 `enabled: false`。

### 3.3 B1 策略本质

`B1Selector` 的核心思想是，在高流动性股票池里找“低位触发但大结构未坏”的标的，主要依赖：

- `KDJ`
  - 关注 `J` 值是否处在较低位置，默认阈值 `15`。
  - 同时结合 `J` 的历史分位阈值 `0.10`。
- 知行线结构
  - 通过 `zxdq` 与 `zxdkx` 的位置关系判断中期结构。
- 周线均线多头排列
  - 用周线 MA 判断更大级别趋势是否健康。
- 成交量健康度
  - 最近窗口内最大成交量日不能是阴线，避免“放量出货型假信号”。

因此，B1 不是简单抄底，而是强调：

- 流动性足够
- 位置相对低
- 中期结构未坏
- 周期共振成立
- 量价不出现明显反向破坏

### 3.4 Brick 策略现状

`BrickChartSelector` 仍然完整保留，包含：

- 通达信砖型图公式计算
- 红绿柱切换与增长判定
- 砖型图前置绿柱数量约束
- 知行线与周线多头过滤

但当前默认主流程中：

- `config/rules_preselect.yaml` 将其关闭
- `config/quant_review.yaml` 也将 `brick` 放入 `disabled_strategies`

说明它目前不是默认推荐来源，更多是保留为实验或历史策略分支。

## 4. 第 4 步程序化复核

### 4.1 入口与定位

- 入口文件：`agent/quant_reviewer.py`
- 前置过滤：`pipeline/review_prefilter.py`
- 配置文件：`config/quant_review.yaml`

这一步与第 2 步“解耦”，明确不复用 KDJ、知行线、砖型图、周线多头这些初选条件，而是单独回答一个问题：

> 这只股票在当前时点，是否适合作为短周期交易候选继续保留、观察或推荐？

### 4.2 四维评分框架

程序化复核保留了原 prompt 中的四维结构：

1. `trend_structure`
   - 趋势结构。
   - 主要看快慢 EMA、斜率、突破新鲜度、回撤幅度、价格是否持续站上快线。
2. `price_position`
   - 价格位置。
   - 主要看 120 日区间位置、60 日涨幅、距长期高点空间、ATR 延伸程度。
3. `volume_behavior`
   - 量价行为。
   - 主要看上涨/下跌量比、OBV、回调缩量、是否存在放量分歧。
4. `previous_abnormal_move`
   - 历史异动 / 建仓痕迹。
   - 主要看近 60 日内是否存在带量脉冲、突破、异动后维持能力。

最终根据总分和各子项门槛给出：

- `PASS`
- `WATCH`
- `FAIL`

当前默认 `PASS` 总分门槛是 `4.0`，而且位置分还必须达到更高要求，整体偏保守。

### 4.3 第 4 步前置过滤

评分前还有一层 Tushare 元数据过滤，目标是让实盘和回测共享同一套“候选可交易性约束”。当前默认启用：

- ST 过滤
- 次新过滤（上市天数不足）
- 近端解禁过滤
- 行业强度过滤
- 市场环境过滤

其本质是先筛掉“不该评分”的票，再进入四维评分。

## 5. 前端与后端架构

### 5.1 后端结构

后端位于 `backend/app/`，分层相对清晰：

- `main.py`
  - FastAPI 应用入口。
  - 注册 API、CORS、静态数据目录、WebSocket。
- `api/`
  - 路由层。
  - 包括 `config`、`stock`、`analysis`、`watchlist`、`tasks`。
- `services/`
  - 服务层。
  - 负责调用旧主流程、执行单股分析、管理后台任务、查询 Tushare 数据状态。
- `models.py`
  - SQLite 表结构。
  - 包括配置、候选、分析结果、观察列表、任务记录等。
- `config.py`
  - 统一读取 `.env` 和环境变量。

### 5.2 后端如何复用旧逻辑

几个关键服务值得注意：

- `analysis_service.py`
  - 直接读取 `data/raw/*.csv`
  - 用 `B1Selector` 做单股 B1 检查
  - 用 `QuantReviewer.review_stock_df()` 做单股量化评分
- `task_service.py`
  - 后台任务实际上是子进程执行 `run_all.py`
  - 通过 WebSocket 向前端推送日志和进度

因此后端不是“重新实现业务逻辑”，而是“业务编排层 + API 适配层”。

### 5.3 前端结构

前端位于 `frontend/src/`：

- `views/`
  - 页面级组件。
  - 包括 `TomorrowStar`、`Update`、`Diagnosis`、`Watchlist`、`Config`、`SystemInfo`。
- `api/index.ts`
  - 统一封装后端接口。
- `store/`
  - Pinia 状态管理。
- `router/index.ts`
  - 路由入口。
- `components/common/PageLayout.vue`
  - 页面布局壳层。

当前页面职责：

- `TomorrowStar`
  - 查看历史候选、PASS 结果、触发生成任务。
- `Update`
  - 查看数据状态并启动全量更新。
- `Diagnosis`
  - 单股诊断，展示 B1 与量化评分。
- `Watchlist`
  - 管理重点观察股票。
- `Config`
  - 管理 Token 与系统配置。

## 6. 其他重要能力

### 6.1 单股分析与持仓视角

- `agent/single_stock_analysis.py`
  - 单票分析工具，偏补充型。
- `agent/holding_report.py`
  - 从持仓视角输出报告，更适合复盘“继续持有还是减仓观察”。

### 6.2 图表与看盘

- `dashboard/export_kline_charts.py`
  - 为候选结果批量导出图表。
- `dashboard/app.py`
  - Streamlit 看盘面板。

### 6.3 回测

- `pipeline/backtest_quant.py`
  - 保持第 2 步初选不变，对候选日执行第 4 步程序化复核。
  - 输出事件表和统计结果。

## 7. 开发与测试入口

### 7.1 本地开发启动

推荐先使用根目录脚本：

```bash
./start-dev.sh
```

这个脚本会：

- 自动检查并创建 `.venv`
- 安装根依赖与 `backend/requirements.txt`
- 检查前端 `node_modules`
- 创建 `data/db`、`data/raw`、`data/candidates`、`data/review`、`data/kline`、`data/logs`
- 启动 FastAPI `:8000` 与 Vite `:5173`

也可以分开启动：

```bash
# 后端
cd backend
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm run dev
```

### 7.2 常用命令

```bash
# 运行完整主流程
python run_all.py --reviewer quant

# 只跑量化初选
python -m pipeline.cli preselect

# 后端测试
pytest

# 前端构建与测试
cd frontend
npm run build
npm run test
npm run test:coverage
```

说明：

- Python 测试入口由根目录 `pytest.ini` 控制，默认只收集 `backend/tests`。
- 前端测试基于 `vitest` + `jsdom`。
- 前端 `lint` 脚本已存在，但仓库当前未看到项目级 ESLint 配置文件，使用前需要确认配置是否完整。

### 7.3 环境与配置边界

配置来源分两层：

- `.env`
  - 运行环境、Token、默认 reviewer、分数阈值、前端 API 地址。
- `config/*.yaml`
  - 策略与流程配置，例如抓数范围、初选参数、量化复核阈值、预过滤开关。

一个实用判断原则：

- 改“运行环境/服务地址/API Key”看 `.env`
- 改“选股逻辑/评分阈值/策略行为”看 `config/*.yaml`

## 8. API 与页面映射

当前前端页面基本都能在后端找到清晰映射：

- `TomorrowStar`
  - 后端对应 `backend/app/api/analysis.py`
  - 读取候选列表、读取评分结果、触发“明日之星”生成
- `Update`
  - 后端对应 `backend/app/api/tasks.py`
  - 查看数据状态、启动全量更新、查看任务历史、通过 WebSocket 看日志
- `Diagnosis`
  - 后端对应 `backend/app/api/analysis.py` 与 `backend/app/api/stock.py`
  - 单股 B1 检查、量化评分、K 线数据、历史诊断
- `Config`
  - 后端对应 `backend/app/api/config.py`
  - 读取配置、保存 `.env`、校验 Tushare Token
- `Watchlist`
  - 后端对应 `backend/app/api/watchlist.py`
  - 管理重点观察股票及其分析记录

这部分很重要，因为它说明前端开发通常不需要直接碰 `pipeline/`，而是经由后端 service 调用旧逻辑。

## 9. 开发判断建议

日常开发时可按问题类型定位：

- 结果不符合预期
  - 先看 `pipeline/` 和 `agent/`。
- API 不通 / 页面数据错误
  - 看 `backend/app/api/`、`backend/app/services/`。
- 页面交互或展示问题
  - 看 `frontend/src/views/`、`frontend/src/api/`。
- 任务执行卡住
  - 看 `backend/app/services/task_service.py` 与 `run_all.py`。

最重要的判断原则只有一条：

> 这个仓库的业务核心依然是本地量化主流程，前后端只是对它做了服务化和可视化封装。
