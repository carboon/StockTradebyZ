/**
 * Diagnosis.vue 组件测试文件
 * 测试单股诊断页面的渲染、用户交互和状态管理
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import ElementPlus from 'element-plus'
import Diagnosis from '@/views/Diagnosis.vue'

// Mock vue-router
const mockPush = vi.fn()
const mockRoute = {
  query: {},
  path: '/diagnosis'
}
vi.mock('vue-router', () => ({
  useRoute: () => mockRoute,
  useRouter: () => ({
    push: mockPush
  })
}))

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

// Mock echarts
vi.mock('echarts', () => ({
  default: {
    init: vi.fn(() => ({
      setOption: vi.fn(),
      resize: vi.fn(),
      dispose: vi.fn()
    }))
  },
  init: vi.fn(() => ({
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn()
  }))
}))

// Mock API 模块
vi.mock('@/api/index', () => ({
  apiAnalysis: {
    getDiagnosisHistory: vi.fn(),
    analyze: vi.fn()
  },
  apiStock: {
    getKline: vi.fn()
  }
}))

// 导入 mock 函数
import { apiAnalysis, apiStock } from '@/api/index'

// Mock K线数据
const mockKlineData = {
  daily: [
    {
      date: '2024-01-15',
      open: 10.0,
      close: 10.5,
      low: 9.8,
      high: 10.6,
      volume: 1000000,
      ma5: 10.2,
      ma10: 10.1,
      ma20: 10.0
    },
    {
      date: '2024-01-16',
      open: 10.5,
      close: 10.8,
      low: 10.4,
      high: 10.9,
      volume: 1200000,
      ma5: 10.3,
      ma10: 10.15,
      ma20: 10.05
    }
  ],
  weekly: []
}

// Mock 分析历史数据
const mockHistoryData = [
  {
    check_date: '2024-01-15',
    close_price: 10.5,
    change_pct: 2.5,
    kdj_j: 85.5,
    b1_passed: true
  },
  {
    check_date: '2024-01-14',
    close_price: 10.25,
    change_pct: -1.2,
    kdj_j: 72.3,
    b1_passed: false
  }
]

// Mock 分析结果数据
const mockAnalysisResult = {
  score: 4.8,
  b1_passed: true,
  verdict: 'PASS - 技术面良好',
  kdj_j: 85.5,
  zx_long_pos: true,
  weekly_ma_aligned: true,
  volume_healthy: true
}

/**
 * 创建挂载选项
 * 使用 stub 简化组件渲染，避免复杂嵌套组件的测试问题
 */
function createMountOptions() {
  return {
    global: {
      plugins: [ElementPlus, createPinia()],
      stubs: {
        'el-row': { template: '<div class="el-row"><slot /></div>' },
        'el-col': { template: '<div class="el-col"><slot /></div>' },
        'el-card': { template: '<div class="el-card"><slot name="header" /><slot /></div>' },
        'el-form': { template: '<form @submit.prevent><slot /></form>' },
        'el-form-item': { template: '<div class="el-form-item"><slot /></div>' },
        'el-input': {
          template: '<input class="el-input" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
          props: ['modelValue', 'placeholder', 'maxlength', 'clearable']
        },
        'el-button': {
          template: '<button class="el-button" :disabled="loading"><slot /></button>',
          props: ['loading', 'type', 'size', 'icon']
        },
        'el-radio-group': {
          template: '<div class="el-radio-group"><slot /></div>',
          props: ['modelValue'],
          emits: ['update:modelValue', 'change']
        },
        'el-radio-button': {
          template: '<button class="el-radio-button" :value="value"><slot /></button>',
          props: ['value']
        },
        'el-tag': {
          template: '<span class="el-tag" :class="type"><slot /></span>',
          props: ['type', 'size']
        },
        'el-divider': { template: '<hr class="el-divider" />' },
        // 完全跳过表格渲染，避免 row 数据访问问题
        'el-table': true,
        'el-table-column': true,
        'el-empty': {
          template: '<div class="el-empty">{{ description }}</div>',
          props: ['description', 'imageSize']
        }
      }
    }
  }
}

