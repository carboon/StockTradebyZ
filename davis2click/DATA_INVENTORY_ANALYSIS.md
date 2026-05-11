# 数据资产盘点 & 戴维斯双击可行性分析

> 分析日期: 2026-05-11 | 基于当前工程实际数据状态

---

## 1. 主工程数据资产

### 1.1 data/raw/ — 个股日线行情 (CSV)

- **数量**: 5,487 只股票，每只一个 `.csv`
- **字段**: `date, open, close, high, low, volume`
- **时间跨度**: 2019-01-01 ~ 最新交易日
- **来源**: `pipeline/fetch_kline.py` 通过 Tushare `daily` 接口拉取
- **质量**: 高，覆盖全A股，历史约7年

### 1.2 PostgreSQL 数据库 (20+ 表)

| 表 | 用途 | 与戴维斯模型的相关性 |
|---|------|---------------------|
| `stocks` | 全A股基本信息（code, name, market, industry） | **高** — 候选池、行业分类 |
| `stock_daily` | 日线 OHLCV + 资金流向（主力/散户买卖额） | **高** — 行情源 + 资金流向因子 |
| `stock_active_pool_ranks` | 每日流动性排名（43日滚动成交额 TOP2000） | **中** — 流动性过滤 |
| `candidates` | B1 策略每日候选股（KDJ + 均线） | **中** — 与双击模型交叉验证 |
| `analysis_results` | LLM/量化评审结果（PASS/WATCH/FAIL） | **中** — 评分体系参考 |
| `daily_b1_checks` | 每日 B1 技术指标快照（KDJ_J, 均线排列, 量比） | **中** — 技术因子复用 |
| `daily_b1_check_details` | B1 评分的详细规则命中记录 | **低** — 调试用 |
| `stock_analysis` | 统一分析缓存 | **中** — 跨策略复用 |

### 1.3 data/candidates/ — 历史候选池

- **格式**: `candidates_YYYY-MM-DD.json`
- **时间**: 从 2025-08-06 到 2026-05-07，约 **35 个交易日**
- **内容**: 每日期选出的 20-80 只候选股（code, close, turnover_n, kdj_j, strategy）
- **策略**: `b1`（KDJ + 均线多头）为主

### 1.4 data/review/ — 量化评审历史

- **规模**: 86 个日期子目录，**10,711 个 JSON** 文件
- **时间**: 2024-01-03 ~ 2026-05-07
- **内容**: 每只候选股的4维量化评分：
  - `trend_structure`（趋势结构）
  - `price_position`（价格位置）
  - `volume_behavior`（量价行为）
  - `previous_abnormal_move`（历史异动）
  - `total_score` / `verdict` / `signal_type`
- **聚合文件**: 每个日期目录下的 `suggestion.json`（当日推荐汇总）

### 1.5 主力工程代码资产

| 位置 | 功能 | 可复用性 |
|------|------|---------|
| `pipeline/fetch_kline.py` | Tushare 日线拉取 + PG入库 | **高** — 批量API拉取框架 |
| `pipeline/select_stock.py` | B1/Brick 初选逻辑 | **高** — 筛选管道模式参考 |
| `agent/quant_reviewer.py` | 4维量化打分 | **高** — 因子计算 + 评分框架 |
| `backend/app/services/tushare_service.py` | Tushare API 封装 | **高** — 直接复用 |

---

## 2. 戴维斯模型数据缺口

| 缺口数据 | 影响 | 数据获取难度 |
|---------|------|------------|
| **PE/PB/PS 估值** | 无法筛选估值低位（第二腿核心） | **低** — `daily_basic` 全市场单次调用 |
| **PE/PB 历史分位数** | 无历史分位无法判断"低位" | **中** — 需本地维护5年时间序列 |
| **利润表（净利润/营收）** | 无法计算增速/加速度（第一腿核心） | **中** — `income` 逐只拉取，~15分钟/轮 |
| **财务指标（毛利率/ROE）** | 缺失毛利率趋势、盈利质量 | **中** — `fina_indicator` 逐只拉取 |
| **资产负债表（商誉/应收）** | 缺失风控因子 | **中** — `balancesheet` 逐只拉取 |
| **现金流** | 缺失现金流质量因子 | **中** — `cashflow` 逐只拉取 |
| **北向资金 / 融资融券** | 缺失催化剂确认 | **中** — `hk_hold`/`margin_detail` 逐只 |
| **质押数据** | 缺失风控因子 | **低** — `pledge_stat` 批量3000只 |

---

## 3. 可立即进行的分析（零新数据）

以下分析使用现有 `data/review/` + `data/candidates/` + `stock_daily` 即可完成：

