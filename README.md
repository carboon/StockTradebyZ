# StockTrader 2.0

一个面向 A 股的本地量化选股与复核项目，提供 Web 可视化界面。

> 📘 **部署运行指南**: 请查看 [DEPLOYMENT.md](DEPLOYMENT.md) 获取详细的部署和运行说明。

---

## 快速开始

```bash
# 本地开发模式
./start-dev.sh

# Docker 部署模式
./start-docker.sh up
```

访问 http://localhost:3000 查看可视化界面。

---

## 核心流程

- 用 Tushare 拉取全市场日线数据到本地 CSV
- 从流动性最强的股票池中做 B1 初选
- 用本地 quant 程序化复核做第 4 步评分
- 只输出 `PASS` 且达到分数门槛的推荐结果

当前默认行为已经和代码保持一致：

- `python run_all.py` 默认等价于 `python run_all.py --reviewer quant`
- 第 1 步默认抓取全部板块，不再只抓主板
- 第 2 步默认只保留 `B1`，`brick` 已默认关闭
- 流动性股票池默认取前 `2000` 只，而不是 `5000` 只
- `run_all.py` 会先检查 `data/raw/` 是否已经有当前配置下的完整 CSV；如果已完整存在，会跳过重复下载

---

## 1. 当前代码能力

当前仓库已经确认可用的能力如下。

### 1.1 主流程

入口文件：[run_all.py](run_all.py)

完整流程：

1. 抓取日线数据：`pipeline.fetch_kline`
2. 量化初选：`pipeline.cli preselect`
3. 导出候选图表：`dashboard/export_kline_charts.py`
4. 复核评分：
   - 默认：`agent/quant_reviewer.py`
   - 可选：`agent/glm_reviewer.py` / `agent/qwen_reviewer.py` / `agent/gemini_review.py`
5. 输出推荐结果：读取 `data/review/<date>/suggestion.json`
6. quant 模式下，如存在 `PASS` 股票，会额外导出这些股票的 K 线图

### 1.2 量化初选

入口文件：[pipeline/cli.py](pipeline/cli.py)

当前默认逻辑：

- 先计算全市场 `43` 日滚动成交额
- 只保留流动性最强的前 `2000` 只股票
- 只运行 `B1` 策略
- `brick` 代码仍在仓库中，但默认不参与主流程

对应配置文件：[config/rules_preselect.yaml](config/rules_preselect.yaml)

### 1.3 quant 程序化复核

入口文件：[agent/quant_reviewer.py](agent/quant_reviewer.py)

当前评分维度：

- 趋势结构
- 价格位置
- 量价行为
- 历史异动 / 建仓痕迹

当前默认还启用了第 4 步前置过滤：

- ST 过滤
- 次新过滤
- 解禁过滤
- 行业强度过滤
- 市场环境过滤

对应配置文件：[config/quant_review.yaml](config/quant_review.yaml)

### 1.4 LLM 图表复核

可选模型：

- GLM：`agent/glm_reviewer.py`
- Qwen：`agent/qwen_reviewer.py`
- Gemini：`agent/gemini_review.py`

LLM 模式仍然可用，但当前主流程默认已经切到 quant，本地 quant 模式更适合日常批量跑。

### 1.5 图表与看盘

- 批量导出候选图：`dashboard/export_kline_charts.py`
- Streamlit 看盘面板：`dashboard/app.py`

### 1.6 单票持仓报告

新增脚本：[agent/holding_report.py](agent/holding_report.py)

功能：

- 输入股票代码、买入起点、分析终点
- 从 `data/raw/{code}.csv` 读取历史数据
- 复用 quant 评分口径，比较起点和终点的指标变化
- 输出 Markdown 报告
- 给出更偏持仓视角的“继续持有 / 减仓观察点”

### 1.7 滚动回测

入口文件：[pipeline/backtest_quant.py](pipeline/backtest_quant.py)

功能：

- 保持第 2 步初选规则不变
- 对每个候选日运行 quant 程序化复核
- 输出滚动事件表和汇总统计

### 1.8 单票 AI 分析工具

入口文件：[agent/single_stock_analysis.py](agent/single_stock_analysis.py)

这是一个补充型工具，不是主流程必需。它会：

- 检查或刷新单票 CSV
- 做简化 B1 判断
- 导出单票图表
- 调用 LLM 给单票打分

如果你主要做批量选股，优先使用 `run_all.py` 或 `quant_reviewer.py`。

---

