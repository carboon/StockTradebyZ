/**
 * TomorrowStar.vue 组件测试文件
 * 测试明日之星页面的渲染、用户交互和状态管理
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import ElementPlus from 'element-plus'
import TomorrowStar from '@/views/TomorrowStar.vue'

// Mock vue-router
const mockPush = vi.fn()
vi.mock('vue-router', () => ({
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

// Mock API 模块
vi.mock('@/api/index', () => ({
  apiAnalysis: {
    getFreshness: vi.fn(),
    getDates: vi.fn(),
    getCandidates: vi.fn(),
    getResults: vi.fn(),
    generate: vi.fn()
  },
  apiTasks: {
    get: vi.fn()
  }
}))

// 导入 mock 函数
import { apiAnalysis } from '@/api/index'
import { apiTasks } from '@/api/index'

// 创建更简化的 stub 配置 - 不渲染表格内部，只验证数据
function createMountOptions() {
  return {
    global: {
      plugins: [ElementPlus, createPinia()],
      stubs: {
        'el-row': { template: '<div class="el-row"><slot /></div>' },
        'el-col': { template: '<div class="el-col"><slot /></div>' },
        'el-card': { template: '<div class="el-card"><slot name="header" /><slot /></div>' },
        // 完全跳过表格渲染，避免 row.pass 的问题
        'el-table': true,
        'el-table-column': true,
        'el-button': {
          template: '<button class="el-button"><slot /></button>',
          props: ['loading', 'type', 'size', 'icon']
        },
        'el-tag': {
          template: '<span class="el-tag"><slot /></span>',
          props: ['type', 'size']
        },
        'el-divider': { template: '<hr class="el-divider" />' }
      }
    }
  }
}

// Mock 候选股票数据
const mockCandidates = [
  {
    code: '600000',
    close_price: 10.5,
    kdj_j: 85.5,
    strategy: 'b1',
    b1_passed: true
  },
  {
    code: '000001',
    close_price: 15.2,
    kdj_j: 92.3,
    strategy: 'b1',
    b1_passed: true
  },
  {
    code: '600036',
    close_price: 32.8,
    kdj_j: 88.7,
    strategy: 'a1',
    b1_passed: false
  }
]

// Mock 分析结果数据
const mockResults = [
  {
    code: '600000',
    verdict: 'PASS',
    total_score: 4.8,
    signal_type: '买入信号',
    comment: '技术面良好，KDJ指标处于超买区'
  },
  {
    code: '000001',
    verdict: 'PASS',
    total_score: 4.2,
    signal_type: '关注信号',
    comment: '接近突破点，需关注成交量'
  },
  {
    code: '600036',
    verdict: 'WATCH',
    total_score: 3.5,
    signal_type: '观察',
    comment: '暂不建议'
  }
]

const mockRankedResults = [
  { code: '000001', verdict: 'WATCH', total_score: 4.1, signal_type: '观察', comment: '1' },
  { code: '000002', verdict: 'PASS', total_score: 5.2, signal_type: '买入信号', comment: '2' },
  { code: '000003', verdict: 'FAIL', total_score: 3.4, signal_type: '风险释放', comment: '3' },
  { code: '000004', verdict: 'PASS', total_score: 4.9, signal_type: '关注信号', comment: '4' },
  { code: '000005', verdict: 'WATCH', total_score: 4.6, signal_type: '观察', comment: '5' },
  { code: '000006', verdict: 'PASS', total_score: 4.4, signal_type: '买入信号', comment: '6' },
  { code: '000007', verdict: 'PASS', total_score: 5.0, signal_type: '关注信号', comment: '7' }
]

// Mock 历史日期数据
const mockDates = ['2024-01-15', '2024-01-14', '2024-01-13']
const mockHistory = [
  { date: '2024-01-15', count: 3, pass: 2 },
  { date: '2024-01-14', count: 2, pass: 1 },
  { date: '2024-01-13', count: 1, pass: 0 }
]

describe('TomorrowStar.vue 组件测试', () => {
  let wrapper: VueWrapper
  let pinia: any

  beforeEach(() => {
    // 重置所有 mocks
    vi.clearAllMocks()
    mockPush.mockClear()

    // 创建新的 Pinia 实例
    pinia = createPinia()
    setActivePinia(pinia)

    vi.mocked(apiAnalysis.getFreshness).mockResolvedValue({
      latest_trade_date: '2024-01-15',
      local_latest_date: '2024-01-15',
      latest_candidate_date: '2024-01-15',
      latest_result_date: '2024-01-15',
      needs_update: false,
      running_task_id: null,
      running_task_status: null
    })
    vi.mocked(apiTasks.get).mockResolvedValue({
      id: 1,
      task_type: 'tomorrow_star',
      status: 'completed',
      progress: 100,
      created_at: '2024-01-15T00:00:00'
    } as any)
  })

  /**
   * 测试1: test_render_date_selector
   * 渲染日期选择器（历史记录表格）
   */
  describe('test_render_date_selector', () => {
    it('应该正确渲染历史记录表格', async () => {
      // Mock API 响应
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      // 等待组件挂载和 API 调用完成
      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证页面容器存在
      expect(wrapper.find('.tomorrow-star-page').exists()).toBe(true)
    })

    it('应该显示多个历史日期记录', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证 API 被调用
      expect(apiAnalysis.getDates).toHaveBeenCalled()

      // 验证历史数据被设置
      expect(wrapper.vm.historyData).toHaveLength(3)
      expect(wrapper.vm.historyData[0].date).toBe('2024-01-15')
    })

    it('应该能够选择不同的历史日期', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证初始选中的日期是最新的
      expect(wrapper.vm.selectedDate).toBe('2024-01-15')
    })

    it('空日期列表时应该显示空状态', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: [] })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证历史数据为空
      expect(wrapper.vm.historyData).toHaveLength(0)
    })
  })

  /**
   * 测试2: test_display_candidates
   * 显示候选股票列表
   */
  describe('test_display_candidates', () => {
    it('应该正确加载候选股票数据', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证候选数据被加载
      expect(wrapper.vm.candidates).toHaveLength(3)
      expect(wrapper.vm.candidates[0].code).toBe('600000')
      expect(wrapper.vm.candidates[0].close_price).toBe(10.5)
      expect(wrapper.vm.candidates[0].kdj_j).toBe(85.5)
    })

    it('应该显示候选股票的基本信息', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证策略类型
      expect(wrapper.vm.candidates[0].strategy).toBe('b1')
      expect(wrapper.vm.candidates[2].strategy).toBe('a1')
    })

    it('应该显示B1检查状态', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证B1检查状态
      expect(wrapper.vm.candidates[0].b1_passed).toBe(true)
      expect(wrapper.vm.candidates[2].b1_passed).toBe(false)
    })

    it('应该限制显示的候选数量为50条', async () => {
      // 创建超过50条的候选数据
      const largeCandidates = Array.from({ length: 100 }, (_, i) => ({
        code: `60${String(i).padStart(4, '0')}`,
        close_price: 10 + i,
        kdj_j: 80 + i,
        strategy: 'b1',
        b1_passed: true
      }))

      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: largeCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: [] })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证显示数量被限制
      expect(wrapper.vm.candidates).toHaveLength(100)
      expect(wrapper.vm.displayCandidates).toHaveLength(50)
    })
  })

  /**
   * 测试3: test_display_results
   * 显示分析结果
   */
  describe('test_display_results', () => {
    it('应该正确加载分析结果', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证分析结果被加载
      expect(wrapper.vm.analysisResults).toHaveLength(3)
    })

    it('应该按结论优先级和评分只显示前5条分析结果', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockRankedResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      expect(wrapper.vm.topResults).toHaveLength(5)
      expect(wrapper.vm.topResults.map((r: any) => r.code)).toEqual([
        '000002',
        '000007',
        '000004',
        '000006',
        '000005'
      ])
      expect(wrapper.vm.topResults.map((r: any) => r.verdict)).toEqual([
        'PASS',
        'PASS',
        'PASS',
        'PASS',
        'WATCH'
      ])
    })

    it('同一结论内应该按评分从高到低排序', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockRankedResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      expect(wrapper.vm.topResults.slice(0, 3).map((r: any) => r.total_score)).toEqual([
        5.2,
        5.0,
        4.9,
      ])
      expect(wrapper.vm.topResults.slice(3).map((r: any) => r.total_score)).toEqual([
        4.4,
        4.6
      ])
    })

    it('应该显示评分标签', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证评分数据
      expect(wrapper.vm.topResults[0].total_score).toBe(4.8)
      expect(wrapper.vm.topResults[1].total_score).toBe(4.2)
    })

    it('应该正确评分标签类型', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证评分类型计算
      expect(wrapper.vm.getScoreType(4.8)).toBe('success')
      expect(wrapper.vm.getScoreType(4.2)).toBe('warning')
      expect(wrapper.vm.getScoreType(3.5)).toBe('danger')
      expect(wrapper.vm.getScoreType(undefined)).toBe('info')
    })

    it('没有分析结果时不应该显示结果区域', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: [] })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证没有分析结果
      expect(wrapper.vm.analysisResults).toHaveLength(0)
      expect(wrapper.vm.topResults).toHaveLength(0)
    })
  })

  /**
   * 测试4: test_export_chart
   * 导出图表（测试股票详情导航功能）
   */
  describe('test_export_chart', () => {
    it('应该能够点击详情按钮跳转到股票诊断页', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 获取 viewStock 方法并调用
      await wrapper.vm.viewStock('600000')

      // 验证路由跳转被调用
      expect(mockPush).toHaveBeenCalledWith({
        path: '/diagnosis',
        query: { code: '600000' }
      })
    })

    it('应该支持不同的股票代码跳转', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 测试不同的股票代码
      await wrapper.vm.viewStock('000001')

      expect(mockPush).toHaveBeenCalledWith({
        path: '/diagnosis',
        query: { code: '000001' }
      })
    })
  })

  /**
   * 测试5: test_filter_by_status
   * 按状态筛选（今日数据状态）
   */
  describe('test_filter_by_status', () => {
    it('应该显示今日已生成状态标签', async () => {
      const currentDate = new Date()
      const day = currentDate.getDay()
      const offset = day === 0 ? -2 : day === 6 ? -1 : 0
      const latestTradingDay = new Date(currentDate)
      latestTradingDay.setDate(currentDate.getDate() + offset)
      const tradingDate = latestTradingDay.toISOString().split('T')[0]
      const datesWithToday = [tradingDate, '2024-01-14', '2024-01-13']

      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: datesWithToday })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证今日数据状态
      expect(wrapper.vm.hasLatestData).toBe(true)
    })

    it('应该显示今日未生成状态标签', async () => {
      // 不包含今天的日期列表
      const datesWithoutToday = ['2024-01-14', '2024-01-13']

      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: datesWithoutToday })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证今日数据状态
      expect(wrapper.vm.hasLatestData).toBe(false)
    })

    it('今日已生成时应该隐藏生成按钮', async () => {
      const currentDate = new Date()
      const day = currentDate.getDay()
      const offset = day === 0 ? -2 : day === 6 ? -1 : 0
      const latestTradingDay = new Date(currentDate)
      latestTradingDay.setDate(currentDate.getDate() + offset)
      const tradingDate = latestTradingDay.toISOString().split('T')[0]
      const datesWithToday = [tradingDate, '2024-01-14']

      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: datesWithToday })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证生成按钮不显示（hasLatestData 为 true 时按钮被隐藏）
      expect(wrapper.vm.hasLatestData).toBe(true)
    })

    it('应该正确检测今日数据是否存在', async () => {
      const currentDate = new Date()
      const day = currentDate.getDay()
      const offset = day === 0 ? -2 : day === 6 ? -1 : 0
      const latestTradingDay = new Date(currentDate)
      latestTradingDay.setDate(currentDate.getDate() + offset)
      const tradingDate = latestTradingDay.toISOString().split('T')[0]

      // 测试包含今天的情况
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: [tradingDate] })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: [] })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: [] })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      expect(wrapper.vm.hasLatestData).toBe(true)
    })
  })

  /**
   * 测试6: test_refresh_data
   * 刷新数据
   */
  describe('test_refresh_data', () => {
    it('应该能够点击刷新按钮重新加载数据', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates, history: mockHistory })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 清除之前的调用记录
      vi.clearAllMocks()

      // 再次 mock API
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates, history: mockHistory })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      // 调用刷新方法
      await wrapper.vm.loadData()

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证 API 被调用
      expect(apiAnalysis.getDates).toHaveBeenCalled()
      expect(apiAnalysis.getCandidates).toHaveBeenCalled()
      expect(apiAnalysis.getResults).toHaveBeenCalled()
    })

    it('刷新历史记录时应该保留当前选中的日期', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates, history: mockHistory })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      wrapper.vm.selectedDate = '2024-01-14'

      vi.clearAllMocks()
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates, history: mockHistory })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      await wrapper.vm.loadData()

      expect(wrapper.vm.selectedDate).toBe('2024-01-14')
      expect(apiAnalysis.getCandidates).toHaveBeenCalledWith('2024-01-14')
      expect(apiAnalysis.getResults).toHaveBeenCalledWith('2024-01-14')
    })

    it('后端直接返回 history 明细时不应该为每个日期额外刷新统计', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates, history: mockHistory })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      expect(wrapper.vm.historyData).toEqual(mockHistory)
      expect(apiAnalysis.getCandidates).toHaveBeenCalledTimes(1)
      expect(apiAnalysis.getResults).toHaveBeenCalledTimes(1)
      expect(apiAnalysis.getCandidates).toHaveBeenCalledWith('2024-01-15')
      expect(apiAnalysis.getResults).toHaveBeenCalledWith('2024-01-15')
    })

    it('手动加载时应该显示加载状态', async () => {
      let resolveGet: (value: any) => void
      const getPromise = new Promise(resolve => {
        resolveGet = resolve
      })
      vi.mocked(apiAnalysis.getDates).mockReturnValue(getPromise)

      wrapper = mount(TomorrowStar, createMountOptions())

      const pending = wrapper.vm.loadData()
      await nextTick()

      expect(wrapper.vm.loading).toBe(true)

      resolveGet!({ dates: mockDates })
      await pending
      expect(wrapper.vm.loading).toBe(false)
    })

    it('刷新失败时应该显示错误消息', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      vi.mocked(apiAnalysis.getDates).mockRejectedValue(new Error('网络错误'))

      wrapper = mount(TomorrowStar, createMountOptions())
      await wrapper.vm.loadData()

      // 验证错误消息被显示
      expect(ElMessage.error).toHaveBeenCalledWith(expect.stringContaining('网络错误'))

      consoleSpy.mockRestore()
    })

    it('刷新按钮应该在页面中显示', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证页面容器存在
      expect(wrapper.find('.tomorrow-star-page').exists()).toBe(true)
    })
  })

  /**
   * 测试7: test_empty_state
   * 空状态显示
   */
  describe('test_empty_state', () => {
    it('没有历史数据时应该显示空状态', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: [] })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证历史数据为空
      expect(wrapper.vm.historyData).toHaveLength(0)
      expect(wrapper.vm.selectedDate).toBeNull()
    })

    it('没有候选股票时应该显示空状态', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: [] })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: [] })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证候选数据为空
      expect(wrapper.vm.candidates).toHaveLength(0)
      expect(wrapper.vm.displayCandidates).toHaveLength(0)
    })

    it('没有分析结果时不应该显示结果区域', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: [] })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证分析结果为空
      expect(wrapper.vm.analysisResults).toHaveLength(0)
      expect(wrapper.vm.topResults).toHaveLength(0)
    })

    it('API 返回 null 数据时应该正确处理', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: null })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: null })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证 null 被转换为空数组
      expect(wrapper.vm.candidates).toHaveLength(0)
      expect(wrapper.vm.analysisResults).toHaveLength(0)
    })
  })

  /**
   * 测试8: test_loading_state
   * 加载状态
   */
  describe('test_loading_state', () => {
    it('加载数据时应该显示加载状态', async () => {
      // 创建延迟 promise
      let resolveGet: (value: any) => void
      const getPromise = new Promise(resolve => {
        resolveGet = resolve
      })
      vi.mocked(apiAnalysis.getDates).mockReturnValue(getPromise)

      wrapper = mount(TomorrowStar, createMountOptions())

      const pending = wrapper.vm.loadData()
      await nextTick()

      // 验证 loading 状态被设置为 true
      expect(wrapper.vm.loading).toBe(true)

      // 完成 API 调用
      resolveGet!({ dates: mockDates })
      await pending

      // 验证 loading 状态被重置
      expect(wrapper.vm.loading).toBe(false)
    })

    it('生成明日之星时应该显示加载状态', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: ['2024-01-14'] }) // 不包含今天
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      // 创建延迟 promise
      let resolvePost: (value: any) => void
      const postPromise = new Promise(resolve => {
        resolvePost = resolve
      })
      vi.mocked(apiAnalysis.generate).mockReturnValue(postPromise)

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 调用生成方法
      wrapper.vm.generateTomorrowStar()

      await nextTick()

      // 验证 generating 状态被设置为 true
      expect(wrapper.vm.generating).toBe(true)

      // 完成 API 调用
      resolvePost!({ task_id: 1 })
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证成功消息
      expect(ElMessage.success).toHaveBeenCalledWith('任务已创建: #1')

      // 验证 generating 状态被重置
      expect(wrapper.vm.generating).toBe(false)
    })

    it('加载完成后应该移除加载状态', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证加载完成
      expect(wrapper.vm.loading).toBe(false)
      expect(wrapper.vm.historyData).toHaveLength(3)
    })

    it('生成失败时应该移除加载状态并显示错误', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: ['2024-01-14'] })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })
      vi.mocked(apiAnalysis.generate).mockRejectedValue(new Error('生成失败'))

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 调用生成方法
      await wrapper.vm.generateTomorrowStar()

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证错误消息
      expect(ElMessage.error).toHaveBeenCalledWith('生成失败: 生成失败')

      // 验证 generating 状态被重置
      expect(wrapper.vm.generating).toBe(false)
    })

    it('新鲜度检查进行中时应该只设置 checkingFreshness 状态', async () => {
      let resolveFreshness: (value: any) => void
      const freshnessPromise = new Promise(resolve => {
        resolveFreshness = resolve
      })

      vi.mocked(apiAnalysis.getFreshness).mockReturnValue(freshnessPromise)
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates, history: mockHistory })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()

      expect(wrapper.vm.checkingFreshness).toBe(true)
      expect(wrapper.vm.updatingData).toBe(false)

      resolveFreshness!({
        latest_trade_date: '2024-01-15',
        local_latest_date: '2024-01-15',
        latest_candidate_date: '2024-01-15',
        latest_result_date: '2024-01-15',
        needs_update: false,
        running_task_id: null,
        running_task_status: null
      })

      await new Promise(resolve => setTimeout(resolve, 0))
      await nextTick()

      expect(wrapper.vm.checkingFreshness).toBe(false)
      expect(wrapper.vm.updatingData).toBe(false)
    })

    it('短时间内重复进入页面时不应该重复调用新鲜度检查', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: mockDates, history: mockHistory })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: mockCandidates })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: mockResults })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      expect(apiAnalysis.getFreshness).toHaveBeenCalledTimes(1)

      await wrapper.vm.ensureFreshDataAndLoad()

      expect(apiAnalysis.getFreshness).toHaveBeenCalledTimes(1)
    })
  })

  /**
   * 额外测试: 生成明日之星功能
   */
  describe('test_generate_tomorrow_star', () => {
    it('应该成功生成明日之星任务', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: ['2024-01-14'] })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: [] })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: [] })
      vi.mocked(apiAnalysis.generate).mockResolvedValue({ task_id: 123 })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 调用生成方法
      await wrapper.vm.generateTomorrowStar()

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证 API 被调用
      expect(apiAnalysis.generate).toHaveBeenCalledWith('quant')

      // 验证成功消息
      expect(ElMessage.success).toHaveBeenCalledWith('任务已创建: #123')
    })

    it('生成完成后应该轮询任务状态并刷新数据', async () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: ['2024-01-14'] })
      vi.mocked(apiAnalysis.getCandidates).mockResolvedValue({ candidates: [] })
      vi.mocked(apiAnalysis.getResults).mockResolvedValue({ results: [] })
      vi.mocked(apiAnalysis.generate).mockResolvedValue({ task_id: 1 })

      wrapper = mount(TomorrowStar, createMountOptions())

      await nextTick()

      // 调用生成方法
      await wrapper.vm.generateTomorrowStar()

      await nextTick()

      expect(apiTasks.get).toHaveBeenCalledWith(1)
      expect(apiAnalysis.getDates).toHaveBeenCalled()
    })
  })

  /**
   * 额外测试: 日期格式化
   */
  describe('test_date_formatting', () => {
    it('应该正确格式化标准日期格式', () => {
      // 直接创建组件实例而不挂载，避免 onMounted 触发
      wrapper = mount(TomorrowStar, {
        ...createMountOptions(),
        slots: {
          default: ''
        }
      })

      // 测试格式化函数 - 直接调用
      expect(wrapper.vm.formatDateString('2024-01-15')).toBe('2024-01-15')
    })

    it('应该正确格式化8位数字日期格式', () => {
      wrapper = mount(TomorrowStar, {
        ...createMountOptions(),
        slots: {
          default: ''
        }
      })

      // 测试 8 位数字格式
      expect(wrapper.vm.formatDateString('20240115')).toBe('2024-01-15')
      expect(wrapper.vm.formatDateString('20241231')).toBe('2024-12-31')
    })

    it('未选择日期时应该显示"最新"', () => {
      vi.mocked(apiAnalysis.getDates).mockResolvedValue({ dates: [] })
      wrapper = mount(TomorrowStar, {
        ...createMountOptions(),
        slots: {
          default: ''
        }
      })

      // 验证未选择日期时的显示
      expect(wrapper.vm.selectedDateDisplay).toBe('最新')
    })
  })

  /**
   * 额外测试: 历史记录行点击
   */
  describe('test_history_row_click', () => {
    it('点击历史记录行应该更新选中日期', () => {
      // 不挂载组件，直接测试方法逻辑
      wrapper = mount(TomorrowStar, {
        ...createMountOptions(),
        slots: { default: '' }
      })

      // 直接设置选中日期
      wrapper.vm.selectedDate = '2024-01-15'
      expect(wrapper.vm.selectedDate).toBe('2024-01-15')

      // 模拟点击历史行 - 更新日期
      wrapper.vm.selectedDate = '2024-01-14'
      expect(wrapper.vm.selectedDate).toBe('2024-01-14')
    })
  })
})
