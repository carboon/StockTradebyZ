import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import ElementPlus from 'element-plus'
import Config from '@/views/Config.vue'

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

vi.mock('@/api/index', () => ({
  apiConfig: {
    getAll: vi.fn(),
    update: vi.fn(),
    verifyTushare: vi.fn(),
    saveEnv: vi.fn(),
    getTushareStatus: vi.fn(),
  },
  apiTasks: {
    getDiagnostics: vi.fn(),
    startUpdate: vi.fn(),
    getRunning: vi.fn(),
  },
}))

import { ElMessage } from 'element-plus'
import { apiConfig, apiTasks } from '@/api/index'

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

function setViewport(width: number) {
  Object.defineProperty(window, 'innerWidth', {
    value: width,
    writable: true,
    configurable: true,
  })
  window.dispatchEvent(new Event('resize'))
}

function mountComponent() {
  return mount(Config, {
    global: {
      plugins: [ElementPlus, createPinia()],
      stubs: {
        'el-card': { template: '<div class="el-card"><slot name="header" /><slot /></div>' },
        'el-form': { template: '<form class="el-form"><slot /></form>' },
        'el-form-item': { template: '<div class="el-form-item"><slot /></div>' },
        'el-input': { template: '<input class="el-input" :value="modelValue" />', props: ['modelValue'] },
        'el-input-number': { template: '<input class="el-input-number" :value="modelValue" />', props: ['modelValue'] },
        'el-button': { template: '<button class="el-button" @click="$emit(\'click\')"><slot /></button>', props: ['loading', 'type'] },
        'el-divider': { template: '<div class="el-divider"><slot /></div>' },
        'el-radio-group': { template: '<div class="el-radio-group"><slot /></div>', props: ['modelValue'] },
        'el-radio': { template: '<label class="el-radio"><slot /></label>', props: ['value'] },
        'el-tabs': { template: '<div class="el-tabs"><slot /></div>', props: ['modelValue'] },
        'el-tab-pane': { template: '<div class="el-tab-pane"><slot /></div>', props: ['label', 'name'] },
        'el-alert': { template: '<div class="el-alert">{{ title }}{{ description }}</div>', props: ['title', 'description'] },
        'el-tooltip': { template: '<div><slot /></div>' },
        'el-icon': { template: '<i><slot /></i>' },
        'el-tag': { template: '<span class="el-tag"><slot /></span>', props: ['type', 'size'] },
      },
    },
  })
}

describe('Config.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    mockPush.mockReset()
    setViewport(1280)

    vi.mocked(apiConfig.getAll).mockResolvedValue({
      configs: [
        { key: 'tushare_token', value: 'saved_token' },
        { key: 'default_reviewer', value: 'quant' },
        { key: 'min_score_threshold', value: '4.0' },
      ],
    } as any)
    vi.mocked(apiConfig.getTushareStatus).mockResolvedValue({
      configured: true,
      available: true,
      message: 'Token有效',
      data_status: {
        raw_data: { exists: true, count: 3200, latest_date: '2025-04-25' },
        candidates: { exists: true, count: 30, latest_date: '2025-04-25' },
        analysis: { exists: true, count: 20, latest_date: '2025-04-25' },
        kline: { exists: true, count: 100, latest_date: '2025-04-25' },
      },
    } as any)
    vi.mocked(apiConfig.verifyTushare).mockResolvedValue({ valid: true, message: 'Token 有效' } as any)
    vi.mocked(apiConfig.saveEnv).mockResolvedValue({ status: 'ok' } as any)
    vi.mocked(apiTasks.getDiagnostics).mockResolvedValue({ checks: [] } as any)
    vi.mocked(apiTasks.startUpdate).mockResolvedValue({ task: { id: 101 } } as any)
    vi.mocked(apiTasks.getRunning).mockResolvedValue({ tasks: [] } as any)
  })

  it('renders config sections and loads initial diagnostics', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.find('.config-page').exists()).toBe(true)
    expect(wrapper.text()).toContain('配置管理')
    expect(wrapper.text()).toContain('Tushare 配置')
    expect(wrapper.text()).toContain('首次启动自检')
    expect(apiTasks.getDiagnostics).toHaveBeenCalled()
  })

  it('verifies tushare token through the store flow', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.configs.tushare_token = 'valid_token_123'
    await wrapper.vm.verifyTushare()

    expect(apiConfig.verifyTushare).toHaveBeenCalledWith('valid_token_123')
    expect(ElMessage.success).toHaveBeenCalledWith('验证成功，请保存配置')
  })

  it('warns when trying to verify an empty token', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.configs.tushare_token = ''
    await wrapper.vm.verifyTushare()

    expect(apiConfig.verifyTushare).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith('请先输入 API Token')
  })

  it('saves config through the store and routes to tomorrow-star when not initializing', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.configs.tushare_token = 'new_token'
    wrapper.vm.configs.min_score_threshold = 4.5
    await wrapper.vm.saveConfigs(false)

    expect(apiConfig.verifyTushare).toHaveBeenCalledWith('new_token')
    expect(apiConfig.saveEnv).toHaveBeenCalledWith(expect.objectContaining({
      tushare_token: 'new_token',
      default_reviewer: 'quant',
      min_score_threshold: '4.5',
    }))
    expect(ElMessage.success).toHaveBeenCalledWith('配置已保存')
    expect(mockPush).toHaveBeenCalledWith('/tomorrow-star')
  })

  it('reloads config values from the store', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.configs.tushare_token = 'dirty_value'
    vi.mocked(apiConfig.getAll).mockResolvedValueOnce({
      configs: [
        { key: 'tushare_token', value: 'reloaded_token' },
        { key: 'default_reviewer', value: 'quant' },
        { key: 'min_score_threshold', value: '3.5' },
      ],
    } as any)

    await wrapper.vm.loadConfigs()

    expect(apiConfig.getAll).toHaveBeenCalled()
    expect(wrapper.vm.configs.tushare_token).toBe('reloaded_token')
    expect(wrapper.vm.configs.min_score_threshold).toBe(3.5)
  })

  it('shows the mobile action bar on small screens', async () => {
    setViewport(390)
    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.isMobile).toBe(true)
    expect(wrapper.find('.mobile-action-bar').exists()).toBe(true)
  })
})
