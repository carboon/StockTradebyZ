# StockTrader 2.0

一个面向 A 股的本地量化选股与复核系统，提供 Web 可视化界面。

## 🚀 快速开始

### Windows（推荐）

```powershell
.\bootstrap-local.bat
```

首次运行会自动安装依赖并启动服务。访问 http://127.0.0.1:5173

### macOS / Linux

```bash
./start-dev.sh
```

访问 http://localhost:3000

详细部署指南请查看 [DEPLOYMENT.md](DEPLOYMENT.md)

---

## ✨ 核心功能

- **数据抓取**: 从 Tushare 自动获取全市场日线数据
- **量化初选**: 基于流动性和技术形态筛选候选股票
- **智能复核**: 本地量化评分或 LLM 图表分析
- **Web 界面**: 可视化查看候选股和评分结果
- **持仓分析**: 单票持仓报告和减仓建议
- **滚动回测**: 策略历史表现验证

---

## 📖 文档导航

| 文档 | 说明 |
|------|------|
| [DEPLOYMENT.md](DEPLOYMENT.md) | 完整部署指南（Docker、本地、定时任务） |
| [WINDOWS_DEPLOYMENT.md](WINDOWS_DEPLOYMENT.md) | Windows 专属部署说明 |
| [README.dev.md](README.dev.md) | 开发者文档（架构、API、测试） |

---

## 🔧 主要组件

### 1. 主流程 (`run_all.py`)

一键执行完整选股流程：

```bash
python run_all.py                    # 默认使用量化复核
python run_all.py --reviewer glm     # 使用 GLM 模型复核
python run_all.py --skip-fetch       # 跳过数据下载
```

### 2. 量化复核 (`agent/quant_reviewer.py`)

本地程序化评分，无需 API Key：

```bash
python agent/quant_reviewer.py --code 600519 --date 2024-04-27
```

### 3. 持仓报告 (`agent/holding_report.py`)

生成持仓视角的分析报告：

```bash
python agent/holding_report.py --code 601975 --start-date 2024-04-17 --end-date 2024-04-27
```

### 4. Web 面板 (`dashboard/app.py`)

```bash
streamlit run dashboard/app.py
```

更多命令请参考 [README.dev.md](README.dev.md#常用命令)

---

## ⚙️ 配置说明

### 必需配置

在 `.env` 文件中设置：

```env
TUSHARE_TOKEN=your_token_here
```

获取 Token: https://tushare.pro/user/token

### 可选配置

- `ZHIPUAI_API_KEY` - 智谱 GLM 模型
- `DASHSCOPE_API_KEY` - 通义千问模型  
- `GEMINI_API_KEY` - Google Gemini 模型

配置文件位于 `config/` 目录：

- `fetch_kline.yaml` - 数据抓取配置
- `rules_preselect.yaml` - 初选规则
- `quant_review.yaml` - 量化评分规则

---

## 📁 输出目录

```
data/
├── raw/              # 原始日线数据
├── candidates/       # 初选候选股
├── review/           # 评分结果和推荐
│   └── <date>/
│       └── suggestion.json  # 最终推荐
├── kline/            # K线图表
└── logs/             # 运行日志
```

---

## 💡 日常使用建议

### 盘后完整流程

```bash
source .venv/bin/activate
python run_all.py
```

查看推荐结果：`data/review/<date>/suggestion.json`

### 仅重算评分（数据已更新）

```bash
python run_all.py --skip-fetch
```

### 单票补充分析

```bash
python agent/quant_reviewer.py --code 600519
```

### 参数调优后验证

```bash
python -m pipeline.backtest_quant --start-date 2023-01-01 --end-date 2024-04-27
```

详细使用场景请查看 [README.dev.md](README.dev.md#日常操作流程)

---

## 🛠️ 技术栈

- **后端**: Python 3.11+, FastAPI, SQLite
- **前端**: Vue 3, TypeScript, Vite
- **数据**: Tushare, Pandas, NumPy
- **分析**: Numba, Plotly, Streamlit
- **AI**: OpenAI, ZhipuAI, DashScope, Gemini (可选)

---

## ❓ 常见问题

### 端口被占用

系统会自动检测并分配可用端口，无需手动干预。

### numba 安装失败

确保使用 Python 3.11+：

```bash
python --version  # 应 >= 3.11
```

### 没有推荐股票

这是正常现象，量化规则偏保守。检查：
- 数据是否最新
- 评分阈值是否过高
- 前置过滤条件

更多问题请查看 [DEPLOYMENT.md](DEPLOYMENT.md#常见问题)

---

## 📄 许可证

本项目采用 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) 协议。

- ✅ 允许学习、研究、非商业用途
- ❌ 禁止商业使用
- 📝 引用须注明原作者

Copyright © 2026 SebastienZh. All rights reserved.
