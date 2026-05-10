import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import ElementPlus from 'element-plus'
import Watchlist from '@/views/Watchlist.vue'

const mockRouterPush = vi.fn()
const mockChart = {
  setOption: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn(),
}

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockRouterPush }),
}))

vi.mock('echarts/core', () => ({
  use: vi.fn(),
  init: vi.fn(() => mockChart),
}))

vi.mock('echarts/charts', () => ({
  CandlestickChart: {},
  LineChart: {},
}))

vi.mock('echarts/components', () => ({
  DataZoomComponent: {},
  GridComponent: {},
  TooltipComponent: {},
}))

vi.mock('echarts/renderers', () => ({
  CanvasRenderer: {},
}))

vi.mock('element-plus', async () => {
  const actual = await vi.importActual('element-plus')
  return {
    ...actual,
    ElMessage: {
      success: vi.fn(),
      error: vi.fn(),
      warning: vi.fn(),
      info: vi.fn(),
    },
  }
})

vi.mock('@/api', () => ({
  apiWatchlist: {
    getAll: vi.fn(),
    add: vi.fn(),
    delete: vi.fn(),
    update: vi.fn(),
    getAnalysis: vi.fn(),
    analyze: vi.fn(),
  },
  apiStock: {
    getKline: vi.fn(),
  },
  isRequestCanceled: vi.fn(() => false),
}))

import { ElMessage } from 'element-plus'
import { apiStock, apiWatchlist } from '@/api'

const watchlistItems = [
  {
    id: 1,
    code: '600000',
    name: '浦发银行',
    add_reason: '观察',
    entry_price: 10,
    position_ratio: 0.3,
    priority: 1,
    is_active: true,
    added_at: '2025-04-25T10:00:00Z',
  },
  {
    id: 2,
    code: '000001',
    name: '平安银行',
    add_reason: '跟踪',
    priority: 0,
    is_active: true,
    added_at: '2025-04-24T10:00:00Z',
  },
]

const analysisRows = [
  {
    id: 11,
    watchlist_id: 1,
    analysis_date: '2025-04-25T10:00:00Z',
    verdict: 'PASS',
    score: 4.5,
    buy_action: 'buy',
    hold_action: 'hold',
    risk_level: 'medium',
    buy_recommendation: '可试仓',
    hold_recommendation: '继续持有',
    risk_recommendation: '注意回撤',
    recommendation: '建议持有',
  },
]

const klineData = {
  code: '600000',
  name: '浦发银行',
  daily: [
    {
      date: '2025-04-24',
      open: 10,
      close: 10.2,
      low: 9.8,
      high: 10.3,
      volume: 10000,
      ma20: 10.1,
      ma60: 9.9,
    },
    {
      date: '2025-04-25',
      open: 10.2,
      close: 10.5,
      low: 10.1,
      high: 10.7,
      volume: 12000,
      ma20: 10.15,
      ma60: 10,
    },
  ],
}

const fullKlineData = {
  ...klineData,
  daily: [
    ...Array.from({ length: 118 }, (_, index) => ({
      date: `2025-01-${String((index % 28) + 1).padStart(2, '0')}`,
      open: 10,
      close: 10.1,
      low: 9.9,
      high: 10.3,
      volume: 10000,
      ma20: 10,
      ma60: 9.95,
    })),
    ...klineData.daily,
  ],
}

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

function mountComponent() {
  return mount(Watchlist, {
    global: {
      plugins: [ElementPlus, createPinia()],
      stubs: {
        'el-card': { template: '<div class="el-card"><slot name="header" /><slot /></div>' },
        'el-table': { template: '<div class="el-table" />', props: ['data'] },
        'el-table-column': true,
        'el-button': { template: '<button class="el-button" @click="$emit(\'click\')"><slot /></button>' },
        'el-dialog': { template: '<div class="el-dialog"><slot /><slot name="footer" /></div>' },
        'el-form': { template: '<form><slot /></form>' },
        'el-form-item': { template: '<div><slot /></div>' },
        'el-input': { template: '<input />' },
        'el-divider': { template: '<div class="el-divider" />' },
        'el-empty': { template: '<div class="el-empty">{{ description }}</div>', props: ['description'] },
        'el-tag': { template: '<span class="el-tag"><slot /></span>', props: ['type', 'size', 'effect'] },
        'el-row': { template: '<div><slot /></div>' },
        'el-col': { template: '<div><slot /></div>' },
        'el-tooltip': { template: '<div><slot /><slot name="content" /></div>' },
        'el-skeleton': { template: '<div class="el-skeleton" />' },
      },
    },
  })
}

