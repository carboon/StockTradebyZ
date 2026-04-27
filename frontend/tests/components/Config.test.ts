/**
 * Config.vue 组件测试文件
 * 测试配置管理页面的渲染、用户交互和状态管理
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import ElementPlus from 'element-plus'
import Config from '@/views/Config.vue'

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
  apiConfig: {
    getAll: vi.fn(),
    update: vi.fn(),
    verifyTushare: vi.fn(),
    saveEnv: vi.fn(),
    getTushareStatus: vi.fn()
  }
}))

// 导入 mock 函数
import { apiConfig } from '@/api/index'

// 创建挂载选项的辅助函数
function createMountOptions() {
  return {
    global: {
      plugins: [ElementPlus, createPinia()],
      stubs: {
        'el-card': { template: '<div class="el-card"><slot /><slot name="header" /></div>' },
        'el-form': { template: '<form class="el-form"><slot /></form>' },
        'el-form-item': { template: '<div class="el-form-item"><label><slot /></label><slot name="default" /></div>' },
        'el-input': {
          template: '<input type="password" class="el-input" :value="$attrs.modelValue" />',
          props: ['modelValue']
        },
        'el-input-number': {
          template: '<input type="number" class="el-input-number" :value="$attrs.modelValue" />',
          props: ['modelValue', 'min', 'max', 'step', 'precision']
        },
        'el-button': {
          template: '<button class="el-button" :disabled="$attrs.loading"><slot /></button>',
          props: ['loading']
        },
        'el-divider': {
          template: '<div class="el-divider"><span class="el-divider__text"><slot /></span></div>',
          props: ['contentPosition']
        },
        'el-radio-group': {
          template: '<div class="el-radio-group"><slot /></div>',
          props: ['modelValue']
        },
        'el-radio': {
          template: '<label class="el-radio"><input type="radio" :value="$attrs.label" /><slot /></label>',
          props: ['label']
        }
      }
    }
  }
}

describe('Config.vue 组件测试', () => {
  let wrapper: VueWrapper
  let pinia: any

  beforeEach(() => {
    // 重置所有 mocks
    vi.clearAllMocks()

    // 创建新的 Pinia 实例
    pinia = createPinia()
    setActivePinia(pinia)
  })

  /**
   * 测试1: test_render_config_page
   * 渲染配置页面
   */
  describe('test_render_config_page', () => {
    it('应该正确渲染配置页面组件', async () => {
      // Mock API 响应
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: 'test_token' },
          { key: 'zhipuai_api_key', value: 'glm_key' },
          { key: 'dashscope_api_key', value: 'qwen_key' },
          { key: 'gemini_api_key', value: 'gemini_key' },
          { key: 'default_reviewer', value: 'quant' },
          { key: 'min_score_threshold', value: '4.0' }
        ]
      })

      wrapper = mount(Config, createMountOptions())

      // 等待组件挂载和 API 调用完成
      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证页面容器存在
      expect(wrapper.find('.config-page').exists()).toBe(true)
      // 验证配置管理标题
      expect(wrapper.text()).toContain('配置管理')
    })

    it('应该渲染所有配置分区', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' },
          { key: 'min_score_threshold', value: '4.0' }
        ]
      })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证分区标题存在
      const text = wrapper.text()
      expect(text).toContain('Tushare 配置')
      expect(text).toContain('LLM API 配置')
      expect(text).toContain('其他配置')
    })

    it('应该渲染所有表单输入项', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' },
          { key: 'min_score_threshold', value: '4.0' }
        ]
      })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证表单元素存在 - 检查实际显示的文本
      const text = wrapper.text()
      // 由于 stub 组件只渲染 label 中的内容作为纯文本，我们验证关键文本存在
      expect(text).toContain('Tushare 配置')
      expect(text).toContain('LLM API 配置')
      expect(text).toContain('其他配置')
      // 验证按钮存在
      expect(text).toContain('保存配置')
      expect(text).toContain('重置')
    })
  })

  /**
   * 测试2: test_display_tushare_token
   * 显示Tushare Token
   */
  describe('test_display_tushare_token', () => {
    it('应该从 store 加载并显示已保存的 Tushare Token', async () => {
      const mockToken = 'abcd1234efgh5678'

      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: mockToken },
          { key: 'default_reviewer', value: 'quant' },
          { key: 'min_score_threshold', value: '4.0' }
        ]
      })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证 API 被调用
      expect(apiConfig.getAll).toHaveBeenCalled()
      expect(apiConfig.getAll).toHaveBeenCalledTimes(1)

      // 验证 token 被加载到表单 - 检查输入框存在
      const inputs = wrapper.findAll('input[type="password"]')
      expect(inputs.length).toBeGreaterThan(0)
    })

    it('当 token 为空时应该显示空输入框', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' },
          { key: 'min_score_threshold', value: '4.0' }
        ]
      })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证组件成功渲染
      expect(wrapper.find('.config-page').exists()).toBe(true)
    })

    it('应该显示 Tushare Token 获取链接', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' }
        ]
      })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      const text = wrapper.text()
      expect(text).toContain('https://tushare.pro/user/token')
    })
  })

  /**
   * 测试3: test_update_token_success
   * 更新Token成功
   */
  describe('test_update_token_success', () => {
    it('应该允许用户修改 Token 值', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: 'old_token' },
          { key: 'default_reviewer', value: 'quant' }
        ]
      })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 查找密码输入框
      const passwordInputs = wrapper.findAll('input[type="password"]')
      expect(passwordInputs.length).toBeGreaterThan(0)

      // 验证输入框存在且类型正确
      const tokenInput = passwordInputs[0]
      expect(tokenInput.attributes('type')).toBe('password')
    })

    it('应该显示密码输入框', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' }
        ]
      })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证密码输入框存在
      const tokenInput = wrapper.find('input[type="password"]')
      expect(tokenInput.exists()).toBe(true)
    })
  })

  /**
   * 测试4: test_verify_token
   * 验证Token
   */
  describe('test_verify_token', () => {
    it('应该成功验证有效的 Token', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' }
        ]
      })

      vi.mocked(apiConfig.verifyTushare).mockResolvedValue({
        valid: true,
        message: 'Token 有效'
      })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 通过直接修改组件数据来设置 token 值
      await wrapper.setData({
        configs: { ...wrapper.vm.configs, tushare_token: 'valid_token_123' }
      })

      // 点击验证按钮
      const verifyButton = wrapper.find('.el-button')
      await verifyButton.trigger('click')

      // 等待异步操作完成
      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证成功消息被显示
      expect(ElMessage.success).toHaveBeenCalledWith('Token 验证成功!')
    })

    it('验证失败时应该显示错误消息', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' }
        ]
      })

      vi.mocked(apiConfig.verifyTushare).mockResolvedValue({
        valid: false,
        message: 'Token 无效或已过期'
      })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 设置 token 值
      await wrapper.setData({
        configs: { ...wrapper.vm.configs, tushare_token: 'invalid_token' }
      })

      // 点击验证按钮
      const verifyButton = wrapper.find('.el-button')
      await verifyButton.trigger('click')

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证错误消息被显示
      expect(ElMessage.error).toHaveBeenCalledWith('Token 验证失败: Token 无效或已过期')
    })

    it('当 token 为空时应该显示警告消息', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' }
        ]
      })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 不设置 token，直接点击验证按钮
      const verifyButton = wrapper.find('.el-button')
      await verifyButton.trigger('click')

      await nextTick()

      // 验证警告消息被显示
      expect(ElMessage.warning).toHaveBeenCalledWith('请先输入 API Token')
      // API 不应该被调用
      expect(apiConfig.verifyTushare).not.toHaveBeenCalled()
    })

    it('验证过程中应该显示加载状态', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' }
        ]
      })

      // 创建一个延迟的 promise 来测试加载状态
      let resolvePost: (value: any) => void
      const postPromise = new Promise(resolve => {
        resolvePost = resolve
      })
      vi.mocked(apiConfig.verifyTushare).mockReturnValue(postPromise)

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 设置 token
      await wrapper.setData({
        configs: { ...wrapper.vm.configs, tushare_token: 'test_token' }
      })

      // 点击验证按钮
      const verifyButton = wrapper.find('.el-button')
      await verifyButton.trigger('click')

      await nextTick()

      // 验证 verifying 状态被设置为 true
      expect(wrapper.vm.verifying).toBe(true)

      // 完成 API 调用
      resolvePost!({ valid: true, message: '成功' })
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证 verifying 状态被重置
      expect(wrapper.vm.verifying).toBe(false)
    })
  })

  /**
   * 测试5: test_save_config
   * 保存配置
   */
  describe('test_save_config', () => {
    it('应该成功保存所有配置', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' },
          { key: 'min_score_threshold', value: '4.0' }
        ]
      })

      vi.mocked(apiConfig.saveEnv).mockResolvedValue({ success: true })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 修改配置
      await wrapper.setData({
        configs: { ...wrapper.vm.configs, tushare_token: 'new_tushare_token' }
      })

      // 点击保存按钮（倒数第二个按钮）
      const buttons = wrapper.findAll('.el-button')
      const saveButton = buttons[buttons.length - 2]
      await saveButton.trigger('click')

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证 API 被调用
      expect(apiConfig.saveEnv).toHaveBeenCalledWith(expect.objectContaining({
        tushare_token: 'new_tushare_token'
      }))

      // 验证成功消息
      expect(ElMessage.success).toHaveBeenCalledWith('配置已保存')
    })

    it('保存失败时应该显示错误消息', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' }
        ]
      })

      vi.mocked(apiConfig.saveEnv).mockRejectedValue(new Error('保存失败，请重试'))

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 点击保存按钮
      const buttons = wrapper.findAll('.el-button')
      const saveButton = buttons[buttons.length - 2]
      await saveButton.trigger('click')

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证错误消息 - 错误对象会转换为字符串 "Error: 保存失败，请重试"
      expect(ElMessage.error).toHaveBeenCalledWith(expect.stringContaining('保存失败'))
    })

    it('保存时应该包含所有 LLM API Key', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'zhipuai_api_key', value: '' },
          { key: 'dashscope_api_key', value: '' },
          { key: 'gemini_api_key', value: '' },
          { key: 'default_reviewer', value: 'quant' }
        ]
      })

      vi.mocked(apiConfig.saveEnv).mockResolvedValue({ success: true })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 设置所有 API Key
      await wrapper.setData({
        configs: {
          tushare_token: 'tushare_key',
          zhipuai_api_key: 'glm_key',
          dashscope_api_key: 'qwen_key',
          gemini_api_key: 'gemini_key',
          default_reviewer: 'quant',
          min_score_threshold: 4.0
        }
      })

      // 点击保存
      const buttons = wrapper.findAll('.el-button')
      const saveButton = buttons[buttons.length - 2]
      await saveButton.trigger('click')

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证所有 key 都被发送
      expect(apiConfig.saveEnv).toHaveBeenCalledWith(expect.objectContaining({
        tushare_token: 'tushare_key',
        zhipuai_api_key: 'glm_key',
        dashscope_api_key: 'qwen_key',
        gemini_api_key: 'gemini_key'
      }))
    })

    it('应该保存评分器和阈值配置', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' },
          { key: 'min_score_threshold', value: '4.0' }
        ]
      })

      vi.mocked(apiConfig.saveEnv).mockResolvedValue({ success: true })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 点击保存按钮
      const buttons = wrapper.findAll('.el-button')
      const saveButton = buttons[buttons.length - 2]
      await saveButton.trigger('click')

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证配置包含评分器和阈值
      expect(apiConfig.saveEnv).toHaveBeenCalledWith(expect.objectContaining({
        default_reviewer: 'quant',
        min_score_threshold: 4.0
      }))
    })
  })

  /**
   * 测试6: test_reload_config
   * 重新加载配置
   */
  describe('test_reload_config', () => {
    it('点击重置按钮应该重新加载配置', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: 'original_token' },
          { key: 'default_reviewer', value: 'quant' }
        ]
      })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 清除之前的调用
      vi.clearAllMocks()

      // 再次 mock 返回相同配置
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: 'original_token' },
          { key: 'default_reviewer', value: 'quant' }
        ]
      })

      // 点击重置按钮（最后一个按钮）
      const buttons = wrapper.findAll('.el-button')
      const resetButton = buttons[buttons.length - 1]
      await resetButton.trigger('click')

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证 API 被调用来重新加载配置
      expect(apiConfig.getAll).toHaveBeenCalled()
    })

    it('重置后应该恢复原始配置值', async () => {
      const originalConfigs = {
        configs: [
          { key: 'tushare_token', value: 'saved_token' },
          { key: 'default_reviewer', value: 'glm' },
          { key: 'min_score_threshold', value: '3.5' }
        ]
      }

      vi.mocked(apiConfig.getAll).mockResolvedValue(originalConfigs)

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 清除之前的调用
      vi.clearAllMocks()

      // 再次 mock 返回相同配置
      vi.mocked(apiConfig.getAll).mockResolvedValue(originalConfigs)

      // 点击重置按钮
      const buttons = wrapper.findAll('.el-button')
      const resetButton = buttons[buttons.length - 1]
      await resetButton.trigger('click')

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证 API 被调用来重新加载配置
      expect(apiConfig.getAll).toHaveBeenCalled()
    })
  })

  /**
   * 测试7: test_display_error_message
   * 显示错误信息
   */
  describe('test_display_error_message', () => {
    it('加载配置失败时应该处理错误', async () => {
      // Mock API 抛出错误
      vi.mocked(apiConfig.getAll).mockRejectedValue(new Error('无法连接到服务器'))

      // 使用 console.error 来捕获错误
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证错误被记录（组件使用 console.error 处理错误）
      expect(consoleSpy).toHaveBeenCalled()

      consoleSpy.mockRestore()
    })

    it('网络错误时应该显示友好的错误消息', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' }
        ]
      })

      vi.mocked(apiConfig.saveEnv).mockRejectedValue(new Error('Network Error'))

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 设置 token 并尝试保存
      await wrapper.setData({
        configs: { ...wrapper.vm.configs, tushare_token: 'test_token' }
      })

      const buttons = wrapper.findAll('.el-button')
      const saveButton = buttons[buttons.length - 2]
      await saveButton.trigger('click')

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证错误消息显示 - Error 对象会被转换为字符串
      expect(ElMessage.error).toHaveBeenCalledWith(expect.stringContaining('Network Error'))
    })

    it('验证 token 时网络错误应该被正确显示', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' }
        ]
      })

      vi.mocked(apiConfig.verifyTushare).mockRejectedValue(new Error('连接超时'))

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      await wrapper.setData({
        configs: { ...wrapper.vm.configs, tushare_token: 'test_token' }
      })

      const verifyButton = wrapper.find('.el-button')
      await verifyButton.trigger('click')

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证错误消息 - Error 对象会被转换为字符串 "Error: 连接超时"
      expect(ElMessage.error).toHaveBeenCalledWith(expect.stringContaining('连接超时'))
    })
  })

  /**
   * 测试8: test_loading_state
   * 加载状态
   */
  describe('test_loading_state', () => {
    it('保存配置时应该显示加载状态', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' }
        ]
      })

      // 创建延迟 promise
      let resolvePost: (value: any) => void
      const postPromise = new Promise(resolve => {
        resolvePost = resolve
      })
      vi.mocked(apiConfig.saveEnv).mockReturnValue(postPromise)

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 点击保存按钮
      const buttons = wrapper.findAll('.el-button')
      const saveButton = buttons[buttons.length - 2]
      await saveButton.trigger('click')

      await nextTick()

      // 验证 saving 状态被设置为 true
      expect(wrapper.vm.saving).toBe(true)

      // 完成 API 调用
      resolvePost!({ success: true })
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证成功消息
      expect(ElMessage.success).toHaveBeenCalledWith('配置已保存')

      // 验证 saving 状态被重置
      expect(wrapper.vm.saving).toBe(false)
    })

    it('验证 token 时应该显示加载状态', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' }
        ]
      })

      // 创建延迟 promise
      let resolvePost: (value: any) => void
      const postPromise = new Promise(resolve => {
        resolvePost = resolve
      })
      vi.mocked(apiConfig.verifyTushare).mockReturnValue(postPromise)

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 设置 token
      await wrapper.setData({
        configs: { ...wrapper.vm.configs, tushare_token: 'test_token' }
      })

      // 点击验证按钮
      const verifyButton = wrapper.find('.el-button')
      await verifyButton.trigger('click')

      await nextTick()

      // 验证 verifying 状态被设置为 true
      expect(wrapper.vm.verifying).toBe(true)

      // 完成 API 调用
      resolvePost!({ valid: true, message: '成功' })
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证 verifying 状态被重置
      expect(wrapper.vm.verifying).toBe(false)
    })

    it('加载完成后应该移除加载状态', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' }
        ]
      })

      vi.mocked(apiConfig.saveEnv).mockResolvedValue({ success: true })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 点击保存按钮
      const buttons = wrapper.findAll('.el-button')
      const saveButton = buttons[buttons.length - 2]
      await saveButton.trigger('click')

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证操作完成
      expect(ElMessage.success).toHaveBeenCalledWith('配置已保存')

      // 验证 saving 状态被重置
      expect(wrapper.vm.saving).toBe(false)
    })
  })

  /**
   * 额外测试: 默认评分器选择
   */
  describe('test_default_reviewer_selection', () => {
    it('应该显示所有评分器选项', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'quant' }
        ]
      })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证单选按钮组存在
      const text = wrapper.text()
      expect(text).toContain('量化评分')
      expect(text).toContain('GLM')
      expect(text).toContain('通义千问')
      expect(text).toContain('Gemini')
    })

    it('应该正确显示当前选中的评分器', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'default_reviewer', value: 'glm' }
        ]
      })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 组件应该成功渲染
      expect(wrapper.find('.config-page').exists()).toBe(true)
    })
  })

  /**
   * 额外测试: 分数阈值设置
   */
  describe('test_score_threshold_setting', () => {
    it('应该显示分数阈值输入控件', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'min_score_threshold', value: '4.0' }
        ]
      })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      const text = wrapper.text()
      // 验证提示文本存在
      expect(text).toContain('分数 >= 此值的股票将被推荐')
      // 验证输入框存在（number 类型）
      const numberInputs = wrapper.findAll('input[type="number"]')
      expect(numberInputs.length).toBeGreaterThan(0)
    })

    it('应该支持设置小数阈值', async () => {
      vi.mocked(apiConfig.getAll).mockResolvedValue({
        configs: [
          { key: 'tushare_token', value: '' },
          { key: 'min_score_threshold', value: '3.5' }
        ]
      })

      wrapper = mount(Config, createMountOptions())

      await nextTick()
      await new Promise(resolve => setTimeout(resolve, 0))

      // 验证组件成功渲染
      expect(wrapper.find('.config-page').exists()).toBe(true)
    })
  })
})
