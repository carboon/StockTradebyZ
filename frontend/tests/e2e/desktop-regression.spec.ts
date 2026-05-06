import { test, expect } from './fixtures'

test.describe('desktop regression baseline', () => {
  test('desktop TomorrowStar keeps table layout', async ({ page, mockApp, isMobile }) => {
    test.skip(isMobile, 'desktop regression only validates desktop project')

    await mockApp({ admin: true })
    await page.goto('/tomorrow-star')

    await expect(page.getByText('历史记录')).toBeVisible()
    await expect(page.getByText('候选列表')).toBeVisible()
    await expect(page.locator('.el-table')).toHaveCount(3)
  })

  test('desktop Diagnosis keeps range switch buttons', async ({ page, mockApp, isMobile }) => {
    test.skip(isMobile, 'desktop regression only validates desktop project')

    await mockApp({ admin: true })
    await page.goto('/diagnosis?code=000001')

    await expect(page.getByRole('button', { name: '30天' })).toBeVisible()
    await expect(page.getByRole('button', { name: '60天' })).toBeVisible()
    await expect(page.getByText('B1检查详情')).toBeVisible()
  })
})
