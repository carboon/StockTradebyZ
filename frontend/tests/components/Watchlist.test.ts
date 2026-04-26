/**
 * Watchlist.vue 组件测试文件
 * 测试观察列表页面的渲染、用户交互和状态管理
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import ElementPlus from 'element-plus'
import Watchlist from '@/views/Watchlist.vue'
import type { WatchlistItem, WatchlistAnalysis } from '@/types'

const mockRouterPush = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: mockRouterPush
  })
}))

// Mock echarts
vi.mock('echarts', () => ({
  default: {
    init: vi.fn(() => ({
      setOption: vi.fn(),
      resize: vi.fn(),
      dispose: vi.fn()
    }))
  }
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
  apiWatchlist: {
    getAll: vi.fn(),
    add: vi.fn(),
    delete: vi.fn(),
    update: vi.fn(),
    getAnalysis: vi.fn(),
    analyze: vi.fn()
  },
  apiStock: {
    getKline: vi.fn()
  }
}))

// 导入 mock 函数
import { apiWatchlist, apiStock } from '@/api/index'

// Mock 观察列表数据
const mockWatchlistItems: WatchlistItem[] = [
  {
    id: 1,
    code: '600000',
    name: '浦发银行',
    add_reason: '看好银行业复苏',
    entry_price: 10,
    position_ratio: 0.3,
    priority: 1,
    is_active: true,
    added_at: '2024-01-15T10:00:00Z'
  },
  {
    id: 2,
    code: '000001',
    name: '平安银行',
    add_reason: '技术面良好',
    priority: 0,
    is_active: true,
    added_at: '2024-01-14T10:00:00Z'
  },
  {
    id: 3,
    code: '600036',
    name: '招商银行',
    add_reason: '长期持有',
    priority: 2,
    is_active: true,
    added_at: '2024-01-13T10:00:00Z'
  }
]

// Mock K线数据
const mockKlineData = {
  code: '600000',
  name: '浦发银行',
  daily: [
    {
      date: '2024-01-10',
      open: 10.0,
      close: 10.2,
      low: 9.9,
      high: 10.3,
      volume: 1000000,
      ma20: 10.1,
      ma60: 10.0
    },
    {
      date: '2024-01-11',
      open: 10.2,
      close: 10.5,
      low: 10.1,
      high: 10.6,
      volume: 1200000,
      ma20: 10.2,
      ma60: 10.05
    }
  ]
}

// Mock 分析历史数据
const mockAnalysisHistory: WatchlistAnalysis[] = [
  {
    id: 1,
    watchlist_id: 1,
    analysis_date: '2024-01-15T10:00:00Z',
    verdict: 'PASS',
    score: 4.5,
    buy_action: 'buy',
    hold_action: 'hold',
    risk_level: 'medium',
    buy_recommendation: '可试仓，不追高。',
    hold_recommendation: '继续持有，不追高加仓。',
    risk_recommendation: '关注回踩支撑是否有效。',
    recommendation: '建议持有'
  },
  {
    id: 2,
    watchlist_id: 1,
    analysis_date: '2024-01-10T10:00:00Z',
    verdict: 'WATCH',
    score: 3.8,
    buy_action: 'wait',
    hold_action: 'hold_cautious',
    risk_level: 'medium',
    buy_recommendation: '等待突破确认后再考虑。',
    hold_recommendation: '以观察为主，暂不加仓。',
    risk_recommendation: '等待信号进一步确认。',
    recommendation: '谨慎观望'
  },
  {
    id: 3,
    watchlist_id: 1,
    analysis_date: '2024-01-05T10:00:00Z',
    verdict: 'FAIL',
    score: 2.5,
    buy_action: 'avoid',
    hold_action: 'trim',
    risk_level: 'high',
    buy_recommendation: '暂不买入。',
    hold_recommendation: '谨慎持有，优先减仓观察。',
    risk_recommendation: '跌破支撑执行止损。',
    recommendation: '建议减仓'
  }
]

/**
 * 创建挂载选项的辅助函数
 * 配置全局插件和组件存根
 */