## 2. 当前策略原理

### 2.1 第 1 步：数据抓取

默认读取 [config/fetch_kline.yaml](config/fetch_kline.yaml)：

- 数据源：Tushare 日线 `qfq`
- 默认抓取区间：`20190101` 到 `today`
- 默认抓取全部板块
- 输出目录：`data/raw/`

### 2.2 第 2 步：量化初选

当前主流程默认只做 `B1`。

`B1` 的核心思路是：

- 先从全市场中选出成交额最活跃的股票
- 再在这些股票中寻找“低位触发但大结构未破坏”的形态

具体包含：

- `KDJ` 低位过滤
- 知行线条件
- 周线多头排列
- 最近 20 日最大成交量日不能是阴线

### 2.3 第 4 步：quant 程序化复核

quant 复核和 B1 是解耦的，不会简单重复第 2 步条件。

它更关注：

- 当前是不是主升启动，而不是普通反弹
- 当前位置是不是还具有性价比
- 量价结构是不是健康
- 过去一段时间有没有明显建仓痕迹

当前推荐规则偏保守：

- `score >= 4.0` 不等于一定 `PASS`
- 还要同时满足趋势、位置、量价、异动等子项门槛
- 所以很多票可能是 `WATCH`，而不是 `PASS`

---

## 3. 环境要求

### 3.1 Python 版本

当前工程建议：

- Python `>= 3.11`
- 推荐 Python `3.12`

原因：

- `run_all.py` 已内置 Python 版本检查
- `requirements.txt` 中的 `numba==0.64.0` 不支持 Python 3.9

如果你在 macOS 上，建议直接使用 Homebrew Python：

~~~bash
/opt/homebrew/bin/python3.12 --version
~~~

### 3.2 依赖

基础依赖见：[requirements.txt](requirements.txt)

当前主要依赖：

- `tushare`
- `pandas`
- `numpy`
- `numba`
- `streamlit`
- `plotly`
- `openai`

如果你要导出 JPG 图表，还需要额外安装：

~~~bash
pip install kaleido
~~~

### 3.3 环境变量

主流程至少需要：

- `TUSHARE_TOKEN`

如果你使用 LLM 复核，还需要对应的 API Key：

- `ZHIPUAI_API_KEY`
- `DASHSCOPE_API_KEY`
- `GEMINI_API_KEY`

说明：

- quant 模式不需要 LLM API Key
- 但 quant 主流程默认启用了第 4 步前置过滤，仍然需要 `TUSHARE_TOKEN`

---

## 4. 安装方式

推荐使用虚拟环境，不要直接用系统 Python。

### 4.1 macOS / Linux 推荐安装

~~~bash
cd /Volumes/DATA/StockTradebyZ
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pip install kaleido
~~~

如果你在中国大陆网络环境下安装较慢，可以使用阿里云镜像：

~~~bash
python -m pip install -U pip -i https://mirrors.aliyun.com/pypi/simple/
python -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
python -m pip install kaleido -i https://mirrors.aliyun.com/pypi/simple/
~~~

### 4.2 设置环境变量

#### macOS / Linux

~~~bash
export TUSHARE_TOKEN=你的TushareToken
export ZHIPUAI_API_KEY=你的智谱Key
export DASHSCOPE_API_KEY=你的通义Key
export GEMINI_API_KEY=你的GeminiKey
~~~

如果只跑 quant：

~~~bash
export TUSHARE_TOKEN=你的TushareToken
~~~

#### Windows PowerShell

~~~powershell
[Environment]::SetEnvironmentVariable("TUSHARE_TOKEN", "你的TushareToken", "User")
[Environment]::SetEnvironmentVariable("ZHIPUAI_API_KEY", "你的智谱Key", "User")
[Environment]::SetEnvironmentVariable("DASHSCOPE_API_KEY", "你的通义Key", "User")
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "你的GeminiKey", "User")
~~~

---

## 5. 快速开始

### 5.1 一键跑完整默认流程

~~~bash
python run_all.py
~~~

这条命令当前默认使用 quant 程序化复核，相当于：

~~~bash
python run_all.py --reviewer quant
~~~

### 5.2 常用运行方式

~~~bash
python run_all.py
python run_all.py --reviewer quant
python run_all.py --reviewer glm
python run_all.py --reviewer qwen
python run_all.py --reviewer gemini
python run_all.py --skip-fetch
python run_all.py --start-from 2
python run_all.py --start-from 4
~~~

说明：

