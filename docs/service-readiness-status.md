# 100 用户服务化当前状态

> 更新时间：2026-05-01  
> 目标部署：`2U4G` 单机  
> 目标规模：约 `100` 注册用户

本文档用于保留“当前真实状态”和“仍待确认内容”，避免阶段性报告互相冲突。

## 当前结论

当前版本已经完成核心服务化改造，整体方向正确，且相比早期版本已有明显改善。

基于最近一次聚焦复测，当前更稳妥的结论是：

- **可以支持 `100` 注册用户规模下的灰度与日常使用**
- **建议先按 `10-20` 人同时在线进行灰度验证**
- **暂不建议直接下“稳定支持 100 人并发高频分析”的结论**

这不是因为核心链路还不可用，而是因为最终容量判断仍需灰度验证确认。

## 最近一次聚焦复测结果

针对服务化核心链路复测：

- 运行命令：

```bash
./.venv/bin/pytest \
  backend/tests/test_services/test_analysis_service.py \
  backend/tests/test_services/test_task_service.py \
  backend/tests/test_api/test_analysis_api.py \
  backend/tests/test_api/test_watchlist_api.py \
  backend/tests/test_api/test_tasks_api.py \
  -q
```

- 结果：
  - `162 passed`
  - `5 failed`

这说明：

- 核心链路已经大幅收敛
- 当前剩余问题已不是大面积架构性故障
- 但“最终完全通过”这一结论还不能写

## 已确认完成的事项

以下事项已经可以认为完成：

- `single_analysis` 的 SQLAlchemy 2.0 / SQLite JSON 查询兼容性已修复
- `analyze_stock()` 的缓存命中与实时返回结构已基本统一
- `GET /api/v1/analysis/tomorrow-star/results` 已改为仅读，不再补算、不再写文件
- `watchlist/analyze` 冷缓存路径已改成后台任务化返回 `pending`
- `watchlist/analyze` 的测试 patch 与 SQLite 测试隔离问题已修复，相关 API 用例已全通过
- 高频写入压力已通过 usage log 聚合、API key 更新时间降频等方式得到明显缓解
- 服务化关键测试已从大面积失败收敛到少量剩余问题

## 仍待确认的事项

以下内容需要继续确认，不应在文档里提前写成“已完全解决”。

### 1. 灰度结论仍需真实流量验证

虽然代码和测试已经明显收敛，但 `2U4G / 100 用户` 的最终判断仍建议经过真实灰度验证确认：

- 10-20 人同时在线
- 高频浏览明日之星
- K 线查询
- 少量单股分析
- 少量观察分析

关注指标：

- P95 / P99 接口耗时
- 分析任务完成率
- 任务排队情况
- 错误率

## 当前建议口径

当前建议对内/对外统一使用以下表述：

- 已完成首轮核心服务化改造
- 已具备 `100` 注册用户规模下的小规模线上使用能力
- 建议先进行 `10-20` 人同时在线灰度验证
- 灰度通过后，再确认是否正式宣称支持 `100` 用户规模

## 不建议当前使用的表述

以下说法当前仍然偏满，不建议写入正式结论：

- “系统已稳定支持 100 人并发”
- “最终集成测试全部通过”
- “所有服务化问题已完全关闭”
- “观察列表链路已无待确认问题”

## 与其他文档的关系

- 架构分析与改造方案：看 [service-readiness-100-users.md](/Volumes/DATA/StockTradebyZ/docs/service-readiness-100-users.md:1)
- 执行清单：看 [service-readiness-100-users-todo.md](/Volumes/DATA/StockTradebyZ/docs/service-readiness-100-users-todo.md:1)
- 本文档只负责记录**当前真实状态**和**仍待确认事项**
