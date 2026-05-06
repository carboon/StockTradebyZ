import { test, expect } from './fixtures'

test.describe('mobile touch flows', () => {
  test('touch interactions update TomorrowStar selection and navigate to Diagnosis', async ({ page, mockApp }, testInfo) => {
    test.skip(testInfo.project.name !== 'mobile-chrome', 'touch flows only validate phone layout')

    await mockApp({ admin: true })
    await page.goto('/tomorrow-star', { waitUntil: 'networkidle' })

    const historyItems = page.locator('.mobile-history-item')
    await expect(historyItems).toHaveCount(2)

    await historyItems.nth(1).tap()
    await expect(historyItems.nth(1)).toHaveClass(/active/)
    await expect(page.getByText('已选 2026-05-04')).toBeVisible()

    const analysisItems = page.locator('.mobile-analysis-item')
    await expect(analysisItems.first()).toBeVisible()
    await analysisItems.first().tap()

    await expect(page).toHaveURL(/\/diagnosis\?/)
    await expect(page).toHaveURL(/source=tomorrow-star/)
    await expect(page).toHaveURL(/days=30/)
    await expect(page.getByText('来自明日之星，默认展示30天')).toBeVisible()
  })

  test('touch interactions support Watchlist selection and Config action bar after scroll', async ({ page, mockApp }, testInfo) => {
    test.skip(testInfo.project.name !== 'mobile-chrome', 'touch flows only validate phone layout')

    await mockApp({ admin: true })
    await page.goto('/watchlist', { waitUntil: 'networkidle' })

    const watchlistCard = page.locator('.mobile-stock-card').first()
    await expect(watchlistCard).toBeVisible()
    await watchlistCard.tap()
    await expect(page.locator('.decision-card .decision-title').filter({ hasText: '建仓建议' })).toBeVisible()

    await page.goto('/config', { waitUntil: 'networkidle' })
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))

    const mobileActionBar = page.locator('.mobile-action-bar')
    await expect(mobileActionBar).toBeVisible()
    await expect(mobileActionBar.getByRole('button', { name: '保存配置' })).toBeVisible()
    await expect(mobileActionBar.getByRole('button', { name: '保存并初始化' })).toBeVisible()
  })
})
