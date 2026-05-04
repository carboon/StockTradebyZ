# dailyUpdateTest

`dailyUpdateTest` 用来验证当前项目的完整日更链路是否可回放、可补数、可重算。

## 目标

覆盖这条真实链路：

1. 删除指定交易日的最新数据
2. 基于前一交易日重算离线结果
3. 通过现有抓取流程补回指定交易日增量
4. 再基于指定交易日重算离线结果
5. 输出耗时、负载、关键计数和报告

## 当前前提

- 当前仓库仍是 `PostgreSQL + data/raw CSV + data/candidates + data/review` 混合运行
- `pipeline.cli preselect` 和 `agent/quant_reviewer.py` 仍会读取 `data/raw`
- 所以这个测试不只会改数据库，也会改 `data/raw/*.csv`

## 文件位置

脚本：

```bash
python backend/daily_update_test.py --help
```

## 推荐执行方式

进入后端容器后执行：

```bash
./deploy/scripts/start.sh exec-backend
python backend/daily_update_test.py --target-date 2026-04-30
```

如果希望测试完成后自动恢复原始状态：

```bash
python backend/daily_update_test.py --target-date 2026-04-30 --restore-after
```

如果也要验证 Top5 历史文件生成：

```bash
python backend/daily_update_test.py --target-date 2026-04-30 --with-history
```

## 做了什么

脚本会做这些动作：

1. 快照指定交易日的数据库行
2. 快照相关文件
3. 从 `data/raw/*.csv` 删除该交易日行
4. 从这些表删除该交易日数据
   - `stock_daily`
   - `candidates`
   - `analysis_results`
   - `daily_b1_checks`
   - `stock_analysis`
   - `data_update_log`
5. 以前一交易日重新跑一次：
   - `pipeline.cli preselect`
   - `agent/quant_reviewer.py`
   - 同步候选和分析结果入库
6. 跑一次：
   - `python -m pipeline.fetch_kline --incremental --db`
7. 再以目标交易日重跑一次：
   - `pipeline.cli preselect`
   - `agent/quant_reviewer.py`
   - 同步候选和分析结果入库
8. 输出报告到 `data/logs/dailyUpdateTest/<timestamp>/report.json`

运行过程中还会持续写这些文件：

- `runtime_state.json`
  当前整体运行状态
- `stages/<stage>.json`
  每个阶段的开始/结束状态
- `events.jsonl`
  结构化事件流
- `commands/<command>.log`
  每个子命令的完整输出

## 输出内容

报告里重点关注：

- 每个阶段耗时
- 最慢阶段排序
- 删除前后、补数后、重算后的行数变化
- 命令执行返回码
- 标准输出和错误输出尾部
- 当前进程的 `maxrss`
- 系统 `loadavg`

如果你想实时判断是不是卡住，优先看：

```bash
cat data/logs/dailyUpdateTest/<timestamp>/runtime_state.json
tail -n 20 data/logs/dailyUpdateTest/<timestamp>/events.jsonl
tail -n 50 data/logs/dailyUpdateTest/<timestamp>/commands/fetch_incremental_with_db.log
```

## 风险说明

- 这是破坏性测试，不要在你不想改动的数据目录上直接运行
- 不带 `--restore-after` 时，脚本结束后会保留“重算后的最新状态”
- `--restore-after` 会恢复目标交易日相关数据，但不会回滚整个仓库的所有副作用

## 目前结论

这个测试用例已经按“当前真实代码路径”设计，不是假流程。

但它也暴露了当前架构现状：

- 离线计算还没有完全切到数据库
- `run_all.py` 也还不是一个真正可按任意交易日重放的统一编排入口
- 所以 `dailyUpdateTest` 采用的是“现有真实步骤编排”，而不是强行套 `run_all.py`
