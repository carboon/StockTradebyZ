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

  // 状态检查去重：防止并发重复请求
  let statusCheckPromise: Promise<TushareStatusResponse> | null = null
  let lastStatusCheckTime = 0
  const STATUS_CHECK_DEBOUNCE_MS = 2000 // 2秒内不重复检查

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
      return '首次初始化已完成，原始数据、候选结果和分析结果均已就绪。'
    }

    const status = dataStatus.value
    if (!status) {
      return '尚未检测到初始化结果，请先前往任务中心执行首次初始化。'
    }

    const missing: string[] = []
    const rawCsvLikelyReady = Boolean(status.raw_data?.latest_trade_date)
      && (Boolean(status.candidates?.exists) || Boolean(status.analysis?.exists))
    if (!status.raw_data?.exists && !rawCsvLikelyReady) missing.push('原始数据')
    if (!status.raw_data?.exists && rawCsvLikelyReady) {
      return '候选结果和分析结果已生成，但数据库中的 K 线主表尚未同步完成。请前往任务中心查看“数据库同步”阶段状态。'
    }
    if (!status.candidates?.exists) missing.push('候选结果')
    if (!status.analysis?.exists) missing.push('分析结果')

    if (status.raw_data?.exists && status.raw_data?.is_latest_complete) {
      if (!status.candidates?.exists && !status.analysis?.exists) {
        return '原始数据已存在且已是最新交易日，当前只需补全候选结果和分析结果；重新初始化时会自动跳过重新抓取。'
      }
      if (!status.candidates?.exists) {
        return '原始数据已存在且已是最新交易日，当前只需补全候选结果；重新初始化时会自动跳过重新抓取。'
      }
      if (!status.analysis?.exists) {
        return '原始数据已存在且已是最新交易日，当前只需补全分析结果；重新初始化时会自动跳过重新抓取。'
      }
    }

    if (missing.length > 0) {
      return `尚未完成首次初始化，当前缺少：${missing.join('、')}。请前往任务中心继续初始化。`
    }

    return '初始化状态待确认，请前往任务中心重新检查。'
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
    const now = Date.now()

    // 如果距离上次检查不到2秒，且已有状态，直接返回
    if (tushareStatus.value && now - lastStatusCheckTime < STATUS_CHECK_DEBOUNCE_MS) {
      return tushareStatus.value
    }

    // 如果正在检查，等待已有请求完成
    if (statusCheckPromise) {
      return statusCheckPromise
    }

    // 发起新请求
    statusCheckPromise = (async () => {
      try {
        const result = await apiConfig.getTushareStatus()
        apiAvailable.value = true
        statusError.value = ''
        tushareStatus.value = result
        lastStatusCheckTime = now
        return result
      } catch (error) {
        console.error('Failed to check tushare status:', error)
        apiAvailable.value = false
        statusError.value = error instanceof Error ? error.message : 'Tushare 状态检查失败'
        tushareStatus.value = null
        throw error
      } finally {
        statusCheckPromise = null
      }
    })()

    return statusCheckPromise
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
