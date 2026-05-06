# Playwright E2E Baseline

最小移动端回归基线，覆盖：

- 移动端 `TomorrowStar -> Diagnosis` 默认 `30天` 链路
- 移动端 `Watchlist / Config` 关键入口存在性
- 桌面端 `TomorrowStar / Diagnosis` 基础结构未退化

运行方式：

```bash
cd frontend
npm run test:e2e
```

常用变体：

```bash
npm run test:e2e:headed
npm run test:e2e -- --project=mobile-chrome
npm run test:e2e -- --project=desktop-chrome
```

说明：

- 默认自动启动本地 Vite dev server。
- 测试通过 `route.fulfill()` mock `/api/**`，不依赖真实后端。
- 登录态通过预置 `localStorage.stocktrade_token` 和 `/v1/auth/me` mock 完成。
- 当前基线偏验收级，不验证复杂图表渲染细节，只验证关键视图与路由规则。
