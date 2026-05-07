<template>
  <div class="watchlist-page">
    <!-- 加载状态 -->
    <div v-if="isLoading && watchlist.length === 0" class="loading-container">
      <el-skeleton :rows="3" animated />
      <div class="loading-text">加载中...</div>
    </div>

    <!-- 上方区域：左侧列表 + 右侧详情 -->
    <template v-else>
    <div class="top-section">
      <el-card class="list-card">
          <template #header>
            <div class="card-header">
              <div class="card-header__title">
                <span>我的观察</span>
                <el-tag v-if="isRefreshingList" type="info" size="small">刷新中...</el-tag>
              </div>
              <el-button
                type="primary"
                size="small"
                :icon="Plus"
                @click="showAddDialog = true"
              >
                添加
              </el-button>
            </div>
          </template>

          <div v-if="isMobile" class="watchlist-mobile-list">
            <el-empty v-if="watchlist.length === 0" description="暂无观察股票" :image-size="60" />
            <button
              v-for="item in watchlist"
              v-else
              :key="item.id"
              type="button"
              class="mobile-stock-card"
              :class="{ active: selectedStock?.id === item.id }"
              @click="selectStock(item)"
            >
              <div class="mobile-stock-card__header">
                <div class="mobile-stock-card__identity">
                  <span class="mobile-stock-card__code">{{ item.code }}</span>
                  <span class="mobile-stock-card__name">{{ item.name || item.code }}</span>
                </div>
                <el-tag v-if="selectedStock?.id === item.id" type="primary" size="small">当前查看</el-tag>
              </div>
              <div class="mobile-stock-card__meta">
                <div class="mobile-stock-card__meta-item">
                  <span class="label">成本</span>
                  <span class="value">{{ item.entry_price != null ? item.entry_price.toFixed(2) : '-' }}</span>
                </div>
                <div class="mobile-stock-card__meta-item">
                  <span class="label">仓位</span>
                  <span class="value">{{ formatPositionRatio(item.position_ratio) }}</span>
                </div>
              </div>
              <div class="mobile-stock-card__footer">
                <div class="mobile-stock-card__risk">
                  <span class="label">最新结论</span>
                  <el-tag
                    v-if="getLatestAnalysisForStock(item.id)?.risk_level"
                    :type="getRiskLevelType(getLatestAnalysisForStock(item.id)?.risk_level)"
                    size="small"
                  >
                    风险{{ getRiskLevelLabel(getLatestAnalysisForStock(item.id)?.risk_level) }}
                  </el-tag>
                  <el-tag
                    v-else-if="getLatestAnalysisForStock(item.id)?.verdict"
                    :type="getVerdictType(getLatestAnalysisForStock(item.id)?.verdict)"
                    size="small"
                  >
                    {{ getLatestAnalysisForStock(item.id)?.verdict }}
                  </el-tag>
                  <span v-else class="value">{{ item.add_reason || '待分析' }}</span>
                </div>
                <div class="mobile-stock-card__actions">
                  <el-button text type="primary" size="small" @click.stop="openEditDialog(item)">编辑</el-button>
                  <el-button text type="danger" size="small" @click.stop="removeStock(item)">删除</el-button>
                </div>
              </div>
            </button>
          </div>

          <el-table
            v-else
            :data="watchlist"
            @row-click="selectStock"
            highlight-current-row
            class="watchlist-table"
            height="100%"
          >
          <el-table-column prop="code" label="代码" width="80" />
          <el-table-column prop="name" label="名称" />
            <el-table-column label="操作" width="120" align="center">
              <template #default="{ row }">
                <div class="row-actions">
                  <el-button
                    text
                    type="primary"
                    size="small"
                    @click.stop="openEditDialog(row)"
                  >
                    编辑
                  </el-button>
                  <el-divider direction="vertical" />
                  <el-button
                    text
                    type="danger"
                    size="small"
                    :icon="Delete"
                    @click.stop="removeStock(row)"
                  >
                    删除
                  </el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
      </el-card>

      <el-card v-if="selectedStock" class="detail-card">
        <template #header>
              <div class="card-header">
                <span class="stock-title">{{ selectedStock.code }} {{ selectedStock.name || '' }}</span>
                <div class="header-actions">
                  <el-button size="small" @click="goToDiagnosis(selectedStock.code)">
                    单股诊断
                  </el-button>
                  <el-tag type="primary" effect="plain" size="small" class="analyzing-tag" :class="{ visible: analyzing }">
                    分析中...
                  </el-tag>
                </div>
              </div>
            </template>

            <!-- K线图 -->
            <div ref="chartRef" v-loading="loadingChart" class="chart-container" element-loading-text="加载中..." />

            <!-- 趋势分析 -->
            <el-divider />
            <div class="trend-section">
              <h4>趋势分析 (基于技术指标)</h4>
              <el-row :gutter="20" class="position-row">
                <el-col :span="summarySpan">
                  <div class="trend-box">
                    <div class="trend-label">买入成本</div>
                    <div class="price-range">
                      <span>{{ selectedStock.entry_price != null ? selectedStock.entry_price.toFixed(2) : '-' }}</span>
                    </div>
                  </div>
                </el-col>
                <el-col :span="summarySpan">
                  <div class="trend-box">
                    <div class="trend-label">当前仓位</div>
                    <div class="price-range">
                      <span>{{ formatPositionRatio(selectedStock.position_ratio) }}</span>
                    </div>
                  </div>
                </el-col>
              </el-row>
              <el-row :gutter="20" class="position-row" v-if="analysisHistory.length > 0">
                <el-col :span="actionSpan">
                  <div class="trend-box compact">
                    <div class="trend-label">买入动作</div>
                    <el-tag :type="getBuyActionType(analysisHistory[0].buy_action)" size="small">
                      {{ getBuyActionLabel(analysisHistory[0].buy_action) }}
                    </el-tag>
                  </div>
                </el-col>
                <el-col :span="actionSpan">
                  <div class="trend-box compact">
                    <div class="trend-label">持仓动作</div>
                    <el-tag :type="getHoldActionType(analysisHistory[0].hold_action)" size="small">
                      {{ getHoldActionLabel(analysisHistory[0].hold_action) }}
                    </el-tag>
                  </div>
                </el-col>
                <el-col :span="actionSpan">
                  <div class="trend-box compact">
                    <div class="trend-label">风险等级</div>
                    <el-tooltip placement="top" effect="light">
                      <template #content>
                        <div class="risk-tooltip">
                          <div
                            v-for="(line, index) in getRiskLevelTooltipLines(analysisHistory[0])"
                            :key="`latest-risk-${index}`"
                            class="risk-tooltip-line"
                          >
                            {{ line }}
                          </div>
                        </div>
                      </template>
                      <el-tag :type="getRiskLevelType(analysisHistory[0].risk_level)" size="small">
                        {{ getRiskLevelLabel(analysisHistory[0].risk_level) }}
                      </el-tag>
                    </el-tooltip>
                  </div>
                </el-col>
              </el-row>
              <div v-if="latestAnalysis" class="decision-section">
                <div class="decision-card">
                  <div class="decision-title">建仓建议</div>
                  <div class="decision-text">{{ latestAnalysis.buy_recommendation || latestAnalysis.recommendation || '-' }}</div>
                </div>
                <div class="decision-card">
                  <div class="decision-title">持仓建议</div>
                  <div class="decision-text">{{ latestAnalysis.hold_recommendation || latestAnalysis.recommendation || '-' }}</div>
                </div>
                <div class="decision-card">
                  <div class="decision-title">风控建议</div>
                  <div class="decision-text">{{ latestAnalysis.risk_recommendation || latestAnalysis.recommendation || '-' }}</div>
                </div>
              </div>
              <el-row :gutter="20">
                <el-col :span="summarySpan">
                  <div class="trend-box">
                    <div class="trend-label">当前趋势</div>
                    <el-tag :type="trendData.outlook === 'bullish' ? 'success' : trendData.outlook === 'bearish' ? 'danger' : 'info'" size="large">
                      {{ trendText }}
                    </el-tag>
                  </div>
                </el-col>
                <el-col :span="summarySpan">
                  <div class="trend-box">
                    <div class="trend-label">支撑位 / 压力位</div>
                    <div class="price-range">
                      <span class="support">{{ trendData.support ? trendData.support.toFixed(2) : '-' }}</span>
                      <span class="divider">/</span>
                      <span class="resistance">{{ trendData.resistance ? trendData.resistance.toFixed(2) : '-' }}</span>
                    </div>
                  </div>
                </el-col>
              </el-row>
            </div>

      </el-card>
      <el-empty v-else class="detail-empty" description="请从左侧选择股票" />
    </div>

    <!-- 下方区域：历史分析记录 -->
    <el-card v-if="selectedStock" class="history-card">
          <template #header>
            <div class="card-header">
              <span>历史分析记录</span>
            </div>
          </template>

          <el-empty v-if="historyRows.length === 0" description="暂无分析记录" :image-size="60" />
          <div v-else-if="isMobile" class="history-mobile-list">
            <div
              v-for="row in pagedHistoryRows"
              :key="`${row.id}-${row.analysis_date}`"
              class="history-mobile-card"
            >
              <div class="history-mobile-card__header">
                <span class="history-mobile-card__date">{{ formatTradeDate(row.analysis_date) }}</span>
                <div class="history-mobile-card__tags">
                  <el-tag :type="getVerdictType(row.verdict)" size="small">
                    {{ row.verdict || '-' }}
                  </el-tag>
                  <el-tag v-if="row.risk_level" :type="getRiskLevelType(row.risk_level)" size="small">
                    风险{{ getRiskLevelLabel(row.risk_level) }}
                  </el-tag>
                </div>
              </div>
              <div class="history-mobile-card__metrics">
                <span>评分 {{ row.score != null ? row.score.toFixed(1) : '-' }}</span>
                <span>买入 {{ getBuyActionLabel(row.buy_action) }}</span>
                <span>持仓 {{ getHoldActionLabel(row.hold_action) }}</span>
              </div>
              <div class="history-mobile-card__section">
                <span class="label">建仓建议</span>
                <p>{{ row.buy_recommendation || row.recommendation || '-' }}</p>
              </div>
              <div class="history-mobile-card__section">
                <span class="label">持仓建议</span>
                <p>{{ row.hold_recommendation || row.recommendation || '-' }}</p>
              </div>
              <div class="history-mobile-card__section">
                <span class="label">风控建议</span>
                <p>{{ row.risk_recommendation || row.recommendation || '-' }}</p>
              </div>
            </div>
          </div>
          <el-table v-else :data="pagedHistoryRows" class="history-table">
            <el-table-column prop="analysis_date" label="交易日" min-width="130">
              <template #default="{ row }">
                {{ formatTradeDate(row.analysis_date) }}
              </template>
            </el-table-column>
            <el-table-column prop="verdict" label="结论" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="getVerdictType(row.verdict)" size="small">
                  {{ row.verdict || '-' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="score" label="评分" width="90" align="center">
              <template #default="{ row }">
                {{ row.score != null ? row.score.toFixed(1) : '-' }}
              </template>
            </el-table-column>
            <el-table-column label="买入动作" width="110" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.buy_action" :type="getBuyActionType(row.buy_action)" size="small">
                  {{ getBuyActionLabel(row.buy_action) }}
                </el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="持仓动作" width="120" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.hold_action" :type="getHoldActionType(row.hold_action)" size="small">
                  {{ getHoldActionLabel(row.hold_action) }}
                </el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="风险等级" width="120" align="center">
              <template #default="{ row }">
                <el-tooltip v-if="row.risk_level" placement="top" effect="light">
                  <template #content>
                    <div class="risk-tooltip">
                      <div
                        v-for="(line, index) in getRiskLevelTooltipLines(row)"
                        :key="`history-risk-${row.id}-${index}`"
                        class="risk-tooltip-line"
                      >
                        {{ line }}
                      </div>
                    </div>
                  </template>
                  <el-tag :type="getRiskLevelType(row.risk_level)" size="small">
                    {{ getRiskLevelLabel(row.risk_level) }}
                  </el-tag>
                </el-tooltip>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="建仓建议" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.buy_recommendation || row.recommendation || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="持仓建议" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.hold_recommendation || row.recommendation || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="风控建议" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.risk_recommendation || row.recommendation || '-' }}
              </template>
            </el-table-column>
          </el-table>
          <div v-if="historyRows.length > historyPageSize" class="history-pagination">
            <el-pagination
              v-model:current-page="historyPage"
              :page-size="historyPageSize"
              layout="prev, pager, next"
              :total="historyRows.length"
              :hide-on-single-page="false"
              background
              size="small"
            />
          </div>
        </el-card>

    <!-- 添加对话框 -->
    <el-dialog
      v-model="showAddDialog"
      title="添加到观察列表"
      :width="isMobile ? '100%' : '400px'"
      :fullscreen="isMobile"
      :top="isMobile ? '0' : '15vh'"
    >
      <el-form :model="addForm" :label-width="isMobile ? 'auto' : '80px'" :label-position="isMobile ? 'top' : 'right'">
        <el-form-item label="股票代码">
          <el-input
            v-model="addForm.code"
            placeholder="请输入6位股票代码"
            maxlength="6"
          />
        </el-form-item>
        <el-form-item label="买入成本">
          <el-input
            v-model="addForm.entryPrice"
            placeholder="可选，如 12.35"
          />
        </el-form-item>
        <el-form-item label="仓位">
          <el-input
            v-model="addForm.positionRatio"
            placeholder="可选，如 30 表示 30%"
          />
        </el-form-item>
        <el-form-item label="备注原因">
          <el-input
            v-model="addForm.reason"
            type="textarea"
            placeholder="可选"
            :rows="2"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="addToWatchlist">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="showEditDialog"
      title="编辑持仓信息"
      :width="isMobile ? '100%' : '400px'"
      :fullscreen="isMobile"
      :top="isMobile ? '0' : '15vh'"
    >
      <el-form :model="editForm" :label-width="isMobile ? 'auto' : '80px'" :label-position="isMobile ? 'top' : 'right'">
        <el-form-item label="股票代码">
          <el-input v-model="editForm.code" disabled />
        </el-form-item>
        <el-form-item label="买入成本">
          <el-input
            v-model="editForm.entryPrice"
            placeholder="可选，如 12.35"
          />
        </el-form-item>
        <el-form-item label="仓位">
          <el-input
            v-model="editForm.positionRatio"
            placeholder="可选，如 30 表示 30%"
          />
        </el-form-item>
        <el-form-item label="备注原因">
          <el-input
            v-model="editForm.reason"
            type="textarea"
            placeholder="可选"
            :rows="2"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditDialog = false">取消</el-button>
        <el-button type="primary" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, onActivated, onDeactivated, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Delete } from '@element-plus/icons-vue'
