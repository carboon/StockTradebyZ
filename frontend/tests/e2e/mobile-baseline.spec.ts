import { test, expect } from './fixtures'

test.describe('mobile baseline', () => {
  test('TomorrowStar -> Diagnosis keeps 30-day mobile path', async ({ page, mockApp }, testInfo) => {
    test.skip(testInfo.project.name !== 'mobile-chrome', 'mobile baseline only validates phone layout')

    await mockApp({ admin: true })
    await page.goto('/tomorrow-star', { waitUntil: 'networkidle' })

    await expect(page.getByText('历史信息')).toBeVisible()
    await expect(page.getByText('分析结果 Top 5')).toBeVisible()
    await page.getByRole('button', { name: /000001/ }).click()

    await expect(page).toHaveURL(/\/diagnosis\?/)
    await expect(page).toHaveURL(/source=tomorrow-star/)
    await expect(page).toHaveURL(/days=30/)
    await expect(page.getByText('来自明日之星，默认展示30天')).toBeVisible()
    await expect(page.getByText('平安银行')).toBeVisible()
  })

  test('Watchlist and Config render mobile-specific entry points', async ({ page, mockApp }, testInfo) => {
    test.skip(testInfo.project.name !== 'mobile-chrome', 'mobile baseline only validates phone layout')

    await mockApp({ admin: true })
    await page.goto('/watchlist', { waitUntil: 'networkidle' })
    await expect(page.getByText('我的观察')).toBeVisible()
    await page.getByRole('button', { name: /000001/ }).click()
    await expect(page.locator('.decision-card .decision-title').filter({ hasText: '建仓建议' })).toBeVisible()

    await page.goto('/config', { waitUntil: 'networkidle' })
    await expect(page.getByText('参数配置')).toBeVisible()
    await expect(page.getByRole('button', { name: '保存配置' }).last()).toBeVisible()
    await expect(page.getByRole('button', { name: '保存并初始化' }).last()).toBeVisible()
  })
})