- `--reviewer quant`：本地评分，默认模式
- `--reviewer glm/qwen/gemini`：调用视觉模型复核
- `--skip-fetch`：强制跳过第 1 步
- `--start-from N`：从指定步骤开始跑

### 5.3 `run_all.py` 的当前行为

- 如果 `data/raw/` 中已经存在当前抓取配置下的完整 CSV，步骤 1 会自动跳过
- 如果是 quant 模式，步骤 3 不会先导出全部候选图
- quant 评分完成后，如果存在 `PASS` 股票，会额外导出这些 `PASS` 股票的 K 线图

### 5.4 推荐的日常操作流程

如果你当前主要使用本地 quant 模式，推荐按下面的顺序每天使用。

#### 场景 A：盘后跑完整默认流程

适合：

- 正常收盘后更新数据
- 重新生成候选和评分
- 看当天是否出现新的 `PASS`

推荐命令：

~~~bash
source .venv/bin/activate
python run_all.py
~~~

说明：

- 这是最稳妥的默认用法
- 如果 `data/raw/` 已经完整存在，步骤 1 会自动跳过，不会重复下载
- 如果当天没有 `PASS`，最终会直接显示“暂无达标推荐股票”

#### 场景 B：数据已经更新，只想重跑初选和复核

适合：

- 你已经确认 `data/raw/` 是最新的
- 或者你刚调了初选 / quant 参数，想快速重算结果

推荐命令：

~~~bash
source .venv/bin/activate
python run_all.py --skip-fetch
~~~

或者：

~~~bash
source .venv/bin/activate
python run_all.py --start-from 2
~~~

#### 场景 C：只看今天候选和推荐

先跑主流程：

~~~bash
python run_all.py
~~~

然后重点看这两个文件：

- `data/candidates/candidates_latest.json`
- `data/review/<pick_date>/suggestion.json`

如果 quant 模式有 `PASS`，再去看：

- `data/kline/<pick_date>/`

#### 场景 D：对某只股票做补充判断

如果一只股票没有进推荐，但你仍然想单独看它当前评分：

~~~bash
python agent/quant_reviewer.py --code 600519 --date 2026-04-21
~~~

如果你已经买入，想按持仓视角看“继续持有 / 减仓”观察点：

~~~bash
python agent/holding_report.py --code 601975 --start-date 2026-04-17 --end-date 2026-04-21
~~~

#### 场景 E：盘后浏览图表

如果你更习惯先看图再决定：

~~~bash
streamlit run dashboard/app.py
~~~

或者导出候选图表：

~~~bash
python dashboard/export_kline_charts.py
~~~

#### 场景 F：每周或改参数后做验证

如果你改了以下配置：

- `config/rules_preselect.yaml`
- `config/quant_review.yaml`

建议至少补一次滚动回测：

~~~bash
python -m pipeline.backtest_quant --start-date 2023-01-01 --end-date 2026-04-21
~~~

#### 一个最实用的日常闭环

推荐你日常就按这 4 步执行：

1. `python run_all.py`
2. 查看 `suggestion.json`，确认当天有没有 `PASS`
3. 对你关心的股票用 `quant_reviewer.py --code` 或 `holding_report.py` 做单票补充分析
4. 如果最近改过参数，再用 `pipeline.backtest_quant` 做回看验证

---

## 6. 分步使用方式

### 6.1 拉取日线数据

入口：[pipeline/fetch_kline.py](pipeline/fetch_kline.py)

~~~bash
python -m pipeline.fetch_kline
python -m pipeline.fetch_kline --boards main
python -m pipeline.fetch_kline --boards main gem star bj
python -m pipeline.fetch_kline --config config/fetch_kline.yaml
~~~

关键配置：

- `start` / `end`
- `stocklist`
- `exclude_boards`
- `out`
- `workers`

### 6.2 量化初选

入口：[pipeline/cli.py](pipeline/cli.py)

~~~bash
python -m pipeline.cli preselect
python -m pipeline.cli preselect --date 2026-04-21
python -m pipeline.cli preselect --config config/rules_preselect.yaml
python -m pipeline.cli preselect --data data/raw --output data/candidates
~~~

输出：

- `data/candidates/candidates_<pick_date>.json`
- `data/candidates/candidates_latest.json`

### 6.3 导出候选 K 线图

入口：[dashboard/export_kline_charts.py](dashboard/export_kline_charts.py)