import { apiWatchlist, apiStock, isRequestCanceled } from '@/api'
import { ElMessage } from 'element-plus'
import { useResponsive } from '@/composables/useResponsive'
import { useAuthStore } from '@/store/auth'
import type { KLineData, WatchlistItem, WatchlistAnalysis } from '@/types'
import type { ECharts } from 'echarts/core'

const router = useRouter()
const { isMobile } = useResponsive()
const authStore = useAuthStore()
const WATCHLIST_STATE_KEY_PREFIX = 'stocktrade:watchlist:state'
const WATCHLIST_CACHE_TTL_MS = 5 * 60 * 1000
const WATCHLIST_CHART_CACHE_KEY_PREFIX = 'stocktrade:watchlist:chart-cache'
const WATCHLIST_CHART_CACHE_TTL_MS = 30 * 60 * 1000
const INITIAL_CHART_DAYS = 60
const FULL_CHART_DAYS = 120

type WatchlistTrendState = {
  outlook: 'bullish' | 'bearish' | 'neutral'
  support: number | null
  resistance: number | null
}

type WatchlistViewState = {
  selectedStockId: number | null
  watchlist: WatchlistItem[]
  analysisHistory: WatchlistAnalysis[]
  trendData: WatchlistTrendState
  cachedAt: number
}

