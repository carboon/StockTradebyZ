# StockTrader 2.0 架构说明

## 当前运行模型

系统当前收敛为：

`浏览器 -> nginx/nginx-dev -> backend -> PostgreSQL`

说明：

- 开发环境使用 `frontend-dev + nginx-dev`
- 生产环境使用 `nginx` 托管前端静态资源
- `backend` 负责 API、任务编排、结果拼装
- `pipeline/` 和 `agent/` 保留离线量化与复核逻辑

## 目录职责

- `frontend/`
  Vue 页面层
- `backend/`
  FastAPI、任务中心、数据接口
- `pipeline/`
  抓数、初选、候选构建
- `agent/`
  quant 复核、单股分析
- `deploy/`
  Docker 运行与部署
- `data/`
  快照、缓存、导出与运行期文件

## 在线与离线边界

在线接口：

- 以查询为主
- 优先读数据库和历史文件
- 不在普通查询请求里触发大规模补算

离线任务：

- 由管理员触发
- 生成公共结果
- 用户页面只消费结果

## 数据边界

- 正式主库只有 PostgreSQL
- 文件系统只保留快照、缓存、导出用途

## 当前官方入口

- 开发：`./start.sh`
- 停止：`./stop.sh`
- 生产：`./deploy/scripts/start.sh prod --build`
- 发布：`./deploy/scripts/release.sh`
