import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import ElementPlus from 'element-plus'
import Update from '@/views/Update.vue'

const mockPush = vi.fn()
const mockRoute = {
  query: {},
}

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockPush }),
  useRoute: () => mockRoute,
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
    ElMessageBox: {
      confirm: vi.fn(),
    },
  }
})

vi.mock('@/api', () => ({
  apiTasks: {
    getRunning: vi.fn(),
    getAll: vi.fn(),
    getStatus: vi.fn(),
    getAdminSummary: vi.fn(),
    getEnvironment: vi.fn(),
    getDiagnostics: vi.fn(),
    getIncrementalStatus: vi.fn(),
    getLogs: vi.fn(),
    cancel: vi.fn(),
    clearTasks: vi.fn(),
    startUpdate: vi.fn(),
    startIncrementalUpdate: vi.fn(),
    getOverview: vi.fn(),
  },
  apiConfig: {
    getTushareStatus: vi.fn(),
    getAll: vi.fn(),
    verifyTushare: vi.fn(),
    update: vi.fn(),
    saveEnv: vi.fn(),
  },
}))

import { ElMessage } from 'element-plus'
import { apiConfig, apiTasks } from '@/api'

class MockWebSocket {
  static OPEN = 1
  readyState = 1
  onmessage: ((event: { data: string }) => void) | null = null
  close = vi.fn()
  constructor(public url: string) {}
}

Object.defineProperty(globalThis, 'WebSocket', {
  value: MockWebSocket,
  writable: true,
})

Object.defineProperty(document, 'visibilityState', {
  value: 'visible',
  configurable: true,
})

Object.defineProperty(globalThis.navigator, 'clipboard', {
  value: {
    writeText: vi.fn().mockResolvedValue(undefined),
  },
  configurable: true,
})

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

function mockTaskStatus({
  raw = true,
  candidates = true,
  analysis = true,
} = {}) {
  vi.mocked(apiTasks.getStatus).mockResolvedValue({
    raw_data: { exists: raw, count: raw ? 3200 : 0, latest_date: '2025-04-25' },
    candidates: { exists: candidates, count: candidates ? 120 : 0, latest_date: '2025-04-25' },
    analysis: { exists: analysis, count: analysis ? 30 : 0, latest_date: '2025-04-25' },
    kline: { exists: true, count: 100, latest_date: '2025-04-25' },
  } as any)
}

function mockConfigStatus({
  ready = true,
  initialized = true,
} = {}) {
  vi.mocked(apiConfig.getTushareStatus).mockResolvedValue({
    configured: ready,
    available: ready,
    message: ready ? 'Token有效' : '请配置 Token',
    data_status: {
      raw_data: { exists: initialized, count: initialized ? 3200 : 0, latest_date: '2025-04-25' },
      candidates: { exists: initialized, count: initialized ? 120 : 0, latest_date: '2025-04-25' },
      analysis: { exists: initialized, count: initialized ? 30 : 0, latest_date: '2025-04-25' },
      kline: { exists: true, count: 100, latest_date: '2025-04-25' },
    },
  } as any)
}

function buildTask(overrides: Record<string, unknown> = {}) {
  return {
    id: 11,
    task_type: 'full_update',
    status: 'running',
    task_stage: 'fetch_data',
    progress: 35,
    summary: '首次初始化',
    created_at: '2025-04-25T10:00:00',
    started_at: '2025-04-25T10:00:10',
    error_message: null,
    ...overrides,
  }
}

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
  return mount(Update, {
    global: {
      plugins: [ElementPlus, createPinia()],
      stubs: {
        'el-card': { template: '<div class="el-card"><slot name="header" /><slot /></div>' },
        'el-tabs': { template: '<div class="el-tabs"><slot /></div>' },
        'el-tab-pane': { template: '<div class="el-tab-pane"><slot /></div>' },
        'el-button': { template: '<button class="el-button" @click="$emit(\'click\')"><slot /></button>' },
        'el-tag': { template: '<span class="el-tag"><slot /></span>' },
        'el-icon': { template: '<i class="el-icon"><slot /></i>' },
        'el-checkbox': { template: '<input class="el-checkbox" type="checkbox" />' },
        'el-radio-group': { template: '<div class="el-radio-group"><slot /></div>' },
        'el-radio-button': { template: '<button class="el-radio-button"><slot /></button>' },
        'el-table': { template: '<div class="el-table"><slot /></div>' },
        'el-table-column': true,
        'el-empty': { template: '<div class="el-empty"><slot />{{ description }}</div>', props: ['description'] },
        'el-progress': { template: '<div class="el-progress" />' },
        'el-alert': { template: '<div class="el-alert">{{ title }}{{ description }}</div>', props: ['title', 'description'] },
        'el-collapse': { template: '<div class="el-collapse"><slot /></div>' },
        'el-collapse-item': { template: '<div class="el-collapse-item"><slot name="title" /><slot /></div>' },
      },
    },
  })
}