type WatchlistChartCacheEntry = {
  code: string
  days: number
  cachedAt: number
  data: KLineData
}

type WatchlistChartCacheMap = Record<string, WatchlistChartCacheEntry>

function getWatchlistStateKey() {
  return `${WATCHLIST_STATE_KEY_PREFIX}:${authStore.user?.id || 'guest'}`
}

function getWatchlistChartCacheKey() {
  return `${WATCHLIST_CHART_CACHE_KEY_PREFIX}:${authStore.user?.id || 'guest'}`
}

const watchlist = ref<WatchlistItem[]>([])
const selectedStock = ref<WatchlistItem | null>(null)
const analysisHistory = ref<WatchlistAnalysis[]>([])

const showAddDialog = ref(false)
const showEditDialog = ref(false)
const addForm = ref({ code: '', reason: '', entryPrice: '', positionRatio: '' })
const editForm = ref({ id: 0, code: '', reason: '', entryPrice: '', positionRatio: '' })
const analyzing = ref(false)

// 缓存优化
const chartDataCache = new Map<string, KLineData>()
const chartDataDaysCache = new Map<string, number>()
const analysisCache = new Map<number, WatchlistAnalysis[]>()
const loadingChart = ref(false)
const loadingAnalysis = ref(false)

const chartRef = ref<HTMLElement>()
let chartInstance: ECharts | null = null
let chartRuntimePromise: Promise<{ init: (dom: HTMLElement) => ECharts }> | null = null
const requestControllers = new Map<string, AbortController>()
let selectionSequence = 0

// 加载状态
const isLoading = ref(false)
const isDataReady = ref(false)
const isHydratedFromCache = ref(false)
const isRefreshingList = ref(false)

const trendData = ref<WatchlistTrendState>({
  outlook: 'neutral',
  support: null as number | null,
  resistance: null as number | null,
})

const trendText = computed(() => {
  const texts: Record<string, string> = {
    bullish: '看涨',
    bearish: '看跌',
    neutral: '中性',
  }
  return texts[trendData.value.outlook] || '未知'
})

const latestAnalysis = computed(() => analysisHistory.value[0] || null)
const summarySpan = computed(() => (isMobile.value ? 24 : 12))
const actionSpan = computed(() => (isMobile.value ? 24 : 8))
const historyPage = ref(1)
const historyPageSize = 5
const historyRows = computed(() => {
  const deduped = new Map<string, WatchlistAnalysis>()

  for (const item of analysisHistory.value) {
    const key = normalizeAnalysisDate(item.analysis_date)
    if (!deduped.has(key)) {
      deduped.set(key, item)
    }
  }

  return Array.from(deduped.values())
})
const pagedHistoryRows = computed(() => {
  const start = (historyPage.value - 1) * historyPageSize
  return historyRows.value.slice(start, start + historyPageSize)
})

