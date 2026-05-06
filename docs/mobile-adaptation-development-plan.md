# 移动端兼容开发计划

## 目标

在不影响桌面端展示和现有交互的前提下，为高频页面提供可用的移动端体验。本次改造采用单前端代码库的响应式方案，不新增独立移动站。

硬约束：

- 桌面端结构和能力不退化
- 移动端优先覆盖高频业务页
- 本地开发环境支持手机局域网联调
- 移动端从“明日之星”进入“单股诊断”时，K 线默认展示 30 天

## 适配范围

P0：

- `frontend/src/components/common/PageLayout.vue`
- `frontend/src/views/TomorrowStar.vue`
- `frontend/src/views/Diagnosis.vue`

P1：

- `frontend/src/views/Watchlist.vue`
- `frontend/src/views/Login.vue`
- `frontend/src/views/Register.vue`
- `frontend/src/views/Config.vue`
- `frontend/src/views/Profile.vue`
- `frontend/src/views/SystemInfo.vue`

P2：

- `frontend/src/views/Update.vue`
- `frontend/src/views/Admin.vue`

## 页面规则

### 明日之星

移动端只保留两块：

1. 历史信息：日期、候选数、趋势启动数、状态
2. 分析结果 Top 5：代码、名称、评分、信号类型、简评

点击 Top 5 卡片跳转单股诊断，并透传 `source=tomorrow-star&days=30`。桌面端保留现有完整布局。

### 单股诊断

移动端采用单列布局。若 `isMobile && source === 'tomorrow-star'`，默认固定 30 天 K 线。桌面端保留现有多周期切换。

### 重点观察

移动端拆为“列表页 + 详情页”，桌面端保留左右同屏结构。

### 配置、登录、个人资料、系统说明

以表单和内容排版适配为主：输入框改为 100% 宽度，标签顶置，必要时增加底部粘性操作栏。

### 运维管理、用户管理

移动端采用降级方案，只保留关键状态、核心动作和摘要信息；桌面端保持完整能力。

## 技术方案

- 统一断点：
  - `mobile < 768`
  - `tablet 768-1023`
  - `desktop >= 1024`
- 新增 `frontend/src/composables/useResponsive.ts`
- 样式改动优先放在移动断点内，避免影响桌面端
- 表格类页面采用双模式渲染：
  - 桌面端 `el-table`
  - 移动端卡片列表
- 图表页面补充 resize 处理，覆盖断点切换、屏幕旋转和页面激活

## 本地开发与联调

- 前端开发服务需支持 `0.0.0.0`
- 手机和电脑在同一局域网时，可通过 `http://<LAN-IP>:5173` 访问前端
- API 地址不能写死 `127.0.0.1`，需通过环境变量配置
- 在 `README.dev.md` 补充“移动端本地联调说明”

### 本机启动 + 局域网验证方式

推荐两种方式：

1. Docker 统一入口：`http://<LAN-IP>:8080`
2. Vite 直连前端：`http://<LAN-IP>:5173`

建议流程：

```bash
# 方式一：完整联调
./start.sh

# 方式二：只启动前端，便于调样式
cd frontend
VITE_API_PROXY_TARGET=http://<LAN-IP>:8000 npm run dev:mobile
```

执行要求：

- 电脑与手机连接同一 Wi-Fi
- 本机防火墙放行 `5173`、`8000`、`8080`
- 使用 `ipconfig getifaddr en0` 或等效命令获取本机局域网 IP
- 手机优先访问 `http://<LAN-IP>:8080` 验证完整链路
- 若只调前端样式，再访问 `http://<LAN-IP>:5173`
- 联调时确认 API、静态资源、登录态与 WebSocket 在局域网地址下可用

## 开发阶段

### Phase 1：基础设施

- [ ] 新增 `useResponsive`
- [ ] 定义统一断点与全局响应式 token
- [ ] 修正全局 `100vh` 容器策略
- [ ] 统一最小触控尺寸

### Phase 2：主框架

- [ ] 改造 `PageLayout.vue`
- [ ] 手机端实现抽屉导航
- [ ] 手机端压缩顶部栏
- [ ] 合并状态入口
- [ ] 验证桌面端框架不退化

### Phase 3：明日之星

- [ ] 增加移动端分支视图
- [ ] 实现历史信息卡片列表
- [ ] 实现 Top 5 卡片列表
- [ ] 点击历史项刷新 Top 5
- [ ] 点击 Top 5 跳转单股诊断
- [ ] 透传 `source=tomorrow-star&days=30`
- [ ] 桌面端保留原布局

### Phase 4：单股诊断

- [ ] 读取跳转参数
- [ ] 实现移动端默认 30 天逻辑
- [ ] 弱化移动端周期切换
- [ ] 分析面板改单列
- [ ] 历史表改卡片
- [ ] 图表补充 resize 处理
- [ ] 桌面端保持现状

### Phase 5：重点观察

- [ ] 移动端拆为列表页/详情页
- [ ] 列表改卡片
- [ ] 详情保留图表和建议
- [ ] 历史分析改摘要卡
- [ ] 编辑删除改抽屉或全屏弹层

### Phase 6：账户与配置

- [ ] 适配 `Login/Register`
- [ ] 适配 `Config`
- [ ] 适配 `Profile`
- [ ] 适配 `SystemInfo`

### Phase 7：后台页降级

- [ ] 适配 `Update` 的移动端摘要版
- [ ] 适配 `Admin` 的移动端卡片版
- [ ] 保留桌面端完整能力

### Phase 8：联调与文档

- [ ] 前端支持 `0.0.0.0`
- [ ] 验证手机局域网访问
- [ ] 配置移动联调 API 地址
- [ ] 更新 `README.dev.md`

## 验收标准

- 桌面端展示与主要交互不退化
- 移动端“明日之星”仅展示历史信息和 Top 5
- 从移动端“明日之星”进入“单股诊断”时，K 线默认 30 天
- 核心页面在手机尺寸下无横向滚动
- 本地开发环境支持手机直接访问测试
