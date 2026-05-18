<template>
  <div class="sector-analysis-page">
    <el-alert
      class="page-alert"
      type="info"
      :closable="false"
      show-icon
      title="板块分析采用配置驱动"
      description="板块目录使用 sector_analysis_catalog，股票池使用 sector_analysis_pool。板块详情页按板块独立历史日期查看对应个股，不再固定展示最新当前热盘快照。"
    />

    <div v-if="!configStore.dataInitialized" class="page-empty">
      <el-empty description="首次初始化尚未完成，板块分析暂不可用" :image-size="120">
        <el-button type="primary" @click="router.push('/update')">
          前往任务中心初始化
        </el-button>
      </el-empty>
    </div>

    <template v-else-if="isOverview">
      <el-card class="overview-card" shadow="never">
        <div class="overview-card__header">
          <div>
            <div class="overview-card__eyebrow">战略主题目录</div>
            <h2>板块分析总览</h2>
            <p>总览按综合强弱从高到低排列，历史轮动信息集中展示在这里；板块详情页则改为左侧历史日期、右侧对应个股的查看方式。</p>
          </div>
          <div class="overview-card__meta">
            <el-tag type="success" effect="plain">板块数 {{ sectorCatalog.sectors.length }}</el-tag>
            <el-tag type="info" effect="plain">最新日期 {{ analyticsLatestDate || '-' }}</el-tag>
            <el-tag type="warning" effect="plain">窗口 {{ analyticsWindowSize }} 日</el-tag>
          </div>
        </div>
        <div class="overview-summary">
          <div class="summary-pill">
            <span class="summary-pill__label">最强板块</span>
            <strong>{{ topSectorName }}</strong>
          </div>
          <div class="summary-pill">
            <span class="summary-pill__label">趋势启动</span>
            <strong>{{ totalTrendStartCount }}</strong>
          </div>
          <div class="summary-pill">
            <span class="summary-pill__label">PASS</span>
            <strong>{{ totalPassCount }}</strong>
          </div>
          <div class="summary-pill">
            <span class="summary-pill__label">负面结构</span>
            <strong>{{ totalNegativeCount }}</strong>
          </div>
        </div>
      </el-card>

      <el-card class="panel-card" shadow="never">
        <template #header>
          <div class="panel-card__header">
            <span>板块历史轮动图</span>
            <el-tag size="small" type="info" effect="plain">默认展示当前最强的 {{ overviewSeries.length }} 个板块</el-tag>
          </div>
        </template>
        <div v-loading="sectorLoading" class="chart-panel">
          <div v-if="overviewSeries.length > 0" ref="overviewChartRef" class="rotation-chart" />
          <el-empty v-else description="暂无板块轮动数据" :image-size="92" />
        </div>
      </el-card>

      <el-card class="panel-card" shadow="never">
        <template #header>
          <div class="panel-card__header">
            <span>板块强弱排序</span>
            <el-tag size="small" type="info" effect="plain">已按综合强弱从高到低排序</el-tag>
          </div>
        </template>

        <el-table
          v-loading="sectorLoading"
          :data="sectorSummaries"
          stripe
          class="sector-table"
        >
          <el-table-column label="板块" min-width="200">
            <template #default="{ row }">
              <button type="button" class="sector-link" @click="goToSector(row.sector_key)">
                <span>{{ row.sector_name }}</span>
              </button>
            </template>
          </el-table-column>
          <el-table-column label="快照/池" min-width="96" align="center">
            <template #default="{ row }">
              {{ row.tracked_count }}/{{ row.pool_count }}
            </template>
          </el-table-column>
          <el-table-column label="B1" prop="b1_count" min-width="72" align="center" />
          <el-table-column label="启动" prop="trend_start_count" min-width="72" align="center" />
          <el-table-column label="PASS" prop="pass_count" min-width="72" align="center" />
          <el-table-column label="负面" prop="negative_flag_count" min-width="76" align="center" />
          <el-table-column label="龙头" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="leader-tags">
                <el-tag
                  v-for="leader in row.leaders"
                  :key="`${row.sector_key}-${leader.code}`"
                  size="small"
                  effect="plain"
                >
                  {{ leader.code }} {{ leader.name || '' }}
                </el-tag>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <div class="sector-grid">
        <button
          v-for="sector in sectorSummaries"
          :key="sector.sector_key"
          type="button"
          class="sector-card"
          @click="goToSector(sector.sector_key)"
        >
          <div class="sector-card__top">
            <div>
              <div class="sector-card__title">{{ sector.sector_name }}</div>
              <div class="sector-card__description">{{ sector.description }}</div>
            </div>
          </div>
          <div class="sector-card__stats">
            <span>快照 {{ sector.tracked_count }}/{{ sector.pool_count }}</span>
            <span>B1 {{ sector.b1_count }}</span>
            <span>启动 {{ sector.trend_start_count }}</span>
            <span>PASS {{ sector.pass_count }}</span>
          </div>
          <div class="sector-card__meta">
            <el-tag size="small" effect="plain">负面 {{ sector.negative_flag_count }}</el-tag>
            <el-tag size="small" type="info" effect="plain">高分 {{ sector.high_score_count }}</el-tag>
          </div>
          <div class="sector-card__tags">
            <el-tag
              v-for="item in rowPolicyTags(sector)"
              :key="`${sector.sector_key}-${item}`"
              size="small"
              effect="plain"
            >
              {{ item }}
            </el-tag>
          </div>
        </button>
      </div>
    </template>

    <template v-else-if="selectedSector && selectedSectorSummary">
      <el-card class="sector-info-card" shadow="never">
        <template #header>
          <div class="card-header">
            <div class="title-section">
              <span>{{ selectedSectorSummary.sector_name }}</span>
            </div>
            <div class="header-actions">
              <el-button size="small" @click="goToOverview">
                返回总览
              </el-button>
            </div>
          </div>
        </template>

        <div class="sector-info-card__description">
          {{ selectedSectorSummary.description }}
        </div>
        <div class="sector-info-card__tags">
          <el-tag size="small" effect="plain">股票池 {{ selectedSectorPoolItems.length }} 只</el-tag>
          <el-tag
            v-for="item in rowPolicyTags(selectedSectorSummary)"
            :key="`sector-info-${item}`"
            size="small"
            effect="plain"
          >
            {{ item }}
          </el-tag>
        </div>
      </el-card>

      <div v-if="isMobile" class="mobile-layout">
        <el-card class="mobile-section-card">
          <template #header>
            <div class="card-header">
              <div class="title-section">
                <span>历史记录</span>
                <el-tag v-if="selectedSectorDate" size="small" type="info" effect="plain">
                  已选 {{ selectedSectorViewingDateDisplay }}
                </el-tag>
              </div>
            </div>
          </template>

          <div class="table-header-tip mobile-tip">
            <span class="tip-item">· 点击日期查看该板块当日个股</span>
            <span class="tip-item">· 右侧内容跟随左侧日期</span>
          </div>

          <div v-if="displaySectorHistoryRows.length > 0" class="mobile-history-list">
            <button
              v-for="row in displaySectorHistoryRows"
              :key="row.rawDate"
              type="button"
              class="mobile-history-item"
              :class="{ active: selectedSectorDate === row.rawDate }"
              @click="selectSectorDate(row)"
            >
              <div class="mobile-history-item__header">
                <span class="mobile-history-item__date">{{ row.date }}</span>
                <div class="mobile-history-item__status">
                  <el-tag
                    v-if="row.rawDate === selectedSectorLatestDate"
                    type="success"
                    size="small"
                    class="status-tag"
                  >
                    最新
                  </el-tag>
                </div>
              </div>
              <div class="mobile-history-item__meta">
                <span>快照 {{ row.count === '-' ? '-' : row.count }}</span>
                <span>趋势启动 {{ row.pass === '-' ? '-' : row.pass }}</span>
                <span>B1通过 {{ row.b1PassCount === '-' ? '-' : row.b1PassCount }}</span>
              </div>
            </button>
          </div>
          <el-empty v-else description="暂无历史记录" :image-size="90" />

          <div class="pagination-wrap mobile-pagination">
            <div class="mobile-pagination__summary">
              第 {{ sectorHistoryPage }} / {{ sectorHistoryPageCount }} 页
            </div>
            <el-pagination
              v-model:current-page="sectorHistoryPage"
              :page-size="historyPageSize"
              layout="prev, pager, next"
              :total="sectorHistoryRows.length"
              :hide-on-single-page="false"
              background
              size="small"
            />
          </div>
        </el-card>

        <el-card
          class="mobile-section-card"
          v-loading="sectorRowsLoading"
          element-loading-text="正在刷新板块个股..."
        >
          <template #header>
            <div class="card-header">
              <div class="title-section">
                <span>{{ selectedSectorSummary.sector_name }} 个股信息</span>
                <el-tag size="small" type="success" class="date-tag">
                  {{ selectedSectorViewingDateDisplay || '-' }}
                </el-tag>
              </div>
              <div class="header-actions">
                <el-button
                  type="primary"
                  size="small"
                  :loading="sectorRowsLoading"
                  @click="refreshSelectedSectorDateRows"
                >
                  刷新
                </el-button>
              </div>
            </div>
          </template>

          <div class="table-header-tip mobile-tip">
            <span class="tip-item">· 该板块按所选日期独立展示入池与评分结果</span>
            <span class="tip-item">· 默认按趋势启动、B1通过、评分排序</span>
          </div>

          <div v-if="displaySectorCandidateRows.length > 0" class="mobile-analysis-list">
            <button
              v-for="row in displaySectorCandidateRows"
              :key="row.code"
              type="button"
              class="mobile-analysis-item"
              @click="viewStock(row.code)"
            >
              <div class="mobile-analysis-item__header">
                <div>
                  <div class="mobile-analysis-item__code">{{ row.code }}</div>
                  <div class="mobile-analysis-item__name">{{ row.name || row.code }}</div>
                </div>
                <el-tag :type="getScoreType(row.total_score)" size="small">
                  {{ typeof row.total_score === 'number' ? row.total_score.toFixed(1) : '-' }}
                </el-tag>
              </div>
              <div class="mobile-analysis-item__meta">
                <div class="mobile-analysis-tags">
                  <el-tag :type="getBooleanTagType(row.b1_passed)" size="small">
                    B1 {{ getBooleanTagLabel(row.b1_passed) }}
                  </el-tag>
                  <el-tag :type="getSignalTypeTag(row.signal_type)" size="small">
                    {{ getSignalTypeLabel(row.signal_type) }}
                  </el-tag>
                  <el-tag type="info" size="small">
                    活跃 {{ formatActivePoolRank(row.active_pool_rank) }}
                  </el-tag>
                </div>
                <div class="mobile-analysis-prices">
                  <span>开 {{ formatPlanPrice(row.open_price) }}</span>
                  <span>收 {{ formatPlanPrice(row.close_price) }}</span>
                  <span :class="getChangeClass(row.change_pct)">{{ formatChange(row.change_pct) }}</span>
                </div>
                <div class="mobile-analysis-prices">
                  <span>换手 {{ formatTurnoverRate(row.turnover_rate) }}</span>
                  <span>量比 {{ formatVolumeRatio(row.volume_ratio) }}</span>
                </div>
                <span class="mobile-analysis-item__comment">{{ getCandidateInlineNote(row) }}</span>
              </div>
            </button>
          </div>
          <el-empty v-else description="该日期暂无板块个股记录" :image-size="90" />

          <div v-if="selectedSectorCurrentRows.length > 0" class="pagination-wrap mobile-pagination">
            <div class="mobile-pagination__summary">
              第 {{ sectorCandidatePage }} / {{ sectorCandidatePageCount }} 页
            </div>
            <el-pagination
              v-model:current-page="sectorCandidatePage"
              :page-size="candidatePageSize"
              layout="prev, pager, next"
              :total="selectedSectorCurrentRows.length"
              :hide-on-single-page="false"
              background
              size="small"
            />
          </div>
        </el-card>
      </div>

      <div v-else class="top-grid is-current-hot">
        <div class="history-column">
          <el-card class="history-card matched-height">
            <template #header>
              <div class="card-header">
                <span>历史记录</span>
              </div>
            </template>

            <div class="table-header-tip">
              <span class="tip-item">· 点击日期查看该板块对应个股</span>
              <span class="tip-item">· 右侧跟随左侧选择</span>
            </div>

            <el-table
              :data="displaySectorHistoryRows"
              @row-click="selectSectorDate"
              class="history-table"
              :height="historyTableHeight"
              highlight-current-row
              :current-row-key="selectedSectorDate"
              row-key="rawDate"
            >
              <el-table-column prop="date" label="时间" min-width="150" />
              <el-table-column prop="count" label="快照" width="72" align="center">
                <template #default="{ row }">
                  {{ row.count === '-' ? '-' : row.count }}
                </template>
              </el-table-column>
              <el-table-column prop="pass" label="启动" width="72" align="center">
                <template #default="{ row }">
                  {{ row.pass === '-' ? '-' : row.pass }}
                </template>
              </el-table-column>
              <el-table-column prop="b1PassCount" label="B1" width="72" align="center">
                <template #default="{ row }">
                  <el-tag v-if="row.b1PassCount !== '-'" :type="row.b1PassCount > 0 ? 'success' : 'info'" size="small">
                    {{ row.b1PassCount }}
                  </el-tag>
                  <span v-else>-</span>
                </template>
              </el-table-column>
            </el-table>

            <div class="pagination-wrap">
              <span class="pagination-total">共 {{ sectorHistoryRows.length }} 日</span>
              <el-pagination
                v-model:current-page="sectorHistoryPage"
                :page-size="historyPageSize"
                layout="prev, pager, next"
                :total="sectorHistoryRows.length"
                :hide-on-single-page="false"
                background
                size="small"
              />
            </div>
          </el-card>
        </div>

        <div class="content-column">
          <el-card
            class="candidates-card matched-height"
            v-loading="sectorRowsLoading"
            element-loading-text="正在刷新板块个股..."
          >
            <template #header>
              <div class="card-header">
                <div class="title-section">
                  <span>{{ selectedSectorSummary.sector_name }} 个股信息</span>
                  <el-tag size="small" type="success" class="date-tag">
                    {{ selectedSectorViewingDateDisplay || '-' }}
                  </el-tag>
                </div>
                <div class="header-actions">
                  <el-button
                    type="primary"
                    size="small"
                    :loading="sectorRowsLoading"
                    @click="refreshSelectedSectorDateRows"
                  >
                    刷新
                  </el-button>
                </div>
              </div>
            </template>

            <div class="table-header-tip">
              <span class="tip-item">· 该板块按所选日期独立展示入池与评分结果</span>
              <span class="tip-item">· 默认按趋势启动、B1通过、评分排序</span>
            </div>

            <div v-if="candidateSortLabel" class="sort-hint">
              当前排序：{{ candidateSortLabel }}
            </div>

            <el-table
              v-if="displaySectorCandidateRows.length > 0"
              :data="displaySectorCandidateRows"
              stripe
              class="candidates-table"
              :height="candidateTableHeight"
              table-layout="fixed"
              size="small"
              @sort-change="handleCandidateSortChange"
            >
              <el-table-column prop="code" label="代码" width="72" sortable="custom" :sort-orders="candidateSortOrders" />
              <el-table-column prop="name" label="名称" width="86" sortable="custom" :sort-orders="candidateSortOrders" show-overflow-tooltip>
                <template #default="{ row }">
                  <span class="stock-name-cell">{{ row.name || row.code }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="b1_passed" label="B1" width="58" align="center" sortable="custom" :sort-orders="candidateSortOrders">
                <template #default="{ row }">
                  <el-tag :type="getBooleanTagType(row.b1_passed)" size="small">
                    {{ getBooleanTagLabel(row.b1_passed) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="signal_type" label="信号" width="88" align="center" sortable="custom" :sort-orders="candidateSortOrders">
                <template #default="{ row }">
                  <el-tag :type="getSignalTypeTag(row.signal_type)" size="small">
                    {{ getSignalTypeLabel(row.signal_type) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="total_score" label="评分" width="62" align="right" sortable="custom" :sort-orders="candidateSortOrders">
                <template #default="{ row }">
                  <el-tag :type="getScoreType(row.total_score)" size="small">
                    {{ typeof row.total_score === 'number' ? row.total_score.toFixed(1) : '-' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="active_pool_rank" label="活跃" width="62" align="center" sortable="custom" :sort-orders="candidateSortOrders">
                <template #default="{ row }">
                  {{ formatActivePoolRank(row.active_pool_rank) }}
                </template>
              </el-table-column>
              <el-table-column prop="open_price" label="开盘" width="64" align="right" sortable="custom" :sort-orders="candidateSortOrders">
                <template #default="{ row }">
                  {{ formatPlanPrice(row.open_price) }}
                </template>
              </el-table-column>
              <el-table-column prop="close_price" label="收盘" width="64" align="right" sortable="custom" :sort-orders="candidateSortOrders">
                <template #default="{ row }">
                  {{ formatPlanPrice(row.close_price) }}
                </template>
              </el-table-column>
              <el-table-column prop="change_pct" label="涨跌" width="68" align="right" sortable="custom" :sort-orders="candidateSortOrders">
                <template #default="{ row }">
                  <span :class="getChangeClass(row.change_pct)">
                    {{ typeof row.change_pct === 'number' ? `${row.change_pct.toFixed(2)}%` : '-' }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="turnover_rate" label="换手" width="64" align="right" sortable="custom" :sort-orders="candidateSortOrders">
                <template #default="{ row }">
                  {{ formatTurnoverRate(row.turnover_rate) }}
                </template>
              </el-table-column>
              <el-table-column prop="volume_ratio" label="量比" width="56" align="right" sortable="custom" :sort-orders="candidateSortOrders">
                <template #default="{ row }">
                  {{ formatVolumeRatio(row.volume_ratio) }}
                </template>
              </el-table-column>
              <el-table-column label="备注" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">
                  {{ getCandidateInlineNote(row) }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="56" align="center">
                <template #default="{ row }">
                  <el-button text type="primary" size="small" @click="viewStock(row.code)">
                    详情
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="该日期暂无板块个股记录" :image-size="90" />

            <div v-if="selectedSectorCurrentRows.length > 0" class="pagination-wrap">
              <el-pagination
                v-model:current-page="sectorCandidatePage"
                :page-size="candidatePageSize"
                layout="total, prev, pager, next"
                :total="selectedSectorCurrentRows.length"
                :hide-on-single-page="false"
                background
              />
            </div>
          </el-card>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import type { ECharts, EChartsCoreOption } from 'echarts/core'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { apiAnalysis, isRequestCanceled } from '@/api'
import { useConfigStore } from '@/store/config'
import { useResponsive } from '@/composables/useResponsive'
import type {
  CurrentHotSectorAnalysisResponse,
  CurrentHotSectorHistoryPoint,
  CurrentHotSectorHistorySeries,
  CurrentHotSectorSummaryItem,
  SectorAnalysisRow,
} from '@/types'
import { formatChange } from '@/utils'
import { loadKLineChartRuntime } from '@/utils/klineChart'
import {
  DEFAULT_SECTOR_ANALYSIS_CATALOG,
  SECTOR_ANALYSIS_ROOT_PATH,
  buildSectorMenuEntries,
  getSectorRoutePath,
  resolveSectorAnalysisCatalog,
  resolveSectorStockPool,
  type SectorAnalysisCatalogEntry,
  type SectorStockItem,
} from '@/utils/sectorAnalysis'

type SectorSnapshotRow = SectorAnalysisRow

type SectorHistoryRow = {
  date: string
  rawDate: string
  count: number | '-'
  pass: number | '-'
  b1PassCount: number | '-'
}

type SectorSortProp =
  | 'code'
  | 'name'
  | 'open_price'
  | 'close_price'
  | 'change_pct'
  | 'turnover_rate'
  | 'volume_ratio'
  | 'active_pool_rank'
  | 'b1_passed'
  | 'signal_type'
  | 'total_score'

type SortOrder = 'ascending' | 'descending' | null
type SectorCandidateSortState = {
  prop: SectorSortProp | ''
  order: SortOrder
}

type OverviewSeriesItem = {
  sector_key: string
  sector_name: string
  points: CurrentHotSectorHistoryPoint[]
}

const CHART_COLORS = ['#0f766e', '#1d4ed8', '#dc2626', '#d97706', '#7c3aed', '#0891b2']
const candidateSortOrders: Array<Exclude<SortOrder, null>> = ['descending', 'ascending']
const candidatePageSize = 18

const router = useRouter()
const route = useRoute()
const configStore = useConfigStore()
const { isMobile } = useResponsive()

const sectorLoading = ref(false)
const sectorRowsLoading = ref(false)
const sectorAnalysis = ref<CurrentHotSectorAnalysisResponse | null>(null)
const selectedSectorDate = ref<string | null>(null)
const sectorHistoryPage = ref(1)
const sectorCandidatePage = ref(1)
const sectorCandidateSort = ref<SectorCandidateSortState>({ prop: '', order: null })
const dateRowsCache = ref<Map<string, SectorSnapshotRow[]>>(new Map())

const overviewChartRef = ref<HTMLDivElement | null>(null)
let overviewChartInstance: ECharts | null = null
let resizeListenerBound = false

const requestControllers = new Map<string, AbortController>()

const sectorCatalog = computed(() => resolveSectorAnalysisCatalog(configStore.configs.sector_analysis_catalog))
const sectorMenuEntries = computed(() => buildSectorMenuEntries(sectorCatalog.value))
const sectorStockPool = computed(() => resolveSectorStockPool(
  configStore.configs.sector_analysis_pool,
  configStore.configs.current_hot_pool,
))
const currentSectorKey = computed(() => String(route.params.sectorKey ?? '').trim())
const selectedSector = computed<SectorAnalysisCatalogEntry | null>(() => {
  if (!currentSectorKey.value || currentSectorKey.value === sectorCatalog.value.defaultSectorKey) {
    return null
  }
  return sectorCatalog.value.sectors.find((item) => item.key === currentSectorKey.value) || null
})
const isOverview = computed(() => !selectedSector.value)
const analyticsLatestDate = computed(() => sectorAnalysis.value?.latest_date || '')
const analyticsWindowSize = computed(() => sectorAnalysis.value?.window_size || 120)
const historyPageSize = computed(() => (isMobile.value ? 5 : 15))
const historyTableHeight = computed(() => (isMobile.value ? undefined : 620))
const candidateTableHeight = computed(() => (isMobile.value ? undefined : 700))

function normalizeLabel(value: string): string {
  return value.trim().toLowerCase().replace(/[\s_\-/]+/g, '')
}

function formatDateString(dateStr: string): string {
  if (!dateStr) return ''
  if (/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) return dateStr
  if (/^\d{8}$/.test(dateStr)) return `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`
  return dateStr
}

function formatPlanPrice(value?: number | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '-'
}

function toFiniteNumber(value?: number | string | null): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function formatTurnoverRate(value?: number | null): string {
  const numericValue = toFiniteNumber(value)
  return numericValue === null ? '-' : `${numericValue.toFixed(2)}%`
}

function formatVolumeRatio(value?: number | null): string {
  const numericValue = toFiniteNumber(value)
  return numericValue === null ? '-' : numericValue.toFixed(2)
}

function formatActivePoolRank(value?: number | null): string {
  const numericValue = toFiniteNumber(value)
  return numericValue === null ? '-' : String(Math.round(numericValue))
}

function getScoreType(score?: number | null): string {
  if (typeof score !== 'number') return 'info'
  if (score >= 4.0) return 'success'
  if (score >= 3.5) return 'warning'
  return 'danger'
}

function getSignalTypeLabel(signalType?: string | null): string {
  const signalMap: Record<string, string> = {
    trend_start: '趋势启动',
    rebound: '反弹延续',
    distribution_risk: '风险释放',
  }
  return signalMap[signalType || ''] || signalType || '-'
}

function getSignalTypeTag(signalType?: string | null): string {
  if (signalType === 'trend_start') return 'success'
  if (signalType === 'rebound') return 'warning'
  if (signalType === 'distribution_risk') return 'danger'
  return 'info'
}

function getBooleanTagType(value?: boolean | null): string {
  if (value === true) return 'success'
  if (value === false) return 'info'
  return 'warning'
}

function getBooleanTagLabel(value?: boolean | null): string {
  if (value === true) return '通过'
  if (value === false) return '未过'
  return '-'
}

function getChangeClass(value?: number | null): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return ''
  if (value > 0) return 'text-up'
  if (value < 0) return 'text-down'
  return ''
}

function verdictRank(value?: string | null): number {
  if (value === 'PASS') return 0
  if (value === 'WATCH') return 1
  if (value === 'FAIL') return 2
  return 3
}

function getPoolItemsBySector(sector: SectorAnalysisCatalogEntry): SectorStockItem[] {
  const candidates = [sector.key, sector.name]
  const normalizedCandidates = candidates.map((item) => normalizeLabel(item))

  for (const [bucketKey, items] of Object.entries(sectorStockPool.value)) {
    if (normalizedCandidates.includes(normalizeLabel(bucketKey))) {
      return items
    }
  }
  return []
}

function rowPolicyTags(row: Pick<CurrentHotSectorSummaryItem, 'policy_focus' | 'focus_tracks'>): string[] {
  return [...row.policy_focus, ...row.focus_tracks]
}

function buildFallbackSectorSummary(sector: SectorAnalysisCatalogEntry): CurrentHotSectorSummaryItem {
  return {
    sector_key: sector.key,
    sector_name: sector.name,
    description: sector.description,
    policy_focus: sector.policyFocus,
    focus_tracks: sector.focusTracks,
    rank: null,
    previous_rank: null,
    rank_change: null,
    pool_count: getPoolItemsBySector(sector).length,
    tracked_count: 0,
    pool_hit_ratio: 0,
    b1_count: 0,
    trend_start_count: 0,
    pass_count: 0,
    high_score_count: 0,
    negative_flag_count: 0,
    active_top20_count: 0,
    active_top50_count: 0,
    avg_score: null,
    avg_change_pct: null,
    best_active_pool_rank: null,
    strength_score: 0,
    leaders: [],
  }
}

const sectorSummaries = computed<CurrentHotSectorSummaryItem[]>(() => {
  const items = sectorAnalysis.value?.sectors || []
  if (items.length > 0) return items
  return sectorCatalog.value.sectors.map((sector) => buildFallbackSectorSummary(sector))
})

const selectedSectorSummary = computed<CurrentHotSectorSummaryItem | null>(() => {
  if (!selectedSector.value) return null
  return sectorSummaries.value.find((item) => item.sector_key === selectedSector.value?.key) || buildFallbackSectorSummary(selectedSector.value)
})

const selectedSectorPoolItems = computed(() => selectedSector.value ? getPoolItemsBySector(selectedSector.value) : [])
const selectedSectorHistorySeries = computed<CurrentHotSectorHistorySeries | null>(() => {
  if (!selectedSector.value) return null
  return sectorAnalysis.value?.history.find((item) => item.sector_key === selectedSector.value?.key) || null
})

function normalizeSectorHistoryRows(series: CurrentHotSectorHistorySeries | null): SectorHistoryRow[] {
  if (!series) return []
  return [...series.points]
    .map((point) => ({
      date: formatDateString(point.date),
      rawDate: formatDateString(point.date),
      count: typeof point.tracked_count === 'number' ? point.tracked_count : ('-' as const),
      pass: typeof point.trend_start_count === 'number' ? point.trend_start_count : ('-' as const),
      b1PassCount: typeof point.b1_count === 'number' ? point.b1_count : ('-' as const),
    }))
    .sort((a, b) => b.rawDate.localeCompare(a.rawDate))
}

const sectorHistoryRows = computed(() => normalizeSectorHistoryRows(selectedSectorHistorySeries.value))
const selectedSectorLatestDate = computed(() => sectorHistoryRows.value[0]?.rawDate || '')
const sectorHistoryPageCount = computed(() => Math.max(1, Math.ceil(sectorHistoryRows.value.length / historyPageSize.value)))
const displaySectorHistoryRows = computed(() => {
  if (sectorHistoryPage.value > sectorHistoryPageCount.value) {
    sectorHistoryPage.value = sectorHistoryPageCount.value
  }
  const start = (sectorHistoryPage.value - 1) * historyPageSize.value
  return sectorHistoryRows.value.slice(start, start + historyPageSize.value)
})
const selectedSectorViewingDateDisplay = computed(() => (
  selectedSectorDate.value
    ? formatDateString(selectedSectorDate.value)
    : formatDateString(selectedSectorLatestDate.value)
))

function buildSectorDateCacheKey(sectorKey: string, date: string): string {
  return `${sectorKey}@@${date}`
}

const selectedDateRows = computed(() => {
  const sectorKey = selectedSector.value?.key || ''
  const date = selectedSectorDate.value || selectedSectorLatestDate.value || ''
  const cacheKey = sectorKey && date ? buildSectorDateCacheKey(sectorKey, date) : ''
  return cacheKey ? (dateRowsCache.value.get(cacheKey) || []) : []
})

function getSignalPriority(signalType?: string | null): number {
  return signalType === 'trend_start' ? 0 : 1
}

function getB1PassPriority(pass?: boolean | null): number {
  if (pass === true) return 0
  if (pass === false) return 1
  return 2
}

function getScoreSortValue(score?: number | null): number {
  return typeof score === 'number' ? -score : 9999
}

function getDefaultRowSort(a: SectorSnapshotRow, b: SectorSnapshotRow): number {
  const signalDiff = getSignalPriority(a.signal_type) - getSignalPriority(b.signal_type)
  if (signalDiff !== 0) return signalDiff

  const b1Diff = getB1PassPriority(a.b1_passed) - getB1PassPriority(b.b1_passed)
  if (b1Diff !== 0) return b1Diff

  const verdictDiff = verdictRank(a.verdict) - verdictRank(b.verdict)
  if (verdictDiff !== 0) return verdictDiff

  const scoreDiff = getScoreSortValue(a.total_score) - getScoreSortValue(b.total_score)
  if (scoreDiff !== 0) return scoreDiff

  const rankA = typeof a.active_pool_rank === 'number' ? a.active_pool_rank : Number.MAX_SAFE_INTEGER
  const rankB = typeof b.active_pool_rank === 'number' ? b.active_pool_rank : Number.MAX_SAFE_INTEGER
  if (rankA !== rankB) return rankA - rankB

  return a.code.localeCompare(b.code)
}

function getRowSortableValue(row: SectorSnapshotRow, prop: SectorSortProp): number | string | boolean | null {
  if (prop === 'code') return row.code
  if (prop === 'name') return row.name || ''
  if (prop === 'b1_passed') return row.b1_passed ?? null
  if (prop === 'signal_type') return row.signal_type ? getSignalPriority(row.signal_type) : null
  if (prop === 'total_score') return toFiniteNumber(row.total_score)
  if (prop === 'active_pool_rank') {
    const rank = toFiniteNumber(row.active_pool_rank)
    return rank === null ? null : -rank
  }
  return toFiniteNumber(row[prop] as number | string | null | undefined)
}

function compareNullableValues(
  aValue: number | string | boolean | null,
  bValue: number | string | boolean | null,
  order: Exclude<SortOrder, null>,
): number {
  const direction = order === 'ascending' ? 1 : -1
  const aMissing = aValue === null || aValue === ''
  const bMissing = bValue === null || bValue === ''
  if (aMissing || bMissing) {
    if (aMissing && bMissing) return 0
    return aMissing ? 1 : -1
  }

  if (typeof aValue === 'string' || typeof bValue === 'string') {
    return String(aValue).localeCompare(String(bValue), 'zh-Hans-CN') * direction
  }

  if (typeof aValue === 'boolean' || typeof bValue === 'boolean') {
    const diff = (aValue === true ? 1 : 0) - (bValue === true ? 1 : 0)
    return diff * direction
  }

  return (Number(aValue) - Number(bValue)) * direction
}

function sortSectorRows(rows: SectorSnapshotRow[]): SectorSnapshotRow[] {
  const state = sectorCandidateSort.value
  return [...rows].sort((a, b) => {
    if (!state.prop || !state.order) {
      return getDefaultRowSort(a, b)
    }
    const diff = compareNullableValues(
      getRowSortableValue(a, state.prop),
      getRowSortableValue(b, state.prop),
      state.order,
    )
    return diff !== 0 ? diff : getDefaultRowSort(a, b)
  })
}

const selectedSectorCurrentRows = computed(() => {
  return sortSectorRows(selectedDateRows.value)
})

const sectorCandidatePageCount = computed(() => Math.max(1, Math.ceil(selectedSectorCurrentRows.value.length / candidatePageSize)))
const displaySectorCandidateRows = computed(() => {
  if (sectorCandidatePage.value > sectorCandidatePageCount.value) {
    sectorCandidatePage.value = sectorCandidatePageCount.value
  }
  const start = (sectorCandidatePage.value - 1) * candidatePageSize
  return selectedSectorCurrentRows.value.slice(start, start + candidatePageSize)
})

const overviewSeries = computed<OverviewSeriesItem[]>(() => {
  const history = sectorAnalysis.value?.history || []
  const preferredKeys = sectorAnalysis.value?.top_sector_keys || sectorSummaries.value.slice(0, 5).map((item) => item.sector_key)
  return preferredKeys
    .map((sectorKey) => history.find((item) => item.sector_key === sectorKey))
    .filter((item): item is OverviewSeriesItem => Boolean(item && item.points.length > 0))
})

const topSectorName = computed(() => sectorSummaries.value[0]?.sector_name || '-')
const totalTrendStartCount = computed(() => sectorSummaries.value.reduce((sum, item) => sum + item.trend_start_count, 0))
const totalPassCount = computed(() => sectorSummaries.value.reduce((sum, item) => sum + item.pass_count, 0))
const totalNegativeCount = computed(() => sectorSummaries.value.reduce((sum, item) => sum + item.negative_flag_count, 0))

const candidateSortLabel = computed(() => {
  const state = sectorCandidateSort.value
  if (!state.prop || !state.order) return ''
  const labels: Record<SectorSortProp, string> = {
    code: '代码',
    name: '名称',
    open_price: '开盘',
    close_price: '收盘',
    change_pct: '涨跌',
    turnover_rate: '换手',
    volume_ratio: '量比',
    active_pool_rank: '活跃排名',
    b1_passed: 'B1',
    signal_type: '信号',
    total_score: '评分',
  }
  const direction = state.order === 'ascending' ? '从低到高' : '从高到低'
  return `${labels[state.prop]} ${direction}`
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

function buildOverviewRotationOption(series: OverviewSeriesItem[]): EChartsCoreOption {
  const dates = sectorAnalysis.value?.dates || []
  return {
    animationDuration: 400,
    color: CHART_COLORS,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line' },
      formatter: (params: any) => {
        const list = Array.isArray(params) ? params : [params]
        const date = list[0]?.axisValue || '-'
        const lines = [`<b>${date}</b>`]
        for (const item of list) {
          const rawData = item?.data
          const point = rawData && typeof rawData === 'object'
            ? rawData as { value?: number; rank?: number }
            : { value: rawData as number | undefined }
          lines.push(`${item.marker || ''}${item.seriesName}: ${typeof point.value === 'number' ? point.value.toFixed(2) : '-'} / 排名 ${point.rank || '-'}`)
        }
        return lines.join('<br/>')
      },
    },
    legend: {
      top: 8,
      data: series.map((item) => item.sector_name),
    },
    grid: {
      left: 56,
      right: 24,
      top: 56,
      bottom: 40,
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLabel: {
        color: '#64748b',
        formatter: (value: string) => value.slice(5),
      },
      axisLine: {
        lineStyle: { color: '#cbd5e1' },
      },
    },
    yAxis: {
      type: 'value',
      name: '强度分',
      axisLabel: {
        color: '#64748b',
      },
      splitLine: {
        lineStyle: { color: '#e2e8f0' },
      },
    },
    series: series.map((item, index) => {
      const pointsByDate = new Map(item.points.map((point) => [point.date, point]))
      return {
        name: item.sector_name,
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: {
          width: index < 2 ? 3 : 2,
        },
        data: dates.map((date) => {
          const point = pointsByDate.get(date)
          return point
            ? {
                value: point.strength_score,
                rank: point.rank,
              }
            : null
        }),
      }
    }),
  }
}

async function renderOverviewChart() {
  if (!isOverview.value) {
    if (overviewChartInstance) {
      overviewChartInstance.dispose()
      overviewChartInstance = null
    }
    return
  }
  if (!overviewChartRef.value || overviewSeries.value.length === 0) {
    overviewChartInstance?.clear()
    return
  }

  const { initChart } = await loadKLineChartRuntime()
  if (overviewChartInstance && overviewChartInstance.getDom() !== overviewChartRef.value) {
    overviewChartInstance.dispose()
    overviewChartInstance = null
  }
  if (!overviewChartInstance) {
    overviewChartInstance = initChart(overviewChartRef.value)
  }
  overviewChartInstance.setOption(buildOverviewRotationOption(overviewSeries.value), true)
  overviewChartInstance.resize()
}

function disposeCharts() {
  if (overviewChartInstance) {
    overviewChartInstance.dispose()
    overviewChartInstance = null
  }
}

function handleWindowResize() {
  overviewChartInstance?.resize()
}

function isSectorAnalysisRoutePath(path: string): boolean {
  return path === SECTOR_ANALYSIS_ROOT_PATH || path.startsWith(`${SECTOR_ANALYSIS_ROOT_PATH}/`)
}

function bindWindowResize() {
  if (resizeListenerBound) return
  window.addEventListener('resize', handleWindowResize)
  resizeListenerBound = true
}

function unbindWindowResize() {
  if (!resizeListenerBound) return
  window.removeEventListener('resize', handleWindowResize)
  resizeListenerBound = false
}

function viewStock(code: string) {
  router.push({ path: '/diagnosis', query: { code, source: 'current-hot', days: '30' } })
}

function getPullbackQualityLabel(value?: string | null): string {
  switch (value) {
    case 'contracting':
      return '缩量回调'
    case 'neutral':
      return '中性回调'
    case 'abnormal_bear':
      return '异常阴量'
    case 'expanding_selloff':
      return '下跌上量'
    case 'insufficient_data':
      return '样本不足'
    case 'disabled':
      return '未启用'
    default:
      return typeof value === 'string' ? value : ''
  }
}

function getPullbackNegativeFlagLabel(value: string): string {
  switch (value) {
    case 'down_volume_increasing':
      return '下跌逐步上量'
    case 'abnormal_bear_bar':
      return '异常放量阴线'
    default:
      return value
  }
}

function getCandidateInlineNote(row: SectorSnapshotRow): string {
  const parts: string[] = []

  const pullbackQuality = getPullbackQualityLabel(row.pullback_quality)
  const pullbackFlags = (row.pullback_negative_flags || [])
    .map((item) => String(item || '').trim())
    .filter(Boolean)
    .map(getPullbackNegativeFlagLabel)

  if (pullbackQuality) {
    parts.push(`回调:${pullbackQuality}`)
  }
  if (pullbackFlags.length > 0) {
    parts.push(`负面:${pullbackFlags.join('/')}`)
  }

  const prefilterSummary = typeof row.prefilter_summary === 'string' ? row.prefilter_summary.trim() : ''
  if (row.prefilter_passed === false) {
    parts.push(prefilterSummary ? `前置:${prefilterSummary}` : '前置:未通过')
  }

  const comment = typeof row.comment === 'string' ? row.comment.trim() : ''
  if (comment) {
    parts.push(comment)
  }

  return parts.join('；') || '点击查看单股诊断'
}

function goToSector(sectorKey: string) {
  router.push(getSectorRoutePath(sectorKey))
}

function goToOverview() {
  router.push(getSectorRoutePath(sectorCatalog.value.defaultSectorKey || DEFAULT_SECTOR_ANALYSIS_CATALOG.defaultSectorKey))
}

async function loadSectorAnalytics() {
  sectorLoading.value = true
  try {
    sectorAnalysis.value = await apiAnalysis.getSectorAnalysisOverview(120, 5)
  } catch (error) {
    if (isRequestCanceled(error)) return
    sectorAnalysis.value = null
    ElMessage.error(error instanceof Error ? error.message : '板块强弱数据加载失败')
  } finally {
    sectorLoading.value = false
  }
}

async function loadSectorDateRows(date: string, force: boolean = false) {
  const normalizedDate = formatDateString(date)
  const sectorKey = selectedSector.value?.key || ''
  if (!normalizedDate || !sectorKey) return

  const cacheKey = buildSectorDateCacheKey(sectorKey, normalizedDate)
  if (!force && dateRowsCache.value.has(cacheKey)) {
    return
  }

  const signal = beginRequest('sector-date-rows')
  sectorRowsLoading.value = true
  try {
    const response = await apiAnalysis.getSectorAnalysisRows(sectorKey, normalizedDate, { signal })
    const nextCache = new Map(dateRowsCache.value)
    nextCache.set(cacheKey, response.rows || [])
    dateRowsCache.value = nextCache
  } catch (error) {
    if (isRequestCanceled(error)) return
    ElMessage.error(error instanceof Error ? error.message : '板块个股数据加载失败')
  } finally {
    finishRequest('sector-date-rows', signal)
    sectorRowsLoading.value = false
  }
}

async function refreshSelectedSectorDateRows() {
  const targetDate = selectedSectorDate.value || selectedSectorLatestDate.value
  if (!targetDate) return
  await loadSectorDateRows(targetDate, true)
}

async function selectSectorDate(row: SectorHistoryRow) {
  selectedSectorDate.value = row.rawDate
  sectorCandidatePage.value = 1
  await loadSectorDateRows(row.rawDate)
}

function handleCandidateSortChange({ prop, order }: { prop: string; order: SortOrder }) {
  sectorCandidateSort.value = {
    prop: (prop || '') as SectorSortProp | '',
    order,
  }
  sectorCandidatePage.value = 1
}

watch(
  [() => route.path, () => route.params.sectorKey],
  ([path, value]) => {
    if (!isSectorAnalysisRoutePath(path)) {
      return
    }
    const current = String(value ?? '').trim()
    const validKeys = new Set(sectorMenuEntries.value.map((item) => item.key))
    if (!current) {
      router.replace(getSectorRoutePath(sectorCatalog.value.defaultSectorKey))
      return
    }
    if (!validKeys.has(current)) {
      router.replace(getSectorRoutePath(sectorCatalog.value.defaultSectorKey))
    }
  },
  { immediate: true },
)

watch(
  [() => selectedSector.value?.key, () => sectorHistoryRows.value.map((item) => item.rawDate).join('|')],
  async () => {
    sectorHistoryPage.value = 1
    sectorCandidatePage.value = 1

    if (!selectedSector.value) {
      selectedSectorDate.value = null
      return
    }

    const availableDates = sectorHistoryRows.value.map((item) => item.rawDate)
    const nextDate = availableDates.includes(selectedSectorDate.value || '')
      ? selectedSectorDate.value
      : (availableDates[0] || null)

    selectedSectorDate.value = nextDate
    if (nextDate) {
      await loadSectorDateRows(nextDate)
    }
  },
  { immediate: true },
)

watch(
  [() => isOverview.value, () => overviewSeries.value.map((item) => item.sector_key).join('|'), () => sectorAnalysis.value?.dates.join('|') || ''],
  async () => {
    await nextTick()
    await renderOverviewChart()
  },
)

watch(() => configStore.dataInitialized, async (ready, previous) => {
  if (ready && !previous) {
    await loadSectorAnalytics()
  }
})

onMounted(async () => {
  bindWindowResize()

  await Promise.allSettled([
    configStore.loadConfigs(),
    configStore.checkTushareStatus(),
  ])

  if (configStore.dataInitialized) {
    await loadSectorAnalytics()
    await nextTick()
    await renderOverviewChart()
  }
})

onActivated(async () => {
  bindWindowResize()
  if (configStore.dataInitialized) {
    await nextTick()
    await renderOverviewChart()
  }
})

onDeactivated(() => {
  cancelAllPageRequests()
  disposeCharts()
  unbindWindowResize()
})

onBeforeUnmount(() => {
  cancelAllPageRequests()
  disposeCharts()
  unbindWindowResize()
})
</script>

<style scoped lang="scss">
.sector-analysis-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-alert {
  border-radius: 16px;
}

.page-empty {
  padding: 32px 0;
}

.overview-card,
.panel-card,
.sector-info-card {
  border-radius: 18px;
}

.overview-card {
  border: 1px solid #dbeafe;
  background: linear-gradient(135deg, #f8fbff 0%, #eef6ff 100%);
}

.overview-card__header,
.panel-card__header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.overview-card__header {
  h2 {
    margin: 4px 0 10px;
    font-size: 24px;
    color: #0f172a;
  }

  p {
    margin: 0;
    color: #475569;
    line-height: 1.7;
  }
}

.overview-card__eyebrow {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: #0f766e;
  text-transform: uppercase;
}

.overview-card__meta,
.header-actions,
.leader-tags,
.sector-card__tags,
.sector-card__meta,
.sector-info-card__tags,
.mobile-analysis-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.overview-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-top: 20px;
}

.summary-pill {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid #e2e8f0;

  strong {
    font-size: 22px;
    color: #0f172a;
  }
}

.summary-pill__label {
  font-size: 12px;
  color: #64748b;
}

.chart-panel {
  min-height: 360px;
}

.rotation-chart {
  width: 100%;
  height: 360px;
}

.sector-link {
  border: 0;
  background: transparent;
  padding: 0;
  color: #0f766e;
  font-weight: 600;
  cursor: pointer;
}

.sector-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
}

.sector-card {
  display: flex;
  flex-direction: column;
  gap: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 18px;
  background: #fff;
  padding: 18px;
  text-align: left;
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;

  &:hover {
    transform: translateY(-2px);
    border-color: #7dd3fc;
    box-shadow: 0 14px 30px rgba(15, 23, 42, 0.08);
  }
}

.sector-card__top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.sector-card__title {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

.sector-card__description {
  margin-top: 8px;
  color: #475569;
  line-height: 1.7;
}

.sector-card__stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  color: #334155;
  font-size: 13px;
}

.sector-info-card__description {
  color: #475569;
  line-height: 1.8;
}

.sector-info-card__tags {
  margin-top: 12px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.title-section {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-weight: 600;
  color: #111827;
}

.top-grid {
  display: grid;
  grid-template-columns: clamp(360px, 22vw, 420px) minmax(0, 1fr);
  gap: 16px;
  align-items: stretch;
  min-height: calc(100vh - 174px);
}

.history-column,
.content-column {
  min-width: 0;
  display: flex;
}

.mobile-layout {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.mobile-history-list,
.mobile-analysis-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mobile-history-item,
.mobile-analysis-item {
  width: 100%;
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.mobile-history-item.active {
  border-color: #409eff;
  box-shadow: 0 0 0 1px rgba(64, 158, 255, 0.12);
  background: #f7fbff;
}

.mobile-history-item__header,
.mobile-analysis-item__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.mobile-history-item__date,
.mobile-analysis-item__code {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
}

.mobile-history-item__status {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 4px;
}

.mobile-history-item__meta,
.mobile-analysis-item__meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 10px;
  font-size: 13px;
  color: #606266;
}

.mobile-analysis-item__name {
  margin-top: 4px;
  font-size: 13px;
  color: #606266;
}

.mobile-analysis-item__comment {
  line-height: 1.5;
  color: #374151;
  word-break: break-word;
}

.mobile-analysis-prices {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.mobile-pagination {
  flex-direction: column;
  align-items: center;
  gap: 8px;
  justify-content: center;

  .mobile-pagination__summary {
    font-size: 12px;
    color: #64748b;
    line-height: 1;
  }
}

.table-header-tip {
  margin-bottom: 8px;
  padding: 8px 8px;
  background-color: #f5f7fa;
  border-radius: 4px;
  font-size: 12px;
  color: #606266;
  line-height: 1.6;

  .tip-item {
    margin-right: 12px;

    &:last-child {
      margin-right: 0;
    }
  }
}

.sort-hint {
  margin-bottom: 8px;
  font-size: 12px;
  color: #64748b;
}

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
  height: 100%;

  :deep(.el-card__body) {
    overflow: hidden;
  }

  .history-table {
    flex: 1 1 auto;
    font-size: 12px;

    :deep(.el-table__row) {
      cursor: pointer;

      &:hover {
        background-color: #f0f9ff;
      }
    }

    :deep(.el-table__cell) {
      padding: 5px 0;
    }

    :deep(.cell) {
      padding: 0 10px;
    }
  }

  .pagination-wrap {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-top: 8px;
    flex-shrink: 0;
    min-height: 32px;
    overflow: hidden;
  }

  .pagination-total {
    flex: 0 0 auto;
    font-size: 12px;
    color: #64748b;
    white-space: nowrap;
  }

  :deep(.el-pagination) {
    min-width: 0;
    justify-content: flex-end;
    overflow: hidden;
  }

  :deep(.el-pager) {
    max-width: 212px;
    overflow: hidden;
  }
}

.candidates-card {
  :deep(.el-card__body) {
    overflow: hidden;
  }

  .candidates-table {
    flex: 1 1 auto;
    min-height: 200px;
    width: 100%;
    font-size: 12px;

    :deep(.cell) {
      white-space: nowrap;
      padding: 0 5px;
    }

    :deep(.el-table__cell) {
      padding: 5px 0;
    }

    :deep(.el-table-fixed-column--right::before),
    :deep(.el-table-fixed-column--right::after) {
      display: none;
    }
  }

  .pagination-wrap {
    display: flex;
    justify-content: flex-end;
    margin-top: 8px;
    flex-shrink: 0;
    min-height: 32px;
  }
}

.stock-name-cell {
  display: inline-block;
  max-width: 4em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.text-up {
  color: #dc2626;
}

.text-down {
  color: #16a34a;
}

.el-tag,
.el-button {
  border-radius: 4px;
}

@media (max-width: 768px) {
  .overview-card__header,
  .panel-card__header,
  .card-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .overview-card__meta,
  .header-actions {
    justify-content: flex-start;
  }

  .sector-card__stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .rotation-chart {
    height: 320px;
  }

  .table-header-tip {
    .tip-item {
      display: block;
      margin-right: 0;
    }
  }

  .matched-height,
  .history-card,
  .candidates-card {
    height: auto;
    min-height: 0;

    :deep(.el-card__body) {
      overflow: visible;
    }
  }
}
</style>