function resetHistoryPagination() {
  historyPage.value = 1
}

function getLatestAnalysisForStock(id: number): WatchlistAnalysis | null {
  if (selectedStock.value?.id === id && analysisHistory.value.length > 0) {
    return analysisHistory.value[0] || null
  }

  const cached = analysisCache.get(id)
  return cached?.[0] || null
}

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

function cancelWatchlistPageRequests() {
  requestControllers.forEach((controller) => controller.abort())
  requestControllers.clear()
}

function resetWatchlistViewState(options?: { clearStorageForUserId?: number | null }) {
  watchlist.value = []
  selectedStock.value = null
  analysisHistory.value = []
  trendData.value = {
    outlook: 'neutral',
    support: null,
    resistance: null,
  }
  chartDataCache.clear()
  chartDataDaysCache.clear()
  analysisCache.clear()
  isLoading.value = false
  isDataReady.value = false
  isHydratedFromCache.value = false
  isRefreshingList.value = false
  loadingChart.value = false
  loadingAnalysis.value = false
  analyzing.value = false
  if (options && Object.prototype.hasOwnProperty.call(options, 'clearStorageForUserId')) {
    clearWatchlistState(options.clearStorageForUserId)
    clearChartCache(options.clearStorageForUserId)
  }
}

onMounted(async () => {
  window.addEventListener('resize', handleResize)
  hydrateWatchlistState()
  await ensureDataLoaded(true)
})

onActivated(async () => {
  chartInstance?.resize()

  // 确保数据已加载，然后再恢复选中状态
  await ensureDataLoaded(!isHydratedFromCache.value)
  if (!selectedStock.value && watchlist.value.length > 0) {
    await restoreSelectedStock()
  }
})

onDeactivated(() => {
  selectionSequence += 1
  cancelWatchlistPageRequests()
  loadingChart.value = false
  loadingAnalysis.value = false
  isLoading.value = false
  loadPromise = null
})

onUnmounted(() => {
  selectionSequence += 1
  if (chartInstance) {
    chartInstance.dispose()
  }
  window.removeEventListener('resize', handleResize)
  cancelWatchlistPageRequests()
})

watch(
  () => authStore.user?.id,
  (newUserId, oldUserId) => {
    selectionSequence += 1
    cancelWatchlistPageRequests()
    resetWatchlistViewState(
      oldUserId != null && oldUserId !== newUserId
        ? { clearStorageForUserId: oldUserId }
        : undefined,
    )
  },
)

function handleResize() {
  chartInstance?.resize()
}

// 确保数据已加载（避免重复加载）
let loadPromise: Promise<void> | null = null

async function ensureDataLoaded(forceRefresh: boolean = false) {
  if (!forceRefresh && isDataReady.value && watchlist.value.length > 0) {
    return
  }

  // 如果正在加载，等待已有请求完成
  if (loadPromise) {
    return loadPromise
  }

  // 发起新加载
  loadPromise = (async () => {
    isLoading.value = watchlist.value.length === 0
    isRefreshingList.value = watchlist.value.length > 0
    try {
      await loadWatchlist()
      isDataReady.value = true
    } finally {
      isLoading.value = false
      isRefreshingList.value = false
      loadPromise = null
    }
  })()

  return loadPromise
}

async function loadWatchlist() {
  const signal = beginRequest('watchlist')
  try {
    const data = await apiWatchlist.getAll({ signal })
    const previousState = loadWatchlistState()
    const previousSelectedId = selectedStock.value?.id || previousState?.selectedStockId || null
    watchlist.value = data.items || []
    if (!watchlist.value.length) {
      selectedStock.value = null
      analysisHistory.value = []
      resetHistoryPagination()
      persistWatchlistState()
      return
    }

    if (selectedStock.value) {
      const refreshed = watchlist.value.find((item) => item.id === selectedStock.value?.id) || null
      selectedStock.value = refreshed
    } else if (previousSelectedId) {
      selectedStock.value = watchlist.value.find((item) => item.id === previousSelectedId) || null
    }

    if (!selectedStock.value) {
      analysisHistory.value = []
      resetHistoryPagination()
      trendData.value = {
        outlook: 'neutral',
        support: null,
        resistance: null,
      }
    }

    persistWatchlistState()

    if (selectedStock.value) {
      queueDetailRefresh(selectedStock.value)
    }
  } catch (error: any) {
    if (isRequestCanceled(error)) return
    console.error('Failed to load watchlist:', error)
  } finally {
    finishRequest('watchlist', signal)
  }
}

async function selectStock(row: WatchlistItem) {
  const requestId = ++selectionSequence
  cancelRequest('chart')
  cancelRequest('chartExtended')
  cancelRequest('analysis')
  cancelRequest('watchlistAnalyze')
  selectedStock.value = row
  resetHistoryPagination()
  persistWatchlistState()

  // 并行加载K线和分析数据
  await Promise.all([
    loadChart(row.code),
    loadAnalysis(row.id)
  ])
  if (requestId !== selectionSequence) return

  // 自动触发分析，但不阻塞当前视图渲染
  void analyzeNow()
}

async function loadChart(code: string) {
  const signal = beginRequest('chart')
  loadingChart.value = true

  try {
    let data = chartDataCache.get(code)
    let cachedDays = chartDataDaysCache.get(code) || 0

    if (!data) {
      const persistent = loadChartCache(code)
      if (persistent) {
        data = persistent.data
        cachedDays = persistent.days
        chartDataCache.set(code, persistent.data)
        chartDataDaysCache.set(code, persistent.days)
      }
    }

    if (!data) {
      data = await apiStock.getKline(code, INITIAL_CHART_DAYS, false, { signal })
      cachedDays = INITIAL_CHART_DAYS
      setChartCache(code, data, INITIAL_CHART_DAYS)
    }

    await nextTick()
    await renderChart(data)

    // 简单计算支撑位和压力位
    const closes = data.daily.map((d) => d.close)
    const max = Math.max(...closes)
    const min = Math.min(...closes)
    const current = closes[closes.length - 1]

    trendData.value = {
      outlook: current > (max + min) / 2 ? 'bullish' : 'bearish',
      support: min,
      resistance: max,
    }
    persistWatchlistState()
    queueFullChartRefresh(code, cachedDays)
  } catch (error: any) {
    if (isRequestCanceled(error)) return
    console.error('加载K线图失败:', error)
  } finally {
    finishRequest('chart', signal)
    loadingChart.value = false
  }
}

