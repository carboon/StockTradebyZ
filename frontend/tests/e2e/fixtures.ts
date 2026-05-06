import { expect, test as base, type Page } from '@playwright/test'

type MockOptions = {
  admin?: boolean
}

const user = {
  id: 1,
  username: 'playwright-admin',
  display_name: 'Playwright Admin',
  role: 'admin',
  is_active: true,
  created_at: '2026-05-01T09:00:00',
  daily_quota: 5000,
}

function buildTomorrowCandidates() {
  return [
    { id: 1, pick_date: '2026-05-05', code: '000001', name: '平安银行', close_price: 12.35, change_pct: 2.4, kdj_j: 15.2 },
    { id: 2, pick_date: '2026-05-05', code: '600036', name: '招商银行', close_price: 44.21, change_pct: 1.3, kdj_j: 18.5 },
    { id: 3, pick_date: '2026-05-05', code: '300750', name: '宁德时代', close_price: 203.4, change_pct: 3.2, kdj_j: 21.1 },
    { id: 4, pick_date: '2026-05-05', code: '002594', name: '比亚迪', close_price: 245.8, change_pct: 2.7, kdj_j: 19.4 },
    { id: 5, pick_date: '2026-05-05', code: '600519', name: '贵州茅台', close_price: 1620.5, change_pct: 1.1, kdj_j: 16.8 },
  ]
}

function buildTomorrowResults() {
  return [
    { id: 11, pick_date: '2026-05-05', code: '000001', verdict: 'PASS', total_score: 4.8, signal_type: 'trend_start', comment: '量价同步改善' },
    { id: 12, pick_date: '2026-05-05', code: '600036', verdict: 'PASS', total_score: 4.6, signal_type: 'trend_start', comment: '结构稳定向上' },
    { id: 13, pick_date: '2026-05-05', code: '300750', verdict: 'WATCH', total_score: 4.5, signal_type: 'watch', comment: '回踩后量能修复' },
    { id: 14, pick_date: '2026-05-05', code: '002594', verdict: 'WATCH', total_score: 4.4, signal_type: 'watch', comment: '趋势延续，等待确认' },
    { id: 15, pick_date: '2026-05-05', code: '600519', verdict: 'WATCH', total_score: 4.3, signal_type: 'watch', comment: '高位强势震荡' },
  ]
}

