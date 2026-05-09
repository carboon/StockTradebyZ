# 修复工具手册

这份文档收口当前项目里已经落地的修复工具、它们解决的问题、推荐使用方式，以及执行顺序。

目标不是列所有脚本，而是回答这几个问题：

1. 当前遇到的数据异常属于哪一类
2. 应该用哪个修复工具
3. 该怎么跑，先小范围还是直接全量
4. 跑完后看什么来确认修复生效

## 当前问题分类

### 1. 历史评分链路异常

典型表现：

- 明日之星历史页面出现大量 `prefilter_blocked`
- 候选股很多，但历史分析结果评分为空或全是旧版异常结果
- `candidate_count` 和 `analysis_count` 不一致
- 当前热盘历史结果缺少 `details_json`
- 运行记录和实际候选/分析条数不一致

这类问题用：

- `bash deploy/scripts/repair_historical_scores.sh`

### 2. `stock_daily` 基础行情数据不完整

典型表现：

- 单股诊断提示“样本不足，无法完成第 4 步程序化复核”
- 某些股票在库里只有 `0`、`1` 条，或明显少于 `250` 条日线
- 后续 B1、历史详情、当前热盘/明日之星的单股评分缺乏基础行情支撑

这类问题用：

- `bash deploy/scripts/repair_incomplete_stock_daily.sh`

### 3. 单股诊断临时样本不足

这是服务侧自愈，不是独立脚本。

当前行为：

- 单股诊断在分析前会先检查本地历史窗口
- 如果样本明显不足，会先按股补历史日线，再继续 B1 和量化评分
- 如果当天旧任务结果是“样本不足”，不会继续复用那条旧任务

相关代码：

- [analysis_service.py](../backend/app/services/analysis_service.py)
- [task_service.py](../backend/app/services/task_service.py)

说明：

- 这个能力适合“临时查一只股票时自动补”
- 不适合代替大范围数据修库；库里缺口很多时，仍应先跑批量修复脚本

## 工具一：历史评分修复

文件：

- [deploy/scripts/repair_historical_scores.sh](../deploy/scripts/repair_historical_scores.sh)
- [backend/scripts/repair_historical_scores.py](../backend/scripts/repair_historical_scores.py)

### 解决的问题

- 明日之星历史结果中旧版 `prefilter_blocked + 空评分`
- 历史结果缺失 `prefilter` 明细
- 明日之星运行记录计数异常
- 当前热盘历史记录中 `details_json` 缺失
- 候选条数和分析条数不一致

### 推荐用法

先看扫描结果：

```bash
bash deploy/scripts/repair_historical_scores.sh --window-size 5
```

只修明日之星：

```bash
bash deploy/scripts/repair_historical_scores.sh --scope tomorrow-star
```

只修当前热盘：

```bash
bash deploy/scripts/repair_historical_scores.sh --scope current-hot
```

同时修两个范围：

```bash
bash deploy/scripts/repair_historical_scores.sh --scope both
```

指定日期：

```bash
bash deploy/scripts/repair_historical_scores.sh --scope tomorrow-star --dates 2026-02-04 2026-02-05
```

指定区间：

```bash
bash deploy/scripts/repair_historical_scores.sh --scope both --start-date 2026-02-01 --end-date 2026-02-10
```

### 速度说明

这条链路已经做过一轮优化：

- 明日之星修复不再逐日重复回放
- 连续交易日会按批重建
- `run_backtest()` 和连续候选重算改成按批执行

所以现在推荐优先按范围执行，不需要再手动逐日拆。

### 修复后重点确认

- 历史页面不再出现旧版 `prefilter_blocked`
- 分析结果不再大面积空评分
- `candidate_count == analysis_count`
- 当前热盘历史结果 `details_json` 完整

## 工具二：基础日线数据修复

文件：

- [deploy/scripts/repair_incomplete_stock_daily.sh](../deploy/scripts/repair_incomplete_stock_daily.sh)
- [backend/scripts/repair_incomplete_stock_daily.py](../backend/scripts/repair_incomplete_stock_daily.py)

### 解决的问题

- `stock_daily` 完全缺失
- `stock_daily` 只有极少数记录，比如 `0/1/10` 条
- 单股诊断样本不足
- 明日之星、当前热盘、历史详情的单股分析缺少足够基础行情

### 推荐用法

先看命中范围：

```bash
bash deploy/scripts/repair_incomplete_stock_daily.sh --min-days 250 --limit 20 --dry-run
```

小批量实际修复：

```bash
bash deploy/scripts/repair_incomplete_stock_daily.sh --min-days 250 --limit 200
```

只修指定股票：

```bash
bash deploy/scripts/repair_incomplete_stock_daily.sh --codes 601992 000638 --min-days 250
```

如果还要同时回写 `data/raw/*.csv`：

```bash
bash deploy/scripts/repair_incomplete_stock_daily.sh --min-days 250 --limit 200 --write-csv
```

### 关键参数

- `--min-days`
  判断“样本不足”的阈值，默认 `250`
- `--limit`
  本次最多修多少只股票，建议先小批量
- `--codes`
  只修指定代码
- `--dry-run`
  只看待修复范围，不实际抓取
- `--write-csv`
  同时回写 `data/raw/*.csv`
- `--flush-codes`
  累计多少只股票后统一写库，默认 `20`
- `--upsert-batch-size`
  单次数据库 UPSERT 的内部批大小，默认 `5000`

### 速度说明

这条脚本已经做过一轮提速：

- 默认不写 CSV，只修数据库
- 不再每只股票单独开事务提交
- 改为累计多只股票后批量 UPSERT

现阶段最大的瓶颈仍然是 Tushare 的逐股拉取，不是 PostgreSQL。

### 修复后重点确认

- 单股诊断不再返回“样本不足”
- 某只股票 `stock_daily` 行数明显增加
- 后续历史详情/B1/量化评分能正常产出

## 旧工具说明

文件：

- [backend/scripts/fetch_missing_stock_daily.py](../backend/scripts/fetch_missing_stock_daily.py)

说明：

- 这个脚本只处理“`stock_daily` 完全没有记录”的股票
- 对“已有 `1` 条但严重不足”的情况无效

当前建议：

- 除非明确只想补完全缺失的股票，否则优先使用 `repair_incomplete_stock_daily.sh`

## 推荐执行顺序

如果你面对的是“历史页面异常 + 单股诊断样本不足”这种混合问题，建议按这个顺序：

1. 先修基础日线

```bash
bash deploy/scripts/repair_incomplete_stock_daily.sh --min-days 250 --limit 200
```

2. 再修历史评分

```bash
bash deploy/scripts/repair_historical_scores.sh --scope both
```

3. 最后抽查页面

- 单股诊断任选几只之前报“样本不足”的股票
- 明日之星任选几天之前异常的历史页
- 当前热盘任选几天历史结果，确认 `details_json` 和评分显示正常

## 是否需要重启

脚本本身不需要重启服务，改完后直接可跑。

只有服务逻辑本身发生变更时，比如：

- 单股诊断自动补历史
- 任务复用逻辑变更

才需要重启 `stocktrade-backend` 让新代码进程生效。

## 当前已确认的修复结论

- `601992` 单股诊断样本不足问题已经修复
  - 修复前：`stock_daily` 只有 `1` 条
  - 修复后：补到 `484` 条，单股诊断可正常评分
- `000004`、`000638` 已验证可通过基础日线修复脚本补齐到 `1700+` 条
- 历史评分修复链路已支持按批重建，适合直接在生产环境按范围执行