function queueFullChartRefresh(code: string, currentDays: number) {
  if (currentDays >= FULL_CHART_DAYS) return
  if (selectedStock.value?.code !== code) return
  void refreshFullChartInBackground(code)
}

async function refreshFullChartInBackground(code: string) {
  const signal = beginRequest('chartExtended')
  try {
    const fullData = await apiStock.getKline(code, FULL_CHART_DAYS, false, { signal, timeoutMs: 20000 })
    if (selectedStock.value?.code !== code) return

    setChartCache(code, fullData, FULL_CHART_DAYS)
    await renderChart(fullData)

    const closes = fullData.daily.map((d) => d.close)
    const max = Math.max(...closes)
    const min = Math.min(...closes)
    const current = closes[closes.length - 1]
    trendData.value = {
      outlook: current > (max + min) / 2 ? 'bullish' : 'bearish',
      support: min,
      resistance: max,
    }
    persistWatchlistState()
  } catch (error) {
    if (isRequestCanceled(error)) return
    console.error('后台补全K线失败:', error)
  } finally {
    finishRequest('chartExtended', signal)
  }
}

async function loadAnalysis(id: number) {
  const signal = beginRequest('analysis')
  loadingAnalysis.value = true

  try {
    // 使用缓存
    let data = analysisCache.get(id)
    if (!data) {
      const response = await apiWatchlist.getAnalysis(id, { signal })
      data = response.analyses || []
      analysisCache.set(id, data)
    }

    analysisHistory.value = data
    resetHistoryPagination()
    persistWatchlistState()
  } catch (error) {
    if (isRequestCanceled(error)) return
    console.error('Failed to load analysis:', error)
  } finally {
    finishRequest('analysis', signal)
    loadingAnalysis.value = false
  }
}

async function renderChart(data: KLineData) {
  if (!chartRef.value) return

  const { init } = await loadChartRuntime()

  if (!chartInstance) {
    chartInstance = init(chartRef.value)
  }

  const dates = data.daily.map((d) => d.date)
  const values = data.daily.map((d) => [d.open, d.close, d.low, d.high])
  const ma20 = data.daily.map((d) => d.ma20)
  const ma60 = data.daily.map((d) => d.ma60)
  const option = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (params: Array<{ seriesName: string; axisValue: string; data: number[] | number | null }>) => {
        const lines = [params[0]?.axisValue || '-']

        for (const item of params) {
          if (item.seriesName === 'K线' && Array.isArray(item.data)) {
            const [open, close, low, high] = item.data
            lines.push(`开盘: ${formatChartNumber(open)}`)
            lines.push(`收盘: ${formatChartNumber(close)}`)
            lines.push(`最低: ${formatChartNumber(low)}`)
            lines.push(`最高: ${formatChartNumber(high)}`)
            continue
          }

          lines.push(`${item.seriesName}: ${formatChartNumber(item.data)}`)
        }

        return lines.join('<br/>')
      },
    },
    grid: [
      { left: '8%', right: '8%', top: '10%', height: '65%' },
      { left: '8%', right: '8%', top: '80%', height: '15%' },
    ],
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: false } },
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { fontSize: 10 } },
    ],
    yAxis: [
      { scale: true, gridIndex: 0 },
      { scale: true, gridIndex: 1, splitLine: { show: false } },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 50, end: 100 },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: values,
        itemStyle: {
          color: '#ef5350',
          color0: '#26a69a',
          borderColor: '#ef5350',
          borderColor0: '#26a69a',
        },
      },
      {
        name: 'MA20',
        type: 'line',
        data: ma20,
        smooth: true,
        lineStyle: { width: 1, color: '#2980b9' },
        symbol: 'none',
      },
      {
        name: 'MA60',
        type: 'line',
        data: ma60,
        smooth: true,
        lineStyle: { width: 1, color: '#8e44ad' },
        symbol: 'none',
      },
    ],
  }

  chartInstance.setOption(option)
}

function formatChartNumber(value: number[] | number | null | undefined) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '-'
  }
  return value.toFixed(2)
}

async function loadChartRuntime() {
  if (!chartRuntimePromise) {
    chartRuntimePromise = (async () => {
      const [{ use, init }, charts, components, renderers] = await Promise.all([
        import('echarts/core'),
        import('echarts/charts'),
        import('echarts/components'),
        import('echarts/renderers'),
      ])

      use([
        charts.CandlestickChart,
        charts.LineChart,
        components.TooltipComponent,
        components.GridComponent,
        components.DataZoomComponent,
        renderers.CanvasRenderer,
      ])

      return { init }
    })()
  }

  return chartRuntimePromise
}

async function addToWatchlist() {
  const code = addForm.value.code.trim()
  if (!code) {
    ElMessage.warning('请输入股票代码')
    return
  }

  try {
    const entryPrice = (addForm.value.entryPrice || '').trim()
    const positionRatio = (addForm.value.positionRatio || '').trim()
    if (entryPrice || positionRatio) {
      await apiWatchlist.add(
        code,
        addForm.value.reason,
        0,
        entryPrice ? Number(entryPrice) : undefined,
        positionRatio ? Number(positionRatio) / 100 : undefined,
      )
    } else {
      await apiWatchlist.add(code, addForm.value.reason)
    }
    showAddDialog.value = false
    addForm.value = { code: '', reason: '', entryPrice: '', positionRatio: '' }
    await loadWatchlist()
    persistWatchlistState()
    ElMessage.success('添加成功')
  } catch (error: any) {
    ElMessage.error('添加失败: ' + error.message)
  }
}

function openEditDialog(row: WatchlistItem) {
  editForm.value = {
    id: row.id,
    code: row.code,
    reason: row.add_reason || '',
    entryPrice: row.entry_price != null ? String(row.entry_price) : '',
    positionRatio: row.position_ratio != null ? String(row.position_ratio * 100) : '',
  }
  showEditDialog.value = true
}

