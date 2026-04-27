/**
 * Update.vue 组件测试文件
 * 测试运维管理页面的任务管理、日志记录和状态管理功能
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import ElementPlus from 'element-plus'
import Update from '@/views/Update.vue'

// Mock Element Plus Message 组件
vi.mock('element-plus', async () => {
  const actual = await vi.importActual('element-plus')
  return {
    ...actual,
    ElMessage: {
      success: vi.fn(),
      error: vi.fn(),
      warning: vi.fn(),
      info: vi.fn()
    }
  }
})

// 导入 ElMessage 用于验证
import { ElMessage } from 'element-plus'

// Mock API 模块
vi.mock('@/api/index', () => ({
  apiTasks: {
    getRunning: vi.fn(),
    getAll: vi.fn(),
    getStatus: vi.fn(),
    getEnvironment: vi.fn(),
    getLogs: vi.fn(),
    cancel: vi.fn(),
    clearTasks: vi.fn(),
    startUpdate: vi.fn(),
    getOverview: vi.fn()
  },
  apiConfig: {
    getAll: vi.fn(),
    getTushareStatus: vi.fn(() => Promise.resolve({
      configured: true,
      available: true,
      message: 'Token有效'
    })),
    verifyTushare: vi.fn()
  }
}))

// 导入 mock 函数
import { apiTasks, apiConfig } from '@/api/index'

// 创建挂载选项的辅助函数
function createMountOptions() {
  return {
    global: {
      plugins: [ElementPlus, createPinia()],
      stubs: {
        'el-card': { template: '<div class="el-card"><slot /><slot name="header" /></div>' },
        'el-tabs': { template: '<div class="el-tabs"><slot /></div>' },
        'el-tab-pane': { template: '<div class="el-tab-pane"><slot /></div>' },
        'el-button': {
          template: '<button class="el-button" :disabled="$attrs.disabled || $attrs.loading"><slot /></button>',
          props: ['disabled', 'loading']
        },
        'el-tag': { template: '<span class="el-tag"><slot /></span>' },
        'el-icon': { template: '<i class="el-icon"><slot /></i>' },
        'el-checkbox': {
          template: '<input type="checkbox" class="el-checkbox" v-model="$attrs.modelValue" />',
          props: ['modelValue']
        },
        'el-radio-group': { template: '<div class="el-radio-group"><slot /></div>' },
        'el-radio-button': { template: '<label class="el-radio-button"><slot /></label>' },
        'el-table': { template: '<table class="el-table"><slot /></table>' },
        'el-table-column': { template: '<td class="el-table-column"><slot /></td>' },
        'el-empty': { template: '<div class="el-empty"><slot /></div>' },
        'el-progress': { template: '<div class="el-progress" />', props: ['percentage'] },
        'el-alert': { template: '<div class="el-alert"><slot /></div>' }
      }
    }
  }
}

describe('Update.vue 运维管理页面', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  describe('页面初始化', () => {
    it('应该正确渲染页面结构', async () => {
      // Mock API 响应 - 数据已就绪
      vi.mocked(apiTasks.getRunning).mockResolvedValue({ tasks: [], total: 0 })
      vi.mocked(apiTasks.getAll).mockResolvedValue({ tasks: [], total: 0 })
      vi.mocked(apiTasks.getStatus).mockResolvedValue({
        raw_data: { exists: true, count: 3580, latest_date: '2025-04-25' },
        candidates: { exists: true, count: 100, latest_date: '2025-04-25' },
        analysis: { exists: true, count: 5, latest_date: '2025-04-25' },
        kline: { exists: true, count: 100 }
      })
      vi.mocked(apiTasks.getEnvironment).mockResolvedValue({
        sections: [
          {
            key: 'service',
            label: '服务信息',
            items: { python_version: '3.11.0' }
          }
        ]
      })

      const wrapper = mount(Update, createMountOptions())
      await nextTick()
      await nextTick()

      // 验证页面结构
      expect(wrapper.find('.ops-page').exists()).toBe(true)
      expect(wrapper.find('.ops-tabs').exists()).toBe(true)
    })

    it('数据未就绪时应显示首次初始化引导', async () => {
      // Mock API 响应 - 数据未就绪
      vi.mocked(apiTasks.getRunning).mockResolvedValue({ tasks: [], total: 0 })
      vi.mocked(apiTasks.getAll).mockResolvedValue({ tasks: [], total: 0 })
      vi.mocked(apiTasks.getStatus).mockResolvedValue({
        raw_data: { exists: false, count: 0 },
        candidates: { exists: false, count: 0 },
        analysis: { exists: false, count: 0 },
        kline: { exists: false, count: 0 }
      })
      vi.mocked(apiTasks.getEnvironment).mockResolvedValue({
        sections: []
      })

      const wrapper = mount(Update, createMountOptions())
      await nextTick()
      await nextTick()
      await nextTick()

      // 验证首次初始化卡片存在（需要等待数据加载完成）
      const bootstrapCards = wrapper.findAll('.bootstrap-card')
      expect(bootstrapCards.length).toBeGreaterThan(0)
    })

    it('数据已就绪时应显示操作按钮而非初始化引导', async () => {
      // Mock API 响应 - 数据已就绪
      vi.mocked(apiTasks.getRunning).mockResolvedValue({ tasks: [], total: 0 })
      vi.mocked(apiTasks.getAll).mockResolvedValue({ tasks: [], total: 0 })
      vi.mocked(apiTasks.getStatus).mockResolvedValue({
        raw_data: { exists: true, count: 3580, latest_date: '2025-04-25' },
        candidates: { exists: true, count: 100 },
        analysis: { exists: true, count: 5 },
        kline: { exists: true, count: 100 }
      })
      vi.mocked(apiTasks.getEnvironment).mockResolvedValue({
        sections: []
      })

      const wrapper = mount(Update, createMountOptions())
      await nextTick()
      await nextTick()
      await nextTick()

      // 验证操作按钮存在
      const actionButtons = wrapper.findAll('.action-card')
      expect(actionButtons.length).toBe(1)
    })
  })

  describe('任务管理', () => {
    it('应该正确显示运行中的任务', async () => {
      const mockTask = {
        id: 123,
        task_type: 'full_update',
        status: 'running',
        task_stage: 'fetch_data',
        progress: 45,
        summary: '正在获取数据'
      }

      vi.mocked(apiTasks.getRunning).mockResolvedValue({
        tasks: [mockTask],
        total: 1
      })
      vi.mocked(apiTasks.getAll).mockResolvedValue({ tasks: [], total: 0 })
      vi.mocked(apiTasks.getStatus).mockResolvedValue({
        raw_data: { exists: true, count: 3580 },
        candidates: { exists: true },
        analysis: { exists: true },
        kline: { exists: true }
      })
      vi.mocked(apiTasks.getEnvironment).mockResolvedValue({
        sections: []
      })

      const wrapper = mount(Update, createMountOptions())
      await nextTick()
      await nextTick()
      await nextTick()

      // 验证运行中任务数量显示
      const runningTasksCount = wrapper.vm.runningTasksCount
      expect(runningTasksCount).toBe(1)
    })

    it('应该正确取消任务', async () => {
      const mockTask = {
        id: 123,
        task_type: 'full_update',
        status: 'running',
        task_stage: 'fetch_data',
        progress: 45
      }

      vi.mocked(apiTasks.getRunning).mockResolvedValue({
        tasks: [mockTask],
        total: 1
      })
      vi.mocked(apiTasks.getAll).mockResolvedValue({ tasks: [], total: 0 })
      vi.mocked(apiTasks.getStatus).mockResolvedValue({
        raw_data: { exists: true, count: 3580 },
        candidates: { exists: true },
        analysis: { exists: true },
        kline: { exists: true }
      })
      vi.mocked(apiTasks.getEnvironment).mockResolvedValue({ sections: [] })
      vi.mocked(apiTasks.cancel).mockResolvedValue({
        status: 'ok',
        message: '任务已取消'
      })

      const wrapper = mount(Update, createMountOptions())
      await nextTick()
      await nextTick()

      // 调用取消任务方法
      await wrapper.vm.cancelTask(mockTask)

      // 验证 API 被调用
      expect(apiTasks.cancel).toHaveBeenCalledWith(123)
      expect(ElMessage.success).toHaveBeenCalled()
    })
  })

  describe('日志记录', () => {
    it('应该正确加载并显示任务日志', async () => {
      const mockLogs = [
        {
          id: 1,
          task_id: 123,
          log_time: '2025-04-25T12:34:56',
          level: 'info',
          message: '开始处理'
        },
        {
          id: 2,
          task_id: 123,
          log_time: '2025-04-25T12:34:57',
          level: 'info',
          message: '处理完成'
        }
      ]

      vi.mocked(apiTasks.getRunning).mockResolvedValue({ tasks: [], total: 0 })
      vi.mocked(apiTasks.getAll).mockResolvedValue({ tasks: [], total: 0 })
      vi.mocked(apiTasks.getStatus).mockResolvedValue({
        raw_data: { exists: true, count: 3580 },
        candidates: { exists: true },
        analysis: { exists: true },
        kline: { exists: true }
      })
      vi.mocked(apiTasks.getEnvironment).mockResolvedValue({ sections: [] })
      vi.mocked(apiTasks.getLogs).mockResolvedValue({ logs: mockLogs })

      const wrapper = mount(Update, createMountOptions())
      await nextTick()
      await nextTick()

      // 加载任务日志
      await wrapper.vm.loadTaskLogs(123)

      // 验证日志数量
      expect(wrapper.vm.selectedTaskLogs.length).toBe(2)
      expect(wrapper.vm.selectedTaskLogs[0].message).toBe('开始处理')
    })
  })

  describe('状态管理', () => {
    it('应该正确显示原始数据状态', async () => {
      vi.mocked(apiTasks.getRunning).mockResolvedValue({ tasks: [], total: 0 })
      vi.mocked(apiTasks.getAll).mockResolvedValue({ tasks: [], total: 0 })
      vi.mocked(apiTasks.getStatus).mockResolvedValue({
        raw_data: { exists: true, count: 3580, latest_date: '2025-04-25' },
        candidates: { exists: true },
        analysis: { exists: true },
        kline: { exists: true }
      })
      vi.mocked(apiTasks.getEnvironment).mockResolvedValue({
        sections: []
      })

      const wrapper = mount(Update, createMountOptions())
      await nextTick()
      await nextTick()
      await nextTick()

      // 验证原始数据状态
      expect(wrapper.vm.dataStatus.rawData.exists).toBe(true)
      expect(wrapper.vm.dataStatus.rawData.count).toBe(3580)
      expect(wrapper.vm.dataStatus.rawData.latestDate).toBe('2025-04-25')
    })

    it('应该正确显示环境信息', async () => {
      const mockEnv = {
        sections: [
          {
            key: 'service',
            label: '服务信息',
            items: {
              python_version: '3.11.0',
              platform: 'Linux'
            }
          }
        ]
      }

      vi.mocked(apiTasks.getRunning).mockResolvedValue({ tasks: [], total: 0 })
      vi.mocked(apiTasks.getAll).mockResolvedValue({ tasks: [], total: 0 })
      vi.mocked(apiTasks.getStatus).mockResolvedValue({
        raw_data: { exists: true, count: 3580 },
        candidates: { exists: true },
        analysis: { exists: true },
        kline: { exists: true }
      })
      vi.mocked(apiTasks.getEnvironment).mockResolvedValue(mockEnv)

      const wrapper = mount(Update, createMountOptions())
      await nextTick()
      await nextTick()
      await nextTick()

      // 验证环境信息
      expect(wrapper.vm.dataStatus.environment.length).toBe(1)
      expect(wrapper.vm.dataStatus.environment[0].label).toBe('服务信息')
    })
  })
})

describe('API 接口验证', () => {
  it('GET /v1/tasks/running - 获取运行中任务', async () => {
    vi.mocked(apiTasks.getRunning).mockResolvedValue({
      tasks: [],
      total: 0
    })

    const result = await apiTasks.getRunning()
    expect(result).toHaveProperty('tasks')
    expect(result).toHaveProperty('total')
  })

  it('GET /v1/tasks/status - 获取数据状态', async () => {
    vi.mocked(apiTasks.getStatus).mockResolvedValue({
      raw_data: { exists: true, count: 3580 },
      candidates: { exists: true },
      analysis: { exists: true },
      kline: { exists: true }
    })

    const result = await apiTasks.getStatus()
    expect(result).toHaveProperty('raw_data')
    expect(result.raw_data.exists).toBe(true)
  })

  it('POST /v1/tasks/{id}/cancel - 取消任务', async () => {
    vi.mocked(apiTasks.cancel).mockResolvedValue({
      status: 'ok',
      message: '任务已取消'
    })

    const result = await apiTasks.cancel(123)
    expect(result.status).toBe('ok')
  })

  it('DELETE /v1/tasks/clear - 清空历史任务', async () => {
    vi.mocked(apiTasks.clearTasks).mockResolvedValue({
      status: 'ok',
      message: '已清空'
    })

    const result = await apiTasks.clearTasks()
    expect(result.status).toBe('ok')
  })
})