describe('Watchlist.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
    window.sessionStorage.clear()
    setActivePinia(createPinia())
    mockRouterPush.mockReset()
    vi.mocked(apiWatchlist.getAll).mockResolvedValue({ items: watchlistItems } as any)
    vi.mocked(apiWatchlist.getAnalysis).mockResolvedValue({ analyses: analysisRows } as any)
    vi.mocked(apiWatchlist.analyze).mockResolvedValue({ status: 'ok' } as any)
    vi.mocked(apiWatchlist.delete).mockResolvedValue({ status: 'ok' } as any)
    vi.mocked(apiStock.getKline)
      .mockResolvedValueOnce(klineData as any)
      .mockResolvedValue(fullKlineData as any)
  })

  it('hydrates cached watchlist immediately and refreshes in background', async () => {
    window.localStorage.setItem('stocktrade:watchlist:state:guest', JSON.stringify({
      selectedStockId: 1,
      watchlist: watchlistItems,
      analysisHistory: analysisRows,
      trendData: { outlook: 'bullish', support: 9.8, resistance: 10.7 },
      cachedAt: Date.now(),
    }))

    const wrapper = mountComponent()

    expect(wrapper.vm.watchlist).toHaveLength(2)
    expect(wrapper.vm.selectedStock?.id).toBe(1)
    expect(wrapper.vm.analysisHistory).toHaveLength(1)

    await flushPromises()

    expect(apiWatchlist.getAll).toHaveBeenCalledTimes(1)
    expect(apiStock.getKline).toHaveBeenNthCalledWith(1, '600000', 60, false, expect.any(Object))
  })

  it('loads fresh list without blocking on detail restore when no cache exists', async () => {
    const wrapper = mountComponent()

    expect(wrapper.vm.isLoading).toBe(true)

    await flushPromises()
    await nextTick()

    expect(wrapper.vm.watchlist).toHaveLength(2)
    expect(wrapper.vm.isLoading).toBe(false)
    expect(wrapper.vm.selectedStock).toBeNull()
  })

  it('selects a stock, loads chart and analysis, then persists view state', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    await wrapper.vm.selectStock(watchlistItems[0])
    await flushPromises()

    expect(wrapper.vm.selectedStock?.id).toBe(1)
    expect(apiStock.getKline).toHaveBeenNthCalledWith(1, '600000', 60, false, expect.any(Object))
    expect(apiWatchlist.getAnalysis).toHaveBeenCalledWith(1, expect.any(Object))

    const saved = JSON.parse(window.localStorage.getItem('stocktrade:watchlist:state:guest') || '{}')
    expect(saved.selectedStockId).toBe(1)
    expect(saved.watchlist).toHaveLength(2)
  })

  it('clears selected detail state when the selected stock disappears after refresh', async () => {
    window.localStorage.setItem('stocktrade:watchlist:state:guest', JSON.stringify({
      selectedStockId: 1,
      watchlist: watchlistItems,
      analysisHistory: analysisRows,
      trendData: { outlook: 'bullish', support: 9.8, resistance: 10.7 },
      cachedAt: Date.now(),
    }))
    vi.mocked(apiWatchlist.getAll).mockResolvedValue({ items: [watchlistItems[1]] } as any)

    const wrapper = mountComponent()
    await flushPromises()
    await wrapper.vm.loadWatchlist()

    expect(wrapper.vm.selectedStock).toBeNull()
    expect(wrapper.vm.analysisHistory).toHaveLength(0)
    expect(wrapper.vm.trendData.outlook).toBe('neutral')
  })

  it('uses persistent chart cache before requesting fresh data', async () => {
    window.localStorage.setItem('stocktrade:watchlist:chart-cache', JSON.stringify({
      '600000': {
        code: '600000',
        days: 60,
        cachedAt: Date.now(),
        data: klineData,
      },
    }))

    const wrapper = mountComponent()
    await flushPromises()

    await wrapper.vm.selectStock(watchlistItems[0])
    await flushPromises()

    expect(apiStock.getKline).toHaveBeenCalledWith('600000', 120, false, expect.objectContaining({ timeoutMs: 20000 }))
  })

  it('formats MA values in chart tooltip with two decimals', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    await wrapper.vm.selectStock(watchlistItems[0])
    await flushPromises()

    const option = mockChart.setOption.mock.calls.at(-1)?.[0]
    const formatter = option?.tooltip?.formatter
    expect(typeof formatter).toBe('function')

    const html = formatter([
      { seriesName: 'K线', axisValue: '2025-04-25', data: [10.2, 10.5, 10.1, 10.7] },
      { seriesName: 'MA20', axisValue: '2025-04-25', data: 10.156 },
      { seriesName: 'MA60', axisValue: '2025-04-25', data: 9.995 },
    ])

    expect(html).toContain('MA20: 10.16')
    expect(html).toContain('MA60: 9.99')
    expect(html).toContain('开盘: 10.20')
    expect(html).toContain('收盘: 10.50')
  })

  it('removes the selected stock and reloads the list', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.selectedStock = watchlistItems[0]
    vi.mocked(apiWatchlist.getAll).mockResolvedValue({ items: [watchlistItems[1]] } as any)

    await wrapper.vm.removeStock(watchlistItems[0])
    await flushPromises()

    expect(apiWatchlist.delete).toHaveBeenCalledWith(1)
    expect(apiWatchlist.getAll).toHaveBeenCalledTimes(2)
    expect(wrapper.vm.selectedStock).toBeNull()
    expect(ElMessage.success).toHaveBeenCalledWith('已删除')
  })
})
