# AgentTrader

一个面向 A 股的半自动选股项目：

- 使用 Tushare 拉取股票日线数据
- 用量化规则做初选（目前只实现了B1选股）
- 导出候选股票 K 线图
- 调用 LLM（智谱 GLM-4V-Flash / 通义千问 VL / Google Gemini）对图表进行 AI 复评打分
- 或使用本地程序化复核器（`--reviewer quant`）替代视觉模型

---

## 更新说明

- 推翻了旧版选股模式（各式各样的B1太麻烦了）
- 新加入了AI看图打分精选功能（是的，不用再自己看图了）
- 当前默认只保留 B1 选股
- **新增**：支持智谱 GLM-4V-Flash（完全免费，推荐）/ 通义千问 VL / Google Gemini

---

## 1. 项目流程

完整流程对应 [run_all.py](run_all.py)：

1. 下载 K 线数据（pipeline.fetch_kline）
2. 量化初选（pipeline.cli preselect）
3. 导出候选图表（dashboard/export_kline_charts.py）
4. 复评（支持 GLM-4V-Flash / 通义千问 VL / Gemini / quant 程序化复核）
5. 打印推荐结果（读取 suggestion.json）

输出主链路：

- data/raw：原始日线 CSV
- data/candidates：初选候选列表
- data/kline/日期：候选图表
- data/review/日期：AI 单股评分与汇总建议

---

## 2. 目录说明

- [pipeline](pipeline)：数据抓取与量化初选
- [dashboard](dashboard)：看盘界面与图表导出
- [agent](agent)：复评逻辑（支持 GLM-4V-Flash / 通义千问 VL / Gemini / quant 程序化复核）
- [config](config)：抓取、初选、LLM 复评配置
- [data](data)：运行数据与结果
- [run_all.py](run_all.py)：全流程一键入口

---

## 3. 快速开始（一键跑通）

### 3.1 Clone 项目

~~~bash
git clone https://github.com/SebastienZh/StockTradebyZ
cd StockTradebyZ
~~~

### 3.2 安装依赖

~~~bash
pip install -r requirements.txt
~~~

### 3.3 设置环境变量

**智谱 GLM-4V-Flash（推荐，完全免费）**：

Windows PowerShell：
~~~powershell
[Environment]::SetEnvironmentVariable("TUSHARE_TOKEN", "你的TushareToken", "User")
[Environment]::SetEnvironmentVariable("ZHIPUAI_API_KEY", "你的智谱APIKey", "User")
~~~

获取免费 API Key：https://open.bigmodel.cn/usercenter/apikeys

**通义千问 VL（可选）**：

Windows PowerShell：
~~~powershell
[Environment]::SetEnvironmentVariable("DASHSCOPE_API_KEY", "你的通义千问APIKey", "User")
~~~

获取 API Key：https://bailian.console.aliyun.com/

**Google Gemini（可选）**：

Windows PowerShell：
~~~powershell
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "你的GeminiApiKey", "User")
~~~

写入后请重开终端，环境变量才会在新会话中生效。

### 3.4 运行一键脚本

在项目根目录执行：

~~~bash
python run_all.py
~~~

常用参数：

~~~bash
python run_all.py                              # 使用 GLM-4V-Flash（免费，默认）
python run_all.py --reviewer glm               # 使用智谱 GLM-4V-Flash（免费）
python run_all.py --reviewer qwen              # 使用通义千问 VL
python run_all.py --reviewer gemini            # 使用 Google Gemini
python run_all.py --reviewer quant             # 使用本地程序化复核（无需 API Key）
python run_all.py --skip-fetch                 # 跳过数据下载
python run_all.py --start-from 3               # 从第 3 步开始
~~~

参数说明：

- --reviewer：选择复评器（glm/qwen/gemini/quant），默认 glm（免费）
- --skip-fetch：跳过数据下载，直接进入初选
- --start-from N：从第 N 步开始执行（1 到 4）

---

## 4. 分步运行攻略

### 步骤 1：拉取 K 线

~~~bash
python -m pipeline.fetch_kline
~~~

配置见 [config/fetch_kline.yaml](config/fetch_kline.yaml)：

- start、end：抓取区间
- stocklist：股票池文件
- exclude_boards：排除板块（gem、star、bj）
- out：输出目录（默认 data/raw）
- workers：并发线程数

### 步骤 2：量化初选

~~~bash
python -m pipeline.cli preselect
~~~

可选参数示例：

~~~bash
python -m pipeline.cli preselect --date 2026-03-13
python -m pipeline.cli preselect --config config/rules_preselect.yaml --data data/raw
~~~

规则配置见 [config/rules_preselect.yaml](config/rules_preselect.yaml)。

### 步骤 3：导出候选图表