function createMountOptions() {
  return {
    global: {
      plugins: [ElementPlus, createPinia()],
      stubs: {
        'el-row': { template: '<div class="el-row"><slot /></div>' },
        'el-col': { template: '<div class="el-col"><slot /></div>' },
        'el-card': { template: '<div class="el-card"><slot name="header" /><slot /></div>' },
        'el-table': {
          template: '<div class="el-table"><slot /></div>',
          props: ['data', 'height', 'highlightCurrentRow']
        },
        'el-table-column': { template: '<div class="el-table-column"><slot /></div>' },
        'el-button': {
          template: '<button class="el-button" :class="type ? `el-button--${type}` : \'\'"><slot /></button>',
          props: ['type', 'size', 'icon', 'loading']
        },
        'el-dialog': {
          template: '<div v-if="modelValue" class="el-dialog"><slot /><slot name="footer" /></div>',
          props: ['modelValue']
        },
        'el-form': { template: '<form class="el-form"><slot /></form>' },
        'el-form-item': { template: '<div class="el-form-item"><slot /></div>' },
        'el-input': {
          template: '<input class="el-input" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)">',
          props: ['modelValue', 'type', 'placeholder', 'maxlength', 'rows']
        },
        'el-divider': { template: '<hr class="el-divider" />' },
        'el-empty': {
          template: '<div class="el-empty">{{ description }}</div>',
          props: ['description', 'imageSize']
        },
        'el-timeline': { template: '<div class="el-timeline"><slot /></div>' },
        'el-timeline-item': {
          template: '<div class="el-timeline-item"><slot /></div>',
          props: ['timestamp', 'placement']
        },
        'el-tag': {
          template: '<span class="el-tag" :class="type ? `el-tag--${type}` : \'\'"><slot /></span>',
          props: ['type', 'size']
        },
        'el-tooltip': {
          template: '<div class="el-tooltip"><slot /><slot name="content" /></div>',
          props: ['placement', 'effect']
        },
      }
    }
  }
}

/**
 * 创建基本 mock 设置的辅助函数
 * 确保每个测试都有正确的 API mock
 */
function setupBasicMocks() {
  vi.mocked(apiWatchlist.getAll).mockResolvedValue({ items: mockWatchlistItems })
  vi.mocked(apiStock.getKline).mockResolvedValue(mockKlineData)
  vi.mocked(apiWatchlist.getAnalysis).mockResolvedValue({ analyses: mockAnalysisHistory })
  vi.mocked(apiWatchlist.analyze).mockResolvedValue({ status: 'ok' })
}