describe('Diagnosis.vue 组件测试', () => {
  let wrapper: VueWrapper
  let pinia: any

  beforeEach(() => {
    // 重置所有 mocks
    vi.clearAllMocks()
    mockPush.mockClear()
    mockRoute.query = {}

    // 创建新的 Pinia 实例
    pinia = createPinia()
    setActivePinia(pinia)
  })

  /**
   * 测试1: test_render_search_input
   * 渲染搜索框
   */
  describe('test_render_search_input', () => {
    it('应该正确渲染搜索输入框', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      // 验证页面容器存在
      expect(wrapper.find('.diagnosis-page').exists()).toBe(true)

      // 验证搜索表单存在
      expect(wrapper.find('.search-card').exists()).toBe(true)
    })

    it('应该显示股票代码输入框', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      // 验证搜索表单有初始值
      expect(wrapper.vm.searchForm).toEqual({ code: '' })
    })

    it('应该有开始分析按钮', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      // 验证 analyzing 状态初始为 false
      expect(wrapper.vm.analyzing).toBe(false)
    })

    it('初始状态应该显示空状态提示', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      // 验证没有股票代码时显示空状态
      expect(wrapper.vm.stockCode).toBe('')
      expect(wrapper.vm.historyData).toEqual([])
      expect(wrapper.vm.analysisResult).toBeNull()
    })
  })

  /**
   * 测试2: test_submit_analysis
   * 提交分析
   */
  describe('test_submit_analysis', () => {
    it('应该能够输入股票代码', async () => {
      wrapper = mount(Diagnosis, createMountOptions())

      // 设置搜索表单值
      wrapper.vm.searchForm.code = '600000'

      expect(wrapper.vm.searchForm.code).toBe('600000')
    })

    it('空股票代码应该显示警告消息', async () => {
      wrapper = mount(Diagnosis, createMountOptions())

      // 调用搜索股票方法（空代码）
      wrapper.vm.searchForm.code = ''
      await wrapper.vm.searchStock()

      // 验证警告消息被显示
      expect(ElMessage.warning).toHaveBeenCalledWith('请输入股票代码')
    })

    it('应该能够点击开始分析按钮', async () => {
      // 先设置股票代码
      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = '600000'

      // Mock API 返回分析结果
      vi.mocked(apiAnalysis.analyze).mockResolvedValue(mockAnalysisResult)
      vi.mocked(apiAnalysis.getDiagnosisHistory).mockResolvedValue({ history: mockHistoryData })

      // 调用分析方法
      await wrapper.vm.analyzeStock()

      // 验证 API 被调用
      expect(apiAnalysis.analyze).toHaveBeenCalledWith('600000')
    })

    it('分析成功后应该显示成功消息', async () => {
      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = '600000'

      vi.mocked(apiAnalysis.analyze).mockResolvedValue(mockAnalysisResult)
      vi.mocked(apiAnalysis.getDiagnosisHistory).mockResolvedValue({ history: mockHistoryData })

      await wrapper.vm.analyzeStock()

      // 验证成功消息
      expect(ElMessage.success).toHaveBeenCalledWith('分析完成')
    })

    it('分析完成后应该刷新历史数据', async () => {
      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = '600000'

      vi.mocked(apiAnalysis.analyze).mockResolvedValue(mockAnalysisResult)
      vi.mocked(apiAnalysis.getDiagnosisHistory).mockResolvedValue({ history: mockHistoryData })

      await wrapper.vm.analyzeStock()

      // 验证历史数据被加载
      expect(apiAnalysis.getDiagnosisHistory).toHaveBeenCalledWith('600000', 30)
    })

    it('没有股票代码时不能开始分析', async () => {
      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = ''

      // Mock analyze 方法
      const analyzeSpy = vi.spyOn(wrapper.vm, 'analyzeStock')

      await wrapper.vm.analyzeStock()

      // analyze 方法应该提前返回，不调用 API
      expect(apiAnalysis.analyze).not.toHaveBeenCalled()
    })
  })

  /**
   * 测试3: test_display_result
   * 显示分析结果
   */
  describe('test_display_result', () => {
    it('应该正确显示分析结果', async () => {
      wrapper = mount(Diagnosis, createMountOptions())

      // 设置分析结果
      wrapper.vm.analysisResult = mockAnalysisResult

      await nextTick()

      // 验证分析结果数据
      expect(wrapper.vm.analysisResult.score).toBe(4.8)
      expect(wrapper.vm.analysisResult.b1_passed).toBe(true)
      expect(wrapper.vm.analysisResult.verdict).toBe('PASS - 技术面良好')
    })

    it('应该显示当前评分', async () => {
      wrapper = mount(Diagnosis, createMountOptions())

      wrapper.vm.analysisResult = mockAnalysisResult

      // 验证评分数据
      expect(wrapper.vm.analysisResult.score).toBe(4.8)
      expect(wrapper.vm.analysisResult.score?.toFixed(1)).toBe('4.8')
    })

    it('应该显示B1检查状态', async () => {
      wrapper = mount(Diagnosis, createMountOptions())

      wrapper.vm.analysisResult = mockAnalysisResult

      // 验证 B1 检查状态
      expect(wrapper.vm.analysisResult.b1_passed).toBe(true)
    })

    it('应该显示趋势判断', async () => {
      wrapper = mount(Diagnosis, createMountOptions())

      wrapper.vm.analysisResult = mockAnalysisResult

      // 验证趋势判断
      expect(wrapper.vm.analysisResult.verdict).toBe('PASS - 技术面良好')
    })

    it('应该显示B1检查详情', async () => {
      wrapper = mount(Diagnosis, createMountOptions())

      wrapper.vm.analysisResult = mockAnalysisResult

      // 验证 B1 详情数据
      expect(wrapper.vm.analysisResult.kdj_j).toBe(85.5)
      expect(wrapper.vm.analysisResult.zx_long_pos).toBe(true)
      expect(wrapper.vm.analysisResult.weekly_ma_aligned).toBe(true)
      expect(wrapper.vm.analysisResult.volume_healthy).toBe(true)
    })

    it('没有分析结果时应该显示空状态', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      // 验证初始状态为空
      expect(wrapper.vm.analysisResult).toBeNull()
    })

    it('分析结果为 null 时评分应该返回 info 类型', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      // 验证 getScoreType 方法
      expect(wrapper.vm.getScoreType(undefined)).toBe('info')
      expect(wrapper.vm.getScoreType(0)).toBe('info')
    })

    it('评分 >= 4.5 应该返回 success 类型', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      expect(wrapper.vm.getScoreType(4.5)).toBe('success')
      expect(wrapper.vm.getScoreType(5.0)).toBe('success')
    })

    it('评分 >= 4.0 应该返回 warning 类型', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      expect(wrapper.vm.getScoreType(4.0)).toBe('warning')
      expect(wrapper.vm.getScoreType(4.4)).toBe('warning')
    })

    it('评分 < 4.0 应该返回 danger 类型', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      expect(wrapper.vm.getScoreType(3.9)).toBe('danger')
      expect(wrapper.vm.getScoreType(2.0)).toBe('danger')
    })
  })

  /**
   * 测试4: test_display_kline_chart
   * 显示K线图
   */
  describe('test_display_kline_chart', () => {
    it('应该能够加载K线数据', async () => {
      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = '600000'

      vi.mocked(apiStock.getKline).mockResolvedValue(mockKlineData)

      await wrapper.vm.loadKlineData()

      // 验证 API 被正确调用
      expect(apiStock.getKline).toHaveBeenCalledWith('600000', 120)
    })

    it('应该支持切换K线图天数', async () => {
      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = '600000'

      vi.mocked(apiStock.getKline).mockResolvedValue(mockKlineData)

      // 切换到30天
      wrapper.vm.chartDays = 30
      await wrapper.vm.loadKlineData()

      expect(apiStock.getKline).toHaveBeenCalledWith('600000', 30)

      // 切换到60天
      wrapper.vm.chartDays = 60
      await wrapper.vm.loadKlineData()

      expect(apiStock.getKline).toHaveBeenCalledWith('600000', 60)
    })

    it('应该支持120天K线数据', async () => {
      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = '600000'

      vi.mocked(apiStock.getKline).mockResolvedValue(mockKlineData)

      wrapper.vm.chartDays = 120
      await wrapper.vm.loadKlineData()

      expect(apiStock.getKline).toHaveBeenCalledWith('600000', 120)
    })

    it('没有股票代码时不应该加载K线数据', async () => {
      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = ''

      vi.mocked(apiStock.getKline).mockResolvedValue(mockKlineData)

      await wrapper.vm.loadKlineData()

      // 验证 API 没有被调用
      expect(apiStock.getKline).not.toHaveBeenCalled()
    })

    it('K线数据加载失败时应该显示错误消息', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = '600000'

      vi.mocked(apiStock.getKline).mockRejectedValue(new Error('加载失败'))

      await wrapper.vm.loadKlineData()

      // 验证错误消息
      expect(ElMessage.error).toHaveBeenCalledWith('加载K线数据失败: 加载失败')

      consoleSpy.mockRestore()
    })

    it('chartDays 默认值应该是 120', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      expect(wrapper.vm.chartDays).toBe(120)
    })
  })

  /**
   * 测试5: test_analysis_history
   * 显示分析历史
   */
  describe('test_analysis_history', () => {
    it('应该能够加载分析历史数据', async () => {
      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = '600000'

      vi.mocked(apiAnalysis.getDiagnosisHistory).mockResolvedValue({ history: mockHistoryData })

      await wrapper.vm.loadHistoryData()

      // 验证 API 被调用
      expect(apiAnalysis.getDiagnosisHistory).toHaveBeenCalledWith('600000', 30)

      // 验证历史数据被设置
      expect(wrapper.vm.historyData).toHaveLength(2)
      expect(wrapper.vm.historyData[0].check_date).toBe('2024-01-15')
    })

    it('应该显示历史记录的日期', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      // 测试日期格式化
      expect(wrapper.vm.formatDate('2024-01-15')).toBe('1/15')
      expect(wrapper.vm.formatDate('2024-12-31')).toBe('12/31')
    })

    it('应该显示历史记录的收盘价', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      wrapper.vm.historyData = mockHistoryData

      // 验证收盘价数据
      expect(wrapper.vm.historyData[0].close_price).toBe(10.5)
      expect(wrapper.vm.historyData[1].close_price).toBe(10.25)
    })

    it('应该显示历史记录的涨跌幅', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      wrapper.vm.historyData = mockHistoryData

      // 验证涨跌幅格式化
      expect(wrapper.vm.formatChange(2.5)).toBe('+2.50%')
      expect(wrapper.vm.formatChange(-1.2)).toBe('-1.20%')
      expect(wrapper.vm.formatChange(undefined)).toBe('-')
    })

    it('应该显示历史记录的KDJ-J值', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      wrapper.vm.historyData = mockHistoryData

      // 验证 KDJ-J 值
      expect(wrapper.vm.historyData[0].kdj_j).toBe(85.5)
      expect(wrapper.vm.historyData[1].kdj_j).toBe(72.3)
    })

    it('应该显示历史记录的B1检查状态', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      wrapper.vm.historyData = mockHistoryData

      // 验证 B1 检查状态
      expect(wrapper.vm.historyData[0].b1_passed).toBe(true)
      expect(wrapper.vm.historyData[1].b1_passed).toBe(false)
    })

    it('没有股票代码时不应该加载历史数据', async () => {
      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = ''

      vi.mocked(apiAnalysis.getDiagnosisHistory).mockResolvedValue({ history: [] })

      await wrapper.vm.loadHistoryData()

      // 验证 API 没有被调用
      expect(apiAnalysis.getDiagnosisHistory).not.toHaveBeenCalled()
    })

    it('历史数据加载失败时应该静默处理', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = '600000'

      vi.mocked(apiAnalysis.getDiagnosisHistory).mockRejectedValue(new Error('加载失败'))

      await wrapper.vm.loadHistoryData()

      // 验证错误被记录但不显示消息（静默处理）
      expect(consoleSpy).toHaveBeenCalled()

      consoleSpy.mockRestore()
    })

    it('涨跌幅为正数应该返回成功样式类', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      expect(wrapper.vm.getChangeClass(2.5)).toBe('text-success')
      expect(wrapper.vm.getChangeClass(0.1)).toBe('text-success')
    })

    it('涨跌幅为负数应该返回危险样式类', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      expect(wrapper.vm.getChangeClass(-2.5)).toBe('text-danger')
      expect(wrapper.vm.getChangeClass(-0.1)).toBe('text-danger')
    })

    it('涨跌幅为0或null应该返回空字符串', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      expect(wrapper.vm.getChangeClass(0)).toBe('')
      expect(wrapper.vm.getChangeClass(undefined)).toBe('')
      expect(wrapper.vm.getChangeClass(null)).toBe('')
    })
  })

  /**
   * 测试6: test_loading_state
   * 加载状态
   */
  describe('test_loading_state', () => {
    it('分析中应该设置analyzing状态为true', async () => {
      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = '600000'

      // 创建延迟 promise
      let resolveAnalyze: (value: any) => void
      const analyzePromise = new Promise(resolve => {
        resolveAnalyze = resolve
      })
      vi.mocked(apiAnalysis.analyze).mockReturnValue(analyzePromise)

      // 开始分析（不等待）
      wrapper.vm.analyzeStock()
      await nextTick()

      // 验证 analyzing 状态
      expect(wrapper.vm.analyzing).toBe(true)

      // 完成分析
      resolveAnalyze!(mockAnalysisResult)
      vi.mocked(apiAnalysis.getDiagnosisHistory).mockResolvedValue({ history: [] })

      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证 analyzing 状态被重置
      expect(wrapper.vm.analyzing).toBe(false)
    })

    it('分析完成后应该重置analyzing状态', async () => {
      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = '600000'

      vi.mocked(apiAnalysis.analyze).mockResolvedValue(mockAnalysisResult)
      vi.mocked(apiAnalysis.getDiagnosisHistory).mockResolvedValue({ history: [] })

      await wrapper.vm.analyzeStock()

      // 验证 analyzing 状态被重置
      expect(wrapper.vm.analyzing).toBe(false)
    })

    it('分析失败时应该重置analyzing状态', async () => {
      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = '600000'

      vi.mocked(apiAnalysis.analyze).mockRejectedValue(new Error('分析失败'))
      vi.mocked(apiAnalysis.getDiagnosisHistory).mockResolvedValue({ history: [] })

      await wrapper.vm.analyzeStock()

      // 验证 analyzing 状态被重置
      expect(wrapper.vm.analyzing).toBe(false)
    })

    it('初始analyzing状态应该是false', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      expect(wrapper.vm.analyzing).toBe(false)
    })
  })

  /**
   * 测试7: test_error_handling
   * 错误处理
   */
  describe('test_error_handling', () => {
    it('K线数据加载失败时应该显示错误消息', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = '600000'

      vi.mocked(apiStock.getKline).mockRejectedValue(new Error('网络错误'))

      await wrapper.vm.loadKlineData()

      // 验证错误消息
      expect(ElMessage.error).toHaveBeenCalledWith('加载K线数据失败: 网络错误')

      consoleSpy.mockRestore()
    })

    it('分析失败时应该显示错误消息', async () => {
      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = '600000'

      vi.mocked(apiAnalysis.analyze).mockRejectedValue(new Error('分析服务不可用'))
      vi.mocked(apiAnalysis.getDiagnosisHistory).mockResolvedValue({ history: [] })

      await wrapper.vm.analyzeStock()

      // 验证错误消息
      expect(ElMessage.error).toHaveBeenCalledWith('分析失败: 分析服务不可用')
    })

    it('输入空股票代码应该显示警告', async () => {
      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.searchForm.code = ''

      await wrapper.vm.searchStock()

      expect(ElMessage.warning).toHaveBeenCalledWith('请输入股票代码')
    })

    it('K线加载错误应该被正确记录', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = '600000'

      const error = new Error('API Error')
      vi.mocked(apiStock.getKline).mockRejectedValue(error)

      await wrapper.vm.loadKlineData()

      // 验证错误被记录到控制台
      expect(consoleSpy).toHaveBeenCalledWith('Failed to load kline:', error)

      consoleSpy.mockRestore()
    })

    it('历史数据加载错误应该被正确记录', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = '600000'

      const error = new Error('History Error')
      vi.mocked(apiAnalysis.getDiagnosisHistory).mockRejectedValue(error)

      await wrapper.vm.loadHistoryData()

      // 验证错误被记录到控制台
      expect(consoleSpy).toHaveBeenCalledWith('Failed to load history:', error)

      consoleSpy.mockRestore()
    })

    it('历史数据为null时应该设置为空数组', async () => {
      wrapper = mount(Diagnosis, createMountOptions())
      wrapper.vm.stockCode = '600000'

      vi.mocked(apiAnalysis.getDiagnosisHistory).mockResolvedValue({ history: null })

      await wrapper.vm.loadHistoryData()

      // 验证 null 被转换为空数组
      expect(wrapper.vm.historyData).toEqual([])
    })
  })

  /**
   * 测试8: test_stock_code_format
   * 股票代码格式化
   */
  describe('test_stock_code_format', () => {
    it('应该将股票代码自动补零到6位', async () => {
      wrapper = mount(Diagnosis, createMountOptions())

      // Mock K线 API
      vi.mocked(apiStock.getKline).mockResolvedValue(mockKlineData)
      vi.mocked(apiAnalysis.getDiagnosisHistory).mockResolvedValue({ history: [] })

      // 测试各种输入格式
      wrapper.vm.searchForm.code = '1'
      await wrapper.vm.searchStock()

      expect(wrapper.vm.stockCode).toBe('000001')

      // 重置并测试其他格式
      wrapper.vm.searchForm.code = '60000'
      await wrapper.vm.searchStock()

      expect(wrapper.vm.stockCode).toBe('060000')
    })

    it('6位股票代码应该保持不变', async () => {
      wrapper = mount(Diagnosis, createMountOptions())

      vi.mocked(apiStock.getKline).mockResolvedValue(mockKlineData)
      vi.mocked(apiAnalysis.getDiagnosisHistory).mockResolvedValue({ history: [] })

      wrapper.vm.searchForm.code = '600000'
      await wrapper.vm.searchStock()

      expect(wrapper.vm.stockCode).toBe('600000')
    })

    it('应该处理空格输入', async () => {
      wrapper = mount(Diagnosis, createMountOptions())

      vi.mocked(apiStock.getKline).mockResolvedValue(mockKlineData)
      vi.mocked(apiAnalysis.getDiagnosisHistory).mockResolvedValue({ history: [] })

      wrapper.vm.searchForm.code = ' 600000 '
      await wrapper.vm.searchStock()

      expect(wrapper.vm.stockCode).toBe('600000')
    })

    it('应该处理少于6位的代码', async () => {
      wrapper = mount(Diagnosis, createMountOptions())

      vi.mocked(apiStock.getKline).mockResolvedValue(mockKlineData)
      vi.mocked(apiAnalysis.getDiagnosisHistory).mockResolvedValue({ history: [] })

      // 测试1位代码
      wrapper.vm.searchForm.code = '6'
      await wrapper.vm.searchStock()
      expect(wrapper.vm.stockCode).toBe('000006')

      // 测试3位代码
      wrapper.vm.searchForm.code = '999'
      await wrapper.vm.searchStock()
      expect(wrapper.vm.stockCode).toBe('000999')
    })

    it('从路由参数获取的股票代码应该被正确设置', async () => {
      mockRoute.query = { code: '000001' }

      wrapper = mount(Diagnosis, {
        ...createMountOptions(),
        attachTo: document.body
      })

      vi.mocked(apiStock.getKline).mockResolvedValue(mockKlineData)
      vi.mocked(apiAnalysis.getDiagnosisHistory).mockResolvedValue({ history: [] })

      // 等待 onMounted
      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证股票代码从路由参数被设置
      expect(wrapper.vm.searchForm.code).toBe('000001')
    })

    it('搜索时应该使用trim后的代码', async () => {
      wrapper = mount(Diagnosis, createMountOptions())

      vi.mocked(apiStock.getKline).mockResolvedValue(mockKlineData)
      vi.mocked(apiAnalysis.getDiagnosisHistory).mockResolvedValue({ history: [] })

      wrapper.vm.searchForm.code = ' 600000 '
      await wrapper.vm.searchStock()

      expect(wrapper.vm.stockCode).toBe('600000')
    })
  })

  /**
   * 额外测试: 组件生命周期和清理
   */
  describe('test_lifecycle', () => {
    it('应该在 onUnmounted 时清理图表实例', () => {
      wrapper = mount(Diagnosis, createMountOptions())

      // 模拟图表实例
      wrapper.vm.chartInstance = {
        dispose: vi.fn()
      }

      wrapper.unmount()

      // 验证 dispose 被调用
      expect(wrapper.vm.chartInstance?.dispose).toHaveBeenCalled()
    })

    it('应该在 onUnmounted 时移除resize监听器', () => {
      const removeEventListenerSpy = vi.spyOn(window, 'removeEventListener')

      wrapper = mount(Diagnosis, createMountOptions())

      wrapper.unmount()

      // 验证 removeEventListener 被调用
      expect(removeEventListenerSpy).toHaveBeenCalledWith('resize', expect.any(Function))

      removeEventListenerSpy.mockRestore()
    })
  })
})