async function mockApi(page: Page, options: MockOptions = {}) {
  const isAdmin = options.admin ?? true

  await page.route('**/api/health', async route => {
    await route.fulfill({ json: { status: 'ok' } })
  })

  await page.route('**/api/v1/auth/me', async route => {
    await route.fulfill({
      json: {
        ...user,
        role: isAdmin ? 'admin' : 'user',
      },
    })
  })

  await page.route('**/api/v1/config/tushare-status', async route => {
    await route.fulfill({
      json: {
        configured: true,
        available: true,
        message: 'mocked',
        data_status: {
          raw_data: { exists: true, is_latest: true, latest_trade_date: '2026-05-05' },
          candidates: { exists: true, latest_trade_date: '2026-05-05' },
          analysis: { exists: true, latest_trade_date: '2026-05-05' },
        },
      },
    })
  })

  await page.route('**/api/v1/tasks/running', async route => {
    await route.fulfill({ json: { tasks: [], total: 0 } })
  })

  await page.route('**/api/v1/tasks/incremental-status', async route => {
    await route.fulfill({
      json: {
        running: false,
        status: 'idle',
        progress: 0,
        current: 0,
        total: 0,
        current_code: '',
        updated_count: 0,
        skipped_count: 0,
        failed_count: 0,
        message: '',
      },
    })
  })

  await page.route('**/api/v1/analysis/tomorrow-star/freshness', async route => {
    await route.fulfill({
      json: {
        latest_trade_date: '2026-05-05',
        latest_trade_data_ready: true,
        local_latest_date: '2026-05-05',
        latest_candidate_date: '2026-05-05',
        latest_result_date: '2026-05-05',
        needs_update: false,
        freshness_version: 'mock-v1',
        running_task_id: null,
        running_task_status: null,
        incremental_update: {
          running: false,
          status: 'idle',
          progress: 0,
          current: 0,
          total: 0,
          updated_count: 0,
          skipped_count: 0,
          failed_count: 0,
          message: '',
        },
      },
    })
  })

  await page.route('**/api/v1/analysis/tomorrow-star/dates', async route => {
    await route.fulfill({
      json: {
        dates: ['2026-05-05', '2026-05-04'],
        history: [
          { date: '2026-05-05', count: 18, pass: 5, status: 'ready' },
          { date: '2026-05-04', count: 16, pass: 4, status: 'ready' },
        ],
      },
    })
  })

  await page.route('**/api/v1/analysis/tomorrow-star/candidates**', async route => {
    await route.fulfill({
      json: {
        pick_date: '2026-05-05',
        candidates: buildTomorrowCandidates(),
        total: 5,
      },
    })
  })

  await page.route('**/api/v1/analysis/tomorrow-star/results**', async route => {
    await route.fulfill({
      json: {
        pick_date: '2026-05-05',
        results: buildTomorrowResults(),
        total: 5,
        min_score_threshold: 3.5,
      },
    })
  })

  await page.route('**/api/v1/stock/search**', async route => {
    await route.fulfill({
      json: {
        items: [
          { code: '000001', name: '平安银行' },
        ],
        total: 1,
      },
    })
  })

  await page.route('**/api/v1/stock/000001', async route => {
    await route.fulfill({
      json: {
        code: '000001',
        name: '平安银行',
        industry: '银行',
        market: 'SZ',
      },
    })
  })

  await page.route('**/api/v1/stock/kline', async route => {
    const body = route.request().postDataJSON() as { code?: string; days?: number } | null
    const days = body?.days ?? 30
    const baseDate = new Date('2026-05-05T00:00:00Z')
    const items = Array.from({ length: days }, (_, index) => {
      const current = new Date(baseDate)
      current.setUTCDate(baseDate.getUTCDate() - (days - index - 1))
      const open = 10 + index * 0.1
      return {
        date: current.toISOString().slice(0, 10),
        open,
        close: open + 0.2,
        high: open + 0.5,
        low: open - 0.3,
        volume: 100000 + index * 1000,
        ma5: open + 0.1,
        ma10: open,
        ma20: open - 0.1,
        ma60: open - 0.2,
      }
    })

    await route.fulfill({
      json: {
        code: body?.code || '000001',
        name: '平安银行',
        daily: items,
        weekly: [],
      },
    })
  })

  await page.route('**/api/v1/analysis/diagnosis/000001/history-status', async route => {
    await route.fulfill({
      json: {
        exists: true,
        generating: false,
        count: 1,
        total: 1,
        generated_at: '2026-05-05T15:00:00',
      },
    })
  })

  await page.route('**/api/v1/analysis/diagnosis/000001/history', async route => {
    await route.fulfill({
      json: {
        code: '000001',
        name: '平安银行',
        history: [
          {
            check_date: '2026-05-05',
            close_price: 12.35,
            change_pct: 2.4,
            b1_passed: true,
            verdict: 'PASS',
            comment: '趋势启动',
            score: 4.8,
            signal_type: 'trend_start',
          },
        ],
        total: 1,
        data_ready: true,
      },
    })
  })

  await page.route('**/api/v1/analysis/diagnosis/analyze', async route => {
    await route.fulfill({
      json: {
        status: 'pending',
        task_id: 11,
        code: '000001',
        ws_url: '/ws/tasks/11',
        message: '分析任务已创建',
      },
    })
  })

  await page.route('**/api/v1/analysis/diagnosis/000001/result', async route => {
    await route.fulfill({
      json: {
        code: '000001',
        name: '平安银行',
        status: 'completed',
        score: 4.8,
        b1_passed: true,
        verdict: 'PASS',
        analysis: {
          comment: '趋势启动，等待确认',
          kdj_j: 15.2,
          zx_long_pos: true,
          weekly_ma_aligned: true,
          volume_healthy: true,
          signal_type: 'trend_start',
          signal_reasoning: '量能改善，结构转强',
          scores: {
            trend_structure: 5,
            price_position: 4,
            volume_behavior: 5,
            previous_abnormal_move: 4,
          },
          trend_reasoning: '趋势向上',
          position_reasoning: '价格位置合理',
          volume_reasoning: '量能配合',
          abnormal_move_reasoning: '历史异动改善',
        },
      },
    })
  })

  await page.route('**/api/v1/watchlist/', async route => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        json: {
          items: [
            {
              id: 1,
              code: '000001',
              name: '平安银行',
              entry_price: 11.9,
              position_ratio: 0.3,
              add_reason: '趋势转强',
              priority: 0,
              is_active: true,
              added_at: '2026-05-01T09:00:00',
            },
          ],
          total: 1,
        },
      })
      return
    }

    await route.fulfill({ json: { success: true } })
  })

  await page.route('**/api/v1/watchlist/*/analysis', async route => {
    await route.fulfill({
      json: {
        code: '000001',
        analyses: [
          {
            id: 10,
            watchlist_id: 1,
            analysis_date: '2026-05-05',
            verdict: 'PASS',
            score: 4.5,
            risk_level: 'medium',
            buy_action: 'wait',
            hold_action: 'hold',
            recommendation: '继续观察',
            buy_recommendation: '等待回踩',
            hold_recommendation: '持仓跟踪',
            risk_recommendation: '跌破支撑减仓',
          },
        ],
        total: 1,
      },
    })
  })

  await page.route('**/api/v1/config/', async route => {
    const method = route.request().method()
    if (method === 'GET') {
      await route.fulfill({
        json: {
          configs: [
            { key: 'tushare_token', value: 'mock-token' },
            { key: 'default_reviewer', value: 'quant' },
            { key: 'min_score_threshold', value: '3.5' },
          ],
        },
      })
      return
    }

    await route.fulfill({ json: { key: 'mock', value: 'ok' } })
  })

  await page.route('**/api/v1/tasks/diagnostics', async route => {
    await route.fulfill({
      json: {
        generated_at: '2026-05-05T15:00:00',
        checks: [],
        running_tasks: [],
        latest_failed_task: null,
        latest_completed_task: null,
        environment: [],
        data_status: {
          raw_data: { exists: true, latest_trade_date: '2026-05-05', is_latest: true },
          candidates: { exists: true, count: 5, latest_date: '2026-05-05' },
          analysis: { exists: true, count: 5, latest_date: '2026-05-05' },
          kline: { exists: true, count: 300, latest_date: '2026-05-05' },
        },
      },
    })
  })

  await page.route('**/api/**', async route => {
    await route.fulfill({ json: {} })
  })
}

type Fixtures = {
  mockApp: (options?: MockOptions) => Promise<void>
}

export const test = base.extend<Fixtures>({
  mockApp: async ({ page }, use) => {
    await page.addInitScript(() => {
      window.localStorage.setItem('stocktrade_token', 'playwright-token')
    })

    await use(async options => {
      await mockApi(page, options)
    })
  },
})

export { expect }