~~~bash
python dashboard/export_kline_charts.py
~~~

输出到 data/kline/选股日期，图像命名为 代码_day.jpg。

### 步骤 4：复评

**智谱 GLM-4V-Flash（推荐，完全免费）**：

~~~bash
python agent/glm_reviewer.py
~~~

**通义千问 VL**：

~~~bash
python agent/qwen_reviewer.py
~~~

**Google Gemini**：

~~~bash
python agent/gemini_review.py
~~~

**quant 程序化复核（无需 API Key）**：

~~~bash
python agent/quant_reviewer.py
python agent/quant_reviewer.py --code 600519 --date 2026-04-16
~~~

可选参数示例：

~~~bash
python agent/glm_reviewer.py --config config/glm_review.yaml
~~~

配置见 [config/glm_review.yaml](config/glm_review.yaml) / [config/qwen_review.yaml](config/qwen_review.yaml) / [config/gemini_review.yaml](config/gemini_review.yaml) / [config/quant_review.yaml](config/quant_review.yaml)。

当前 quant 程序化复核的 `PASS` 以 `5d` 持有目标做约束：除了总分和趋势/量价/异动达标外，`price_position` 还必须达到 `4-5` 分，`3` 分样本仅保留为 `WATCH`。
当前默认直接禁用 `brick` 初选来源，第 4 步只接收 `b1` 来源进入程序化复核与推荐。

读取候选与图表后，输出：

- data/review/日期/代码.json
- data/review/日期/suggestion.json

### 滚动回测

完整滚动回测会保持第 2 步初选不变，并在每个候选日上运行新的 quant 程序化复核：

~~~bash
python -m pipeline.backtest_quant
python -m pipeline.backtest_quant --start-date 2023-01-01 --end-date 2026-04-16
~~~

输出：

- `data/backtest/quant_roll_events_*.csv`
- `data/backtest/quant_roll_summary_*.json`

---

## 5. 关键配置建议

### 6.1 抓取层

- 首次全量抓取建议 workers 设小一些（如 4 到 8）
- 若遇到频率限制，降低并发并重试

### 6.2 初选层

- top_m 决定流动性股票池大小，当前默认取前 2000 只
- 当前默认仅启用 b1.enabled，brick.enabled 默认关闭
- 可先只开一个策略做回放验证

### 6.3 复评层

在对应配置文件中可调整：
- [config/glm_review.yaml](config/glm_review.yaml)（GLM-4V-Flash，免费）
- [config/qwen_review.yaml](config/qwen_review.yaml)（通义千问 VL）
- [config/gemini_review.yaml](config/gemini_review.yaml)（Google Gemini）
- [config/quant_review.yaml](config/quant_review.yaml)（程序化复核）

可调参数：
- model：模型名称（GLM：glm-4v-flash，通义千问：qwen3-vl-plus/qwen-vl-max，Gemini：gemini-3.1-pro-preview）
- request_delay：调用间隔（防限流）
- skip_existing：是否断点续跑
- suggest_min_score：推荐分数门槛

---

## 6. 输出结果解读

### 候选文件

[data/candidates/candidates_latest.json](data/candidates/candidates_latest.json)

- pick_date：选股日期
- candidates：候选列表（含 code、strategy、close 等）

### 复评汇总

data/review/日期/suggestion.json

- recommendations：最终推荐（按分数排序）
- excluded：未达门槛代码
- min_score_threshold：推荐门槛

---

## 7. 常见问题

### Q1：fetch_kline 报 token 错误

- 检查 TUSHARE_TOKEN 是否已设置
- 确认 token 有效且账号权限正常

### Q2：导出图表时报 write_image 错误

- 确认已安装 kaleido
- 重新安装：pip install -U kaleido

### Q3：LLM 运行失败

**智谱 GLM-4V-Flash（推荐）**：
- 检查 ZHIPUAI_API_KEY 是否设置
- 获取免费 API Key：https://open.bigmodel.cn/usercenter/apikeys

**通义千问 VL**：
- 检查 DASHSCOPE_API_KEY 是否设置
- 获取 API Key：https://bailian.console.aliyun.com/

**Google Gemini**：
- 检查 GEMINI_API_KEY 是否设置
- 观察是否命中限流，可提高 request_delay

### Q4：没有候选股票

- 检查 data/raw 是否有最新数据
- 放宽初选阈值（如 B1 或 Brick 参数）
- 检查 pick_date 是否在有效交易日

---

## License

本项目采用 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) 协议发布。

- 允许：学习、研究、非商业用途的使用与分发
- 禁止：任何形式的商业使用、出售或以盈利为目的的部署
- 要求：转载或引用须注明原作者与来源

Copyright © 2026 SebastienZh. All rights reserved.
