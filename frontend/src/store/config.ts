import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiConfig } from '@/api'
import type { TushareStatusResponse } from '@/types'

export const useConfigStore = defineStore('config', () => {
  const configs = ref<Record<string, string>>({})
  const loading = ref(false)
  const tushareStatus = ref<TushareStatusResponse | null>(null)
  const apiAvailable = ref(true)
  const statusError = ref('')

  const tushareToken = computed(() => configs.value.tushare_token || '')
  const hasTushareToken = computed(() => !!tushareToken.value)
  const tushareReady = computed(() => Boolean(tushareStatus.value?.configured && tushareStatus.value?.available))
  const dataStatus = computed(() => tushareStatus.value?.data_status || null)
  const dataInitialized = computed(() => {
    const status = dataStatus.value
    if (!status) return false
    return Boolean(status.raw_data?.exists && status.candidates?.exists && status.analysis?.exists)
  })
  const initializationMessage = computed(() => {
    if (!tushareReady.value) {
      return '请先完成 Tushare 配置和验证。'
    }
    if (dataInitialized.value) {
      return '历史数据、候选结果与分析结果均已就绪。'
    }

    const status = dataStatus.value
    if (!status) {
      return '尚未检测到初始化结果，请先执行首次初始化。'
    }

    const missing: string[] = []
    if (!status.raw_data?.exists) missing.push('原始数据')
    if (!status.candidates?.exists) missing.push('候选结果')
    if (!status.analysis?.exists) missing.push('分析结果')
    return missing.length > 0
      ? `尚未完成首次初始化，当前缺少：${missing.join('、')}。`
      : '尚未完成首次初始化，请前往任务中心执行初始化。'
  })

  // 加载配置
  async function loadConfigs() {
    loading.value = true
    try {
      const data = await apiConfig.getAll()
      configs.value = {}
      for (const item of data.configs) {
        configs.value[item.key] = item.value
      }
    } catch (error) {
      console.error('Failed to load configs:', error)
    } finally {
      loading.value = false
    }
  }

  // 更新配置
  async function updateConfig(key: string, value: string) {
    try {
      await apiConfig.update(key, value)
      configs.value[key] = value
    } catch (error) {
      console.error('Failed to update config:', error)
      throw error
    }
  }

  // 验证 Tushare Token
  async function verifyTushareToken(token: string) {
    try {
      const result = await apiConfig.verifyTushare(token)
      return result
    } catch (error) {
      console.error('Failed to verify token:', error)
      throw error
    }
  }

  // 保存环境变量
  async function saveEnv(config: Record<string, string>) {
    try {
      await apiConfig.saveEnv(config)
      // 更新本地配置
      Object.assign(configs.value, config)
    } catch (error) {
      console.error('Failed to save env:', error)
      throw error
    }
  }

  async function checkTushareStatus() {
    try {
      const result = await apiConfig.getTushareStatus()
      apiAvailable.value = true
      statusError.value = ''
      tushareStatus.value = result
      return result
    } catch (error) {
      console.error('Failed to check tushare status:', error)
      apiAvailable.value = false
      statusError.value = error instanceof Error ? error.message : 'Tushare 状态检查失败'
      tushareStatus.value = null
      throw error
    }
  }

  return {
    configs,
    loading,
    tushareStatus,
    apiAvailable,
    statusError,
    tushareToken,
    hasTushareToken,
    tushareReady,
    dataStatus,
    dataInitialized,
    initializationMessage,
    loadConfigs,
    updateConfig,
    verifyTushareToken,
    saveEnv,
    checkTushareStatus,
  }
})