describe('Update.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.sessionStorage.clear()
    window.localStorage.clear()
    setActivePinia(createPinia())
    mockPush.mockReset()
    vi.mocked(apiTasks.getRunning).mockResolvedValue({ tasks: [], total: 0 } as any)
    vi.mocked(apiTasks.getAll).mockResolvedValue({ tasks: [], total: 0 } as any)
    vi.mocked(apiTasks.getAdminSummary).mockResolvedValue({
      system_ready: true,
      latest_trade_date: '2025-04-25',
      latest_db_date: '2025-04-25',
      latest_candidate_date: '2025-04-25',
      latest_analysis_date: '2025-04-25',
      gap_days: 0,
      data_gap: { has_gap: false },
      data_production: {
        raw_ready_count: 3200,
        raw_missing_count: 0,
        raw_suspended_count: 0,
        raw_long_stale_count: 0,
        raw_invalid_count: 0,
        raw_calendar_latest_trade_date: '2025-04-25',
      },
      pipeline_status: [],
      pending_actions: [],
      current_task: null,
      latest_task: null,
      latest_task_summary: '',
    } as any)
    vi.mocked(apiTasks.getEnvironment).mockResolvedValue({ sections: [] } as any)
    vi.mocked(apiTasks.getDiagnostics).mockResolvedValue({
      generated_at: '2025-04-25T10:00:00',
      checks: [{ key: 'backend', label: '后端服务', status: 'success', summary: '后端接口可访问。' }],
      running_tasks: [],
      latest_failed_task: null,
      latest_completed_task: null,
      environment: [],
      data_status: {
        raw_data: { exists: true, count: 3200, latest_date: '2025-04-25' },
        candidates: { exists: true, count: 120, latest_date: '2025-04-25' },
        analysis: { exists: true, count: 30, latest_date: '2025-04-25' },
        kline: { exists: true, count: 100, latest_date: '2025-04-25' },
      },
    } as any)
    vi.mocked(apiTasks.getIncrementalStatus).mockResolvedValue(buildIncrementalStatus() as any)
    vi.mocked(apiTasks.getLogs).mockResolvedValue({ logs: [] } as any)
    vi.mocked(apiTasks.getOverview).mockResolvedValue({} as any)
    mockTaskStatus()
    mockConfigStatus()
  })

  it('shows bootstrap guidance when initialization is incomplete', async () => {
    mockTaskStatus({ raw: true, candidates: false, analysis: false })
    mockConfigStatus({ ready: true, initialized: false })

    const wrapper = mountComponent()
    await flushPromises()
    await nextTick()

    expect(wrapper.vm.showBootstrap).toBe(true)
    expect(wrapper.vm.bootstrapFinished).toBe(false)
    expect(wrapper.vm.bootstrapSteps).toHaveLength(4)
    expect(wrapper.text()).toContain('首次初始化引导')
  })

  it('keeps local diagnostics collapsed by default', async () => {
    const wrapper = mountComponent()
    await flushPromises()
    await nextTick()

    expect(wrapper.vm.diagnosticsPanels).toEqual([])
    expect(wrapper.text()).toContain('展开本机诊断详情')
  })

  it('starts bootstrap, focuses the task, and switches to log view', async () => {
    mockTaskStatus({ raw: true, candidates: false, analysis: false })
    mockConfigStatus({ ready: true, initialized: false })
    const task = buildTask({ id: 21 })
    vi.mocked(apiTasks.startUpdate).mockResolvedValue({ task, ws_url: '/ws/tasks/21' } as any)
    vi.mocked(apiTasks.getRunning)
      .mockResolvedValueOnce({ tasks: [], total: 0 } as any)
      .mockResolvedValue({ tasks: [task], total: 1 } as any)
    vi.mocked(apiTasks.getLogs).mockResolvedValue({ logs: [{ id: 1, task_id: 21, message: '开始', level: 'info', log_time: '2025-04-25T10:00:00' }] } as any)

    const wrapper = mountComponent()
    await flushPromises()

    await wrapper.vm.startBootstrap()
    await flushPromises()

    expect(apiTasks.startUpdate).toHaveBeenCalledWith('quant', false, 1)
    expect(wrapper.vm.activeTab).toBe('logs')
    expect(wrapper.vm.selectedTask?.id).toBe(21)
    expect(ElMessage.success).toHaveBeenCalledWith('初始化任务已启动 #21')
  })

  it('restores the selected bootstrap task from sessionStorage', async () => {
    mockTaskStatus({ raw: true, candidates: false, analysis: false })
    mockConfigStatus({ ready: true, initialized: false })
    window.localStorage.setItem('stocktrade:init-task-view', JSON.stringify({
      activeTab: 'logs',
      selectedTaskId: 33,
      bootstrapTaskId: 33,
    }))
    const task = buildTask({ id: 33 })
    vi.mocked(apiTasks.getRunning).mockResolvedValue({ tasks: [task], total: 1 } as any)
    vi.mocked(apiTasks.getLogs).mockResolvedValue({ logs: [{ id: 2, task_id: 33, message: '恢复日志', level: 'info', log_time: '2025-04-25T10:00:00' }] } as any)

    const wrapper = mountComponent()
    await flushPromises()
    await nextTick()

    expect(wrapper.vm.activeTab).toBe('logs')
    expect(wrapper.vm.selectedTask?.id).toBe(33)
    expect(apiTasks.getLogs).toHaveBeenCalledWith(33)
  })

  it('cancels a task and reloads task state', async () => {
    const task = buildTask({ id: 45 })
    vi.mocked(apiTasks.cancel).mockResolvedValue({ status: 'ok', message: '任务已取消' } as any)

    const wrapper = mountComponent()
    await flushPromises()
    await wrapper.vm.cancelTask(task)

    expect(apiTasks.cancel).toHaveBeenCalledWith(45)
    expect(ElMessage.success).toHaveBeenCalledWith('任务已取消')
  })

  it('starts incremental update from the latest-trade-day action', async () => {
    vi.mocked(apiTasks.startIncrementalUpdate).mockResolvedValue({
      success: true,
      message: '增量更新已启动',
      running: false,
    } as any)

    const wrapper = mountComponent()
    await flushPromises()

    await wrapper.vm.startDataUpdate()
    await flushPromises()

    expect(apiTasks.startIncrementalUpdate).toHaveBeenCalledTimes(1)
    expect(apiTasks.startUpdate).not.toHaveBeenCalled()
    expect(ElMessage.success).toHaveBeenCalledWith('增量更新已启动')
  })

  it('shows failed incremental warning when last run was interrupted', async () => {
    vi.mocked(apiTasks.getIncrementalStatus).mockResolvedValue(buildIncrementalStatus({
      status: 'failed',
      failed_count: 3,
      last_error: '网络波动，中断后可恢复',
      message: '增量更新失败',
    }) as any)

    const wrapper = mountComponent()
    await flushPromises()
    await nextTick()

    expect(wrapper.text()).toContain('增量更新上次未完成')
    expect(wrapper.text()).toContain('网络波动，中断后可恢复')
  })
})