~~~bash
python dashboard/export_kline_charts.py
python dashboard/export_kline_charts.py --date 2026-04-21
python dashboard/export_kline_charts.py --codes 601975 601083 --date 2026-04-21
~~~

输出：

- `data/kline/<date>/<code>_day.jpg`

### 6.4 quant 程序化复核

入口：[agent/quant_reviewer.py](agent/quant_reviewer.py)

~~~bash
python agent/quant_reviewer.py
python agent/quant_reviewer.py --code 600519
python agent/quant_reviewer.py --code 600519 --date 2026-04-21
python agent/quant_reviewer.py --config config/quant_review.yaml
~~~

输出：

- `data/review/<date>/<code>.json`
- `data/review/<date>/suggestion.json`

### 6.5 LLM 图表复核

~~~bash
python agent/glm_reviewer.py
python agent/qwen_reviewer.py
python agent/gemini_review.py
~~~

也支持单票：

~~~bash
python agent/glm_reviewer.py --code 600519 --date 2026-04-21
python agent/qwen_reviewer.py --code 600519 --date 2026-04-21
python agent/gemini_review.py --code 600519 --date 2026-04-21
~~~

### 6.6 单票持仓报告

入口：[agent/holding_report.py](agent/holding_report.py)

~~~bash
python agent/holding_report.py --code 601975 --start-date 2026-04-17 --end-date 2026-04-21
python agent/holding_report.py --code 601083 --start-date 2026-04-17 --end-date 2026-04-21 --stdout-only
python agent/holding_report.py --code 601975 --start-date 2026-04-17 --end-date 2026-04-21 --output /tmp/601975.md
~~~

输出：

- 默认写入 `data/review/holding_reports/`
- 内容为 Markdown，可直接归档或二次加工

### 6.7 滚动回测

入口：[pipeline/backtest_quant.py](pipeline/backtest_quant.py)

~~~bash
python -m pipeline.backtest_quant
python -m pipeline.backtest_quant --start-date 2023-01-01 --end-date 2026-04-21
python -m pipeline.backtest_quant --preselect-config config/rules_preselect.yaml --review-config config/quant_review.yaml
~~~

输出：

- `data/backtest/quant_roll_events_<start>_<end>.csv`
- `data/backtest/quant_roll_summary_<start>_<end>.json`

### 6.8 Streamlit 看盘面板

入口：[dashboard/app.py](dashboard/app.py)

~~~bash
streamlit run dashboard/app.py
~~~

默认端口配置在 [config/dashboard.yaml](config/dashboard.yaml)，当前是 `8501`。

### 6.9 单票 AI 全分析工具

入口：[agent/single_stock_analysis.py](agent/single_stock_analysis.py)

~~~bash
python agent/single_stock_analysis.py 600519
python agent/single_stock_analysis.py 600519 --model qwen
python agent/single_stock_analysis.py 600519 --model gemini
python agent/single_stock_analysis.py 600519 --force-refresh
~~~

这个工具更适合做单票补充分析，不是批量主流程。

---

## 7. 关键配置文件

### 7.1 数据抓取

[config/fetch_kline.yaml](config/fetch_kline.yaml)

关键项：

- `start`
- `end`
- `stocklist`
- `exclude_boards`
- `out`
- `workers`

当前默认：

- 抓取全部板块
- 输出到 `data/raw`

### 7.2 量化初选

[config/rules_preselect.yaml](config/rules_preselect.yaml)

关键项：

- `global.top_m`
- `global.n_turnover_days`
- `b1.enabled`
- `brick.enabled`

当前默认：

- `top_m: 2000`
- `b1.enabled: true`
- `brick.enabled: false`

### 7.3 quant 复核

[config/quant_review.yaml](config/quant_review.yaml)

关键项：

- `suggest_min_score`
- `thresholds.pass_score`
- `thresholds.watch_score`
- `thresholds.pass_min_position_score`
- `prefilter.*`
- `backtest.*`

当前默认：

- 推荐门槛：`4.0`
- `brick` 来源在第 4 步默认禁用
- 第 4 步前置过滤默认启用

---

## 8. 输出目录说明

主输出目录：

- `data/raw/`：原始日线 CSV
- `data/candidates/`：第 2 步候选结果
- `data/kline/<date>/`：导出的候选图表
- `data/review/<date>/`：单股评分 JSON 与 `suggestion.json`
- `data/review/holding_reports/`：持仓报告 Markdown
- `data/backtest/`：滚动回测输出
- `data/tushare_cache/`：quant 前置过滤缓存
- `data/logs/`：抓取与流程日志

