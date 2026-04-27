import { beforeEach, describe, expect, it, vi } from 'vitest'
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
  },
  apiTasks: {
    startIncrementalUpdate: vi.fn(),
    getIncrementalStatus: vi.fn(),
  },
  isRequestCanceled: vi.fn(() => false),
}))

import { ElMessage } from 'element-plus'
import { apiAnalysis, apiConfig, apiTasks } from '@/api'

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0))
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
  { code: '600000', kdj_j: 25, close_price: 10.5 },
  { code: '000001', kdj_j: 12, close_price: 12.2 },
]

const latestResults = [
  { code: 'A', verdict: 'WATCH', total_score: 4.6, signal_type: 'rebound', comment: '1' },
  { code: 'B', verdict: 'PASS', total_score: 4.2, signal_type: 'trend_start', comment: '2' },
  { code: 'C', verdict: 'PASS', total_score: 5.0, signal_type: 'trend_start', comment: '3' },
  { code: 'D', verdict: 'FAIL', total_score: 4.9, signal_type: 'distribution_risk', comment: '4' },
]

function mountComponent() {
  return mount(TomorrowStar, {
    global: {
      plugins: [ElementPlus, createPinia()],
      stubs: {
        'el-row': { template: '<div><slot /></div>' },
        'el-col': { template: '<div><slot /></div>' },
        'el-card': { template: '<div><slot name="header" /><slot /></div>' },
        'el-table': { template: '<div><slot /></div>' },
        'el-table-column': true,
        'el-button': { template: '<button @click="$emit(\'click\')"><slot /></button>' },
        'el-tag': { template: '<span><slot /></span>' },
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
    vi.mocked(apiAnalysis.getFreshness).mockResolvedValue({
      latest_trade_date: '2024-01-15',
      local_latest_date: '2024-01-15',
      latest_candidate_date: '2024-01-15',
      latest_result_date: '2024-01-15',
      needs_update: false,
      freshness_version: 'v1',
      incremental_update: { running: false, progress: 0, total: 0, updated_count: 0, skipped_count: 0, failed_count: 0, message: '' },
    } as any)
    vi.mocked(apiTasks.getIncrementalStatus).mockResolvedValue({
      running: false,
      progress: 0,
      total: 0,
      updated_count: 0,
      skipped_count: 0,
      failed_count: 0,
      message: '',
    } as any)
    vi.mocked(apiTasks.startIncrementalUpdate).mockResolvedValue({
      success: true,
      running: false,
      message: 'started',
    } as any)
  })

  it('loads history and latest candidate/result data on mount', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.historyData).toHaveLength(2)
    expect(wrapper.vm.latestCandidates).toHaveLength(2)
    expect(wrapper.vm.latestAnalysisResults).toHaveLength(4)
    expect(wrapper.vm.latestDate).toBe('2024-01-15')
  })

  it('sorts top analysis results by verdict priority first, then score', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    const codes = wrapper.vm.topAnalysisResults.map((item: { code: string }) => item.code)
    expect(codes).toEqual(['C', 'B', 'A', 'D'])
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

    await wrapper.vm.selectDate({ date: '2024-01-14', count: 1, pass: 0 })
    await flushPromises()

    expect(wrapper.vm.selectedDate).toBe('2024-01-14')
    expect(wrapper.vm.latestDataDate).toBe('2024-01-14')
    expect(wrapper.vm.latestCandidates[0].code).toBe('300001')
    expect(apiAnalysis.getCandidates).toHaveBeenLastCalledWith('2024-01-14', expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(apiAnalysis.getResults).toHaveBeenLastCalledWith('2024-01-14', expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it('starts incremental update when freshness says data should refresh', async () => {
    vi.mocked(apiAnalysis.getFreshness).mockResolvedValue({
      latest_trade_date: '2024-01-16',
      local_latest_date: '2024-01-15',
      latest_candidate_date: '2024-01-15',
      latest_result_date: '2024-01-15',
      needs_update: true,
      freshness_version: 'v2',
      incremental_update: { running: false, progress: 0, total: 0, updated_count: 0, skipped_count: 0, failed_count: 0, message: '' },
    } as any)

    const wrapper = mountComponent()
    await flushPromises()
    await wrapper.vm.ensureFreshDataAndLoad(true)
    await flushPromises()

    expect(apiTasks.startIncrementalUpdate).toHaveBeenCalledTimes(1)
  })

  it('hydrates cached view state from sessionStorage before reloading', async () => {
    window.sessionStorage.setItem('stocktrade:tomorrow-star:cache', JSON.stringify({
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
  })

  it('refreshes the current date and shows success feedback', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.viewingDate = '2024-01-15'
    await wrapper.vm.refreshCurrentCandidates()
    await flushPromises()

    expect(ElMessage.success).toHaveBeenCalledWith('已刷新 2024-01-15 的数据')
  })
})