async function saveEdit() {
  try {
    const entryPrice = (editForm.value.entryPrice || '').trim()
    const positionRatio = (editForm.value.positionRatio || '').trim()
    const hasNewData = entryPrice || positionRatio

    await apiWatchlist.update(editForm.value.id, {
      reason: editForm.value.reason || undefined,
      entry_price: entryPrice ? Number(entryPrice) : null,
      position_ratio: positionRatio ? Number(positionRatio) / 100 : null,
    })
    showEditDialog.value = false
    await loadWatchlist()
    if (selectedStock.value?.id === editForm.value.id) {
      const updated = watchlist.value.find((item) => item.id === editForm.value.id) || null
      selectedStock.value = updated

      // 如果填写了买入成本或仓位信息，自动触发分析
      if (hasNewData) {
        // 清除缓存
        analysisCache.delete(editForm.value.id)
        await analyzeNow()
      }
    }
    persistWatchlistState()
    ElMessage.success('保存成功')
  } catch (error: any) {
    ElMessage.error('保存失败: ' + error.message)
  }
}

async function removeStock(row: WatchlistItem) {
  try {
    await apiWatchlist.delete(row.id)
    // 清除缓存
    analysisCache.delete(row.id)
    await loadWatchlist()
    if (selectedStock.value?.id === row.id) {
      selectedStock.value = null
    }
    persistWatchlistState()
    ElMessage.success('已删除')
  } catch (error: any) {
    ElMessage.error('删除失败: ' + error.message)
  }
}

async function analyzeNow() {
  if (!selectedStock.value) return
  if (analyzing.value) return // 防止重复分析

  const signal = beginRequest('watchlistAnalyze')
  analyzing.value = true
  try {
    await apiWatchlist.analyze(selectedStock.value.id, { signal })
    // 清除缓存
    analysisCache.delete(selectedStock.value.id)
    await loadAnalysis(selectedStock.value.id)
    persistWatchlistState()
  } catch (error: any) {
    if (isRequestCanceled(error)) return
    console.error('分析失败:', error)
  } finally {
    finishRequest('watchlistAnalyze', signal)
    analyzing.value = false
  }
}

function goToDiagnosis(code: string) {
  router.push({ path: '/diagnosis', query: { code } })
}

function formatPositionRatio(value?: number | null): string {
  if (value == null) return '-'
  return `${(value * 100).toFixed(0)}%`
}

function formatTradeDate(dateStr: string): string {
  return normalizeAnalysisDate(dateStr)
}

function normalizeAnalysisDate(dateStr: string): string {
  if (!dateStr) return '-'
  return dateStr.slice(0, 10)
}

function getVerdictType(verdict?: string): string {
  const types: Record<string, string> = {
    PASS: 'success',
    WATCH: 'warning',
    FAIL: 'danger',
  }
  return types[verdict || ''] || 'info'
}

function getBuyActionLabel(action?: string): string {
  const labels: Record<string, string> = {
    buy: '可买',
    wait: '等待',
    avoid: '回避',
  }
  return labels[action || ''] || '-'
}

function getBuyActionType(action?: string): string {
  const types: Record<string, string> = {
    buy: 'success',
    wait: 'warning',
    avoid: 'danger',
  }
  return types[action || ''] || 'info'
}

function getHoldActionLabel(action?: string): string {
  const labels: Record<string, string> = {
    hold: '继续持有',
    hold_cautious: '谨慎持有',
    trim: '减仓观察',
    add_on_pullback: '回踩加仓',
  }
  return labels[action || ''] || '-'
}

function getHoldActionType(action?: string): string {
  const types: Record<string, string> = {
    hold: 'success',
    hold_cautious: 'warning',
    trim: 'danger',
    add_on_pullback: 'primary',
  }
  return types[action || ''] || 'info'
}

function getRiskLevelLabel(level?: string): string {
  const labels: Record<string, string> = {
    low: '低',
    medium: '中',
    high: '高',
  }
  return labels[level || ''] || '-'
}

function getRiskLevelType(level?: string): string {
  const types: Record<string, string> = {
    low: 'success',
    medium: 'warning',
    high: 'danger',
  }
  return types[level || ''] || 'info'
}

function getRiskLevelTooltipLines(item?: WatchlistAnalysis | null): string[] {
  const entryPrice = selectedStock.value?.entry_price
  const positionRatio = selectedStock.value?.position_ratio
  const currentPrice = item?.close_price
  const pnl = entryPrice && currentPrice ? currentPrice / entryPrice - 1 : null

  const lines: string[] = ['命中说明']

  if (!item?.risk_level) {
    lines.push('• 暂无风险等级数据')
  } else if (item.risk_level === 'high') {
    if (item.verdict === 'FAIL') {
      lines.push('• 命中 FAIL，直接判定为高风险')
    } else {
      lines.push('• 已触发高风险条件')
    }
    if (pnl !== null && pnl <= -0.05) {
      lines.push(`• 浮亏 ${(Math.abs(pnl) * 100).toFixed(1)}% ，已超过 5%`)
    }
    if ((positionRatio || 0) >= 0.7) {
      lines.push(`• 当前仓位 ${((positionRatio || 0) * 100).toFixed(0)}% ，已达到高仓位`)
    }
  } else if (item.risk_level === 'low') {
    lines.push('• 满足 PASS 且评分 >= 4.0')
    lines.push('• 未触发浮亏/高仓位等高风险条件')
  } else {
    if (pnl !== null && pnl >= 0.08) {
      lines.push(`• 浮盈 ${(pnl * 100).toFixed(1)}% ，按中风险处理`)
    } else if ((item.score || 0) >= 4.0) {
      lines.push(`• 评分 ${item.score?.toFixed(1)} >= 4.0 ，按中风险处理`)
    } else {
      lines.push('• 未触发高风险，默认按中风险处理')
    }
  }

  lines.push('规则说明')
  lines.push('• 高: 风险释放/FAIL，或浮亏 >= 5%，或仓位 >= 70%')
  lines.push('• 中: 浮盈 >= 8% 或评分 >= 4.0，且未达到高风险')
  lines.push('• 低: PASS 且评分 >= 4.0，且未触发高风险')
  lines.push('• 其他情况默认中风险')

  return lines
}

