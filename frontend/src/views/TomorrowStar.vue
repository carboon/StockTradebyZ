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

    <!-- 增量更新进度提示 -->
    <el-card v-if="incrementalUpdate.running" class="update-progress-card" shadow="never">
      <div class="progress-content">
        <div class="progress-info">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span class="progress-text">增量更新中...</span>
          <span class="progress-detail">
            {{ incrementalUpdate.updated_count }} 更新 / {{ incrementalUpdate.skipped_count }} 跳过 / {{ incrementalUpdate.failed_count }} 失败
          </span>
          <span v-if="incrementalUpdate.current_code" class="current-code">
            当前: {{ incrementalUpdate.current_code }}
          </span>
        </div>
        <el-progress
          :percentage="incrementalUpdate.progress"
          :stroke-width="12"
          :show-text="true"
        />
      </div>
    </el-card>
    <el-alert
      v-else-if="incrementalUpdate.status === 'failed'"
      class="page-alert"
      type="warning"
      :closable="false"
      show-icon
      title="增量更新上次未完成"
      :description="incrementalUpdate.last_error || incrementalUpdate.message || '可前往任务中心重新发起，系统会尽量从已完成位置继续。'"
    />

    <el-row :gutter="20" class="top-row">
      <!-- 左侧：历史记录 -->
      <el-col :span="8">
        <el-card class="history-card matched-height">
          <template #header>
            <div class="card-header">
              <span>历史记录</span>
            </div>
          </template>

          <div class="table-header-tip">
            <span class="tip-item">· 点击日期查看对应数据</span>
            <span class="tip-item">· 右侧跟随左侧选择</span>
          </div>

          <el-table
            :data="displayHistoryData"
            @row-click="selectDate"
            class="history-table"
            height="400"
            highlight-current-row
            :current-row-key="selectedDate"
            row-key="rawDate"
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
            <el-table-column label="状态" width="80" align="center">
              <template #default="{ row }">
                <div class="history-status-cell">
                  <el-tag
                    v-if="row.rawDate === latestDate"
                    type="success"
                    size="small"
                    class="status-tag"
                  >
                    最新
                  </el-tag>
                  <el-tag
                    :type="getHistoryStatusTagType(row.status)"
                    size="small"
                    class="status-tag"
                  >
                    {{ getHistoryStatusLabel(row.status) }}
                  </el-tag>
                </div>
              </template>
            </el-table-column>
          </el-table>

          <div class="pagination-wrap">
            <el-pagination
              v-model:current-page="historyPage"
              :page-size="historyPageSize"
              layout="total, prev, pager, next"
              :total="totalHistoryCount"
              :hide-on-single-page="false"
              background
              size="small"
            />
          </div>
        </el-card>
      </el-col>

      <!-- 右侧：候选列表（跟随左侧选择） -->
      <el-col :span="16">
        <el-card class="candidates-card matched-height">
          <template #header>
            <div class="card-header">
              <div class="title-section">
                <span>候选股票</span>
                <el-tag size="small" type="success" class="date-tag">
                  {{ viewingDateDisplay }}
                </el-tag>
              </div>
              <div class="header-actions">
                <el-tag v-if="showCachedHint" type="info" size="small" effect="plain">
                  已展示缓存结果
                </el-tag>
                <el-button
                  type="primary"
                  size="small"
                  :icon="Refresh"
                  :loading="loadingLatest"
                  @click="refreshCurrentCandidates"
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
            :data="displayLatestCandidates"
            stripe
            class="candidates-table"
            height="400"
            table-layout="auto"
          >
            <el-table-column prop="code" label="代码" min-width="100" />
            <el-table-column prop="name" label="名称" min-width="120" show-overflow-tooltip />
            <el-table-column prop="open_price" label="开盘价" min-width="100" align="right">
              <template #default="{ row }">
                {{ typeof row.open_price === 'number' ? row.open_price.toFixed(2) : '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="close_price" label="收盘价" min-width="100" align="right">
              <template #default="{ row }">
                {{ typeof row.close_price === 'number' ? row.close_price.toFixed(2) : '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="change_pct" label="涨跌幅" min-width="100" align="right">
              <template #default="{ row }">
                <span :class="typeof row.change_pct === 'number' ? (row.change_pct > 0 ? 'text-up' : row.change_pct < 0 ? 'text-down' : '') : ''">
                  {{ typeof row.change_pct === 'number' ? row.change_pct.toFixed(2) + '%' : '-' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="kdj_j" label="KDJ-J" min-width="100" align="right">
              <template #default="{ row }">
                {{ typeof row.kdj_j === 'number' ? row.kdj_j.toFixed(1) : '-' }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80" align="center" fixed="right">
              <template #default="{ row }">
                <el-button text type="primary" size="small" @click="viewStock(row.code)">
                  详情
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="pagination-wrap">
            <el-pagination
              v-model:current-page="latestCandidatePage"
              :page-size="candidatePageSize"
              layout="total, prev, pager, next"
              :total="totalLatestCandidates"
              :hide-on-single-page="false"
              background
            />
          </div>

          <!-- 分析结果（移入卡片内部以保持对齐） -->
          <el-divider v-if="topAnalysisResults.length > 0" />
          <div v-if="topAnalysisResults.length > 0" class="analysis-section">
            <div class="analysis-tip">
              <span>对候选股票进行量化分析，评估趋势结构、价格位置、量价行为、历史异动四个维度</span>
            </div>
            <h4>分析结果 (Top 5)</h4>
            <el-table
              :data="topAnalysisResults"
              stripe
              size="small"
              max-height="200"
            >
              <el-table-column prop="code" label="代码" width="80" />
              <el-table-column prop="total_score" label="评分" width="80" align="right">
                <template #default="{ row }">
                  <el-tag :type="getScoreType(row.total_score)" size="small">
                    {{ typeof row.total_score === 'number' ? row.total_score.toFixed(1) : '-' }}
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
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onActivated, onDeactivated, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, Loading } from '@element-plus/icons-vue'
import { apiAnalysis, apiTasks, isRequestCanceled } from '@/api'
import { ElMessage } from 'element-plus'
import type {
  Candidate,
  AnalysisResult,
  FreshnessResponse,
  IncrementalUpdateStatus,
  TomorrowStarHistoryItem,
  TomorrowStarWindowStatusResponse,
} from '@/types'
import { useConfigStore } from '@/store/config'
import { getUserSafeErrorMessage, isInitializationPendingError } from '@/utils/userFacingErrors'

const router = useRouter()
const configStore = useConfigStore()

let loadDataRequestId = 0
let candidatesRequestId = 0
const REFRESH_CHECK_INTERVAL_MS = 60_000
const AUTO_INCREMENTAL_ATTEMPT_INTERVAL_MS = 10 * 60 * 1000
const BEIJING_INCREMENTAL_START_MINUTE = 15 * 60
const BEIJING_INCREMENTAL_END_MINUTE = 20 * 60
const TOMORROW_STAR_CACHE_KEY = 'stocktrade:tomorrow-star:cache'
const INCREMENTAL_POLL_INTERVAL_MS = 2000
let incrementalPollTimer: number | null = null
let autoIncrementalAttemptTimer: number | null = null
const requestControllers = new Map<string, AbortController>()

const loading = ref(false)
const loadingLatest = ref(false)
const checkingFreshness = ref(false)

type HistoryRow = {
  date: string
  rawDate: string
  count: number | '-'
  pass: number | '-'
  status: 'pending' | 'running' | 'success' | 'failed' | 'missing'
  analysisCount: number | '-'
  errorMessage?: string | null
  isLatest?: boolean
}

type HistoryLikeItem = {
  date?: string
  pick_date?: string
  count?: number
  pass?: number
  candidate_count?: number
  analysis_count?: number
  trend_start_count?: number
  status?: string
  error_message?: string | null
  is_latest?: boolean
}

const historyData = ref<HistoryRow[]>([])
const selectedDate = ref<string | null>(null)
const latestDate = ref<string>('')
const latestDataDate = ref<string>('')
const lastHistorySignature = ref<string>('')
const lastRefreshCheckAt = ref<number>(0)
const hydratedFromCache = ref(false)
const freshnessVersion = ref<string>('')

// 历史记录分页（左侧）
const historyPage = ref(1)
const historyPageSize = 10

// 最新数据（右侧显示）
const latestCandidates = ref<Candidate[]>([])
const latestAnalysisResults = ref<AnalysisResult[]>([])
const latestCandidatePage = ref(1)
const candidatePageSize = 10

// 当前查看的日期（默认为最新）
const viewingDate = ref<string | null>(null)

// 按日期缓存的数据（避免重复请求）
const candidatesCache = ref<Map<string, { candidates: Candidate[], results: AnalysisResult[], timestamp: number }>>(new Map())
const CACHE_TTL_MS = 5 * 60 * 1000  // 缓存5分钟

// 增量更新状态
const incrementalUpdate = ref<IncrementalUpdateStatus>({
  status: 'idle',
  running: false,
  progress: 0,
  current: 0,
  total: 0,
  current_code: '',
  updated_count: 0,
  skipped_count: 0,
  failed_count: 0,
  started_at: '',
  completed_at: '',
  eta_seconds: null,
  elapsed_seconds: 0,
  resume_supported: true,
  initial_completed: 0,
  completed_in_run: 0,
  checkpoint_path: null,
  last_error: null,
  message: '',
})

const showCachedHint = computed(() => hydratedFromCache.value && !incrementalUpdate.value.running)
const showInitializationAlert = computed(() => configStore.tushareReady && !configStore.dataInitialized)
const showInitializationEmpty = computed(() => showInitializationAlert.value && historyData.value.length === 0 && latestCandidates.value.length === 0)

// 历史记录分页数据
const totalHistoryCount = computed(() => historyData.value.length)
const displayHistoryData = computed(() => {
  const start = (historyPage.value - 1) * historyPageSize
  return historyData.value.slice(start, start + historyPageSize)
})

const totalLatestCandidates = computed(() => latestCandidates.value.length)
const displayLatestCandidates = computed(() => {
  const start = (latestCandidatePage.value - 1) * candidatePageSize
  const sorted = [...latestCandidates.value].sort((a, b) => {
    const aVal = typeof a.kdj_j === 'number' ? a.kdj_j : Number.POSITIVE_INFINITY
    const bVal = typeof b.kdj_j === 'number' ? b.kdj_j : Number.POSITIVE_INFINITY
    if (aVal !== bVal) return aVal - bVal
    return a.code.localeCompare(b.code)
  })
  return sorted.slice(start, start + candidatePageSize)
})

// 当前查看的日期显示
const viewingDateDisplay = computed(() => {
  if (viewingDate.value) {
    return formatDateString(viewingDate.value)
  }
  return latestDate.value ? formatDateString(latestDate.value) : ''
})

function getVerdictPriority(verdict?: string): number {
  const priorityMap: Record<string, number> = {
    PASS: 3,
    WATCH: 2,
    FAIL: 1,
  }
  return priorityMap[verdict || ''] || 0
}

const topAnalysisResults = computed(() => {
  return [...latestAnalysisResults.value]
    .sort((a, b) => {
      const verdictDiff = getVerdictPriority(b.verdict) - getVerdictPriority(a.verdict)
      if (verdictDiff !== 0) return verdictDiff
      return (b.total_score || 0) - (a.total_score || 0)
    })
    .slice(0, 5)
})

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

function cancelAllPageRequests() {
  requestControllers.forEach((controller) => controller.abort())
  requestControllers.clear()
}

function normalizeHistoryStatus(status?: string | null): HistoryRow['status'] {
  const value = String(status || '').toLowerCase()
  if (value === 'success' || value === 'completed' || value === 'done') return 'success'
  if (value === 'running' || value === 'processing' || value === 'in_progress') return 'running'
  if (value === 'failed' || value === 'error') return 'failed'
  if (value === 'pending' || value === 'queued') return 'pending'
  return 'missing'
}

function getHistoryStatusLabel(status: HistoryRow['status']): string {
  const labels: Record<HistoryRow['status'], string> = {
    success: '完成',
    running: '生成中',
    failed: '失败',
    pending: '待生成',
    missing: '缺失',
  }
  return labels[status]
}

function getHistoryStatusTagType(status: HistoryRow['status']): string {
  const tags: Record<HistoryRow['status'], string> = {
    success: 'success',
    running: 'warning',
    failed: 'danger',
    pending: 'info',
    missing: 'info',
  }
  return tags[status]
}

function getHistoryCount(item: HistoryLikeItem): number | '-' {
  if (typeof item.count === 'number') return item.count
  if (typeof item.candidate_count === 'number') return item.candidate_count
  return '-'
}

function getHistoryPassCount(item: HistoryLikeItem): number | '-' {
  if (typeof item.pass === 'number') return item.pass
  if (typeof item.trend_start_count === 'number') return item.trend_start_count
  return '-'
}

function normalizeHistoryRow(
  item: HistoryLikeItem,
  fallbackLatestDate: string,
): HistoryRow | null {
  const rawDate = formatDateString(item.date || item.pick_date || '')
  if (!rawDate) return null

  const count = getHistoryCount(item)
  const pass = getHistoryPassCount(item)
  const analysisCount = typeof item.analysis_count === 'number' ? item.analysis_count : '-'
  const inferredStatus =
    item.status
    || (
      count !== '-'
      || pass !== '-'
      || analysisCount !== '-'
        ? 'success'
        : 'missing'
    )

  return {
    date: rawDate,
    rawDate,
    count,
    pass,
    status: normalizeHistoryStatus(inferredStatus),
    analysisCount,
    errorMessage: item.error_message || null,
    isLatest: Boolean(item.is_latest || (fallbackLatestDate && rawDate === fallbackLatestDate)),
  }
}

function normalizeHistoryRows(
  dates: string[],
  history: TomorrowStarHistoryItem[],
  windowStatus?: TomorrowStarWindowStatusResponse | null,
): HistoryRow[] {
  const latest = formatDateString(windowStatus?.latest_date || dates[0] || '')
  const normalizedMap = new Map<string, HistoryRow>()

  const statusItems = [
    ...(windowStatus?.items || []),
    ...(windowStatus?.history || []),
    ...(windowStatus?.runs || []),
  ]

  statusItems.forEach((item) => {
    const row = normalizeHistoryRow(item, latest)
    if (row) normalizedMap.set(row.rawDate, row)
  })

  history.forEach((item) => {
    const row = normalizeHistoryRow(item, latest)
    if (!row) return
    const existing = normalizedMap.get(row.rawDate)
    normalizedMap.set(row.rawDate, {
      ...(existing || row),
      ...row,
      status: existing?.status || row.status,
      errorMessage: existing?.errorMessage || row.errorMessage,
      isLatest: Boolean(existing?.isLatest || row.isLatest),
    })
  })

  dates.forEach((date) => {
    const rawDate = formatDateString(date)
    if (!rawDate || normalizedMap.has(rawDate)) return
    normalizedMap.set(rawDate, {
      date: rawDate,
      rawDate,
      count: '-',
      pass: '-',
      status: 'missing',
      analysisCount: '-',
      errorMessage: null,
      isLatest: rawDate === latest,
    })
  })

  return [...normalizedMap.values()].sort((a, b) => b.rawDate.localeCompare(a.rawDate))
}

async function loadData(skipLatestLoad: boolean = false) {
  if (loading.value) return

  const requestId = ++loadDataRequestId
  const signal = beginRequest('loadData')
  const previousSelectedDate = selectedDate.value
  const previousViewingDate = viewingDate.value
  loading.value = true
  try {
    const datesData = await apiAnalysis.getDates({ signal })
    if (requestId !== loadDataRequestId) return

    const dates = datesData.dates || []
    const history = datesData.history || []
    const windowStatus = datesData.window_status || null

    if (dates.length > 0) {
      latestDate.value = formatDateString(windowStatus?.latest_date || dates[0])
    } else {
      latestDate.value = formatDateString(windowStatus?.latest_date || '')
    }

    if (history.length > 0 || windowStatus) {
      historyData.value = normalizeHistoryRows(dates, history, windowStatus)
    } else {
      const historyPromises = dates.map(async (date: string) => {
        try {
          const [candidatesData, resultsData] = await Promise.all([
            apiAnalysis.getCandidates(date, { signal }),
            apiAnalysis.getResults(date, { signal })
          ])
          const candidates = candidatesData.candidates || []
          const results = resultsData.results || []
          const passCount = results.filter((r) => r.signal_type === 'trend_start').length

          return {
            date: formatDateString(date),
            rawDate: formatDateString(date),
            count: candidates.length,
            pass: passCount,
            status: 'success',
            analysisCount: results.length,
            errorMessage: null,
            isLatest: formatDateString(date) === latestDate.value,
          } satisfies HistoryRow
        } catch {
          return {
            date: formatDateString(date),
            rawDate: formatDateString(date),
            count: '-',
            pass: '-',
            status: 'missing',
            analysisCount: '-',
            errorMessage: null,
            isLatest: formatDateString(date) === latestDate.value,
          } satisfies HistoryRow
        }
      })

      historyData.value = await Promise.all(historyPromises)
      if (requestId !== loadDataRequestId) return
    }

    lastHistorySignature.value = buildHistorySignature(dates, historyData.value)
    lastRefreshCheckAt.value = Date.now()
    hydratedFromCache.value = false

    if (dates.length === 0) {
      selectedDate.value = null
      viewingDate.value = null
      latestCandidates.value = []
      latestAnalysisResults.value = []
      latestDataDate.value = ''
      return
    }

    const hasPreviousSelectedDate = !!previousSelectedDate && historyData.value.some((item) => item.rawDate === previousSelectedDate)
    selectedDate.value = hasPreviousSelectedDate ? previousSelectedDate : latestDate.value

    const hasPreviousViewingDate = !!previousViewingDate && historyData.value.some((item) => item.rawDate === previousViewingDate)
    viewingDate.value = hasPreviousViewingDate ? previousViewingDate : latestDate.value

    // 加载最新数据（右侧显示）- 根据 skipLatestLoad 参数决定是否跳过
    if (!skipLatestLoad && requestId === loadDataRequestId) {
      await loadLatestCandidates()
    }

    persistTomorrowStarCache()
  } catch (error: any) {
    if (isRequestCanceled(error)) return
    console.error('Failed to load data:', error)
    const message = getUserSafeErrorMessage(error, '加载数据失败')
    ElMessage.error(isInitializationPendingError(error) ? message : `加载数据失败: ${message}`)
  } finally {
    finishRequest('loadData', signal)
    if (requestId === loadDataRequestId) {
      loading.value = false
    }
  }
}

async function loadLatestCandidates() {
  const requestId = ++candidatesRequestId
  const signal = beginRequest('latestCandidates')
  loadingLatest.value = true
  try {
    const candidatesData = await apiAnalysis.getCandidates('', { signal })
    if (requestId !== candidatesRequestId) return
    const candidates = candidatesData.candidates || []
    latestCandidates.value = candidates
    latestCandidatePage.value = 1

    if (candidatesData.pick_date) {
      const newPickDate = formatDate(candidatesData.pick_date)
      latestDataDate.value = newPickDate
      viewingDate.value = newPickDate

      // 如果发现新的日期（与当前 latestDate 不同），刷新左侧历史列表
      if (newPickDate && newPickDate !== latestDate.value) {
        console.log(`检测到新日期 ${newPickDate}，刷新历史列表`)
        // 传入 true 跳过重复的 loadLatestCandidates 调用，避免递归
        await loadData(true)
        if (requestId !== candidatesRequestId) return
        // loadData 完成后，继续加载分析结果（因为上面 return 了，需要在这里加载）
        try {
          const resultsData = await apiAnalysis.getResults('', { signal })
          if (requestId !== candidatesRequestId) return
          latestAnalysisResults.value = resultsData.results || []
          // 缓存最新数据
          candidatesCache.value.set(newPickDate, {
            candidates,
            results: resultsData.results || [],
            timestamp: Date.now()
          })
        } catch {
          latestAnalysisResults.value = []
        }
        persistTomorrowStarCache()
        return
      }
    } else {
      latestDataDate.value = ''
    }

    // 加载最新分析结果
    try {
      const resultsData = await apiAnalysis.getResults('', { signal })
      if (requestId !== candidatesRequestId) return
      latestAnalysisResults.value = resultsData.results || []
      // 缓存最新数据
      if (latestDataDate.value) {
        candidatesCache.value.set(latestDataDate.value, {
          candidates,
          results: resultsData.results || [],
          timestamp: Date.now()
        })
      }
    } catch {
      latestAnalysisResults.value = []
    }

    persistTomorrowStarCache()
  } catch (error) {
    if (isRequestCanceled(error)) return
    console.error('Failed to load latest candidates:', error)
    ElMessage.error(getUserSafeErrorMessage(error, '加载最新候选股票失败'))
  } finally {
    finishRequest('latestCandidates', signal)
    loadingLatest.value = false
  }
}

async function selectDate(row: HistoryRow) {
  selectedDate.value = row.rawDate
  viewingDate.value = row.rawDate
  latestCandidatePage.value = 1
  persistTomorrowStarCache()

  if (row.status !== 'success') {
    latestCandidates.value = []
    latestAnalysisResults.value = []
    latestDataDate.value = row.rawDate
    if (row.status === 'running') {
      ElMessage.info(`${row.rawDate} 正在生成中，稍后再查看`)
    } else if (row.status === 'failed') {
      ElMessage.warning(isInitializationPendingError({ message: row.errorMessage || '' }) ? '系统尚未完成初始化' : (row.errorMessage || `${row.rawDate} 生成失败`))
    } else {
      ElMessage.info(`${row.rawDate} 暂无可展示结果`)
    }
    persistTomorrowStarCache()
    return
  }

  // 先检查缓存
  const cached = candidatesCache.value.get(row.rawDate)
  const now = Date.now()
  if (cached && (now - cached.timestamp) < CACHE_TTL_MS) {
    // 使用缓存数据，立即显示
    latestCandidates.value = cached.candidates
    latestAnalysisResults.value = cached.results
    latestDataDate.value = row.rawDate
    console.log(`使用缓存数据: ${row.rawDate}`)
    persistTomorrowStarCache()
    return
  }

  // 加载选中日期的数据到右侧显示
  const requestId = ++candidatesRequestId
  const signal = beginRequest('latestCandidates')
  loadingLatest.value = true
  try {
    const [candidatesData, resultsData] = await Promise.all([
      apiAnalysis.getCandidates(row.rawDate, { signal }),
      apiAnalysis.getResults(row.rawDate, { signal })
    ])
    if (requestId !== candidatesRequestId) return

    const candidates = candidatesData.candidates || []
    const results = resultsData.results || []

    latestCandidates.value = candidates
    latestAnalysisResults.value = results
    latestDataDate.value = row.rawDate
    latestCandidatePage.value = 1

    // 存入缓存
    candidatesCache.value.set(row.rawDate, {
      candidates,
      results,
      timestamp: now
    })
    persistTomorrowStarCache()
  } catch (error) {
    if (isRequestCanceled(error)) return
    console.error('Failed to load selected date data:', error)
    ElMessage.error(getUserSafeErrorMessage(error, '加载数据失败'))
  } finally {
    finishRequest('latestCandidates', signal)
    loadingLatest.value = false
  }
}

async function refreshCurrentCandidates() {
  if (loading.value) {
    console.log('正在刷新中，忽略此次刷新请求')
    return
  }

  // 清除缓存，强制从后端重新加载
  candidatesCache.value.clear()

  // 强制检查新鲜度并重新加载数据
  await ensureFreshDataAndLoad(true)

  // 刷新当前查看的日期的数据
  const dateToRefresh = viewingDate.value || latestDate.value
  if (dateToRefresh) {
    const requestId = ++candidatesRequestId
    const signal = beginRequest('latestCandidates')
    loadingLatest.value = true
    try {
      const [candidatesData, resultsData] = await Promise.all([
        apiAnalysis.getCandidates(dateToRefresh, { signal }),
        apiAnalysis.getResults(dateToRefresh, { signal })
      ])
      if (requestId !== candidatesRequestId) return

      const candidates = candidatesData.candidates || []
      const results = resultsData.results || []

      latestCandidates.value = candidates
      latestAnalysisResults.value = results
      latestDataDate.value = dateToRefresh
      latestCandidatePage.value = 1

      // 更新缓存
      candidatesCache.value.set(dateToRefresh, {
        candidates,
        results,
        timestamp: Date.now()
      })

      ElMessage.success(`已刷新 ${dateToRefresh} 的数据`)
    } catch (error) {
      if (isRequestCanceled(error)) return
      console.error('Failed to refresh current candidates:', error)
      ElMessage.error(getUserSafeErrorMessage(error, '刷新失败'))
    } finally {
      finishRequest('latestCandidates', signal)
      loadingLatest.value = false
    }
  }
}

async function startIncrementalUpdate() {
  try {
    const result = await apiTasks.startIncrementalUpdate()
    if (!result.success) {
      if (result.running) {
        // 已有任务在运行，开始轮询
        await checkIncrementalStatus()
        startIncrementalPolling()
      }
      return
    }

    // 启动成功，开始轮询状态
    await checkIncrementalStatus()
    startIncrementalPolling()
  } catch (error: any) {
    console.error('Failed to start incremental update:', error)
  }
}

async function checkIncrementalStatus() {
  const signal = beginRequest('incrementalStatus')
  try {
    const status = await apiTasks.getIncrementalStatus({ signal })
    incrementalUpdate.value = status
  } catch (error) {
    if (isRequestCanceled(error)) return
    console.error('Failed to check incremental status:', error)
  } finally {
    finishRequest('incrementalStatus', signal)
  }
}

function startIncrementalPolling() {
  if (incrementalPollTimer) {
    return
  }

  incrementalPollTimer = window.setInterval(async () => {
    await checkIncrementalStatus()

    // 如果更新完成，停止轮询并刷新数据
    if (!incrementalUpdate.value.running) {
      stopIncrementalPolling()
      await loadData()
    }
  }, INCREMENTAL_POLL_INTERVAL_MS)
}

function stopIncrementalPolling() {
  if (incrementalPollTimer) {
    window.clearInterval(incrementalPollTimer)
    incrementalPollTimer = null
  }
}

function getBeijingMinutes(now: Date = new Date()): number {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
  }).formatToParts(now)
  const hour = Number(parts.find((part) => part.type === 'hour')?.value || '0')
  const minute = Number(parts.find((part) => part.type === 'minute')?.value || '0')
  return hour * 60 + minute
}

function isWithinBeijingIncrementalWindow(now: Date = new Date()): boolean {
  const minutes = getBeijingMinutes(now)
  return minutes >= BEIJING_INCREMENTAL_START_MINUTE && minutes < BEIJING_INCREMENTAL_END_MINUTE
}

function shouldAutoStartIncremental(freshness: FreshnessResponse): boolean {
  return Boolean(
    isWithinBeijingIncrementalWindow()
    && freshness.needs_update
    && freshness.latest_trade_data_ready === true
    && !incrementalUpdate.value.running
    && !freshness.running_task_id
    && freshness.incremental_update?.status !== 'failed'
  )
}

function startAutoIncrementalAttemptTimer() {
  stopAutoIncrementalAttemptTimer()
  autoIncrementalAttemptTimer = window.setInterval(() => {
    if (!isWithinBeijingIncrementalWindow()) return
    void ensureFreshDataAndLoad(true)
  }, AUTO_INCREMENTAL_ATTEMPT_INTERVAL_MS)
}

function stopAutoIncrementalAttemptTimer() {
  if (autoIncrementalAttemptTimer) {
    window.clearInterval(autoIncrementalAttemptTimer)
    autoIncrementalAttemptTimer = null
  }
}

async function ensureFreshDataAndLoad(forceReload: boolean = false) {
  if (!configStore.tushareReady) return
  if (checkingFreshness.value || incrementalUpdate.value.running || loading.value) return

  const hasLoadedData = historyData.value.length > 0
  const missingVisibleRightPanelData = Boolean(
    historyData.value.length > 0
    && viewingDate.value
    && latestCandidates.value.length === 0
    && latestAnalysisResults.value.length === 0
  )
  const shouldSkipServerCheck = !forceReload
    && hasLoadedData
    && !missingVisibleRightPanelData
    && (Date.now() - lastRefreshCheckAt.value < REFRESH_CHECK_INTERVAL_MS)

  if (shouldSkipServerCheck) return

  checkingFreshness.value = true
  const signal = beginRequest('freshness')
  try {
    const freshness = await apiAnalysis.getFreshness({ signal })
    lastRefreshCheckAt.value = Date.now()
    const nextFreshnessVersion = freshness.freshness_version || ''
    const freshnessChanged = freshnessVersion.value !== nextFreshnessVersion

    // 更新增量更新状态
    if (freshness.incremental_update) {
      incrementalUpdate.value = freshness.incremental_update
      if (freshness.incremental_update.running) {
        startIncrementalPolling()
      }
    }

    // 如果需要更新且没有正在运行的增量更新，自动启动
    if (shouldAutoStartIncremental(freshness)) {
      await startIncrementalUpdate()
    }

    if (
      !forceReload
      && hydratedFromCache.value
      && !missingVisibleRightPanelData
      && freshnessVersion.value
      && nextFreshnessVersion
      && freshnessVersion.value === nextFreshnessVersion
    ) {
      checkingFreshness.value = false
      return
    }

    freshnessVersion.value = nextFreshnessVersion
    persistTomorrowStarCache()

    if (freshness.incremental_update?.running) {
      checkingFreshness.value = false
      return
    }

    if (
      forceReload
      || !hydratedFromCache.value
      || freshnessChanged
      || historyData.value.length === 0
      || missingVisibleRightPanelData
    ) {
      await checkForRefresh(true)
    }
  } catch (error: any) {
    if (isRequestCanceled(error)) return
    console.error('Failed to ensure tomorrow-star freshness:', error)
    if (historyData.value.length === 0) {
      await loadData()
    }
  } finally {
    finishRequest('freshness', signal)
    checkingFreshness.value = false
  }
}

function viewStock(code: string) {
  router.push({ path: '/diagnosis', query: { code } })
}

function formatDate(date: string | Date): string {
  const d = typeof date === 'string' ? new Date(date) : date
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function formatDateString(dateStr: string): string {
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

function buildHistorySignature(dates: string[], history: Array<{ date: string; count?: number; pass?: number } | HistoryRow>): string {
  if (history.length > 0) {
    return JSON.stringify(
      history.map((item) => ({
        date: formatDateString(('rawDate' in item ? item.rawDate : item.date) || ''),
        count: typeof item.count === 'number' ? item.count : '-',
        pass: typeof item.pass === 'number' ? item.pass : '-',
        status: 'status' in item ? item.status : undefined,
      }))
    )
  }
  return JSON.stringify(dates.map((date) => formatDateString(date)))
}

async function checkForRefresh(forceLoad: boolean = false) {
  if (loading.value) return

  const now = Date.now()
  if (!forceLoad && now - lastRefreshCheckAt.value < REFRESH_CHECK_INTERVAL_MS) return

  lastRefreshCheckAt.value = now

  const signal = beginRequest('datesCheck')
  try {
    const datesData = await apiAnalysis.getDates({ signal })
    const dates = datesData.dates || []
    const history = datesData.history || []
    const nextSignature = buildHistorySignature(dates, history)

    if (forceLoad || historyData.value.length === 0 || nextSignature !== lastHistorySignature.value) {
      await loadData()
    }
  } catch (error) {
    if (isRequestCanceled(error)) return
    console.error('Failed to check tomorrow-star freshness:', error)
  } finally {
    finishRequest('datesCheck', signal)
  }
}

async function refreshStatusAndRetry() {
  await configStore.checkTushareStatus()
  if (configStore.dataInitialized) {
    await ensureFreshDataAndLoad(true)
  }
}

function persistTomorrowStarCache() {
  if (typeof window === 'undefined') return

  const payload = {
    historyData: historyData.value,
    latestCandidates: latestCandidates.value,
    latestAnalysisResults: latestAnalysisResults.value,
    selectedDate: selectedDate.value,
    viewingDate: viewingDate.value,
    latestDate: latestDate.value,
    latestDataDate: latestDataDate.value,
    historyPage: historyPage.value,
    latestCandidatePage: latestCandidatePage.value,
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
    historyData.value = (payload.historyData || []).map((item: any) => ({
      ...item,
      rawDate: formatDateString(item.rawDate || item.date || ''),
      date: formatDateString(item.rawDate || item.date || ''),
      status: normalizeHistoryStatus(item.status),
      analysisCount: typeof item.analysisCount === 'number' ? item.analysisCount : '-',
      errorMessage: item.errorMessage || null,
      isLatest: Boolean(item.isLatest),
    }))
    latestCandidates.value = payload.latestCandidates || []
    latestAnalysisResults.value = payload.latestAnalysisResults || []
    selectedDate.value = payload.selectedDate || null
    viewingDate.value = payload.viewingDate || null
    latestDate.value = payload.latestDate || ''
    latestDataDate.value = payload.latestDataDate || ''
    historyPage.value = Math.max(1, Number(payload.historyPage) || 1)
    latestCandidatePage.value = Math.max(1, Number(payload.latestCandidatePage) || 1)
    lastHistorySignature.value = payload.lastHistorySignature || ''
    freshnessVersion.value = payload.freshnessVersion || ''

    // 防止旧缓存把某一天的右侧结果挂到另一日期上。
    if (
      viewingDate.value
      && latestDataDate.value
      && viewingDate.value !== latestDataDate.value
    ) {
      latestCandidates.value = []
      latestAnalysisResults.value = []
      latestCandidatePage.value = 1
    }

    hydratedFromCache.value = historyData.value.length > 0 || latestCandidates.value.length > 0
  } catch {
    sessionStorage.removeItem(TOMORROW_STAR_CACHE_KEY)
  }
}

async function refreshAfterStatusReady(forceReload: boolean = false) {
  try {
    await configStore.checkTushareStatus()
  } catch {
    return
  }
  await ensureFreshDataAndLoad(forceReload)
}

onMounted(() => {
  hydrateTomorrowStarCache()
  startAutoIncrementalAttemptTimer()

  if (historyData.value.length === 0) {
    void loadData()
    void configStore.checkTushareStatus().catch(() => undefined)
  } else {
    void refreshAfterStatusReady(false)
  }

  // 检查增量更新状态
  void checkIncrementalStatus()
})

onActivated(() => {
  startAutoIncrementalAttemptTimer()
  void refreshAfterStatusReady()
  void checkIncrementalStatus()
})

onDeactivated(() => {
  stopIncrementalPolling()
  stopAutoIncrementalAttemptTimer()
  cancelAllPageRequests()
  loading.value = false
  loadingLatest.value = false
  checkingFreshness.value = false
})

onUnmounted(() => {
  stopIncrementalPolling()
  stopAutoIncrementalAttemptTimer()
  cancelAllPageRequests()
})
</script>

<style scoped lang="scss">
// 8px 网格系统
$space-xs: 8px;
$space-sm: 16px;
$space-md: 24px;
$space-lg: 32px;

.tomorrow-star-page {
  padding: 0;
  margin: 0;

  .page-alert {
    margin-bottom: $space-sm;
  }

  .page-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 560px;
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
  }

  .update-progress-card {
    margin-bottom: $space-sm;
    border: 1px solid #409eff;
    background: #f0f9ff;

    :deep(.el-card__body) {
      padding: $space-sm;
    }

    .progress-content {
      .progress-info {
        display: flex;
        align-items: center;
        gap: $space-xs;
        margin-bottom: $space-xs;

        .progress-text {
          font-weight: 500;
          color: #409eff;
          font-size: 14px;
        }

        .progress-detail {
          color: #606266;
          font-size: 13px;
        }

        .current-code {
          margin-left: auto;
          color: #909399;
          font-size: 12px;
        }
      }
    }
  }

  // 统一卡片样式
  .el-card {
    border-radius: 8px;

    :deep(.el-card__header) {
      padding: $space-xs $space-sm;
      border-bottom: 1px solid #ebeef5;
    }

    :deep(.el-card__body) {
      padding: $space-sm;
    }
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 32px;

    .title-section {
      display: flex;
      align-items: center;
      gap: $space-xs;
      font-size: 14px;
      font-weight: 500;

      .date-tag {
        font-size: 12px;
      }
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: $space-xs;
    }
  }

  // 统一提示框样式
  .table-header-tip {
    margin-bottom: $space-xs;
    padding: $space-xs $space-xs;
    background-color: #f5f7fa;
    border-radius: 4px;
    font-size: 12px;
    color: #606266;
    line-height: 1.6;

    .tip-item {
      margin-right: $space-sm;

      &:last-child {
        margin-right: 0;
      }
    }
  }

  .history-card {
    height: 100%;

    .history-table {
      flex: 1 1 auto;

      :deep(.el-table__row) {
        cursor: pointer;

        &:hover {
          background-color: #f0f9ff;
        }
      }

      :deep(.el-table__cell) {
        padding: $space-xs 0;
      }
    }

    .history-status-cell {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 4px;

      .status-tag {
        min-width: 52px;
      }
    }
  }

  .candidates-card {
    .candidates-table {
      flex: 1 1 auto;
      min-height: 200px;

      :deep(.cell) {
        white-space: nowrap;
      }

      :deep(.el-table__cell) {
        padding: $space-xs 0;
      }
    }

    .pagination-wrap {
      display: flex;
      justify-content: flex-end;
      margin-top: $space-xs;
      flex-shrink: 0;
      min-height: 32px;
    }

    .el-divider {
      margin: $space-sm 0;
      flex-shrink: 0;
    }

    .analysis-section {
      flex-shrink: 0;
      overflow: hidden;
      padding: 0 $space-xs;

      .analysis-tip {
        margin-bottom: $space-xs;
        padding: $space-xs $space-xs;
        background-color: #e8f4fd;
        border-radius: 4px;
        font-size: 12px;
        color: #409eff;
        line-height: 1.6;
      }

      h4 {
        margin: 0 0 $space-xs 0;
        font-size: 14px;
        font-weight: 500;
        color: var(--color-text-secondary);
      }
    }
  }

  .history-card {
    .pagination-wrap {
      display: flex;
      justify-content: flex-end;
      margin-top: $space-xs;
      flex-shrink: 0;
      min-height: 32px;
    }
  }

  // 统一 el-divider 样式
  .el-divider {
    margin: $space-sm 0;
  }

  // 统一 el-tag 样式
  .el-tag {
    border-radius: 4px;
  }

  // 统一按钮样式
  .el-button {
    border-radius: 4px;
  }
}

// 确保 el-row 和 el-col 对齐
.el-row {
  margin: 0 !important;

  .el-col {
    padding: 0 !important;
  }
}

// 顶部两列等高对齐
.top-row {
  display: flex;
  align-items: stretch;

  .el-col {
    display: flex;
    flex-direction: column;
  }
}

// 等高卡片
.matched-height {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;

  :deep(.el-card__body) {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
}

.history-card {
  :deep(.el-card__body) {
    overflow: hidden;
  }

  .history-table {
    flex: 1;
  }
}

.candidates-card {
  :deep(.el-card__body) {
    overflow: hidden;
  }

  .candidates-table {
    flex: 1;
  }

  .pagination-wrap {
    flex-shrink: 0;
  }

  .el-divider {
    flex-shrink: 0;
  }

  .analysis-section {
    flex-shrink: 0;
  }
}

// 涨跌颜色
.text-up {
  color: #e74c3c;
}

.text-down {
  color: #2ecc71;
}
</style>