常用文件：

- `data/candidates/candidates_latest.json`
- `data/review/<date>/suggestion.json`

---

## 9. 部署方案

当前仓库没有提供 `Dockerfile`、`docker-compose.yml`、数据库迁移脚本或专门的服务治理配置，因此最稳妥的部署方式是“本地 Python 虚拟环境 + 文件系统输出”。

下面给出三个建议方案。

### 9.1 方案 A：本地研究机部署

适合：

- 自己日常跑量化初选
- 收盘后手动分析
- 调整参数、看结果

推荐步骤：

1. 安装 Python 3.12
2. 创建 `.venv`
3. 安装依赖
4. 配置环境变量
5. 每天直接运行：

~~~bash
source .venv/bin/activate
python run_all.py
~~~

优点：

- 最简单
- 和当前代码结构最匹配
- 排错成本最低

### 9.2 方案 B：定时批处理部署

适合：

- 每天固定时间自动更新
- 收盘后自动生成候选、评分和报告

建议运行命令：

~~~bash
source /Volumes/DATA/StockTradebyZ/.venv/bin/activate
cd /Volumes/DATA/StockTradebyZ
python run_all.py
~~~

#### Linux `cron` 示例

工作日收盘后执行：

~~~cron
30 16 * * 1-5 cd /Volumes/DATA/StockTradebyZ && /Volumes/DATA/StockTradebyZ/.venv/bin/python run_all.py >> /Volumes/DATA/StockTradebyZ/data/logs/cron_run.log 2>&1
~~~

#### macOS `launchd` 建议

如果你长期在 macOS 本机使用，比起 `cron`，更推荐用 `launchd` 挂一个 plist 定时任务。建议配置：

- 工作目录：项目根目录
- Python：`.venv/bin/python`
- 命令参数：`run_all.py`
- 标准输出 / 错误输出：写入 `data/logs/`

优点：

- 适合稳定日更
- 直接复用当前文件输出结构
- 不需要改代码

### 9.3 方案 C：本地看盘服务部署

适合：

- 局域网内查看候选股
- 在浏览器里看 K 线

启动方式：

~~~bash
source .venv/bin/activate
streamlit run dashboard/app.py --server.port 8501
~~~

注意：

- 当前面板没有鉴权
- 更适合本机或内网使用
- 如果要公网暴露，建议额外加反向代理和访问控制

### 9.4 当前不建议的部署方式

当前阶段不建议直接上：

- 多机分布式部署
- 容器编排部署
- 直接公网开放 Streamlit

原因：

- 仓库当前是典型的本地研究型结构
- 输出依赖本地文件目录
- 没有任务队列、数据库、鉴权和服务拆分

如果后续要做容器化，建议补齐这些内容后再上：

- `Dockerfile`
- `docker-compose.yml`
- `.env.example`
- 明确的日志卷与数据卷
- Web 鉴权
- 定时调度器

---

## 10. 常见问题

### 10.1 `numba` 安装失败

通常不是网络问题本身，而是 Python 版本不对。

请先确认：

- 不要使用系统自带 Python 3.9
- 改用 Python 3.11 或 3.12

推荐：

~~~bash
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
~~~

### 10.2 `run_all.py` 报 Python 版本过低

说明当前解释器不符合项目要求。直接切到虚拟环境或 Homebrew Python 即可。

### 10.3 抓取时报 token 错误

检查：

- `TUSHARE_TOKEN` 是否已设置
- token 是否有效
- Tushare 账号权限是否正常

### 10.4 导出图表时报 `write_image` 或 `kaleido` 错误

安装：

~~~bash
python -m pip install kaleido
~~~

### 10.5 quant 模式为什么没有推荐股票

这通常不是程序错误，而是当前规则偏保守。

常见原因：

- 候选股票没有达到 `PASS`
- 虽然 `score >= 4.0`，但某个子项不满足 `PASS` 硬条件
- 第 4 步前置过滤拦截了部分股票

### 10.6 没有候选股票

检查：

- `data/raw/` 是否已有最新数据
- `pick_date` 是否是有效交易日
- `top_m` 是否过小
- `B1` 条件是否过严

---

## License

本项目采用 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) 协议发布。

- 允许：学习、研究、非商业用途的使用与分发
- 禁止：任何形式的商业使用、出售或以盈利为目的的部署
- 要求：转载或引用须注明原作者与来源

Copyright © 2026 SebastienZh. All rights reserved.