async function restoreSelectedStock() {
  const state = loadWatchlistState()
  if (!state || selectedStock.value) return

  try {
    const selectedId = state.selectedStockId as number | undefined
    if (!selectedId) return

    const target = watchlist.value.find((item) => item.id === selectedId) || null
    if (!target) return

    selectedStock.value = target
    trendData.value = state.trendData || trendData.value
    analysisHistory.value = state.analysisHistory || []
    await nextTick()
    queueDetailRefresh(target)
  } catch {
    clearWatchlistState()
  }
}

function persistWatchlistState() {
  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return

  const state: WatchlistViewState = {
    selectedStockId: selectedStock.value?.id || null,
    watchlist: watchlist.value,
    analysisHistory: analysisHistory.value,
    trendData: trendData.value,
    cachedAt: Date.now(),
  }

  window.localStorage.setItem(getWatchlistStateKey(), JSON.stringify(state))
}

function hydrateWatchlistState() {
  const state = loadWatchlistState()
  if (!state) return

  watchlist.value = state.watchlist || []
  analysisHistory.value = state.analysisHistory || []
  trendData.value = state.trendData || trendData.value
  isDataReady.value = watchlist.value.length > 0
  isHydratedFromCache.value = watchlist.value.length > 0

  if (state.selectedStockId) {
    selectedStock.value = watchlist.value.find((item) => item.id === state.selectedStockId) || null
  }
}

function loadWatchlistState(): WatchlistViewState | null {
  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return null

  const raw = window.localStorage.getItem(getWatchlistStateKey())
  if (!raw) return null

  try {
    const state = JSON.parse(raw) as WatchlistViewState
    if (!state.cachedAt || Date.now() - state.cachedAt > WATCHLIST_CACHE_TTL_MS) {
      clearWatchlistState()
      return null
    }
    return state
  } catch {
    clearWatchlistState()
    return null
  }
}

function clearWatchlistState(userIdToClear?: number | null) {
  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return
  const key = userIdToClear != null ? `${WATCHLIST_STATE_KEY_PREFIX}:${userIdToClear}` : getWatchlistStateKey()
  window.localStorage.removeItem(key)
}

function clearChartCache(userIdToClear?: number | null) {
  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return
  const key = userIdToClear != null ? `${WATCHLIST_CHART_CACHE_KEY_PREFIX}:${userIdToClear}` : getWatchlistChartCacheKey()
  window.localStorage.removeItem(key)
}

function loadChartCache(code: string): WatchlistChartCacheEntry | null {
  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return null
  const raw = window.localStorage.getItem(getWatchlistChartCacheKey())
  if (!raw) return null

  try {
    const cache = JSON.parse(raw) as WatchlistChartCacheMap
    const entry = cache[code]
    if (!entry) return null
    if (!entry.cachedAt || Date.now() - entry.cachedAt > WATCHLIST_CHART_CACHE_TTL_MS) {
      delete cache[code]
      window.localStorage.setItem(getWatchlistChartCacheKey(), JSON.stringify(cache))
      return null
    }
    return entry
  } catch {
    window.localStorage.removeItem(getWatchlistChartCacheKey())
    return null
  }
}

function setChartCache(code: string, data: KLineData, days: number) {
  chartDataCache.set(code, data)
  chartDataDaysCache.set(code, days)

  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return

  const nextEntry: WatchlistChartCacheEntry = {
    code,
    days,
    cachedAt: Date.now(),
    data,
  }

  let cache: WatchlistChartCacheMap = {}
  try {
    cache = JSON.parse(window.localStorage.getItem(getWatchlistChartCacheKey()) || '{}') as WatchlistChartCacheMap
  } catch {
    cache = {}
  }

  cache[code] = nextEntry
  const trimmedEntries = Object.values(cache)
    .sort((a, b) => b.cachedAt - a.cachedAt)
    .slice(0, 12)
  const trimmedCache = Object.fromEntries(trimmedEntries.map((entry) => [entry.code, entry]))
  window.localStorage.setItem(getWatchlistChartCacheKey(), JSON.stringify(trimmedCache))
}

function queueDetailRefresh(target: WatchlistItem) {
  void nextTick(() => {
    void loadChart(target.code)
    if (analysisHistory.value.length === 0) {
      void loadAnalysis(target.id)
    } else {
      void refreshAnalysisInBackground(target.id)
    }
  })
}

async function refreshAnalysisInBackground(id: number) {
  analysisCache.delete(id)
  await loadAnalysis(id)
}

</script>

