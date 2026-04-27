<template>
  <div class="diagnosis-page">
    <el-alert
      v-if="showInitializationAlert"
      class="page-alert"
      type="info"
      :closable="false"
      show-icon
      title="尚未完成首次初始化"
      :description="configStore.initializationMessage"
    />

    <!-- 搜索栏 -->
    <el-card class="search-card">
      <el-form :inline="true" :model="searchForm" @submit.prevent="searchAndAnalyze">
        <el-form-item label="股票代码">
          <el-input
            v-model="searchForm.code"
            placeholder="请输入6位股票代码"
            maxlength="6"
            clearable
            style="width: 200px"
          >
            <template #append>
              <el-button :icon="Search" @click="searchAndAnalyze" />
            </template>
          </el-input>
        </el-form-item>
        <el-form-item v-if="stockCode">
          <el-button @click="addCurrentToWatchlist" :loading="addingToWatchlist" :disabled="isInWatchlist">
            {{ isInWatchlist ? '已纳入重点观察' : '纳入重点观察' }}
          </el-button>
        </el-form-item>
        <el-form-item v-if="analyzing">
          <el-tag type="primary" effect="plain">分析中...</el-tag>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 分析结果 -->
    <template v-if="stockCode">
      <el-row :gutter="20" class="content-row">
        <!-- K线图 -->
        <el-col :span="16">
          <el-card class="chart-card">
            <template #header>
              <div class="card-header">
                <span>{{ stockCode }} {{ stockName || '' }} K线图</span>
                <el-radio-group v-model="chartDays" size="small" @change="loadKlineData">
                  <el-radio-button :value="30">30天</el-radio-button>
                  <el-radio-button :value="60">60天</el-radio-button>
                  <el-radio-button :value="120">120天</el-radio-button>
                </el-radio-group>
              </div>
            </template>
            <div ref="chartRef" class="chart-container" />
          </el-card>
        </el-col>

        <!-- 分析面板 -->
        <el-col :span="8">
          <el-card class="analysis-card">
            <div v-if="analysisResult" class="analysis-content">
              <div class="analysis-item">
                <span class="label">当前评分</span>
                <el-tag :type="getScoreType(analysisResult.score)" size="large">
                  {{ analysisResult.score ? analysisResult.score.toFixed(1) : '-' }}
                </el-tag>
              </div>

              <div class="analysis-item">
                <span class="label">B1检查</span>
                <el-tag :type="analysisResult.b1_passed ? 'success' : 'danger'">
                  {{ analysisResult.b1_passed ? '通过' : '未通过' }}
                </el-tag>
              </div>

              <div class="analysis-item">
                <span class="label">
                        趋势判断
                        <el-tooltip raw-content content="PASS: 趋势启动，建议关注<br/>WATCH: 结构偏多，继续观察<br/>FAIL: 条件不足，暂不关注" placement="top">
                          <el-icon class="info-icon"><InfoFilled /></el-icon>
                        </el-tooltip>
                      </span>
                <span class="value">{{ analysisResult.verdict || '-' }}</span>
              </div>

              <el-divider />

              <div class="b1-details">
                <div class="section-header">
                  <h5>B1检查详情</h5>
                </div>
                <div class="detail-item">
                  <span class="detail-label">
                        KDJ-J
                        <el-tooltip raw-content content="KDJ指标中的J值<br/>反映价格超买超卖状态<br/>J值低于0表示超卖<br/>高于100表示超买<br/>B1策略寻找J值处于低位的股票" placement="top">
                          <el-icon class="info-icon"><InfoFilled /></el-icon>
                        </el-tooltip>
                      </span>
                  <span class="detail-value">{{ analysisResult.kdj_j ? analysisResult.kdj_j.toFixed(1) : '-' }}</span>
                </div>
                <div class="detail-item">
                  <span class="detail-label">
                        知行线多头
                        <el-tooltip raw-content content="知行线是特殊均线系统<br/>当短期线上穿长期线时<br/>表示趋势转多<br/>股价处于上升通道" placement="top">
                          <el-icon class="info-icon"><InfoFilled /></el-icon>
                        </el-tooltip>
                      </span>
                  <el-tag :type="analysisResult.zx_long_pos ? 'success' : 'info'" size="small">
                    {{ analysisResult.zx_long_pos ? '是' : '否' }}
                  </el-tag>
                </div>
                <div class="detail-item">
                  <span class="detail-label">
                        周线多头
                        <el-tooltip raw-content content="周线级别均线呈多头排列<br/>短期均线>中期均线>长期均线<br/>表示中期趋势向上<br/>股票处于稳健上涨阶段" placement="top">
                          <el-icon class="info-icon"><InfoFilled /></el-icon>
                        </el-tooltip>
                      </span>
                  <el-tag :type="analysisResult.weekly_ma_aligned ? 'success' : 'info'" size="small">
                    {{ analysisResult.weekly_ma_aligned ? '是' : '否' }}
                  </el-tag>
                </div>
                <div class="detail-item">
                  <span class="detail-label">
                        量能健康
                        <el-tooltip raw-content content="成交量处于合理水平<br/>既不过度萎缩(缺乏人气)<br/>也不过度放大(可能透支)<br/>健康的量能配合价格上涨<br/>是持续上涨的基础" placement="top">
                          <el-icon class="info-icon"><InfoFilled /></el-icon>
                        </el-tooltip>
                      </span>
                  <el-tag :type="analysisResult.volume_healthy ? 'success' : 'info'" size="small">
                    {{ analysisResult.volume_healthy ? '是' : '否' }}
                  </el-tag>
                </div>
	              </div>

	              <!-- 评分明细 -->
	              <template v-if="analysisResult.scores && Object.keys(analysisResult.scores).length > 0">
	                <el-divider />

	                <div class="score-details">
	                <div class="section-header">
	                  <h5>评分明细</h5>
	                </div>
	                  <p class="score-summary">{{ analysisResult.comment || '-' }}</p>

	                  <div class="score-grid">
	                    <div class="score-item" v-for="item in scoreItems" :key="item.key">
	                      <div class="score-header">
	                        <span class="score-label">{{ item.label }}</span>
	                        <el-tag :type="getScoreType(item.value)" size="small">
	                          {{ item.value || 0 }}/5
	                        </el-tag>
	                      </div>
	                      <el-tooltip :content="item.reason || '-'" placement="top" :disabled="!item.reason">
                        <div class="score-reason">{{ item.reason || '-' }}</div>
                      </el-tooltip>
	                    </div>
	                  </div>

	                  <!-- 信号类型说明 -->
	                  <div v-if="analysisResult.signal_type" class="signal-type-box">
	                    <span class="signal-label">信号类型:</span>
	                    <el-tag :type="getSignalTagType(analysisResult.signal_type)" size="small">
	                      {{ getSignalLabel(analysisResult.signal_type) }}
	                    </el-tag>
	                    <span class="signal-reason">{{ analysisResult.signal_reasoning || '' }}</span>
	                  </div>
	                </div>
	              </template>
	            </div>

            <el-empty v-else description="暂无分析数据" :image-size="80" />
          </el-card>
        </el-col>
      </el-row>

      <!-- 历史记录 -->
      <el-card class="history-card">
        <template #header>
          <div class="history-header">
            <span>每日检查历史 (近30个交易日收盘后数据)</span>
            <div class="history-actions">
              <span v-if="refreshingHistory" class="refreshing-text">
                正在刷新... ({{ historyData.length }}/30)
              </span>
              <el-button
                type="primary"
                size="small"
                :icon="Refresh"
                :loading="refreshingHistory"
                @click="refreshHistory"
              >
                {{ refreshingHistory ? '刷新中...' : '重新刷新历史数据' }}
              </el-button>
            </div>
          </div>
        </template>
        <el-table
          :data="historyData"
          stripe
          size="small"
          max-height="300"
        >
          <el-table-column prop="check_date" label="交易日" width="110">
            <template #default="{ row }">
              {{ formatDate(row.check_date) }}
            </template>
          </el-table-column>
          <el-table-column prop="close_price" label="收盘价" width="90" align="right">
            <template #default="{ row }">
              {{ row.close_price != null ? row.close_price.toFixed(2) : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="change_pct" label="涨跌幅" width="80" align="right">
            <template #default="{ row }">
              <span :class="getChangeClass(row.change_pct)">
                {{ formatChange(row.change_pct) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="kdj_j" label="KDJ-J" width="70" align="right">
            <template #default="{ row }">
              {{ row.kdj_j != null ? row.kdj_j.toFixed(1) : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="b1_passed" label="B1" width="60" align="center">
            <template #default="{ row }">
              <el-tag :type="row.b1_passed ? 'success' : 'info'" size="small">
                {{ row.b1_passed ? '✓' : '✗' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="score" label="当日评分" width="80" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.score != null" :type="getScoreType(row.score)" size="small">
                {{ row.score.toFixed(1) }}
              </el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column prop="verdict" label="当日信号" width="90" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.verdict" :type="getVerdictType(row.verdict)" size="small">
                {{ row.verdict }}
              </el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>

    <!-- 初始状态 -->
    <el-empty v-else :description="emptyDescription" :image-size="120">
      <el-button v-if="!configStore.dataInitialized && configStore.tushareReady" type="primary" @click="goTaskCenter">
        前往任务中心初始化
      </el-button>
      <el-button v-if="!configStore.tushareReady" @click="goConfig">
        前往配置
      </el-button>
    </el-empty>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, onActivated, onDeactivated, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Search, InfoFilled, Refresh } from '@element-plus/icons-vue'
import { apiAnalysis, apiStock, apiWatchlist, isRequestCanceled } from '@/api'
import { ElMessage } from 'element-plus'
import type { ECharts, EChartsCoreOption } from 'echarts/core'
import type { B1Check, DiagnosisAnalysisDetails, KLineData, WatchlistItem } from '@/types'
import { useConfigStore } from '@/store/config'

const route = useRoute()
const router = useRouter()
const configStore = useConfigStore()
const DIAGNOSIS_STATE_KEY = 'stocktrade:diagnosis:state'
const DIAGNOSIS_CHART_CACHE_KEY = 'stocktrade:diagnosis:chart-cache'
const DIAGNOSIS_CHART_CACHE_TTL_MS = 30 * 60 * 1000
const AUTO_HISTORY_REFRESH_INTERVAL_MS = 5 * 60 * 1000
const DIAGNOSIS_INITIAL_CHART_DAYS = 60

const searchForm = ref({ code: '' })
const stockCode = ref('')
const chartDays = ref(120)
const chartRef = ref<HTMLElement>()
const analyzing = ref(false)
const refreshingHistory = ref(false)
const addingToWatchlist = ref(false)
const isInWatchlist = ref(false)

type DiagnosisViewResult = {
  score?: number
  b1_passed?: boolean
  verdict?: string
  signal_type?: string
  signal_reasoning?: string
  comment?: string
  kdj_j?: number
  zx_long_pos?: boolean
  weekly_ma_aligned?: boolean
  volume_healthy?: boolean
  scores?: Record<string, number>
  trend_reasoning?: string
  position_reasoning?: string
  volume_reasoning?: string
  abnormal_move_reasoning?: string
}

const historyData = ref<B1Check[]>([])
const analysisResult = ref<DiagnosisViewResult | null>(null)
const stockName = ref('')
const lastAutoHistoryRefreshAt = ref<Record<string, number>>({})

// 轮询定时器
let pollingTimer: ReturnType<typeof setInterval> | null = null

// 评分项配置
const scoreConfig = {
  trend_structure: { label: '趋势结构', weight: 0.2 },
  price_position: { label: '价格位置', weight: 0.2 },
  volume_behavior: { label: '量价行为', weight: 0.3 },
  previous_abnormal_move: { label: '历史异动', weight: 0.3 },
}

// 计算评分项
const scoreItems = computed(() => {
  if (!analysisResult.value?.scores) return []
  const scores = analysisResult.value.scores
  return [
    {
      key: 'trend_structure',
      label: scoreConfig.trend_structure.label,
      value: scores.trend_structure,
      reason: analysisResult.value.trend_reasoning || '',
    },
    {
      key: 'price_position',
      label: scoreConfig.price_position.label,
      value: scores.price_position,
      reason: analysisResult.value.position_reasoning || '',
    },
    {
      key: 'volume_behavior',
      label: scoreConfig.volume_behavior.label,
      value: scores.volume_behavior,
      reason: analysisResult.value.volume_reasoning || '',
    },
    {
      key: 'previous_abnormal_move',
      label: scoreConfig.previous_abnormal_move.label,
      value: scores.previous_abnormal_move,
      reason: analysisResult.value.abnormal_move_reasoning || '',
    },
  ]
})
const showInitializationAlert = computed(() => configStore.tushareReady && !configStore.dataInitialized)
const emptyDescription = computed(() => {
  if (!configStore.tushareReady) return '请先完成 Tushare 配置后再进行单股诊断'
  if (!configStore.dataInitialized) return '请先完成首次初始化，再进行单股诊断'
  return '请输入股票代码进行诊断'
})

let chartInstance: ECharts | null = null
let chartRuntimePromise: Promise<{ init: (dom: HTMLElement, theme?: string | object, opts?: object) => ECharts }> | null = null
const diagnosisChartCache = new Map<string, KLineData>()
const diagnosisChartCacheDays = new Map<string, number>()
const requestControllers = new Map<string, AbortController>()
let searchSequence = 0

function beginRequest(key: string): AbortSignal {
  requestControllers.get(key)?.abort()
  const controller = new AbortController()
  requestControllers.set(key, controller)
  return controller.signal
}

function finishRequest(key: string, signal?: AbortSignal) {
  const controller = requestControllers.get(key)
  if (controller && (!signal || controller.signal === signal)) {
    requestControllers.delete(key)
  }
}

function cancelRequest(key: string) {
  const controller = requestControllers.get(key)
  if (controller) {
    controller.abort()
    requestControllers.delete(key)
  }
}

function cancelDiagnosisPageRequests() {
  requestControllers.forEach((controller) => controller.abort())
  requestControllers.clear()
}

onMounted(() => {
  configStore.checkTushareStatus()
  restoreDiagnosisState()

  // 从路由参数获取股票代码
  const routeCode = normalizeRouteCode(route.query.code)
  if (routeCode) {
    searchForm.value.code = routeCode
    searchAndAnalyze()
  }

  window.addEventListener('resize', handleResize)
})

onActivated(() => {
  configStore.checkTushareStatus()
  nextTick(() => {
    chartInstance?.resize()
  })

  const routeCode = normalizeRouteCode(route.query.code)
  if (routeCode && routeCode !== stockCode.value) {
    searchForm.value.code = routeCode
    searchAndAnalyze()
    return
  }

  if (stockCode.value) {
    maybeAutoRefreshHistory(true)
  }
})

onDeactivated(() => {
  searchSequence += 1
  if (pollingTimer) {
    clearInterval(pollingTimer)
    pollingTimer = null
  }
  cancelDiagnosisPageRequests()
  refreshingHistory.value = false
  analyzing.value = false
})

onUnmounted(() => {
  searchSequence += 1
  if (chartInstance) {
    chartInstance.dispose()
  }
  window.removeEventListener('resize', handleResize)
  if (pollingTimer) {
    clearInterval(pollingTimer)
    pollingTimer = null
  }
  cancelDiagnosisPageRequests()
})

function handleResize() {
  chartInstance?.resize()
}

async function searchStock(requestId: number) {
  if (!configStore.tushareReady) {
    ElMessage.warning('请先完成 Tushare 配置')
    return
  }

  const code = searchForm.value.code.trim()
  if (!code) {
    ElMessage.warning('请输入股票代码')
    return
  }

  cancelRequest('stockInfo')
  cancelRequest('watchlistStatus')
  cancelRequest('kline')
  cancelRequest('klineExtended')
  cancelRequest('historyLoad')
  cancelRequest('historyRefresh')
  cancelRequest('historyStatus')
  cancelRequest('analyze')
  stockCode.value = code.padStart(6, '0')
  analysisResult.value = null

  await loadStockInfo()
  if (requestId !== searchSequence) return
  await loadWatchlistStatus()
  if (requestId !== searchSequence) return
  // 加载 K线数据
  await loadKlineData()
  if (requestId !== searchSequence) return

  // 加载历史检查记录
  await loadHistoryData()
  if (requestId !== searchSequence) return
  persistDiagnosisState()
  await maybeAutoRefreshHistory()
}

async function searchAndAnalyze() {
  const requestId = ++searchSequence

  // 如果状态还没加载过，先加载一次
  if (!configStore.tushareStatus) {
    await configStore.checkTushareStatus()
  }

  // 现在再检查初始化状态
  if (!configStore.dataInitialized) {
    ElMessage.info('请先完成首次初始化')
    return
  }

  await searchStock(requestId)
  if (requestId !== searchSequence) return

  // 自动开始分析
  if (stockCode.value) {
    await analyzeStock()
  }
}

async function loadStockInfo() {
  if (!stockCode.value) return

  const signal = beginRequest('stockInfo')
  try {
    const data = await apiStock.getInfo(stockCode.value, { signal })
    stockName.value = data.name || ''
    persistDiagnosisState()
  } catch (error) {
    if (isRequestCanceled(error)) return
    stockName.value = ''
  } finally {
    finishRequest('stockInfo', signal)
  }
}

async function loadWatchlistStatus() {
  if (!stockCode.value) return

  const signal = beginRequest('watchlistStatus')
  try {
    const data = await apiWatchlist.getAll({ signal })
    const items = data.items || []
    isInWatchlist.value = items.some((item: WatchlistItem) => item.code === stockCode.value)
  } catch (error) {
    if (isRequestCanceled(error)) return
    isInWatchlist.value = false
  } finally {
    finishRequest('watchlistStatus', signal)
  }
  persistDiagnosisState()
}

async function refreshHistory() {
  await triggerHistoryRefresh()
}

async function triggerHistoryRefresh(silent: boolean = false) {
  if (!stockCode.value || refreshingHistory.value) return

  refreshingHistory.value = true

  const signal = beginRequest('historyRefresh')
  try {
    await apiAnalysis.refreshHistory(stockCode.value, 30, { signal })
    lastAutoHistoryRefreshAt.value[stockCode.value] = Date.now()
    persistDiagnosisState()
    startPollingHistory(silent)

    if (!silent) {
      ElMessage.info('开始刷新历史数据，请稍候...')
    }
  } catch (error: any) {
    if (isRequestCanceled(error)) return
    if (!silent) {
      ElMessage.error('刷新历史数据失败: ' + error.message)
    }
    refreshingHistory.value = false
  } finally {
    finishRequest('historyRefresh', signal)
  }
}

async function maybeAutoRefreshHistory(force: boolean = false) {
  if (!stockCode.value) return

  const lastRefreshAt = lastAutoHistoryRefreshAt.value[stockCode.value] || 0
  const latestHistory = historyData.value[0]
  const hasScoredToday = Boolean(latestHistory && latestHistory.score != null && latestHistory.verdict)
  const shouldRefresh = force
    ? !refreshingHistory.value && Date.now() - lastRefreshAt >= AUTO_HISTORY_REFRESH_INTERVAL_MS
    : !hasScoredToday || (Date.now() - lastRefreshAt >= AUTO_HISTORY_REFRESH_INTERVAL_MS)

  if (shouldRefresh) {
    await triggerHistoryRefresh(true)
  }
}

function startPollingHistory(silent: boolean = false) {
  if (pollingTimer) {
    clearInterval(pollingTimer)
  }

  // 立即加载一次
  loadHistoryData()

  // 每2秒轮询一次
  pollingTimer = setInterval(async () => {
    const currentCode = stockCode.value
    if (!currentCode) return

    const signal = beginRequest('historyStatus')
    try {
      const status = await apiAnalysis.getHistoryStatus(currentCode, { signal })

      // 加载最新数据
      await loadHistoryData()

      // 如果生成完成，停止轮询并刷新分析
      if (!status.generating) {
        stopPollingHistory()
        // 刷新最新分析
        await analyzeStock()
        if (!silent) {
          ElMessage.success(`历史数据刷新完成，共 ${historyData.value.length} 条`)
        }
      }
    } catch (error) {
      if (isRequestCanceled(error)) return
      // 忽略轮询错误
    } finally {
      finishRequest('historyStatus', signal)
    }
  }, 2000)
}

function stopPollingHistory() {
  if (pollingTimer) {
    clearInterval(pollingTimer)
    pollingTimer = null
  }
  refreshingHistory.value = false
}

async function loadKlineData() {
  if (!stockCode.value) return

  const requestedDays = chartDays.value
  const signal = beginRequest('kline')
  try {
    let data = diagnosisChartCache.get(stockCode.value)
    let cachedDays = diagnosisChartCacheDays.get(stockCode.value) || 0

    if (!data || cachedDays < Math.min(requestedDays, DIAGNOSIS_INITIAL_CHART_DAYS)) {
      const persistent = loadDiagnosisChartCache(stockCode.value)
      if (persistent) {
        data = persistent.data
        cachedDays = persistent.days
        diagnosisChartCache.set(stockCode.value, persistent.data)
        diagnosisChartCacheDays.set(stockCode.value, persistent.days)
      }
    }

    const initialDays = requestedDays >= 120 ? DIAGNOSIS_INITIAL_CHART_DAYS : requestedDays
    if (!data || cachedDays < initialDays) {
      data = await apiStock.getKline(stockCode.value, initialDays, false, { signal })
      cachedDays = initialDays
      setDiagnosisChartCache(stockCode.value, data, initialDays)
    }

    await nextTick()
    await renderChart(data)
    // 确保图表在容器渲染完成后有正确的尺寸
    setTimeout(() => {
      chartInstance?.resize()
    }, 100)
    persistDiagnosisState()
    queueDiagnosisFullChartRefresh(stockCode.value, requestedDays, cachedDays)
  } catch (error: any) {
    if (isRequestCanceled(error)) return
    console.error('Failed to load kline:', error)
    ElMessage.error('加载K线数据失败: ' + error.message)
  } finally {
    finishRequest('kline', signal)
  }
}

async function renderChart(data: KLineData) {
  if (!chartRef.value) return

  const { init } = await loadDiagnosisChartRuntime()

  if (!chartInstance) {
    chartInstance = init(chartRef.value, undefined, { renderer: 'canvas' })
  }

  const dates = data.daily.map((d) => d.date)
  const values = data.daily.map((d) => [d.open, d.close, d.low, d.high])
  const volumes = data.daily.map((d) => d.volume)
  const ma5 = data.daily.map((d) => d.ma5)
  const ma10 = data.daily.map((d) => d.ma10)
  const ma20 = data.daily.map((d) => d.ma20)

  // 中国习惯：红涨绿跌
  const option: EChartsCoreOption = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (params: any) => {
        if (!params || params.length === 0) return ''
        const dataIndex = params[0].dataIndex
        const date = dates[dataIndex]
        const rowData = data.daily[dataIndex]

        let result = `<b>${date}</b><br/>`

        if (rowData) {
          const change = ((rowData.close - rowData.open) / rowData.open * 100)
          const changeText = change >= 0 ? '+' : ''
          const changeColor = change >= 0 ? '#ef5350' : '#26a69a'

          result += `开盘: ${rowData.open?.toFixed(2) || '-'}<br/>`
          result += `收盘: ${rowData.close?.toFixed(2) || '-'}<br/>`
          result += `最低: ${rowData.low?.toFixed(2) || '-'}<br/>`
          result += `最高: ${rowData.high?.toFixed(2) || '-'}<br/>`
          result += `涨跌: <span style="color:${changeColor}">${changeText}${change.toFixed(2)}%</span><br/>`

          if (rowData.ma5 != null && !isNaN(rowData.ma5)) {
            result += `MA5: ${rowData.ma5.toFixed(2)}<br/>`
          }
          if (rowData.ma10 != null && !isNaN(rowData.ma10)) {
            result += `MA10: ${rowData.ma10.toFixed(2)}<br/>`
          }
          if (rowData.ma20 != null && !isNaN(rowData.ma20)) {
            result += `MA20: ${rowData.ma20.toFixed(2)}<br/>`
          }

          if (rowData.volume != null && !isNaN(rowData.volume)) {
            result += `成交量: ${(rowData.volume / 10000).toFixed(2)}万`
          }
        }

        return result
      }
    },
    legend: {
      data: ['K线', 'MA5', 'MA10', 'MA20'],
      top: 10,
    },
    grid: [
      { left: '10%', right: '8%', top: '15%', height: '55%' },
      { left: '10%', right: '8%', top: '75%', height: '15%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        gridIndex: 0,
        axisLabel: { show: false },
      },
      {
        type: 'category',
        data: dates,
        gridIndex: 1,
        axisLabel: { fontSize: 10 },
      },
    ],
    yAxis: [
      {
        scale: true,
        gridIndex: 0,
        splitLine: { show: true, lineStyle: { color: '#f0f0f0' } },
      },
      {
        scale: true,
        gridIndex: 1,
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 50, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], start: 50, end: 100, height: 20 },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: values,
        // 中国习惯：红涨绿跌
        itemStyle: {
          color: '#ef5350',        // 阳线（涨）- 红色
          color0: '#26a69a',       // 阴线（跌）- 绿色
          borderColor: '#ef5350',  // 阳线边框 - 红色
          borderColor0: '#26a69a', // 阴线边框 - 绿色
        },
      },
      {
        name: 'MA5',
        type: 'line',
        data: ma5,
        smooth: true,
        lineStyle: { width: 1 },
        symbol: 'none',
      },
      {
        name: 'MA10',
        type: 'line',
        data: ma10,
        smooth: true,
        lineStyle: { width: 1 },
        symbol: 'none',
      },
      {
        name: 'MA20',
        type: 'line',
        data: ma20,
        smooth: true,
        lineStyle: { width: 1 },
        symbol: 'none',
      },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
        itemStyle: { color: '#778899' },
      },
    ],
  }

  nextTick(() => {
    if (chartInstance) {
      chartInstance.setOption(option)
      chartInstance.resize()
    }
  })
}

function queueDiagnosisFullChartRefresh(code: string, requestedDays: number, currentDays: number) {
  if (requestedDays < 120 || currentDays >= requestedDays) return
  if (stockCode.value !== code) return
  void refreshDiagnosisFullChartInBackground(code, requestedDays)
}

async function refreshDiagnosisFullChartInBackground(code: string, requestedDays: number) {
  const signal = beginRequest('klineExtended')
  try {
    const fullData = await apiStock.getKline(code, requestedDays, false, { signal, timeoutMs: 20000 })
    if (stockCode.value !== code || chartDays.value !== requestedDays) return
    setDiagnosisChartCache(code, fullData, requestedDays)
    await renderChart(fullData)
    persistDiagnosisState()
  } catch (error) {
    if (isRequestCanceled(error)) return
    console.error('Failed to extend diagnosis kline:', error)
  } finally {
    finishRequest('klineExtended', signal)
  }
}

async function loadDiagnosisChartRuntime() {
  if (!chartRuntimePromise) {
    chartRuntimePromise = (async () => {
      const [{ use, init }, charts, components, renderers] = await Promise.all([
        import('echarts/core'),
        import('echarts/charts'),
        import('echarts/components'),
        import('echarts/renderers'),
      ])

      use([
        charts.BarChart,
        charts.CandlestickChart,
        charts.LineChart,
        components.TooltipComponent,
        components.LegendComponent,
        components.GridComponent,
        components.DataZoomComponent,
        renderers.CanvasRenderer,
      ])

      return { init }
    })()
  }

  return chartRuntimePromise
}

async function loadHistoryData() {
  if (!stockCode.value) return

  const signal = beginRequest('historyLoad')
  try {
    const data = await apiAnalysis.getDiagnosisHistory(stockCode.value, 30, { signal })
    historyData.value = (data.history || []).slice(0, 30) // 限制30天
    persistDiagnosisState()
  } catch (error: any) {
    if (isRequestCanceled(error)) return
    console.error('Failed to load history:', error)
  } finally {
    finishRequest('historyLoad', signal)
  }
}

async function analyzeStock() {
  if (!configStore.dataInitialized) {
    ElMessage.info('请先完成首次初始化')
    return
  }
  if (!stockCode.value) return

  const signal = beginRequest('analyze')
  analyzing.value = true
  try {
    const data = await apiAnalysis.analyze(stockCode.value, { signal })
    stockName.value = data.name || stockName.value
    const analysis: DiagnosisAnalysisDetails = data.analysis || {}
    analysisResult.value = {
      score: data.score,
      b1_passed: data.b1_passed,
      verdict: data.verdict,
      // 从 analysis 对象中获取所有字段
      signal_type: analysis.signal_type,
      signal_reasoning: analysis.signal_reasoning,
      comment: analysis.comment,
      // B1 检查详情
      kdj_j: analysis.kdj_j,
      zx_long_pos: analysis.zx_long_pos,
      weekly_ma_aligned: analysis.weekly_ma_aligned,
      volume_healthy: analysis.volume_healthy,
      // 评分明细
      scores: analysis.scores || {},
      trend_reasoning: analysis.trend_reasoning || '',
      position_reasoning: analysis.position_reasoning || '',
      volume_reasoning: analysis.volume_reasoning || '',
      abnormal_move_reasoning: analysis.abnormal_move_reasoning || '',
    }

    // 刷新历史数据
    await loadHistoryData()
    persistDiagnosisState()

    ElMessage.success('分析完成')
  } catch (error: any) {
    if (isRequestCanceled(error)) return
    ElMessage.error('分析失败: ' + error.message)
  } finally {
    finishRequest('analyze', signal)
    analyzing.value = false
  }
}

function goTaskCenter() {
  router.push('/update')
}

function goConfig() {
  router.push('/config')
}

async function addCurrentToWatchlist() {
  if (!stockCode.value || isInWatchlist.value) return

  addingToWatchlist.value = true
  try {
    const reasonParts = []
    if (analysisResult.value?.verdict) {
      reasonParts.push(`诊断结论:${analysisResult.value.verdict}`)
    }
    if (analysisResult.value?.score != null) {
      reasonParts.push(`评分:${analysisResult.value.score.toFixed(1)}`)
    }
    await apiWatchlist.add(stockCode.value, reasonParts.join(' | ') || '单股诊断加入重点观察')
    isInWatchlist.value = true
    persistDiagnosisState()
    ElMessage.success(`已将 ${stockCode.value}${stockName.value ? ` ${stockName.value}` : ''} 纳入重点观察`)
  } catch (error: any) {
    ElMessage.error('纳入重点观察失败: ' + error.message)
  } finally {
    addingToWatchlist.value = false
  }
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  return `${d.getMonth() + 1}/${d.getDate()}`
}

function formatChange(pct?: number): string {
  if (pct === undefined || pct === null) return '-'
  return (pct > 0 ? '+' : '') + pct.toFixed(2) + '%'
}

// 中国习惯：红涨绿跌
function getChangeClass(pct?: number): string {
  if (!pct) return ''
  return pct > 0 ? 'text-up' : 'text-down'
}

function getVerdictType(verdict: string): string {
  const types: Record<string, string> = {
    'PASS': 'success',
    'WATCH': 'warning',
    'FAIL': 'danger',
  }
  return types[verdict] || 'info'
}

function getScoreType(score?: number): string {
  if (!score) return 'info'
  if (score >= 4.5) return 'success'
  if (score >= 4.0) return 'warning'
  return 'danger'
}

function getSignalLabel(signalType: string): string {
  const labels: Record<string, string> = {
    'trend_start': '趋势启动',
    'rebound': '反弹延续',
    'distribution_risk': '风险释放',
  }
  return labels[signalType] || signalType
}

function getSignalTagType(signalType: string): string {
  const types: Record<string, string> = {
    'trend_start': 'success',
    'rebound': 'warning',
    'distribution_risk': 'danger',
  }
  return types[signalType] || 'info'
}

function persistDiagnosisState() {
  if (typeof window === 'undefined') return

  const state = {
    searchForm: searchForm.value,
    stockCode: stockCode.value,
    stockName: stockName.value,
    chartDays: chartDays.value,
    historyData: historyData.value,
    analysisResult: analysisResult.value,
    isInWatchlist: isInWatchlist.value,
    lastAutoHistoryRefreshAt: lastAutoHistoryRefreshAt.value,
  }

  sessionStorage.setItem(DIAGNOSIS_STATE_KEY, JSON.stringify(state))
}

function loadDiagnosisChartCache(code: string): { code: string; days: number; cachedAt: number; data: KLineData } | null {
  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return null

  const raw = window.localStorage.getItem(DIAGNOSIS_CHART_CACHE_KEY)
  if (!raw) return null

  try {
    const cache = JSON.parse(raw) as Record<string, { code: string; days: number; cachedAt: number; data: KLineData }>
    const entry = cache[code]
    if (!entry) return null
    if (!entry.cachedAt || Date.now() - entry.cachedAt > DIAGNOSIS_CHART_CACHE_TTL_MS) {
      delete cache[code]
      window.localStorage.setItem(DIAGNOSIS_CHART_CACHE_KEY, JSON.stringify(cache))
      return null
    }
    return entry
  } catch {
    window.localStorage.removeItem(DIAGNOSIS_CHART_CACHE_KEY)
    return null
  }
}

function setDiagnosisChartCache(code: string, data: KLineData, days: number) {
  diagnosisChartCache.set(code, data)
  diagnosisChartCacheDays.set(code, days)

  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return

  let cache: Record<string, { code: string; days: number; cachedAt: number; data: KLineData }> = {}
  try {
    cache = JSON.parse(window.localStorage.getItem(DIAGNOSIS_CHART_CACHE_KEY) || '{}')
  } catch {
    cache = {}
  }

  cache[code] = {
    code,
    days,
    cachedAt: Date.now(),
    data,
  }

  const trimmed = Object.values(cache)
    .sort((a, b) => b.cachedAt - a.cachedAt)
    .slice(0, 20)
  window.localStorage.setItem(
    DIAGNOSIS_CHART_CACHE_KEY,
    JSON.stringify(Object.fromEntries(trimmed.map((entry) => [entry.code, entry])))
  )
}

function restoreDiagnosisState() {
  if (typeof window === 'undefined') return

  const raw = sessionStorage.getItem(DIAGNOSIS_STATE_KEY)
  if (!raw) return

  try {
    const state = JSON.parse(raw)
    searchForm.value = state.searchForm || { code: '' }
    stockCode.value = state.stockCode || ''
    stockName.value = state.stockName || ''
    chartDays.value = state.chartDays || 120
    historyData.value = state.historyData || []
    analysisResult.value = state.analysisResult || null
    isInWatchlist.value = Boolean(state.isInWatchlist)
    lastAutoHistoryRefreshAt.value = state.lastAutoHistoryRefreshAt || {}

    if (stockCode.value) {
      nextTick(() => {
        loadKlineData()
      })
    }
  } catch {
    sessionStorage.removeItem(DIAGNOSIS_STATE_KEY)
  }
}

function normalizeRouteCode(code: unknown): string {
  const raw = Array.isArray(code) ? code[0] : code
  if (typeof raw !== 'string') return ''
  const trimmed = raw.trim()
  if (!trimmed) return ''
  return trimmed.padStart(6, '0')
}
</script>

<style scoped lang="scss">
.diagnosis-page {
  .page-alert {
    margin-bottom: 16px;
  }

  .search-card {
    margin-bottom: 20px;
  }

  .content-row {
    margin-bottom: 20px;
  }

  .chart-card {
    height: 100%;
    display: flex;
    flex-direction: column;

    :deep(.el-card__body) {
      flex: 1;
      display: flex;
      flex-direction: column;
    }

    .chart-container {
      flex: 1;
      min-height: 400px;
    }
  }

  .analysis-card {
    height: 100%;
    display: flex;
    flex-direction: column;

    :deep(.el-card__body) {
      flex: 1;
      overflow-y: auto;
    }

    .analysis-content {
      :deep(.el-divider) {
        margin: 8px 0;
      }

      .analysis-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 6px 0;
        border-bottom: 1px solid #f0f0f0;

        &:last-of-type {
          border-bottom: none;
        }

        .label {
          display: flex;
          align-items: center;
          gap: 4px;
          color: var(--color-text-secondary);
        }

        .value {
          font-weight: 500;
        }
      }

      .b1-details {
        .section-header {
          margin-bottom: 8px;

		  h5 {
            margin: 0 0 8px 0;
            color: var(--color-text-secondary);
          }

		  :deep(.el-alert) {
		    padding: 8px 12px;

		    .el-alert__title {
		      font-size: 12px;
		      font-weight: 500;
		    }

		    .alert-content {
		      font-size: 11px;
		      color: #606266;
		      margin-top: 4px;
		    }
		  }
		}

        .detail-item {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 6px 0;

          .detail-label {
            display: flex;
            align-items: center;
            gap: 4px;
          }

          .info-icon {
            font-size: 14px;
            color: var(--color-info);
            cursor: help;
          }
        }
      }

      .evaluation-note {
        margin-bottom: 12px;

        :deep(.el-alert__title) {
          font-size: 13px;
          font-weight: 600;
        }

        .note-content {
          font-size: 12px;
          color: #606266;
          line-height: 1.6;
        }
      }

      .score-details {
        .section-header {
          margin-bottom: 8px;

		  h5 {
            margin: 0 0 8px 0;
            color: var(--color-text-secondary);
          }

		  :deep(.el-alert) {
		    padding: 8px 12px;

		    .el-alert__title {
		      font-size: 12px;
		      font-weight: 500;
		    }

		    .alert-content {
		      font-size: 11px;
		      color: #606266;
		      margin-top: 4px;
		    }
		  }
		}

        h5 {
          margin: 0 0 8px 0;
          color: var(--color-text-secondary);
        }

        .score-summary {
          margin: 0 0 10px 0;
          padding: 8px 12px;
          background-color: #f5f7fa;
          border-radius: 4px;
          font-size: 13px;
          color: #606266;
          line-height: 1.5;
        }

        .score-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 10px;
          margin-bottom: 10px;

          .score-item {
            padding: 8px;
            background-color: #fafafa;
            border-radius: 4px;
            border-left: 3px solid #e4e7ed;

            &:nth-child(1) { border-left-color: #409eff; }
            &:nth-child(2) { border-left-color: #67c23a; }
            &:nth-child(3) { border-left-color: #e6a23c; }
            &:nth-child(4) { border-left-color: #f56c6c; }

            .score-header {
              display: flex;
              justify-content: space-between;
              align-items: center;
              margin-bottom: 4px;

              .score-label {
                font-size: 13px;
                font-weight: 500;
                color: #303133;
              }
            }

            .score-reason {
              font-size: 12px;
              color: #909399;
              line-height: 1.4;
              display: -webkit-box;
              -webkit-line-clamp: 2;
              -webkit-box-orient: vertical;
              overflow: hidden;
              cursor: help;
            }
          }
        }

        .signal-type-box {
          padding: 8px 12px;
          background-color: #f0f9ff;
          border-radius: 4px;
          display: flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;

          .signal-label {
            font-size: 13px;
            font-weight: 500;
            color: #303133;
          }

          .signal-reason {
            font-size: 12px;
            color: #606266;
            flex: 1;
          }
        }
      }
    }
  }

  .history-header {
    display: flex;
    justify-content: space-between;
    align-items: center;

    .history-actions {
      display: flex;
      align-items: center;
      gap: 12px;

      .refreshing-text {
        font-size: 13px;
        color: var(--color-warning);
      }
    }
  }

  // 中国习惯：红涨绿跌
  .text-up {
    color: #ef5350;  // 红色 - 涨
  }

  .text-down {
    color: #26a69a;  // 绿色 - 跌
  }
}
</style>
