import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import ElementPlus from 'element-plus'
import Diagnosis from '@/views/Diagnosis.vue'

const mockPush = vi.fn()
const mockRoute = { query: {}, path: '/diagnosis' as const }
const echartsInstance = {
  setOption: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn(),
}

vi.mock('vue-router', () => ({
  useRoute: () => mockRoute,
  useRouter: () => ({ push: mockPush }),
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

vi.mock('echarts/core', () => ({
  use: vi.fn(),
  init: vi.fn(() => echartsInstance),
}))

vi.mock('echarts/charts', () => ({
  BarChart: {},
  CandlestickChart: {},
  LineChart: {},
}))

vi.mock('echarts/components', () => ({
  DataZoomComponent: {},
  GridComponent: {},
  LegendComponent: {},
  TooltipComponent: {},
}))

vi.mock('echarts/renderers', () => ({
  CanvasRenderer: {},
}))

vi.mock('@/api', () => ({
  apiAnalysis: {
    getDiagnosisHistory: vi.fn(),
    getHistoryStatus: vi.fn(),
    refreshHistory: vi.fn(),
    analyze: vi.fn(),
  },
  apiStock: {
    getInfo: vi.fn(),
    getKline: vi.fn(),
  },
  apiWatchlist: {
    getAll: vi.fn(),
    add: vi.fn(),
  },
  apiConfig: {
    getTushareStatus: vi.fn(),
    getAll: vi.fn(),
    verifyTushare: vi.fn(),
    update: vi.fn(),
    saveEnv: vi.fn(),
  },
  isRequestCanceled: vi.fn(() => false),
}))

import { ElMessage } from 'element-plus'
import { apiAnalysis, apiConfig, apiStock, apiWatchlist } from '@/api'

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

const mockKline = {
  daily: [
    { date: '2024-01-15', open: 10, close: 10.5, low: 9.8, high: 10.8, volume: 1000, ma5: 10.2, ma10: 10.1, ma20: 10.0 },
  ],
  weekly: [],
}

const mockFullKline = {
  daily: Array.from({ length: 120 }, (_, index) => ({
    date: `2024-01-${String((index % 28) + 1).padStart(2, '0')}`,
    open: 10,
    close: 10.5,
    low: 9.8,
    high: 10.8,
    volume: 1000,
    ma5: 10.2,
    ma10: 10.1,
    ma20: 10.0,
  })),
  weekly: [],
}

const mockHistory = [
  { check_date: '2024-01-15', close_price: 10.5, change_pct: 2.5, kdj_j: 45.2, b1_passed: true, score: 4.2, verdict: 'PASS' },
]

const mockAnalyzeResponse = {
  name: '浦发银行',
  score: 4.8,
  b1_passed: true,
  verdict: 'PASS',
  analysis: {
    signal_type: 'trend_start',
    signal_reasoning: '趋势启动',
    comment: '结构良好',
    kdj_j: 45.2,
    zx_long_pos: true,
    weekly_ma_aligned: true,
    volume_healthy: true,
    scores: {
      trend_structure: 4.5,
      price_position: 4.0,
      volume_behavior: 5.0,
      previous_abnormal_move: 3.5,
    },
    trend_reasoning: '趋势向上',
    position_reasoning: '位置合理',
    volume_reasoning: '量能健康',
    abnormal_move_reasoning: '历史异动可控',
  },
}

function mockStatus({ ready = true, initialized = true } = {}) {
  vi.mocked(apiConfig.getTushareStatus).mockResolvedValue({
    configured: ready,
    available: ready,
    message: ready ? 'Token有效' : '请配置 Token',
    data_status: {
      raw_data: { exists: initialized, count: 3200, latest_date: '2025-04-25' },
      candidates: { exists: initialized, count: 50, latest_date: '2025-04-25' },
      analysis: { exists: initialized, count: 20, latest_date: '2025-04-25' },
      kline: { exists: true, count: 100, latest_date: '2025-04-25' },
    },
  } as any)
}

function mountComponent() {
  return mount(Diagnosis, {
    global: {
      plugins: [ElementPlus, createPinia()],
      stubs: {
        'el-row': { template: '<div><slot /></div>' },
        'el-col': { template: '<div><slot /></div>' },
        'el-card': { template: '<div><slot name="header" /><slot /></div>' },
        'el-form': { template: '<form><slot /></form>' },
        'el-form-item': { template: '<div><slot /></div>' },
        'el-input': { template: '<input />' },
        'el-button': { template: '<button @click="$emit(\'click\')"><slot /></button>' },
        'el-radio-group': { template: '<div><slot /></div>' },
        'el-radio-button': { template: '<button><slot /></button>' },
        'el-tag': { template: '<span><slot /></span>' },
        'el-divider': { template: '<hr />' },
        'el-table': { template: '<div><slot /></div>' },
        'el-table-column': true,
        'el-empty': { template: '<div class="el-empty">{{ description }}<slot /></div>', props: ['description'] },
        'el-alert': { template: '<div class="el-alert">{{ description }}</div>', props: ['description'] },
        'el-tooltip': { template: '<div><slot /></div>' },
        'el-icon': { template: '<i><slot /></i>' },
      },
    },
  })
}

describe('Diagnosis.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.sessionStorage.clear()
    window.localStorage.clear()
    mockPush.mockReset()
    mockRoute.query = {}
    setActivePinia(createPinia())
    mockStatus()
    vi.mocked(apiStock.getInfo).mockResolvedValue({ code: '600000', name: '浦发银行' } as any)
    vi.mocked(apiStock.getKline)
      .mockResolvedValueOnce(mockKline as any)
      .mockResolvedValue(mockFullKline as any)
    vi.mocked(apiWatchlist.getAll).mockResolvedValue({ items: [] } as any)
    vi.mocked(apiWatchlist.add).mockResolvedValue({} as any)
    vi.mocked(apiAnalysis.getDiagnosisHistory).mockResolvedValue({ history: mockHistory } as any)
    vi.mocked(apiAnalysis.getHistoryStatus).mockResolvedValue({ generating: false } as any)
    vi.mocked(apiAnalysis.refreshHistory).mockResolvedValue({ status: 'ok' } as any)
    vi.mocked(apiAnalysis.analyze).mockResolvedValue(mockAnalyzeResponse as any)
  })

  it('warns when searching without a stock code after status is ready', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    await wrapper.vm.searchStock(1)

    expect(ElMessage.warning).toHaveBeenCalledWith('请输入股票代码')
  })

  it('blocks search-and-analyze when initialization is incomplete', async () => {
    mockStatus({ ready: true, initialized: false })
    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.searchForm.code = '600000'
    await wrapper.vm.searchAndAnalyze()

    expect(ElMessage.info).toHaveBeenCalledWith('请先完成首次初始化')
    expect(apiStock.getInfo).not.toHaveBeenCalled()
    expect(apiAnalysis.analyze).not.toHaveBeenCalled()
  })

  it('runs the current search chain and analysis against the latest APIs', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.searchForm.code = '600000'
    await wrapper.vm.searchAndAnalyze()
    await flushPromises()

    expect(apiStock.getInfo).toHaveBeenCalledWith('600000', expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(apiWatchlist.getAll).toHaveBeenCalledWith(expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(apiStock.getKline).toHaveBeenNthCalledWith(1, '600000', 60, false, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(apiAnalysis.getDiagnosisHistory).toHaveBeenCalledWith('600000', 30, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(apiAnalysis.analyze).toHaveBeenCalledWith('600000', expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it('uses persistent diagnosis chart cache before requesting the full 120-day chart', async () => {
    window.localStorage.setItem('stocktrade:diagnosis:chart-cache', JSON.stringify({
      '600000': {
        code: '600000',
        days: 60,
        cachedAt: Date.now(),
        data: mockKline,
      },
    }))

    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.searchForm.code = '600000'
    await wrapper.vm.searchAndAnalyze()
    await flushPromises()

    expect(apiStock.getKline).toHaveBeenCalledWith('600000', 120, false, expect.objectContaining({ timeoutMs: 20000 }))
  })

  it('maps analysis fields into the view model and emits success feedback', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.stockCode = '600000'
    await wrapper.vm.analyzeStock()

    expect(wrapper.vm.analysisResult.score).toBe(4.8)
    expect(wrapper.vm.analysisResult.signal_type).toBe('trend_start')
    expect(wrapper.vm.analysisResult.scores.trend_structure).toBe(4.5)
    expect(ElMessage.success).toHaveBeenCalledWith('分析完成')
  })

  it('adds the current stock to watchlist with a diagnosis-based reason', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.stockCode = '600000'
    wrapper.vm.stockName = '浦发银行'
    wrapper.vm.analysisResult = {
      verdict: 'PASS',
      score: 4.8,
    }

    await wrapper.vm.addCurrentToWatchlist()

    expect(apiWatchlist.add).toHaveBeenCalledWith('600000', '诊断结论:PASS | 评分:4.8')
    expect(ElMessage.success).toHaveBeenCalled()
  })

  it('routes users to the task center when initialization is required', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.goTaskCenter()

    expect(mockPush).toHaveBeenCalledWith('/update')
  })
})