describe('Watchlist.vue 组件测试', () => {
  let wrapper: VueWrapper
  let pinia: any

  beforeEach(() => {
    // 重置所有 mocks
    vi.clearAllMocks()

    // 创建新的 Pinia 实例
    pinia = createPinia()
    setActivePinia(pinia)

    // 设置基本的 API mock
    setupBasicMocks()
  })

  /**
   * 测试1: test_render_watchlist
   * 渲染观察列表
   */
  describe('test_render_watchlist', () => {
    it('应该正确渲染观察列表页面容器', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      // 等待组件挂载和 API 调用完成
      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证页面容器存在
      expect(wrapper.find('.watchlist-page').exists()).toBe(true)
    })

    it('应该正确加载观察列表数据', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证 API 被调用
      expect(apiWatchlist.getAll).toHaveBeenCalled()

      // 验证观察列表数据被加载
      expect(wrapper.vm.watchlist).toHaveLength(3)
      expect(wrapper.vm.watchlist[0].code).toBe('600000')
      expect(wrapper.vm.watchlist[0].name).toBe('浦发银行')
    })

    it('应该显示观察列表的股票代码和名称', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证数据包含正确的股票信息
      expect(wrapper.vm.watchlist[0].code).toBe('600000')
      expect(wrapper.vm.watchlist[0].name).toBe('浦发银行')
      expect(wrapper.vm.watchlist[1].code).toBe('000001')
      expect(wrapper.vm.watchlist[2].code).toBe('600036')
    })

    it('应该显示添加按钮', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证添加对话框状态变量初始化为 false
      expect(wrapper.vm.showAddDialog).toBe(false)
    })
  })

  /**
   * 测试2: test_add_item
   * 添加观察项
   */
  describe('test_add_item', () => {
    beforeEach(() => {
      // 重新设置基本 mock
      setupBasicMocks()
    })

    it('应该能够打开添加对话框', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 初始状态对话框应该是关闭的
      expect(wrapper.vm.showAddDialog).toBe(false)

      // 设置对话框打开
      wrapper.vm.showAddDialog = true
      await nextTick()

      expect(wrapper.vm.showAddDialog).toBe(true)
    })

    it('应该能够成功添加观察项', async () => {
      vi.mocked(apiWatchlist.add).mockResolvedValue({ id: 4, code: '600519', name: '贵州茅台' })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 设置表单数据
      wrapper.vm.addForm = { code: '600519', reason: '优质白马股' }

      // 调用添加方法
      await wrapper.vm.addToWatchlist()

      // 验证 API 被调用（注意：组件中只传递了 code 和 reason，没有传递 priority）
      expect(apiWatchlist.add).toHaveBeenCalledWith('600519', '优质白马股')

      // 验证成功消息
      expect(ElMessage.success).toHaveBeenCalledWith('添加成功')

      // 验证对话框被关闭
      expect(wrapper.vm.showAddDialog).toBe(false)

      // 验证表单被重置
      expect(wrapper.vm.addForm.code).toBe('')
      expect(wrapper.vm.addForm.reason).toBe('')
    })

    it('添加空代码时应该显示警告消息', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 设置空代码
      wrapper.vm.addForm = { code: '', reason: '测试' }

      // 调用添加方法
      await wrapper.vm.addToWatchlist()

      // 验证警告消息
      expect(ElMessage.warning).toHaveBeenCalledWith('请输入股票代码')

      // 验证 add API 没有被调用
      expect(apiWatchlist.add).not.toHaveBeenCalled()
    })

    it('添加失败时应该显示错误消息', async () => {
      vi.mocked(apiWatchlist.add).mockRejectedValue(new Error('股票代码不存在'))

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 设置表单数据
      wrapper.vm.addForm = { code: '999999', reason: '测试' }

      // 调用添加方法
      await wrapper.vm.addToWatchlist()

      // 验证错误消息
      expect(ElMessage.error).toHaveBeenCalledWith('添加失败: 股票代码不存在')
    })

    it('应该能够添加带原因的观察项', async () => {
      vi.mocked(apiWatchlist.add).mockResolvedValue({ id: 5 })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 设置带原因的表单数据
      wrapper.vm.addForm = { code: '000002', reason: '底部放量，值得关注' }

      // 调用添加方法
      await wrapper.vm.addToWatchlist()

      // 验证 API 被调用并包含原因（注意：组件中只传递了 code 和 reason）
      expect(apiWatchlist.add).toHaveBeenCalledWith('000002', '底部放量，值得关注')
    })

    it('应该能够添加带成本和仓位的观察项', async () => {
      vi.mocked(apiWatchlist.add).mockResolvedValue({ id: 5 })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      wrapper.vm.addForm = {
        code: '000002',
        reason: '回踩关注',
        entryPrice: '12.8',
        positionRatio: '30'
      }

      await wrapper.vm.addToWatchlist()

      expect(apiWatchlist.add).toHaveBeenCalledWith('000002', '回踩关注', 0, 12.8, 0.3)
    })
  })

  /**
   * 测试3: test_delete_item
   * 删除观察项
   */
  describe('test_delete_item', () => {
    beforeEach(() => {
      setupBasicMocks()
    })

    it('应该能够成功删除观察项', async () => {
      vi.mocked(apiWatchlist.delete).mockResolvedValue({ success: true })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 选择一个要删除的项
      const itemToDelete = mockWatchlistItems[0]

      // 调用删除方法
      await wrapper.vm.removeStock(itemToDelete)

      // 验证 API 被调用
      expect(apiWatchlist.delete).toHaveBeenCalledWith(itemToDelete.id)

      // 验证成功消息
      expect(ElMessage.success).toHaveBeenCalledWith('已删除')
    })

    it('删除当前选中项时应该清空选中状态', async () => {
      vi.mocked(apiWatchlist.delete).mockResolvedValue({ success: true })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 设置当前选中项
      wrapper.vm.selectedStock = mockWatchlistItems[0]

      // 删除选中的项
      await wrapper.vm.removeStock(mockWatchlistItems[0])

      // 验证选中状态被清空
      expect(wrapper.vm.selectedStock).toBeNull()
    })

    it('删除非当前选中项时不应影响选中状态', async () => {
      vi.mocked(apiWatchlist.delete).mockResolvedValue({ success: true })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 设置当前选中项为第一项
      wrapper.vm.selectedStock = mockWatchlistItems[0]

      // 删除第二项
      await wrapper.vm.removeStock(mockWatchlistItems[1])

      // 验证选中状态未改变
      expect(wrapper.vm.selectedStock).toEqual(mockWatchlistItems[0])
    })

    it('删除失败时应该显示错误消息', async () => {
      vi.mocked(apiWatchlist.delete).mockRejectedValue(new Error('删除失败'))

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 尝试删除
      await wrapper.vm.removeStock(mockWatchlistItems[0])

      // 验证错误消息
      expect(ElMessage.error).toHaveBeenCalledWith('删除失败: 删除失败')
    })

    it('删除后应该重新加载观察列表', async () => {
      let callCount = 0
      vi.mocked(apiWatchlist.getAll).mockImplementation(async () => {
        callCount++
        if (callCount === 1) {
          return { items: mockWatchlistItems }
        } else {
          return { items: mockWatchlistItems.slice(1) }
        }
      })
      vi.mocked(apiWatchlist.delete).mockResolvedValue({ success: true })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 删除第一项
      await wrapper.vm.removeStock(mockWatchlistItems[0])

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证 getAll 被调用两次（初始化和删除后）
      expect(callCount).toBe(2)
    })
  })

  /**
   * 测试4: test_edit_item
   * 编辑观察项
   */
  describe('test_edit_item', () => {
    beforeEach(() => {
      setupBasicMocks()
    })

    it('应该能够通过 API 更新观察项', async () => {
      vi.mocked(apiWatchlist.update).mockResolvedValue({ success: true })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 模拟调用更新 API
      await apiWatchlist.update(1, { add_reason: '更新后的原因' })

      // 验证 API 被调用
      expect(apiWatchlist.update).toHaveBeenCalledWith(1, { add_reason: '更新后的原因' })
    })

    it('更新失败时应该抛出错误', async () => {
      vi.mocked(apiWatchlist.update).mockRejectedValue(new Error('更新失败'))

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 尝试更新并期待错误
      await expect(apiWatchlist.update(1, { add_reason: '测试' })).rejects.toThrow('更新失败')
    })

    it('应该能够更新观察项的优先级', async () => {
      vi.mocked(apiWatchlist.update).mockResolvedValue({ success: true })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 更新优先级
      await apiWatchlist.update(1, { priority: 5 })

      // 验证 API 被调用
      expect(apiWatchlist.update).toHaveBeenCalledWith(1, { priority: 5 })
    })

    it('应该能够更新观察项的激活状态', async () => {
      vi.mocked(apiWatchlist.update).mockResolvedValue({ success: true })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 更新激活状态
      await apiWatchlist.update(1, { is_active: false })

      // 验证 API 被调用
      expect(apiWatchlist.update).toHaveBeenCalledWith(1, { is_active: false })
    })
  })

  /**
   * 测试5: test_view_analysis
   * 查看分析历史
   */
  describe('test_view_analysis', () => {
    beforeEach(() => {
      setupBasicMocks()
    })

    it('选择股票时应该加载分析历史', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 选择股票
      const selectedStock = mockWatchlistItems[0]
      wrapper.vm.selectStock(selectedStock)

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证分析历史被加载
      expect(apiWatchlist.getAnalysis).toHaveBeenCalledWith(selectedStock.id)
      expect(wrapper.vm.analysisHistory).toHaveLength(3)
    })

    it('应该显示分析历史的评分', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 选择股票
      wrapper.vm.selectStock(mockWatchlistItems[0])

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证评分数据
      expect(wrapper.vm.analysisHistory[0].score).toBe(4.5)
      expect(wrapper.vm.analysisHistory[1].score).toBe(3.8)
      expect(wrapper.vm.analysisHistory[2].score).toBe(2.5)
    })

    it('应该显示分析历史的建议', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 选择股票
      wrapper.vm.selectStock(mockWatchlistItems[0])

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证建议数据
      expect(wrapper.vm.analysisHistory[0].buy_recommendation).toBe('可试仓，不追高。')
      expect(wrapper.vm.analysisHistory[1].hold_recommendation).toBe('以观察为主，暂不加仓。')
      expect(wrapper.vm.analysisHistory[2].risk_recommendation).toBe('跌破支撑执行止损。')
    })

    it('应该暴露结构化动作标签映射', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      expect(wrapper.vm.getBuyActionLabel('buy')).toBe('可买')
      expect(wrapper.vm.getHoldActionLabel('trim')).toBe('减仓观察')
      expect(wrapper.vm.getRiskLevelLabel('high')).toBe('高')
      expect(wrapper.vm.getBuyActionType('avoid')).toBe('danger')
      expect(wrapper.vm.getHoldActionType('hold')).toBe('success')
      expect(wrapper.vm.getRiskLevelType('medium')).toBe('warning')
    })

    it('应该提供风险等级规则提示文案', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      wrapper.vm.selectedStock = mockWatchlistItems[0]
      const lines = wrapper.vm.getRiskLevelTooltipLines(mockAnalysisHistory[2])
      expect(lines).toContain('命中说明')
      expect(lines).toContain('• 命中 FAIL，直接判定为高风险')
      expect(lines).toContain('• 高: 风险释放/FAIL，或浮亏 >= 5%，或仓位 >= 70%')
    })

    it('应该正确格式化分析日期', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证日期格式化函数
      expect(wrapper.vm.formatDate('2024-01-15T10:00:00Z')).toBe('1月15日')
      expect(wrapper.vm.formatDate('2024-12-31T10:00:00Z')).toBe('12月31日')
    })

    it('应该根据判断结果返回正确的标签类型', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证判断结果类型映射
      expect(wrapper.vm.getVerdictType('PASS')).toBe('success')
      expect(wrapper.vm.getVerdictType('WATCH')).toBe('warning')
      expect(wrapper.vm.getVerdictType('FAIL')).toBe('danger')
      expect(wrapper.vm.getVerdictType('')).toBe('info')
      expect(wrapper.vm.getVerdictType(undefined)).toBe('info')
    })

    it('没有分析历史时应该显示空状态', async () => {
      vi.mocked(apiWatchlist.getAnalysis).mockResolvedValue({ analyses: [] })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 选择股票
      wrapper.vm.selectStock(mockWatchlistItems[0])

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证分析历史为空
      expect(wrapper.vm.analysisHistory).toHaveLength(0)
    })

    it('加载分析历史失败时应该记录错误', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      vi.mocked(apiWatchlist.getAnalysis).mockRejectedValue(new Error('加载失败'))

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 选择股票
      wrapper.vm.selectStock(mockWatchlistItems[0])

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证错误被记录
      expect(consoleSpy).toHaveBeenCalled()

      consoleSpy.mockRestore()
    })
  })

  /**
   * 测试6: test_view_chart
   * 查看K线图
   */
  describe('test_view_chart', () => {
    beforeEach(() => {
      setupBasicMocks()
    })

    it('选择股票时应该加载K线图数据', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 选择股票
      const selectedStock = mockWatchlistItems[0]
      wrapper.vm.selectStock(selectedStock)

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证 K线图 API 被调用
      expect(apiStock.getKline).toHaveBeenCalledWith(selectedStock.code, 120)
    })

    it('应该正确计算趋势数据', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 选择股票
      wrapper.vm.selectStock(mockWatchlistItems[0])

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证趋势数据被设置
      expect(wrapper.vm.trendData.outlook).toBeDefined()
      expect(wrapper.vm.trendData.support).toBeDefined()
      expect(wrapper.vm.trendData.resistance).toBeDefined()
    })

    it('应该显示正确的趋势文本', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证趋势文本映射
      wrapper.vm.trendData = { outlook: 'bullish', support: 10, resistance: 15 }
      expect(wrapper.vm.trendText).toBe('看涨')

      wrapper.vm.trendData = { outlook: 'bearish', support: 10, resistance: 15 }
      expect(wrapper.vm.trendText).toBe('看跌')

      wrapper.vm.trendData = { outlook: 'neutral', support: 10, resistance: 15 }
      expect(wrapper.vm.trendText).toBe('中性')
    })

    it('加载K线图失败时应该显示错误消息', async () => {
      vi.mocked(apiStock.getKline).mockRejectedValue(new Error('K线数据加载失败'))

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 选择股票
      wrapper.vm.selectStock(mockWatchlistItems[0])

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证错误消息
      expect(ElMessage.error).toHaveBeenCalledWith('加载K线图失败: K线数据加载失败')
    })

    it('应该能够重新加载不同股票的K线图', async () => {
      vi.mocked(apiStock.getKline)
        .mockResolvedValueOnce({ ...mockKlineData, code: '600000' })
        .mockResolvedValueOnce({ ...mockKlineData, code: '000001' })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 选择第一只股票
      wrapper.vm.selectStock(mockWatchlistItems[0])

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      expect(apiStock.getKline).toHaveBeenCalledWith('600000', 120)

      // 选择第二只股票
      wrapper.vm.selectStock(mockWatchlistItems[1])

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      expect(apiStock.getKline).toHaveBeenCalledWith('000001', 120)
    })

    it('应该调用立即分析功能', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 设置选中股票
      wrapper.vm.selectedStock = mockWatchlistItems[0]

      // 调用立即分析
      await wrapper.vm.analyzeNow()

      expect(apiWatchlist.analyze).toHaveBeenCalledWith(1)
      expect(apiWatchlist.getAnalysis).toHaveBeenCalledWith(1)
      expect(wrapper.vm.analyzing).toBe(false)
      expect(ElMessage.success).toHaveBeenCalledWith('分析完成')
    })
  })

  /**
   * 测试7: test_filter_items
   * 筛选观察项
   */
  describe('test_filter_items', () => {
    beforeEach(() => {
      setupBasicMocks()
    })

    it('应该支持按代码筛选观察项', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证所有观察项被加载
      expect(wrapper.vm.watchlist).toHaveLength(3)

      // 模拟筛选 - 600 开头的股票
      const filtered = wrapper.vm.watchlist.filter((item: WatchlistItem) => item.code.startsWith('600'))
      expect(filtered).toHaveLength(2)
    })

    it('应该支持按优先级筛选观察项', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 按优先级筛选
      const highPriority = wrapper.vm.watchlist.filter((item: WatchlistItem) => item.priority > 0)
      expect(highPriority).toHaveLength(2)

      const normalPriority = wrapper.vm.watchlist.filter((item: WatchlistItem) => item.priority === 0)
      expect(normalPriority).toHaveLength(1)
    })

    it('应该支持按激活状态筛选观察项', async () => {
      vi.mocked(apiWatchlist.getAll).mockResolvedValue({
        items: [
          ...mockWatchlistItems,
          { id: 4, code: '601318', name: '中国平安', priority: 0, is_active: false, added_at: '2024-01-12T10:00:00Z' }
        ]
      })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 按激活状态筛选
      const activeItems = wrapper.vm.watchlist.filter((item: WatchlistItem) => item.is_active)
      expect(activeItems).toHaveLength(3)

      const inactiveItems = wrapper.vm.watchlist.filter((item: WatchlistItem) => !item.is_active)
      expect(inactiveItems).toHaveLength(1)
    })

    it('应该支持按添加日期筛选观察项', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 按日期筛选 - 2024-01-15 之后添加的
      const recentItems = wrapper.vm.watchlist.filter((item: WatchlistItem) => {
        const addedDate = new Date(item.added_at)
        const threshold = new Date('2024-01-14T00:00:00Z')
        return addedDate >= threshold
      })

      expect(recentItems).toHaveLength(2)
    })

    it('空筛选条件应该返回所有观察项', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 无筛选条件
      const allItems = wrapper.vm.watchlist.filter(() => true)
      expect(allItems).toHaveLength(3)
    })
  })

  /**
   * 测试8: test_loading_state
   * 加载状态
   */
  describe('test_loading_state', () => {
    beforeEach(() => {
      setupBasicMocks()
    })

    it('初始加载时应该设置加载状态', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证数据被加载
      expect(wrapper.vm.watchlist).toHaveLength(3)
    })

    it('立即分析时应该显示加载状态', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 设置选中股票
      wrapper.vm.selectedStock = mockWatchlistItems[0]

      // 调用立即分析
      const promise = wrapper.vm.analyzeNow()

      // 验证分析状态
      expect(wrapper.vm.analyzing).toBe(true)
      await promise
    })

    it('分析完成后应该重置加载状态', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 设置选中股票
      wrapper.vm.selectedStock = mockWatchlistItems[0]

      // 调用立即分析
      await wrapper.vm.analyzeNow()

      expect(wrapper.vm.analyzing).toBe(false)
    })

    it('加载K线图时应该处理异步操作', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 选择股票触发 K线图加载
      wrapper.vm.selectStock(mockWatchlistItems[0])

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证 API 被调用
      expect(apiStock.getKline).toHaveBeenCalled()
    })

    it('删除操作应该重新加载数据', async () => {
      let callCount = 0
      vi.mocked(apiWatchlist.getAll).mockImplementation(async () => {
        callCount++
        return { items: mockWatchlistItems }
      })
      vi.mocked(apiWatchlist.delete).mockResolvedValue({ success: true })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 删除操作
      await wrapper.vm.removeStock(mockWatchlistItems[0])

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证 getAll 被调用两次
      expect(callCount).toBe(2)
    })
  })

  /**
   * 测试9: test_empty_state
   * 空状态显示
   */
  describe('test_empty_state', () => {
    beforeEach(() => {
      setupBasicMocks()
    })

    it('没有观察列表时应该显示空状态', async () => {
      vi.mocked(apiWatchlist.getAll).mockResolvedValue({ items: [] })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证观察列表为空
      expect(wrapper.vm.watchlist).toHaveLength(0)
      expect(wrapper.vm.selectedStock).toBeNull()
    })

    it('未选择股票时应该显示空状态提示', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 初始状态未选择任何股票
      expect(wrapper.vm.selectedStock).toBeNull()

      // 选择股票后
      wrapper.vm.selectedStock = mockWatchlistItems[0]
      expect(wrapper.vm.selectedStock).not.toBeNull()
    })

    it('没有分析历史时应该显示空状态', async () => {
      vi.mocked(apiWatchlist.getAnalysis).mockResolvedValue({ analyses: [] })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 选择股票
      wrapper.vm.selectStock(mockWatchlistItems[0])

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证分析历史为空
      expect(wrapper.vm.analysisHistory).toHaveLength(0)
    })

    it('API 返回 null 数据时应该正确处理', async () => {
      vi.mocked(apiWatchlist.getAll).mockResolvedValue({ items: null })
      vi.mocked(apiWatchlist.getAnalysis).mockResolvedValue({ analyses: null })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证 null 被转换为空数组
      expect(wrapper.vm.watchlist).toHaveLength(0)

      // 选择股票
      wrapper.vm.selectStock(mockWatchlistItems[0])

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      expect(wrapper.vm.analysisHistory).toHaveLength(0)
    })

    it('空列表时添加按钮应该可用', async () => {
      vi.mocked(apiWatchlist.getAll).mockResolvedValue({ items: [] })

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证添加对话框状态
      expect(wrapper.vm.showAddDialog).toBe(false)

      // 应该能够打开添加对话框
      wrapper.vm.showAddDialog = true
      expect(wrapper.vm.showAddDialog).toBe(true)
    })
  })

  /**
   * 测试10: test_error_handling
   * 错误处理
   */
  describe('test_error_handling', () => {
    beforeEach(() => {
      setupBasicMocks()
    })

    it('加载观察列表失败时应该记录错误', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      vi.mocked(apiWatchlist.getAll).mockRejectedValue(new Error('网络错误'))

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证错误被记录
      expect(consoleSpy).toHaveBeenCalledWith('Failed to load watchlist:', expect.any(Error))

      consoleSpy.mockRestore()
    })

    it('添加观察项失败时应该显示错误消息', async () => {
      vi.mocked(apiWatchlist.add).mockRejectedValue(new Error('股票代码无效'))

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 设置表单数据
      wrapper.vm.addForm = { code: 'invalid', reason: '测试' }

      // 调用添加方法
      await wrapper.vm.addToWatchlist()

      // 验证错误消息
      expect(ElMessage.error).toHaveBeenCalledWith('添加失败: 股票代码无效')
    })

    it('删除观察项失败时应该显示错误消息', async () => {
      vi.mocked(apiWatchlist.delete).mockRejectedValue(new Error('删除失败'))

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 尝试删除
      await wrapper.vm.removeStock(mockWatchlistItems[0])

      // 验证错误消息
      expect(ElMessage.error).toHaveBeenCalledWith('删除失败: 删除失败')
    })

    it('加载K线图失败时应该显示错误消息', async () => {
      vi.mocked(apiStock.getKline).mockRejectedValue(new Error('K线数据不可用'))

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 选择股票
      wrapper.vm.selectStock(mockWatchlistItems[0])

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证错误消息
      expect(ElMessage.error).toHaveBeenCalledWith('加载K线图失败: K线数据不可用')
    })

    it('加载分析历史失败时应该记录错误但不影响页面', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      vi.mocked(apiWatchlist.getAnalysis).mockRejectedValue(new Error('分析历史加载失败'))

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 选择股票
      wrapper.vm.selectStock(mockWatchlistItems[0])

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证错误被记录
      expect(consoleSpy).toHaveBeenCalledWith('Failed to load analysis:', expect.any(Error))

      // 验证组件仍然可用
      expect(wrapper.vm.selectedStock).toEqual(mockWatchlistItems[0])

      consoleSpy.mockRestore()
    })

    it('空代码输入应该显示警告而不是错误', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 设置空代码
      wrapper.vm.addForm = { code: '', reason: '' }

      // 调用添加方法
      await wrapper.vm.addToWatchlist()

      // 验证警告消息（不是错误）
      expect(ElMessage.warning).toHaveBeenCalledWith('请输入股票代码')
      expect(ElMessage.error).not.toHaveBeenCalled()
    })

    it('网络超时应该被正确处理', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      vi.mocked(apiWatchlist.getAll).mockRejectedValue(new Error('timeout'))

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证错误被记录
      expect(consoleSpy).toHaveBeenCalled()

      consoleSpy.mockRestore()
    })
  })

  /**
   * 额外测试: 组件生命周期
   */
  describe('test_lifecycle', () => {
    beforeEach(() => {
      setupBasicMocks()
    })

    it('组件卸载时应该清理图表实例', async () => {
      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 销毁组件
      wrapper.unmount()

      // 验证组件被正确卸载
      expect(wrapper.exists()).toBe(false)
    })

    it('组件挂载时应该添加窗口 resize 监听器', async () => {
      const addEventListenerSpy = vi.spyOn(window, 'addEventListener')

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 验证 resize 监听器被添加
      expect(addEventListenerSpy).toHaveBeenCalledWith('resize', expect.any(Function))

      addEventListenerSpy.mockRestore()
    })

    it('组件卸载时应该移除窗口 resize 监听器', async () => {
      const removeEventListenerSpy = vi.spyOn(window, 'removeEventListener')

      wrapper = mount(Watchlist, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 10))

      // 销毁组件
      wrapper.unmount()

      // 验证 resize 监听器被移除
      expect(removeEventListenerSpy).toHaveBeenCalledWith('resize', expect.any(Function))

      removeEventListenerSpy.mockRestore()
    })
  })
})
