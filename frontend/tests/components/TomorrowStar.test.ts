import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import TomorrowStar from '@/views/TomorrowStar.vue'

const mockPush = vi.fn()

vi.mock('vue-router', () => ({
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

vi.mock('@/api', () => ({
  apiConfig: {
    getTushareStatus: vi.fn(),
    getAll: vi.fn(),
    verifyTushare: vi.fn(),
    update: vi.fn(),
    saveEnv: vi.fn(),
  },
  apiAnalysis: {
    getFreshness: vi.fn(),
    getDates: vi.fn(),
    getCandidates: vi.fn(),
    getResults: vi.fn(),
    generate: vi.fn(),
    getCurrentHotDates: vi.fn(),
    getCurrentHotCandidates: vi.fn(),
    getCurrentHotResults: vi.fn(),
    getMiddayStatus: vi.fn(),
    getMiddayCurrent: vi.fn(),
    generateMidday: vi.fn(),
    refreshMidday: vi.fn(),
    getCurrentHotMiddayStatus: vi.fn(),
    getCurrentHotMiddayCurrent: vi.fn(),
    generateCurrentHotMidday: vi.fn(),
    refreshCurrentHotMidday: vi.fn(),
  },
  apiTasks: {
    startIncrementalUpdate: vi.fn(),
    getIncrementalStatus: vi.fn(),
  },
  isRequestCanceled: vi.fn(() => false),
}))

import { ElMessage } from 'element-plus'
import { apiAnalysis, apiConfig, apiTasks } from '@/api'

async function flushPromises() {
  for (let i = 0; i < 8; i += 1) {
    await Promise.resolve()
  }
}

function mockStatus({ initialized = true } = {}) {
  vi.mocked(apiConfig.getTushareStatus).mockResolvedValue({
    configured: true,
    available: true,
    message: 'Token有效',
    data_status: {
      raw_data: { exists: initialized, count: 3200, latest_date: '2025-04-25' },
      candidates: { exists: initialized, count: 30, latest_date: '2025-04-25' },
      analysis: { exists: initialized, count: 20, latest_date: '2025-04-25' },
      kline: { exists: true, count: 100, latest_date: '2025-04-25' },
    },
  } as any)
}

const latestCandidates = [
  { code: '600000', name: '浦发银行', kdj_j: 25, close_price: 10.5 },
  { code: '000001', name: '平安银行', kdj_j: 12, close_price: 12.2 },
]

const latestResults = [
  { code: 'A', verdict: 'WATCH', total_score: 4.6, signal_type: 'rebound', comment: '1', prefilter_passed: false, prefilter_summary: '中证 500 / 创业板指环境未达标', prefilter_blocked_by: ['market_regime'] },
  { code: 'B', verdict: 'PASS', total_score: 4.2, signal_type: 'trend_start', comment: '2', prefilter_passed: true },
  { code: 'C', verdict: 'PASS', total_score: 5.0, signal_type: 'trend_start', comment: '3', prefilter_passed: true },
  { code: 'D', verdict: 'FAIL', total_score: 4.9, signal_type: 'distribution_risk', comment: '4', prefilter_passed: false, prefilter_summary: '申万一级行业强度不在前 30%', prefilter_blocked_by: ['industry_strength'] },
]

const currentHotCandidates = [
  { code: '688001', name: '华兴源创', kdj_j: 15, close_price: 28.5, board_name: '半导体设备', b1_passed: true },
  { code: '600001', name: '示例热盘', kdj_j: 12, close_price: 11.2, board_name: '券商', b1_passed: false },
]

const currentHotResults = [
  { code: '688001', verdict: 'PASS', total_score: 4.9, signal_type: 'trend_start', comment: 'a', b1_passed: true },
  { code: '600001', verdict: 'PASS', total_score: 4.8, signal_type: 'trend_start', comment: 'b', b1_passed: false },
  { code: '000002', verdict: 'WATCH', total_score: 4.7, signal_type: 'rebound', comment: 'c', b1_passed: false },
  { code: '300003', verdict: 'WATCH', total_score: 4.6, signal_type: 'rebound', comment: 'd', b1_passed: false },
  { code: '002004', verdict: 'FAIL', total_score: 4.5, signal_type: 'distribution_risk', comment: 'e', b1_passed: false },
  { code: '688005', verdict: 'WATCH', total_score: 4.4, signal_type: 'rebound', comment: 'f', b1_passed: false },
]

function buildIncrementalStatus(overrides: Record<string, unknown> = {}) {
  return {
    status: 'idle',
    running: false,
    progress: 0,
    current: 0,
    total: 0,
    current_code: '',
    updated_count: 0,
    skipped_count: 0,
    failed_count: 0,
    started_at: '',
    completed_at: '',
    eta_seconds: null,
    elapsed_seconds: 0,
    resume_supported: true,
    initial_completed: 0,
    completed_in_run: 0,
    checkpoint_path: null,
    last_error: null,
    message: '',
    ...overrides,
  }
}

function mountComponent() {
  return mount(TomorrowStar, {
    global: {
      plugins: [ElementPlus, createPinia()],
      stubs: {
        'el-tabs': { template: '<div><slot /></div>', props: ['modelValue'] },
        'el-tab-pane': { template: '<div><slot /></div>' },
        'el-row': { template: '<div><slot /></div>' },
        'el-col': { template: '<div><slot /></div>' },
        'el-card': { template: '<div><slot name="header" /><slot /></div>' },
        'el-table': { template: '<div><slot /></div>' },
        'el-table-column': true,
        'el-button': { template: '<button @click="$emit(\'click\')"><slot /></button>' },
        'el-tag': { template: '<span><slot /></span>' },
        'el-radio-group': { template: '<div><slot /></div>', props: ['modelValue'] },
        'el-radio-button': { template: '<span><slot /></span>', props: ['value'] },
        'el-divider': { template: '<hr />' },
        'el-alert': { template: '<div class="el-alert">{{ description }}</div>', props: ['description'] },
        'el-empty': { template: '<div class="el-empty"><slot />{{ description }}</div>', props: ['description'] },
        'el-progress': { template: '<div class="el-progress" />' },
        'el-pagination': { template: '<div class="el-pagination" />' },
        'el-icon': { template: '<i><slot /></i>' },
      },
    },
  })
}

describe('TomorrowStar.vue', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2024-01-15T00:30:00Z'))
    vi.clearAllMocks()
    window.sessionStorage.clear()
    mockPush.mockReset()
    setActivePinia(createPinia())
    mockStatus()
    vi.mocked(apiAnalysis.getDates).mockResolvedValue({
      dates: ['2024-01-15', '2024-01-14'],
      history: [
        { date: '2024-01-15', count: 2, pass: 1 },
        { date: '2024-01-14', count: 1, pass: 0 },
      ],
    } as any)
    vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({
      pick_date: '2024-01-15',
      candidates: latestCandidates,
    } as any)
    vi.mocked(apiAnalysis.getResults).mockResolvedValue({
      results: latestResults,
    } as any)
    vi.mocked(apiAnalysis.getCurrentHotDates).mockResolvedValue({
      dates: ['2024-01-15', '2024-01-14'],
      history: [
        { date: '2024-01-15', count: 6, pass: 2 },
        { date: '2024-01-14', count: 4, pass: 1 },
      ],
    } as any)
    vi.mocked(apiAnalysis.getCurrentHotCandidates).mockResolvedValue({
      pick_date: '2024-01-15',
      candidates: currentHotCandidates,
    } as any)
    vi.mocked(apiAnalysis.getCurrentHotResults).mockResolvedValue({
      results: currentHotResults,
    } as any)
    vi.mocked(apiAnalysis.getFreshness).mockResolvedValue({
      latest_trade_date: '2024-01-15',
      latest_trade_data_ready: false,
      local_latest_date: '2024-01-15',
      latest_candidate_date: '2024-01-15',
      latest_result_date: '2024-01-15',
      needs_update: false,
      freshness_version: 'v1',
      running_task_id: null,
      running_task_status: null,
      incremental_update: buildIncrementalStatus(),
    } as any)
    vi.mocked(apiAnalysis.getMiddayStatus).mockResolvedValue({
      has_data: true,
      status: 'ready',
      trade_date: '2024-01-15',
      snapshot_time: '2024-01-15T12:30:00',
      source_pick_date: '2024-01-15',
    } as any)
    vi.mocked(apiAnalysis.getMiddayCurrent).mockResolvedValue({
      has_data: true,
      status: 'ready',
      trade_date: '2024-01-15',
      snapshot_time: '2024-01-15T12:30:00',
      source_pick_date: '2024-01-15',
      items: [{ code: '600000', name: '浦发银行', b1_passed: true, verdict: 'PASS', signal_type: 'trend_start', score: 4.6 }],
      total: 1,
    } as any)
    vi.mocked(apiAnalysis.getCurrentHotMiddayStatus).mockResolvedValue({
      has_data: true,
      status: 'ready',
      trade_date: '2024-01-15',
      snapshot_time: '2024-01-15T13:00:00',
      source_pick_date: '2024-01-15',
    } as any)
    vi.mocked(apiAnalysis.getCurrentHotMiddayCurrent).mockResolvedValue({
      has_data: true,
      status: 'ready',
      trade_date: '2024-01-15',
      snapshot_time: '2024-01-15T13:00:00',
      source_pick_date: '2024-01-15',
      items: [{ code: '688001', name: '华兴源创', b1_passed: true, verdict: 'PASS', signal_type: 'trend_start', score: 4.9 }],
      total: 1,
    } as any)
    vi.mocked(apiTasks.getIncrementalStatus).mockResolvedValue(buildIncrementalStatus() as any)
    vi.mocked(apiTasks.startIncrementalUpdate).mockResolvedValue({
      success: true,
      running: false,
      message: 'started',
    } as any)
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it('loads history and latest candidate/result data on mount', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.historyData).toHaveLength(2)
    expect(wrapper.vm.latestCandidates).toHaveLength(2)
    expect(wrapper.vm.latestAnalysisResults).toHaveLength(4)
    expect(wrapper.vm.latestDate).toBe('2024-01-15')
    expect(apiAnalysis.getCandidates).toHaveBeenCalledWith(undefined, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(apiAnalysis.getResults).toHaveBeenCalledWith(undefined, expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it('shows market regime explanation when tomorrow-star candidates are blocked by market conditions', async () => {
    vi.mocked(apiAnalysis.getDates).mockResolvedValue({
      dates: ['2024-01-15'],
      history: [
        {
          date: '2024-01-15',
          count: 0,
          pass: 0,
          status: 'market_regime_blocked',
          market_regime_blocked: true,
          market_regime_info: {
            summary: '中证 500 / 创业板指环境未达标',
            details: [
              { name: 'CSI500', close: 7800, ema_fast: 7839.85, ema_slow: 7921.66, return_lookback: -0.0601 },
              { name: 'CHINEXT', close: 2000, ema_fast: 1980, ema_slow: 1990, return_lookback: -0.0078 },
            ],
          },
        },
      ],
    } as any)
    vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({
      candidates: [],
      total: 0,
    } as any)
    vi.mocked(apiAnalysis.getResults).mockResolvedValue({
      results: [],
      total: 0,
      min_score_threshold: 4,
    } as any)

    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.showTomorrowStarMarketRegimeNotice).toBe(true)
    expect(wrapper.text()).toContain('今日未展示候选股票')
    expect(wrapper.text()).toContain('中证 500 / 创业板指环境未达标')
    expect(wrapper.text()).toContain('CSI500：收盘点位 7800.00 低于短期均线 7839.85')
    expect(wrapper.text()).toContain('CHINEXT：短期均线 1980.00 未站上长期均线 1990.00')
  })

  it('sorts top analysis results by trend_start first, then score', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    const codes = wrapper.vm.topAnalysisResults.map((item: { code: string }) => item.code)
    expect(codes).toEqual(['C', 'B', 'D', 'A'])
  })

  it('prefers result names over stale candidate names', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.latestCandidates = [{ code: '600000', name: '海王生物' }]
    expect(wrapper.vm.getAnalysisResultName({ code: '600000', name: 'ST海王' })).toBe('ST海王')
    expect(wrapper.vm.getAnalysisResultName({ code: '999999' })).toBe('999999')
  })

  it('returns prefilter label and summary for tomorrow-star analysis rows', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.getAnalysisPrefilterLabel(wrapper.vm.latestAnalysisResults[0].prefilter_passed)).toBe('否')
    expect(wrapper.vm.getAnalysisPrefilterSummary(wrapper.vm.latestAnalysisResults[0])).toBe('中证 500 / 创业板指环境未达标')
    expect(wrapper.vm.getAnalysisPrefilterLabel(wrapper.vm.latestAnalysisResults[1].prefilter_passed)).toBe('是')
  })

  it('loads date-specific candidates and results when selecting a history row', async () => {
    vi.mocked(apiAnalysis.getCandidates)
      .mockResolvedValueOnce({ pick_date: '2024-01-15', candidates: latestCandidates } as any)
      .mockResolvedValueOnce({ pick_date: '2024-01-14', candidates: [{ code: '300001', kdj_j: 10 }] } as any)
    vi.mocked(apiAnalysis.getResults)
      .mockResolvedValueOnce({ results: latestResults } as any)
      .mockResolvedValueOnce({ results: [{ code: '300001', verdict: 'WATCH', total_score: 3.8 }] } as any)

    const wrapper = mountComponent()
    await flushPromises()

    await wrapper.vm.selectDate({ rawDate: '2024-01-14', date: '2024-01-14', count: 1, pass: 0, status: 'success' })
    await flushPromises()

    expect(wrapper.vm.selectedDate).toBe('2024-01-14')
    expect(wrapper.vm.latestDataDate).toBe('2024-01-14')
    expect(wrapper.vm.latestCandidates[0].code).toBe('300001')
    expect(apiAnalysis.getCandidates).toHaveBeenLastCalledWith('2024-01-14', expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(apiAnalysis.getResults).toHaveBeenLastCalledWith('2024-01-14', expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it('passes tomorrow-star mobile query params when opening diagnosis', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.viewStock('600000')

    expect(mockPush).toHaveBeenCalledWith({
      path: '/diagnosis',
      query: { code: '600000', source: 'tomorrow-star', days: '30' },
    })
  })

  it('does not auto-start incremental update when freshness says data should refresh', async () => {
    vi.mocked(apiAnalysis.getFreshness).mockResolvedValue({
      latest_trade_date: '2024-01-16',
      latest_trade_data_ready: true,
      local_latest_date: '2024-01-15',
      latest_candidate_date: '2024-01-15',
      latest_result_date: '2024-01-15',
      needs_update: true,
      freshness_version: 'v2',
      running_task_id: null,
      running_task_status: null,
      incremental_update: buildIncrementalStatus(),
    } as any)

    const wrapper = mountComponent()
    await flushPromises()
    await wrapper.vm.ensureFreshDataAndLoad(true)
    await flushPromises()

    expect(apiTasks.startIncrementalUpdate).not.toHaveBeenCalled()
  })

  it('shows failed incremental warning and does not auto-restart update', async () => {
    vi.setSystemTime(new Date('2024-01-15T07:30:00Z'))
    vi.mocked(apiAnalysis.getFreshness).mockResolvedValue({
      latest_trade_date: '2024-01-16',
      latest_trade_data_ready: true,
      local_latest_date: '2024-01-15',
      latest_candidate_date: '2024-01-15',
      latest_result_date: '2024-01-15',
      needs_update: true,
      freshness_version: 'v3',
      running_task_id: null,
      running_task_status: null,
      incremental_update: buildIncrementalStatus({
        status: 'failed',
        failed_count: 5,
        last_error: '任务中断，可恢复',
        message: '增量更新失败',
      }),
    } as any)

    const wrapper = mountComponent()
    await flushPromises()
    await wrapper.vm.ensureFreshDataAndLoad(true)
    await flushPromises()

    expect(apiTasks.startIncrementalUpdate).not.toHaveBeenCalled()
    expect(wrapper.vm.incrementalUpdate.last_error).toBe('任务中断，可恢复')
  })

  it('keeps incremental update idle when freshness reports pending work', async () => {
    vi.mocked(apiAnalysis.getFreshness).mockResolvedValue({
      latest_trade_date: '2024-01-16',
      latest_trade_data_ready: true,
      local_latest_date: '2024-01-15',
      latest_candidate_date: '2024-01-15',
      latest_result_date: '2024-01-15',
      needs_update: true,
      freshness_version: 'v-outside-window',
      running_task_id: null,
      running_task_status: null,
      incremental_update: buildIncrementalStatus(),
    } as any)

    const wrapper = mountComponent()
    await flushPromises()
    await wrapper.vm.ensureFreshDataAndLoad(true)
    await flushPromises()

    expect(apiTasks.startIncrementalUpdate).not.toHaveBeenCalled()
  })

  it('hydrates cached view state from sessionStorage before reloading', async () => {
    const statusPayload = {
      configured: true,
      available: true,
      message: 'Token有效',
      data_status: {
        raw_data: { exists: true, count: 3200, latest_date: '2025-04-25' },
        candidates: { exists: true, count: 30, latest_date: '2025-04-25' },
        analysis: { exists: true, count: 20, latest_date: '2025-04-25' },
        kline: { exists: true, count: 100, latest_date: '2025-04-25' },
      },
    }
    let resolveStatus: ((value: any) => void) | null = null
    vi.mocked(apiConfig.getTushareStatus).mockImplementation(
      () => new Promise((resolve) => { resolveStatus = resolve })
    )

    window.sessionStorage.setItem('stocktrade:tomorrow-star:cache:v2', JSON.stringify({
      historyData: [{ date: '2024-01-10', count: 1, pass: 0 }],
      latestCandidates: [{ code: 'cached', kdj_j: 5 }],
      latestAnalysisResults: [{ code: 'cached', verdict: 'WATCH', total_score: 3.5 }],
      selectedDate: '2024-01-10',
      viewingDate: '2024-01-10',
      latestDate: '2024-01-10',
      latestDataDate: '2024-01-10',
      historyPage: 1,
      latestCandidatePage: 1,
      lastHistorySignature: 'cached',
      freshnessVersion: 'cached-v',
      cachedAt: Date.now(),
    }))

    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.hydratedFromCache).toBe(true)
    expect(wrapper.vm.viewingDate).toBe('2024-01-10')
    expect(wrapper.vm.latestCandidates[0].code).toBe('cached')

    resolveStatus?.(statusPayload)
  })

  it('refreshes hydrated cache after tushare status becomes ready', async () => {
    const statusPayload = {
      configured: true,
      available: true,
      message: 'Token有效',
      data_status: {
        raw_data: { exists: true, count: 3200, latest_date: '2025-04-25' },
        candidates: { exists: true, count: 30, latest_date: '2025-04-25' },
        analysis: { exists: true, count: 20, latest_date: '2025-04-25' },
        kline: { exists: true, count: 100, latest_date: '2025-04-25' },
      },
    }
    let resolveStatus: ((value: any) => void) | null = null
    vi.mocked(apiConfig.getTushareStatus).mockImplementation(
      () => new Promise((resolve) => { resolveStatus = resolve })
    )

    window.sessionStorage.setItem('stocktrade:tomorrow-star:cache:v2', JSON.stringify({
      historyData: [{ date: '2024-01-10', count: 1, pass: 0 }],
      latestCandidates: [{ code: 'cached', kdj_j: 5 }],
      latestAnalysisResults: [{ code: 'cached', verdict: 'WATCH', total_score: 3.5 }],
      selectedDate: '2024-01-10',
      viewingDate: '2024-01-10',
      latestDate: '2024-01-10',
      latestDataDate: '2024-01-10',
      historyPage: 1,
      latestCandidatePage: 1,
      lastHistorySignature: 'cached',
      freshnessVersion: 'cached-v',
      cachedAt: Date.now(),
    }))

    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.viewingDate).toBe('2024-01-10')
    expect(wrapper.vm.latestCandidates[0].code).toBe('cached')

    resolveStatus?.(statusPayload)
    await flushPromises()

    expect(wrapper.vm.latestDate).toBe('2024-01-15')
    expect(wrapper.vm.viewingDate).toBe('2024-01-15')
    expect(wrapper.vm.latestCandidates[0].code).toBe('600000')
  })

  it('reloads server data when hydrated cache has history but the right panel is empty', async () => {
    const statusPayload = {
      configured: true,
      available: true,
      message: 'Token有效',
      data_status: {
        raw_data: { exists: true, count: 3200, latest_date: '2025-04-25' },
        candidates: { exists: true, count: 30, latest_date: '2025-04-25' },
        analysis: { exists: true, count: 20, latest_date: '2025-04-25' },
        kline: { exists: true, count: 100, latest_date: '2025-04-25' },
      },
    }
    let resolveStatus: ((value: any) => void) | null = null
    vi.mocked(apiConfig.getTushareStatus).mockImplementation(
      () => new Promise((resolve) => { resolveStatus = resolve })
    )

    window.sessionStorage.setItem('stocktrade:tomorrow-star:cache:v2', JSON.stringify({
      historyData: [{ date: '2024-01-10', rawDate: '2024-01-10', count: 1, pass: 0, status: 'success' }],
      latestCandidates: [],
      latestAnalysisResults: [],
      selectedDate: '2024-01-10',
      viewingDate: '2024-01-10',
      latestDate: '2024-01-10',
      latestDataDate: '2024-01-10',
      historyPage: 1,
      latestCandidatePage: 1,
      lastHistorySignature: 'cached',
      freshnessVersion: 'cached-v',
      cachedAt: Date.now(),
    }))

    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.hydratedFromCache).toBe(true)
    expect(wrapper.vm.latestCandidates).toHaveLength(0)

    resolveStatus?.(statusPayload)
    await flushPromises()
    await flushPromises()

    expect(wrapper.vm.latestDate).toBe('2024-01-15')
    expect(wrapper.vm.viewingDate).toBe('2024-01-15')
    expect(wrapper.vm.latestCandidates[0].code).toBe('600000')
    expect(wrapper.vm.latestAnalysisResults).toHaveLength(4)
  })

  it('refreshes the current date and shows success feedback', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.viewingDate = '2024-01-15'
    await wrapper.vm.refreshCurrentCandidates()
    await flushPromises()

    expect(ElMessage.success).toHaveBeenCalledWith('已刷新 2024-01-15 的数据')
  })

  it('loads current-hot data and filters sci-tech candidates/results', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.activeTab = 'current-hot'
    await flushPromises()

    expect(apiAnalysis.getCurrentHotDates).toHaveBeenCalled()
    expect(wrapper.vm.currentHotLatestCandidates).toHaveLength(2)
    expect(wrapper.vm.displayCurrentHotAnalysisResults).toHaveLength(5)
    expect(wrapper.vm.totalCurrentHotAnalysisResults).toBe(6)
    expect(wrapper.vm.getCurrentHotBoardLabel(wrapper.vm.currentHotLatestCandidates[0])).toBe('半导体设备')
    expect(wrapper.vm.getBooleanTagLabel(wrapper.vm.currentHotLatestCandidates[0].b1_passed)).toBe('通过')
    expect(wrapper.vm.getBooleanTagLabel(wrapper.vm.currentHotLatestCandidates[1].b1_passed)).toBe('未过')

    wrapper.vm.currentHotBoardFilter = 'sci-tech'
    await flushPromises()

    expect(wrapper.vm.displayCurrentHotLatestCandidates.map((item: { code: string }) => item.code)).toEqual(['688001'])
    expect(wrapper.vm.displayCurrentHotAnalysisResults.map((item: { code: string }) => item.code)).toEqual(['688001', '688005'])
  })

  it('falls back to code-derived board labels for current-hot candidates', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.getCurrentHotBoardLabel({ code: '688002' })).toBe('科创板')
    expect(wrapper.vm.getCurrentHotBoardLabel({ code: '600002' })).toBe('其他板块')
  })

  it('switches midday source to current-hot and loads new intraday api', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.activeTab = 'midday-analysis'
    await flushPromises()

    wrapper.vm.middaySource = 'current-hot'
    await flushPromises()

    expect(apiAnalysis.getCurrentHotMiddayStatus).toHaveBeenCalled()
    expect(apiAnalysis.getCurrentHotMiddayCurrent).toHaveBeenCalled()
    expect(wrapper.vm.middayRows[0].code).toBe('688001')
  })
})
