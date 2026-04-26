<template>
  <div class="tomorrow-star-page">
    <el-alert
      v-if="showInitializationAlert"
      class="page-alert"
      type="info"
      :closable="false"
      show-icon
      title="尚未完成首次初始化"
      :description="configStore.initializationMessage"
    />

    <div v-if="showInitializationEmpty" class="page-empty">
      <el-empty description="明日之星尚无可用数据" :image-size="120">
        <el-button type="primary" @click="router.push('/update')">
          前往任务中心初始化
        </el-button>
        <el-button @click="refreshStatusAndRetry">
          重新检查状态
        </el-button>
      </el-empty>
    </div>

    <el-row v-else :gutter="20">
      <!-- 左侧：历史记录 -->
      <el-col :span="8">
        <el-card class="history-card">
          <template #header>
            <div class="card-header">
              <span>历史记录</span>
              <el-button
                type="primary"
                size="small"
                :icon="Refresh"
                :loading="loading"
                @click="ensureFreshDataAndLoad(true)"
              >
                刷新
              </el-button>
            </div>
          </template>

          <div class="table-header-tip">
            <span class="tip-item">· 时间：分析日期</span>
            <span class="tip-item">· 候选数：符合条件的股票数量</span>
            <span class="tip-item">· 趋势启动数：分析结果中判定为趋势启动的股票数量</span>
          </div>
          <el-table
            :data="historyData"
            @row-click="selectDate"
            class="history-table"
            height="460"
          >
            <el-table-column prop="date" label="时间" width="120" />
            <el-table-column prop="count" label="候选数" width="100" align="center">
              <template #default="{ row }">
                {{ row.count === '-' ? '-' : row.count }}
              </template>
            </el-table-column>
            <el-table-column prop="pass" label="趋势启动数" width="120" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.pass !== '-'" :type="row.pass > 0 ? 'success' : 'info'" size="small">
                  {{ row.pass }}
                </el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <!-- 右侧：候选列表 -->
      <el-col :span="16">
        <el-card class="candidates-card">
          <template #header>
            <div class="card-header">
              <div class="title-section">
                <span>候选股票</span>
                <el-tag v-if="dataDate" size="small" type="info" class="date-tag">
                  数据日期: {{ dataDate }}
                </el-tag>
              </div>
              <div class="header-actions">
                <el-tag v-if="showCachedHint" type="info" size="small" effect="plain">
                  已展示上次结果
                </el-tag>
                <el-tag v-if="checkingFreshness" type="info" size="small" effect="plain">
                  后台校验中
                </el-tag>
                <el-tag v-if="updatingData" type="warning" size="small" effect="plain">
                  更新中...
                </el-tag>
                <el-tag v-if="loadingCandidates" type="warning" size="small" effect="plain">
                  筛选中...
                </el-tag>
                <el-button
                  type="primary"
                  size="small"
                  :icon="Refresh"
                  :loading="loadingCandidates"
                  @click="refreshCandidates"
                >
                  刷新
                </el-button>
              </div>
            </div>
          </template>

          <div class="table-header-tip">
            <span class="tip-item">· 筛选逻辑：通过 B1 策略筛选候选股票</span>
            <span class="tip-item">· 条件：KDJ 低位 + 知行线结构通过 + 周线多头排列 + 最大量日非阴线</span>
          </div>

          <el-table
            :data="displayCandidates"
            stripe
            class="candidates-table"
            height="400"
            table-layout="auto"
          >
            <el-table-column prop="code" label="代码" min-width="140" />
            <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
            <el-table-column prop="close_price" label="收盘价" min-width="140" align="right">
              <template #default="{ row }">
                {{ row.close_price ? row.close_price.toFixed(2) : '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="kdj_j" label="KDJ-J" min-width="120" align="right">
              <template #default="{ row }">
                {{ row.kdj_j ? row.kdj_j.toFixed(1) : '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="strategy" label="策略" min-width="120">
              <template #default="{ row }">
                <el-tag size="small" :type="row.strategy === 'b1' ? 'primary' : 'warning'">
                  {{ (row.strategy || '').toUpperCase() }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="b1_passed" label="B1检查" min-width="140" align="center">
              <template #default="{ row }">
                <el-tag :type="row.b1_passed ? 'success' : 'danger'" size="small">
                  {{ row.b1_passed ? '通过' : '未通过' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120" align="center" fixed="right">
              <template #default="{ row }">
                <el-button text type="primary" size="small" @click="viewStock(row.code)">
                  详情
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <div v-if="totalCandidates > candidatePageSize" class="pagination-wrap">
            <el-pagination
              v-model:current-page="candidatePage"
              :page-size="candidatePageSize"
              layout="total, prev, pager, next"
              :total="totalCandidates"
              background
            />
          </div>

          <!-- 分析结果 -->
          <template v-if="topResults.length > 0">
            <el-divider />
            <div class="analysis-section">
              <div class="analysis-tip">
                <span>对候选股票进行量化分析，评估趋势结构、价格位置、量价行为、历史异动四个维度</span>
              </div>
              <h4>分析结果 (Top 5)</h4>
              <el-table
                :data="topResults"
                stripe
                size="small"
                max-height="300"
              >
                <el-table-column prop="code" label="代码" width="80" />
                <el-table-column prop="total_score" label="评分" width="80" align="right">
                  <template #default="{ row }">
                    <el-tag :type="getScoreType(row.total_score)" size="small">
                      {{ row.total_score ? row.total_score.toFixed(1) : '-' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="signal_type" label="信号" width="120">
                  <template #default="{ row }">
                    <el-tag :type="getSignalTypeTag(row.signal_type)" size="small">
                      {{ getSignalTypeLabel(row.signal_type) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="comment" label="评语" show-overflow-tooltip />
                <el-table-column label="操作" width="90" align="center">
                  <template #default="{ row }">
                    <el-button text type="primary" size="small" @click="viewStock(row.code)">
                      详情
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </template>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onActivated } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { apiAnalysis, apiTasks } from '@/api'
import { ElMessage } from 'element-plus'
import type { AnalysisResult, Candidate, Task, TomorrowStarHistoryItem } from '@/types'
import { useConfigStore } from '@/store/config'

const router = useRouter()
const configStore = useConfigStore()
let loadDataRequestId = 0
let candidatesRequestId = 0
const REFRESH_CHECK_INTERVAL_MS = 60_000
const TOMORROW_STAR_CACHE_KEY = 'stocktrade:tomorrow-star:cache'

const loading = ref(false)
const loadingCandidates = ref(false)
const checkingFreshness = ref(false)
const updatingData = ref(false)
type HistoryRow = { date: string; count: number | '-'; pass: number | '-' }

const historyData = ref<HistoryRow[]>([])
const hasLatestData = ref(false)
const dataDate = ref<string>('')

const candidates = ref<Candidate[]>([])
const analysisResults = ref<AnalysisResult[]>([])
const selectedDate = ref<string | null>(null)
const lastHistorySignature = ref<string>('')
const lastRefreshCheckAt = ref<number>(0)
const currentTaskId = ref<number | null>(null)
const hydratedFromCache = ref(false)
const freshnessVersion = ref<string>('')
const candidatePage = ref(1)
const candidatePageSize = 10
const showCachedHint = computed(() => hydratedFromCache.value && !updatingData.value)
const showInitializationAlert = computed(() => configStore.tushareReady && !configStore.dataInitialized)
const showInitializationEmpty = computed(() => showInitializationAlert.value && historyData.value.length === 0 && candidates.value.length === 0)

const totalCandidates = computed(() => candidates.value.length)
const displayCandidates = computed(() => {
  const start = (candidatePage.value - 1) * candidatePageSize
  const sorted = [...candidates.value].sort((a, b) => {
    const aVal = typeof a.kdj_j === 'number' ? a.kdj_j : Number.POSITIVE_INFINITY
    const bVal = typeof b.kdj_j === 'number' ? b.kdj_j : Number.POSITIVE_INFINITY
    if (aVal !== bVal) return aVal - bVal
    return a.code.localeCompare(b.code)
  })
  return sorted.slice(start, start + candidatePageSize)
})

function getVerdictPriority(verdict?: string): number {
  const priorityMap: Record<string, number> = {
    PASS: 3,
    WATCH: 2,
    FAIL: 1,
  }
  return priorityMap[verdict || ''] || 0
}

const topResults = computed(() => {
  return [...analysisResults.value]
    .sort((a, b) => {
      const verdictDiff = getVerdictPriority(b.verdict) - getVerdictPriority(a.verdict)
      if (verdictDiff !== 0) return verdictDiff
      return (b.total_score || 0) - (a.total_score || 0)
    })
    .slice(0, 5)
})

async function loadData() {
  const requestId = ++loadDataRequestId
  loading.value = true
  try {
    // 加载日期列表
    const datesData = await apiAnalysis.getDates()
    if (requestId !== loadDataRequestId) return

    const dates = datesData.dates || []
    const history = datesData.history || []
    const previousSelectedDate = selectedDate.value

    if (history.length > 0) {
      historyData.value = history.map((item) => ({
        date: formatDateString(item.date),
        count: typeof item.count === 'number' ? item.count : '-',
        pass: typeof item.pass === 'number' ? item.pass : '-',
      }))
    } else {
      // 兼容旧接口：如果后端尚未返回明细，则退回到逐日请求
      const historyPromises = dates.map(async (date: string) => {
        try {
          const [candidatesData, resultsData] = await Promise.all([
            apiAnalysis.getCandidates(date),
            apiAnalysis.getResults(date)
          ])
          const candidates = candidatesData.candidates || []
          const results = resultsData.results || []
          const passCount = results.filter((r) => r.verdict === 'PASS').length

          return {
            date: formatDateString(date),
            count: candidates.length,
            pass: passCount,
          } satisfies HistoryRow
        } catch {
          return {
            date: formatDateString(date),
            count: '-',
            pass: '-',
          } satisfies HistoryRow
        }
      })

      historyData.value = await Promise.all(historyPromises)
      if (requestId !== loadDataRequestId) return
    }

    lastHistorySignature.value = buildHistorySignature(dates, historyData.value)
    lastRefreshCheckAt.value = Date.now()
    hydratedFromCache.value = false

    // 检查是否有最新数据（考虑周末情况）
    hasLatestData.value = hasLatestTradingDayData(dates)

    if (dates.length === 0) {
      selectedDate.value = null
      candidates.value = []
      analysisResults.value = []
      dataDate.value = ''
      return
    }

    // 刷新时保留当前选中的历史日期；如果已失效则退回最新日期
    const nextSelectedDate = previousSelectedDate && dates.includes(previousSelectedDate)
      ? previousSelectedDate
      : dates[0]

    selectedDate.value = nextSelectedDate

    if (requestId === loadDataRequestId) {
      await loadCandidatesForDate(nextSelectedDate)
    }

    persistTomorrowStarCache()
  } catch (error: any) {
    console.error('Failed to load data:', error)
    ElMessage.error('加载数据失败: ' + error.message)
  } finally {
    if (requestId === loadDataRequestId) {
      loading.value = false
    }
  }
}

async function pollTaskUntilFinished(taskId: number) {
  currentTaskId.value = taskId

  while (true) {
    const task: Task = await apiTasks.get(taskId)
    if (task.status === 'completed') {
      currentTaskId.value = null
      return
    }
    if (task.status === 'failed' || task.status === 'cancelled') {
      currentTaskId.value = null
      throw new Error(task.error_message || `任务状态异常: ${task.status}`)
    }
    await new Promise((resolve) => setTimeout(resolve, 2000))
  }
}

async function ensureFreshDataAndLoad(forceReload: boolean = false) {
  if (!configStore.tushareReady) return
  if (checkingFreshness.value || updatingData.value) return

  const hasLoadedData = historyData.value.length > 0
  const shouldSkipServerCheck = !forceReload
    && hasLoadedData
    && (Date.now() - lastRefreshCheckAt.value < REFRESH_CHECK_INTERVAL_MS)

  if (shouldSkipServerCheck) return

  checkingFreshness.value = true
  try {
    const freshness = await apiAnalysis.getFreshness()
    lastRefreshCheckAt.value = Date.now()
    const nextFreshnessVersion = freshness.freshness_version || ''

    if (
      !forceReload
      && hydratedFromCache.value
      && freshnessVersion.value
      && nextFreshnessVersion
      && freshnessVersion.value === nextFreshnessVersion
    ) {
      checkingFreshness.value = false
      return
    }

    freshnessVersion.value = nextFreshnessVersion
    persistTomorrowStarCache()

    if (freshness.running_task_id) {
      checkingFreshness.value = false
      updatingData.value = true
      await pollTaskUntilFinished(freshness.running_task_id)
      await loadData()
      return
    }

    if (freshness.needs_update) {
      checkingFreshness.value = false
      updatingData.value = true
      const result = await apiAnalysis.generate('quant')
      ElMessage.info(`检测到新交易日数据，已启动更新任务 #${result.task_id}`)
      await pollTaskUntilFinished(result.task_id)
      await loadData()
      return
    }

    if (!hydratedFromCache.value || forceReload) {
      await checkForRefresh(true)
    }
  } catch (error: any) {
    console.error('Failed to ensure tomorrow-star freshness:', error)
    ElMessage.error(`明日之星数据检查失败: ${error.message || error}`)
    if (historyData.value.length === 0) {
      await loadData()
    }
  } finally {
    checkingFreshness.value = false
    updatingData.value = false
  }
}

async function loadCandidatesForDate(date: string) {
  const requestId = ++candidatesRequestId
  loadingCandidates.value = true
  try {
    const candidatesData = await apiAnalysis.getCandidates(date)
    if (requestId !== candidatesRequestId) return

    candidates.value = candidatesData.candidates || []
    candidatePage.value = 1

    // 设置数据日期
    if (candidatesData.pick_date) {
      dataDate.value = formatDate(candidatesData.pick_date)
    } else {
      dataDate.value = ''
    }

    // 加载分析结果
    try {
      const resultsData = await apiAnalysis.getResults(date)
      if (requestId !== candidatesRequestId) return
      analysisResults.value = resultsData.results || []
      persistTomorrowStarCache()
    } catch {
      if (requestId === candidatesRequestId) {
        analysisResults.value = []
      }
    }
  } catch (error) {
    console.error('Failed to load candidates:', error)
    ElMessage.error('加载候选股票失败')
  } finally {
    if (requestId === candidatesRequestId) {
      loadingCandidates.value = false
    }
  }
}

function formatDate(date: string | Date): string {
  const d = typeof date === 'string' ? new Date(date) : date
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

async function refreshCandidates() {
  if (!configStore.dataInitialized) {
    ElMessage.info('请先完成首次初始化')
    return
  }
  if (selectedDate.value) {
    await loadCandidatesForDate(selectedDate.value)
  } else {
    // 加载最新数据
    await loadCandidatesForDate('')
  }
}

async function refreshStatusAndRetry() {
  await configStore.checkTushareStatus()
  if (configStore.dataInitialized) {
    await ensureFreshDataAndLoad(true)
  }
}

function selectDate(row: HistoryRow) {
  selectedDate.value = row.date
  persistTomorrowStarCache()
  loadCandidatesForDate(row.date)
}

function viewStock(code: string) {
  router.push({ path: '/diagnosis', query: { code } })
}

// 获取最近的交易日（考虑周末）
function getLatestTradingDay(): string {
  const now = new Date()
  const day = now.getDay() // 0=周日, 1=周一, ..., 6=周六

  // 如果是周日 (0)，最近交易日是周五 (-2天)
  // 如果是周六 (6)，最近交易日是周五 (-1天)
  // 否则就是今天
  let offset = 0
  if (day === 0) {
    offset = -2
  } else if (day === 6) {
    offset = -1
  }

  const tradingDay = new Date(now)
  tradingDay.setDate(now.getDate() + offset)

  return tradingDay.toISOString().split('T')[0]
}

// 检查是否有最新交易日数据
function hasLatestTradingDayData(dates: string[]): boolean {
  if (dates.length === 0) return false

  const latestTradingDay = getLatestTradingDay()
  const latestDate = dates[0] // dates是按日期降序排列的

  return latestDate === latestTradingDay
}

function formatDateString(dateStr: string): string {
  // 处理各种日期格式
  if (/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
    return dateStr
  }
  if (/^\d{8}$/.test(dateStr)) {
    return `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`
  }
  return dateStr
}

function getScoreType(score?: number): string {
  if (!score) return 'info'
  if (score >= 4.0) return 'success'
  if (score >= 3.5) return 'warning'
  return 'danger'
}

function getSignalTypeLabel(signalType?: string): string {
  const signalMap: Record<string, string> = {
    'trend_start': '趋势启动',
    'rebound': '反弹延续',
    'distribution_risk': '风险释放',
  }
  return signalMap[signalType || ''] || signalType || '-'
}

function getSignalTypeTag(signalType?: string): string {
  if (signalType === 'trend_start') return 'success'
  if (signalType === 'rebound') return 'warning'
  if (signalType === 'distribution_risk') return 'danger'
  return 'info'
}

function buildHistorySignature(dates: string[], history: Array<HistoryRow | TomorrowStarHistoryItem>): string {
  if (history.length > 0) {
    return JSON.stringify(
      history.map((item) => ({
        date: formatDateString(item.date || ''),
        count: typeof item.count === 'number' ? item.count : '-',
        pass: typeof item.pass === 'number' ? item.pass : '-',
      }))
    )
  }

  return JSON.stringify(dates.map((date) => formatDateString(date)))
}

async function checkForRefresh(forceLoad: boolean = false) {
  if (loading.value || loadingCandidates.value) return

  const now = Date.now()
  if (!forceLoad && now - lastRefreshCheckAt.value < REFRESH_CHECK_INTERVAL_MS) return

  lastRefreshCheckAt.value = now

  try {
    const datesData = await apiAnalysis.getDates()
    const dates = datesData.dates || []
    const history = datesData.history || []
    const nextSignature = buildHistorySignature(dates, history)

    if (forceLoad || historyData.value.length === 0 || nextSignature !== lastHistorySignature.value) {
      await loadData()
    }
  } catch (error) {
    console.error('Failed to check tomorrow-star freshness:', error)
  }
}

onMounted(() => {
  configStore.checkTushareStatus()
  hydrateTomorrowStarCache()

  if (historyData.value.length === 0) {
    loadData()
  }

  ensureFreshDataAndLoad(hydratedFromCache.value ? false : true)
})

onActivated(() => {
  configStore.checkTushareStatus()
  ensureFreshDataAndLoad()
})

function persistTomorrowStarCache() {
  if (typeof window === 'undefined') return

    const payload = {
    historyData: historyData.value,
    candidates: candidates.value,
    analysisResults: analysisResults.value,
    selectedDate: selectedDate.value,
      dataDate: dataDate.value,
      candidatePage: candidatePage.value,
      lastHistorySignature: lastHistorySignature.value,
      freshnessVersion: freshnessVersion.value,
      cachedAt: Date.now(),
    }

  sessionStorage.setItem(TOMORROW_STAR_CACHE_KEY, JSON.stringify(payload))
}

function hydrateTomorrowStarCache() {
  if (typeof window === 'undefined') return

  const raw = sessionStorage.getItem(TOMORROW_STAR_CACHE_KEY)
  if (!raw) return

  try {
    const payload = JSON.parse(raw)
    historyData.value = payload.historyData || []
    candidates.value = payload.candidates || []
    analysisResults.value = payload.analysisResults || []
    selectedDate.value = payload.selectedDate || null
    dataDate.value = payload.dataDate || ''
    candidatePage.value = Math.max(1, Number(payload.candidatePage) || 1)
    lastHistorySignature.value = payload.lastHistorySignature || ''
    freshnessVersion.value = payload.freshnessVersion || ''
    hydratedFromCache.value = historyData.value.length > 0 || candidates.value.length > 0 || analysisResults.value.length > 0
  } catch {
    sessionStorage.removeItem(TOMORROW_STAR_CACHE_KEY)
  }
}
</script>

<style scoped lang="scss">
.tomorrow-star-page {
  .page-alert {
    margin-bottom: 16px;
  }

  .page-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 560px;
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 16px;
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;

    .title-section {
      display: flex;
      align-items: center;
      gap: 12px;

      .date-tag {
        font-size: 12px;
      }
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 12px;
    }
  }

  .history-card {
    .table-header-tip {
      margin-bottom: 12px;
      padding: 10px 12px;
      background-color: #f5f7fa;
      border-radius: 4px;
      font-size: 12px;
      color: #606266;
      line-height: 1.6;

      .tip-item {
        margin-right: 16px;

        &:last-child {
          margin-right: 0;
        }
      }
    }

    .history-table {
      :deep(.el-table__row) {
        cursor: pointer;

        &:hover {
          background-color: #f0f9ff;
        }
      }
    }
  }

  .candidates-card {
    .table-header-tip {
      margin-bottom: 12px;
      padding: 10px 12px;
      background-color: #f5f7fa;
      border-radius: 4px;
      font-size: 12px;
      color: #606266;
      line-height: 1.6;

      .tip-item {
        margin-right: 16px;

        &:last-child {
          margin-right: 0;
        }
      }
    }

    .candidates-table {
      :deep(.cell) {
        white-space: nowrap;
      }
    }

    .pagination-wrap {
      display: flex;
      justify-content: flex-end;
      margin-top: 14px;
    }
  }

  .analysis-section {
    .analysis-tip {
      margin-bottom: 8px;
      padding: 8px 12px;
      background-color: #e8f4fd;
      border-radius: 4px;
      font-size: 12px;
      color: #409eff;
      line-height: 1.6;
    }

    h4 {
      margin: 0 0 12px 0;
      color: var(--color-text-secondary);
    }
  }
}
</style>
