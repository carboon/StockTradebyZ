import { test, expect } from './fixtures'

test.describe('desktop regression baseline', () => {
  test('desktop TomorrowStar keeps table layout', async ({ page, mockApp }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop-chrome', 'desktop regression only validates desktop project')

    await mockApp({ admin: true })
    await page.goto('/tomorrow-star', { waitUntil: 'networkidle' })

    await expect(page.getByText('历史记录')).toBeVisible()
    await expect(page.locator('.candidates-card .card-header .title-section').filter({ hasText: '候选股票' })).toBeVisible()
    await expect(page.locator('.el-table')).toHaveCount(3)
  })

  test('desktop Diagnosis keeps range switch buttons', async ({ page, mockApp }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop-chrome', 'desktop regression only validates desktop project')

    await mockApp({ admin: true })
    await page.goto('/diagnosis?code=000001', { waitUntil: 'networkidle' })

    await expect(page.getByRole('button', { name: '30天' })).toBeVisible()
    await expect(page.getByRole('button', { name: '60天' })).toBeVisible()
    await expect(page.getByText('B1检查详情')).toBeVisible()
  })
})