### 3.1 量化评审有效性回测

- **目的**: 验证 4 维评分体系的预测力
- **方法**: 用 `total_score`/`verdict` 与后续 N 日涨跌幅做 Rank IC 分析
- **数据**: `data/review/*/` 的 10,711 条记录 + `data/raw/*.csv` 的未来行情
- **产出**: 各维度 IC 值、ICIR、分层回测

### 3.2 候选池绩效统计

- **目的**: 统计 B1 策略选股的整体表现
- **方法**: 每期候选股等权组合，跟踪 1/5/10/20 日收益
- **数据**: `data/candidates/` 35期记录
- **产出**: 胜率、平均收益、最大回撤、相对沪深300超额

### 3.3 资金流向因子挖掘

- **目的**: 用 `stock_daily` 的主力/散户买卖数据构建新因子
- **方法**: 主力净流入占比、大单买入强度等衍生因子
- **数据**: `stock_daily` 表 (buy_sm_amount, buy_lg_amount 等)
- **产出**: 资金流向因子的 IC 和分层效果

### 3.4 KDJ 因子归因

- **目的**: 拆解 KDJ_J 值对收益的独立预测力
- **方法**: 按 J 值分组，统计各组后续收益单调性
- **数据**: `daily_b1_checks` 表 + 未来行情
- **产出**: KDJ 因子的有效性评估

### 3.5 行业轮动分析

- **目的**: 候选股在行业间的分布特征和表现差异
- **数据**: `stocks` 表 industry 字段 + review 评分
- **产出**: 行业分布热力图、行业间平均得分差异

---

## 4. 推荐实施路线

### Phase 0: 存量数据回测 (当前 → 1-2天)
- [ ] 评审有效性回测（IC 分析）
- [ ] 候选池绩效基准
- [ ] 资金流向因子探索
- [ ] 修复 `test_tushare.py` 的 venv 路径 + token 配置

### Phase 1: 轻量戴维斯 (1-3天)
- [ ] 拉取 `daily_basic` 全市场 PE/PB/PS（单次调用）
- [ ] 本地启动 PE/PB 时间序列维护
- [ ] 用 PE 分位 + KDJ + 资金流向做"轻量双击"排序
- [ ] 与现有 B1 策略对比

### Phase 2: 完整戴维斯 (1-2周)
- [ ] `income` 逐只拉取（净利润增速/加速度）
- [ ] `fina_indicator` 逐只拉取（毛利率/ROE）
- [ ] `balancesheet` 逐只拉取（商誉/应收/负债风控）
- [ ] 完整因子计算 + 筛选管道
- [ ] 历史回测 + 参数敏感性分析

### Phase 3: 催化剂 & 优化
- [ ] `hk_hold`/`margin_detail` 资金流向因子
- [ ] `pledge_stat` 风控因子
- [ ] 组合优化（行业中性、市值中性）
- [ ] 实盘监控面板

---

## 5. 已知问题 (davis2click/)

| 问题 | 影响 | 修复 |
|------|------|------|
| `test_tushare.py` L8 venv路径指向 `/Volumes/DATA/davis2click/venv/` | 脚本无法运行 | 改为 `/Volumes/DATA/StockTradebyZ/.venv/` 或移除 sys.path |
| `test_tushare.py` L12 token硬编码 | 安全风险 | 从环境变量或配置文件读取 |
| 目录下无 `venv/` | 无隔离环境 | 复用主工程 `.venv/`（已含 tushare）或单独创建 |
| 设计文档中项目路径为 `/Volumes/DATA/davis2click/` | 路径不一致 | 已修正为实际路径 |

---

## 6. 与主工程的协同关系

```
主工程 (StockTradebyZ)
  ├─ pipeline/fetch_kline.py  ← davis2click 可复用拉取框架
  ├─ data/raw/*.csv           ← davis2click 可直接读取行情
  ├─ PostgreSQL stock_daily    ← davis2click 可读取资金流向
  ├─ data/review/             ← davis2click 可做回测验证
  │
  └─ davis2click/             ← 独立子工程
       ├─ 复用主工程数据 + API框架
       ├─ 独立因子计算 + 筛选管道
       └─ 输出独立选股结果
```

设计原则：**davis2click 读取主工程数据，但不写入主工程表**，保持数据边界清晰。

---

## 7. 下一步行动

1. **立即**: 修复 `test_tushare.py` 并运行，确认 Tushare API 权限和数据可获取性
2. **并行**: 基于 `data/review/` 做评审有效性回测
3. **前置**: 拉取 `daily_basic` 全市场 PE/PB，为轻量双击做准备
