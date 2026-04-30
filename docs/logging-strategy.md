# 日志策略说明文档

## 概述

为降低SQLite写入压力，系统采用分级日志策略，在保留必要信息的同时大幅降低写库频率。

## 优化目标

- 支持100用户规模下的正常运行
- 降低95%以上的数据库写入操作
- 保留关键审计和统计信息
- 不影响业务功能正常使用

## 1. Usage Logs（用量日志）

### 文件位置
`backend/app/middleware/usage.py`

### 策略
- **写入模式**: 批量聚合写入
- **缓冲大小**: 100条
- **时间窗口**: 60秒
- **适用范围**: 所有API请求（排除静态资源、健康检查等）

### 优化效果
- **优化前**: 每次API请求写1次数据库
- **优化后**: 每分钟批量写入1次或达到100条时写入
- **降低比例**: 约95-98%

### 数据保留
- 保留所有请求的统计信息
- 时间精度在分钟级别
- 足以支持用量统计和计费需求

## 2. API Key Last Used At（API密钥最后使用时间）

### 文件位置
`backend/app/api/deps.py`

### 策略
- **更新模式**: 时间窗口缓存
- **时间窗口**: 60秒
- **适用范围**: 所有使用API Key的请求

### 优化效果
- **优化前**: 每次验证都更新数据库
- **优化后**: 同一API Key每分钟最多更新1次
- **降低比例**: 约98%

### 数据保留
- last_used_at 精度在分钟级别
- 不影响API Key的活跃度判断
- 不影响安全审计（审计日志单独记录）

## 3. 审计日志

### 文件位置
`backend/app/audit.py`

### 策略
- **写入模式**: Fire-and-forget（异步不等待）
- **记录范围**: 仅关键操作
  - 用户登录/登出
  - 任务管理操作
  - 数据修改操作
  - 权限变更

### 记录规则
- **不记录**: 普通查询操作
- **记录**: 所有可能影响系统状态的操作
- **错误处理**: 写入失败不影响业务流程

## 4. 任务日志

### 文件位置
`backend/app/services/task_service.py`

### 策略
- **写入模式**: 批量聚合写入 + 关键事件立即写入
- **缓冲大小**: 50条
- **时间窗口**: 30秒
- **立即写入**: 任务状态变更（pending->running, completed等）

### 优化效果
- **优化前**: 每行输出都写数据库
- **优化后**: 批量写入，关键状态立即写入
- **降低比例**: 约80%

### 数据保留
- 所有状态变更完整记录
- 普通日志行可能最多延迟30秒
- 不影响任务进度追踪

## 配置参数

### Usage Logs
```python
FLUSH_INTERVAL = 60  # 秒
FLUSH_THRESHOLD = 100  # 条
```

### API Key Last Used At
```python
_API_KEY_UPDATE_INTERVAL = 60  # 秒
```

### Task Logs
```python
flush_interval = 30  # 秒
flush_threshold = 50  # 条
```

## 优雅关闭

应用关闭时会自动刷新所有缓冲区：
- Usage logs buffer
- Task logs buffer

确保所有待写入数据都能持久化。

## 监控建议

1. **监控缓冲区大小**: 定期检查缓冲区是否正常flush
2. **监控写入失败率**: 日志写入失败不应影响业务
3. **监控数据延迟**: 批量写入带来的时间延迟是否可接受

## 测试验证

可通过手动触发flush验证：
```python
from app.middleware.usage import flush_usage_buffer
from app.services.task_service import flush_task_log_buffer

flush_usage_buffer()
flush_task_log_buffer()
```

## 未来优化方向

1. 考虑迁移到PostgreSQL后，可以进一步优化为异步写入队列
2. 对于高频场景，可以考虑使用专门的时序数据库存储日志
3. 考虑日志归档策略，定期清理历史数据