<style scoped lang="scss">
.watchlist-page {
  display: flex;
  flex-direction: column;
  gap: 20px;

  .loading-container {
    padding: 60px 40px;
    text-align: center;

    .loading-text {
      margin-top: 16px;
      color: var(--color-text-light);
      font-size: 14px;
    }
  }

  .top-section {
    display: flex;
    gap: 20px;
    align-items: stretch;
    height: calc(100vh - 320px);
    min-height: 400px;
  }

  .list-card {
    flex: 0 0 320px;
    display: flex;
    flex-direction: column;

    :deep(.el-card__body) {
      flex: 1;
      padding: 0;
      overflow: hidden;
    }

    .watchlist-table {
      height: 100%;
    }

    .watchlist-mobile-list {
      display: flex;
      flex-direction: column;
      gap: 12px;
      padding: 12px;
      overflow: auto;
    }
  }

  .detail-card {
    flex: 1;
    display: flex;
    flex-direction: column;

    :deep(.el-card__body) {
      display: flex;
      flex-direction: column;
      overflow: auto;
    }
  }

  .detail-empty {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 12px;
    background: #fff;
    border: 1px solid var(--el-border-color-light);

    :deep(.el-empty) {
      padding: 40px 0;
    }
  }

  .history-card {
    display: flex;
    flex-direction: column;

    :deep(.el-card__body) {
      max-height: 400px;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    :deep(.el-table) {
      flex: 1;
    }

    .history-pagination {
      display: flex;
      justify-content: center;
      margin-top: 12px;
    }
  }

  .risk-tooltip {
    max-width: 320px;
    line-height: 1.6;
  }

  .risk-tooltip-line {
    white-space: normal;

    & + .risk-tooltip-line {
      margin-top: 4px;
    }
  }

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;

    .card-header__title {
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }

    .stock-title {
      min-width: 150px;
    }

    .header-actions {
      display: flex;
      gap: 8px;
      align-items: center;
    }

    .analyzing-tag {
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.2s;

      &.visible {
        opacity: 1;
        pointer-events: auto;
      }
    }
  }

  .watchlist-table {
    .row-actions {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 4px;
      white-space: nowrap;

      .el-divider--vertical {
        margin: 0 4px;
      }
    }

    :deep(.el-table__row) {
      cursor: pointer;

      &.current-row {
        background-color: #e6f7ff;
      }
    }

    :deep(.el-table__cell) {
      padding: 8px 0;
    }
  }

  .detail-card {
    .el-divider {
      margin: 20px 0;
    }
  }

  .chart-container {
    height: 350px;
    flex-shrink: 0;
  }

  .mobile-stock-card {
    display: flex;
    width: 100%;
    flex-direction: column;
    gap: 12px;
    padding: 14px;
    border: 1px solid var(--el-border-color-light);
    border-radius: 12px;
    background: #fff;
    text-align: left;
    cursor: pointer;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;

    &.active {
      border-color: var(--el-color-primary);
      box-shadow: 0 0 0 1px rgba(64, 158, 255, 0.12);
    }

    &__header,
    &__footer,
    &__meta {
      display: flex;
      justify-content: space-between;
      gap: 12px;
    }

    &__header,
    &__footer {
      align-items: center;
    }

    &__identity {
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 0;
    }

    &__code {
      font-size: 16px;
      font-weight: 600;
      color: var(--color-text-primary);
    }

    &__name {
      color: var(--color-text-secondary);
      font-size: 13px;
      word-break: break-all;
    }

    &__meta-item,
    &__risk {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .label {
      color: var(--color-text-light);
      font-size: 12px;
    }

    .value {
      color: var(--color-text-primary);
      font-size: 13px;
      word-break: break-word;
    }

    &__actions {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      flex-shrink: 0;
    }
  }

  .history-mobile-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
    overflow: auto;
  }

  .history-mobile-card {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 14px;
    border: 1px solid var(--el-border-color-light);
    border-radius: 12px;
    background: var(--color-bg-light);

    &__header,
    &__metrics {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }

    &__date {
      font-weight: 600;
      color: var(--color-text-primary);
    }

    &__tags {
      display: inline-flex;
      gap: 6px;
      flex-wrap: wrap;
    }

    &__metrics {
      color: var(--color-text-secondary);
      font-size: 13px;
    }

    &__section {
      display: flex;
      flex-direction: column;
      gap: 4px;

      .label {
        font-size: 12px;
        color: var(--color-text-light);
      }

      p {
        margin: 0;
        color: var(--color-text-primary);
        line-height: 1.6;
        word-break: break-word;
      }
    }
  }

  .trend-section {
    flex-shrink: 0;

    h4 {
      margin: 0 0 16px 0;
      color: var(--color-text-secondary);
    }

    .position-row {
      margin-bottom: 16px;
    }

    .trend-box {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 16px;
      background-color: var(--color-bg-light);
      border-radius: 8px;

      &.compact {
        padding: 12px 16px;
      }

      .trend-label {
        font-weight: 500;
        color: var(--color-text-secondary);
      }

      .price-range {
        font-size: 16px;

        .support {
          color: var(--color-success);
        }

        .resistance {
          color: var(--color-danger);
        }

        .divider {
          margin: 0 8px;
          color: var(--color-text-light);
        }
      }
    }

    .decision-section {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }

    .decision-card {
      padding: 14px 16px;
      border-radius: 8px;
      background: linear-gradient(180deg, #f8fafc 0%, #eef3f8 100%);
      border: 1px solid #dbe4ee;
    }

    .decision-title {
      margin-bottom: 8px;
      font-size: 12px;
      font-weight: 600;
      color: var(--color-text-secondary);
      letter-spacing: 0.04em;
    }

    .decision-text {
      line-height: 1.6;
      color: var(--color-text-primary);
    }
  }

  .history-section {
    h4 {
      margin: 0 0 16px 0;
      color: var(--color-text-secondary);
    }

    .timeline-content {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 10px;

      .timeline-meta {
        display: flex;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;
      }

      .timeline-recommendations {
        display: flex;
        flex-direction: column;
        gap: 6px;
      }

      .recommendation-item {
        display: flex;
        align-items: flex-start;
        gap: 8px;
      }

      .recommendation-label {
        min-width: 32px;
        color: var(--color-text-light);
      }

      .score {
        font-weight: 500;
      }

      .recommendation-text {
        color: var(--color-text-secondary);
      }
    }
  }

  .history-table {
    :deep(.el-table__cell) {
      vertical-align: top;
    }
  }
}

@media (max-width: 767px) {
  .watchlist-page {
    min-height: auto;
    gap: 16px;

    .top-section {
      flex-direction: column;
      height: auto;
      min-height: 0;
    }

    .list-card,
    .detail-card,
    .detail-empty,
    .history-card {
      width: 100%;
      min-width: 0;

      :deep(.el-card__body) {
        overflow: visible;
      }
    }

    .list-card {
      flex: none;

      :deep(.el-card__body) {
        overflow: visible;
      }
    }

    .detail-card {
      :deep(.el-card__body) {
        padding: 16px;
      }
    }

    .history-card {
      :deep(.el-card__body) {
        max-height: none;
        overflow: visible;
      }
    }

    .card-header {
      align-items: flex-start;
      gap: 10px;

      .stock-title {
        min-width: 0;
        word-break: break-word;
      }

      .header-actions {
        width: 100%;
        justify-content: space-between;
        flex-wrap: wrap;
      }
    }

    .chart-container {
      height: 300px;
    }

    .trend-section {
      .position-row {
        margin-bottom: 12px;
      }

      .trend-box {
        flex-direction: column;
        align-items: flex-start;
        gap: 8px;
      }

      .decision-section {
        grid-template-columns: 1fr;
      }
    }

    :deep(.el-dialog.is-fullscreen) {
      .el-dialog__body {
        padding-bottom: 24px;
      }
    }
  }
}

@media (max-width: 1080px) {
  .watchlist-page {
    .top-section {
      flex-direction: column;
      height: auto;
      min-height: 0;
    }

    .list-card {
      flex: none;
      width: 100%;
    }
  }
}
</style>
