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
    entry_date: '2025-04-20',
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
    exit_plan: {
      action: 'wash_observe',
      target_progress: '接近P50',
      target_prices: {
        '20d': { p50: 10.8, p75: 11.2, p90: 11.8 },
        '10d': { p50: 10.6, p75: 10.9, p90: 11.1 },
      },
      risk_lines: {
        structure_line: 9.8,
        trailing_stop: 10.3,
        hard_stop: 9.6,
      },
      reason: '缩量回踩结构线',
      rules: ['守住结构线继续观察', '跌破移动止盈线减仓'],
    },
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
        'el-date-picker': { template: '<input class="el-date-picker" />', props: ['modelValue', 'type', 'valueFormat', 'placeholder'] },
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
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1200 })
    setActivePinia(createPinia())
    mockRouterPush.mockReset()
    vi.mocked(apiWatchlist.getAll).mockResolvedValue({ items: watchlistItems } as any)
    vi.mocked(apiWatchlist.add).mockResolvedValue(watchlistItems[0] as any)
    vi.mocked(apiWatchlist.update).mockResolvedValue(watchlistItems[0] as any)
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

  it('renders the selected entry date and keeps empty dates safe', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    await wrapper.vm.selectStock(watchlistItems[0])
    await flushPromises()

    expect(wrapper.text()).toContain('实际买入日')
    expect(wrapper.text()).toContain('2025-04-20')
    expect(wrapper.vm.formatEntryDate(null)).toBe('-')
    expect(wrapper.vm.formatEntryDate(undefined)).toBe('-')
  })

  it('renders entry dates in mobile watchlist cards', async () => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 375 })

    const wrapper = mountComponent()
    await flushPromises()
    await nextTick()

    const cards = wrapper.findAll('.mobile-stock-card')
    expect(cards).toHaveLength(2)
    expect(cards[0].text()).toContain('买入日期')
    expect(cards[0].text()).toContain('2025-04-20')
    expect(cards[1].text()).toContain('买入日期')
  })

  it('keeps the desktop watchlist as observation rows only', async () => {
    vi.mocked(apiWatchlist.getAll).mockResolvedValue({
      items: [
        {
          ...watchlistItems[0],
          derived: {
            exit_plan: {
              action_label: '继续持有',
              target_progress: '接近P50',
              target_prices: {
                '20d': { p50: 10.8, p75: 11.2, p90: 11.8 },
              },
              risk_lines: {
                structure_line: 9.8,
                trailing_stop: 10.3,
                hard_stop: 9.6,
              },
              reason: '守住结构线继续观察',
            },
          },
        },
      ],
    } as any)

    const wrapper = mountComponent()
    await flushPromises()
    await nextTick()

    const listText = wrapper.find('.list-card').text()
    expect(listText).toContain('编号')
    expect(listText).toContain('股名')
    expect(listText).toContain('成本')
    expect(listText).toContain('买入日')
    expect(listText).toContain('仓位')
    expect(listText).toContain('600000')
    expect(listText).toContain('浦发银行')
    expect(listText).not.toContain('P50')
    expect(listText).not.toContain('结构线')
    expect(listText).not.toContain('继续持有')
  })

  it('sends entry date when adding a watchlist item', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    Object.assign(wrapper.vm.addForm, {
      code: '600010',
      reason: '试仓',
      entryPrice: '12.3',
      entryDate: '2025-04-22',
      positionRatio: '40',
    })

    await wrapper.vm.addToWatchlist()
    await flushPromises()

    expect(apiWatchlist.add).toHaveBeenCalledWith('600010', '试仓', 0, 12.3, 0.4, '2025-04-22')
    expect(wrapper.vm.addForm.entryDate).toBe('')
  })

  it('prefills and saves entry date in the edit form', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.openEditDialog(watchlistItems[0])
    expect(wrapper.vm.editForm.entryDate).toBe('2025-04-20')

    wrapper.vm.editForm.entryDate = '2025-04-21'
    await wrapper.vm.saveEdit()
    await flushPromises()

    expect(apiWatchlist.update).toHaveBeenCalledWith(1, expect.objectContaining({
      entry_price: 10,
      entry_date: '2025-04-21',
      position_ratio: 0.3,
    }))
  })

  it('renders the latest exit plan in the selected stock detail', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    await wrapper.vm.selectStock(watchlistItems[0])
    await flushPromises()

    expect(wrapper.text()).toContain('持仓计划')
    expect(wrapper.text()).toContain('洗盘观察')
    expect(wrapper.text()).toContain('接近P50')
    expect(wrapper.text()).toContain('目标分位')
    expect(wrapper.text()).toContain('MFE 代表入场后曾经出现过的最大浮盈')
    expect(wrapper.text()).toContain('P50')
    expect(wrapper.text()).toContain('10.80')
    expect(wrapper.text()).toContain('P75')
    expect(wrapper.text()).toContain('11.20')
    expect(wrapper.text()).toContain('P90')
    expect(wrapper.text()).toContain('11.80')
    expect(wrapper.text()).toContain('结构')
    expect(wrapper.text()).toContain('9.80')
    expect(wrapper.text()).toContain('移动')
    expect(wrapper.text()).toContain('10.30')
    expect(wrapper.text()).toContain('止损')
    expect(wrapper.text()).toContain('9.60')
    expect(wrapper.text()).toContain('守住结构线继续观察')
  })

  it('renders the derived exit plan from the watchlist response before history exists', async () => {
    vi.mocked(apiWatchlist.getAll).mockResolvedValue({
      items: [
        {
          ...watchlistItems[0],
          derived: {
            exit_plan: {
              action: 'hold',
              action_label: '继续持有',
              target_prices: {
                '20d': { p50: 10.9, p75: 11.4, p90: 12.0 },
              },
              risk_lines: {
                hard_stop: 9.6,
              },
              reason: '来自观察池派生计划',
            },
          },
        },
      ],
    } as any)
    vi.mocked(apiWatchlist.getAnalysis).mockResolvedValue({ analyses: [] } as any)

    const wrapper = mountComponent()
    await flushPromises()

    await wrapper.vm.selectStock(wrapper.vm.watchlist[0])
    await flushPromises()

    expect(wrapper.text()).toContain('继续持有')
    expect(wrapper.text()).toContain('止损')
    expect(wrapper.text()).toContain('9.60')
    expect(wrapper.text()).toContain('来自观察池派生计划')
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
