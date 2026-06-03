<template>
  <div class="value-lowland-page">
    <el-tabs v-model="activeView" class="top-tabs">
      <el-tab-pane label="筛选结果" name="results" />
      <el-tab-pane label="工作逻辑" name="logic" />
    </el-tabs>

    <template v-if="activeView === 'results'">
    <section class="lowland-toolbar">
      <div class="toolbar-main">
        <div class="toolbar-title">价值洼地筛选器</div>
        <div class="toolbar-meta">
          <span>{{ response?.trade_date || '-' }} 交易日</span>
          <span>{{ filteredItems.length }} 只候选</span>
          <span>AI画像 {{ response?.enriched_count || 0 }} 只</span>
          <span>后台任务 {{ refreshStatusLabel }}</span>
          <span v-if="response?.generated_at">更新 {{ formatDateTime(response.generated_at) }}</span>
        </div>
      </div>
      <div class="toolbar-actions">
        <el-button :icon="Refresh" :loading="refreshingBatch" type="primary" @click="startBackendRefresh">
          后台刷新
        </el-button>
        <el-button :loading="loading" @click="loadData">
          读取结果
        </el-button>
      </div>
    </section>

    <el-alert
      v-if="errorMessage"
      class="page-alert"
      type="warning"
      show-icon
      :closable="false"
      title="价值洼地筛选暂不可用"
      :description="errorMessage"
    />
    <el-alert
      v-else-if="response?.message"
      class="page-alert"
      type="info"
      show-icon
      :closable="false"
      :title="response.message"
    />

    <section class="metric-strip">
      <div class="metric-item">
        <span>鳄鱼严选</span>
        <strong>{{ filteredItems.length }}</strong>
      </div>
    </section>

    <section v-if="sectorOptions.length > 0" class="sector-filter-panel" aria-label="板块过滤">
      <div class="sector-filter-header">
        <span>所属板块</span>
        <el-button size="small" text @click="clearSectorFilters">全部 {{ strictItems.length }}</el-button>
      </div>
      <el-checkbox-group v-model="selectedSectors" class="sector-filter-options">
        <el-checkbox-button
          v-for="option in pagedSectorOptions"
          :key="option.name"
          :label="option.name"
        >
          {{ option.name }} {{ option.count }}
        </el-checkbox-button>
      </el-checkbox-group>
      <div v-if="sectorOptions.length > sectorPageSize" class="sector-pagination">
        <span>共 {{ sectorOptions.length }} 个板块</span>
        <el-pagination
          v-model:current-page="sectorPage"
          small
          background
          layout="prev, pager, next"
          :page-size="sectorPageSize"
          :total="sectorOptions.length"
        />
      </div>
    </section>

    <section class="lowland-layout">
      <main class="ranking-panel">
        <div v-if="loading && filteredItems.length === 0" class="loading-box">
          <el-skeleton :rows="8" animated />
        </div>
        <el-empty v-else-if="filteredItems.length === 0" description="暂无候选" :image-size="90" />
        <el-table
          v-else
          :data="filteredItems"
          class="lowland-table"
          row-key="code"
          height="calc(100vh - 370px)"
          @row-click="selectCandidate"
        >
          <el-table-column prop="rank" label="#" width="56" />
          <el-table-column prop="code" label="代码" width="86" sortable />
          <el-table-column prop="name" label="股票" min-width="110" sortable show-overflow-tooltip>
            <template #default="{ row }">
              <div class="stock-cell">
                <span class="stock-name">{{ row.name || row.code }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="industry" label="所属板块" min-width="118" sortable show-overflow-tooltip>
            <template #default="{ row }">
              {{ row.industry || '-' }}
            </template>
          </el-table-column>
          <el-table-column width="92" sortable prop="score">
            <template #header>
              <HeaderTip label="总分" tip="通过硬筛后的综合排序分，包含国资安全、低位低估、业绩改善、周期弹性、主营集中、稀缺资源和风险扣分。" />
            </template>
            <template #default="{ row }">
              <span class="score-text">{{ formatNumber(row.score, 1) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="low_position_ratio" width="86" sortable>
            <template #header>
              <HeaderTip label="位置" tip="当前收盘价在近两年最高价和最低价区间中的相对位置，越低越接近区间低位。" />
            </template>
            <template #default="{ row }">
              {{ formatPercent(row.low_position_ratio, 0) }}
            </template>
          </el-table-column>
          <el-table-column prop="pb" width="78" sortable>
            <template #header>
              <HeaderTip label="PB" tip="市净率，股价相对每股净资产的倍数；周期资源类公司通常用于辅助判断低估程度。" />
            </template>
            <template #default="{ row }">
              {{ formatNumber(row.pb, 2) }}
            </template>
          </el-table-column>
          <el-table-column width="92" sortable :sort-method="sortByMarketCap">
            <template #header>
              <HeaderTip label="市值" tip="优先使用总市值，缺失时使用流通市值；当前严选会排除市值缺失或大于 300 亿的股票。" />
            </template>
            <template #default="{ row }">
              {{ formatMarketCap(row.total_mv || row.circ_mv) }}
            </template>
          </el-table-column>
          <el-table-column prop="netprofit_yoy" width="86" sortable>
            <template #header>
              <HeaderTip label="净利" tip="最近一期净利润同比增速，用来判断业绩是否出现边际改善或爆发式增长。" />
            </template>
            <template #default="{ row }">
              {{ formatPercentValue(row.netprofit_yoy) }}
            </template>
          </el-table-column>
          <el-table-column prop="rev_yoy" width="86" sortable>
            <template #header>
              <HeaderTip label="营收" tip="最近一期营业收入同比增速；净利或营收至少一项同比不为负才进入鳄鱼严选。" />
            </template>
            <template #default="{ row }">
              {{ formatPercentValue(row.rev_yoy) }}
            </template>
          </el-table-column>
          <el-table-column prop="roe" width="84" sortable>
            <template #header>
              <HeaderTip label="ROE" tip="净资产收益率，反映公司用股东权益创造利润的能力；这里只作为业绩质量辅助指标。" />
            </template>
            <template #default="{ row }">
              {{ formatPercentValue(row.roe) }}
            </template>
          </el-table-column>
          <el-table-column width="88" sortable :sort-method="sortByOwnership">
            <template #header>
              <HeaderTip label="权属" tip="公司画像识别的实际控制人层级；鳄鱼严选只展示央企和省国资。" />
            </template>
            <template #default="{ row }">
              <el-tag size="small" :type="ownershipTagType(row.profile.ownership_type)">
                {{ ownershipLabel(row.profile.ownership_type) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column width="78" sortable :sort-method="sortByCycle">
            <template #header>
              <HeaderTip label="周期" tip="公司画像识别的周期属性；鳄鱼严选只展示资源、化工、能源。" />
            </template>
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ cycleLabel(row.profile.cycle_type) }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </main>

      <aside class="detail-panel">
        <template v-if="selected">
          <div class="detail-header">
            <div>
              <div class="detail-title">{{ selected.name || selected.code }}</div>
              <div class="detail-subtitle">{{ selected.code }} · {{ selected.industry || '-' }}</div>
            </div>
            <el-button
              size="small"
              :loading="refreshingProfile"
              @click="refreshSelectedProfile"
            >
              刷新画像
            </el-button>
          </div>

          <div class="score-grid">
            <div v-for="item in scoreParts" :key="item.label" class="score-part">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
          </div>

          <div class="detail-section">
            <h4>公司画像</h4>
            <p>{{ selected.profile.main_business || '暂无 AI 主营画像。' }}</p>
            <div class="tag-line">
              <el-tag v-for="asset in selected.profile.unique_assets" :key="asset" size="small" effect="plain">{{ asset }}</el-tag>
            </div>
          </div>

          <div class="detail-section">
            <h4>风险与复核</h4>
            <ul>
              <li v-for="note in selected.risk_notes" :key="note">{{ note }}</li>
            </ul>
          </div>

        </template>
        <el-empty v-else description="选择一只候选查看证据" :image-size="90" />
      </aside>
    </section>
    </template>

    <section v-else class="logic-page">
      <div class="logic-header">
        <div>
          <h2>价值洼地筛选器工作逻辑</h2>
          <p>该筛选器按《寒武纪的鳄鱼-知乎合集》里的“筛子”思想实现：先排除明显不能买的，再找相对低位、低估、业绩改善和具备周期弹性的候选。</p>
        </div>
      </div>

      <div class="logic-grid">
        <article class="logic-block">
          <h3>PDF 核心规则</h3>
          <ul>
            <li>只重点看国务院国资委控股央企或省国资委控股国企，民企原则上不作为核心标的。</li>
            <li>不买 ST、退市风险、业绩连续下降或亏损风险明显的股票。</li>
            <li>买在低价低位，最好经历两年以上盘整，避免已经上涨两三倍的高位股。</li>
            <li>市值尽量小于 200 亿，越小越有周期弹性。</li>
            <li>主营集中、业务简单、产品或资源有稀缺性和不可替代性。</li>
            <li>业绩需要出现边际改善，最好能看到爆发式增长或周期价格驱动。</li>
          </ul>
        </article>

        <article class="logic-block">
          <h3>当前实现</h3>
          <ul>
            <li>Tushare 拉取本地日线、最新估值、财务指标，先排除 ST/退市名称。</li>
            <li>鳄鱼严选只保留画像确认的央企或省国资，民企、未知权属、市县级地方国资不展示。</li>
            <li>只保留画像周期类型为资源、化工、能源的股票，军工、公用事业和其他类型不展示。</li>
            <li>市值缺失或大于 300 亿直接排除；大于 200 亿仍会扣分，小于 200 亿优先。</li>
            <li>用两年高低点计算区间位置，只保留区间位置不高于 70% 的低位票，并排除近两年从低点翻倍的股票。</li>
            <li>用净利润同比和营收同比判断业绩边际改善，净利润或营收至少有一项同比不为负才进入严选。</li>
            <li>先用公告、年报、搜索结果和维基类公开资料做权属规则预判，能确认央企/省国资/民企时直接写入画像缓存。</li>
            <li>页面只展示鳄鱼严选；其他画像、证据和风险备注仍写入数据库并保留在个股详情里供复核。</li>
          </ul>
        </article>

        <article class="logic-block">
          <h3>评分模型</h3>
          <div class="score-model">
            <span>国资安全：0-20</span>
            <span>低位低估：0-25</span>
            <span>业绩改善：0-20</span>
            <span>周期弹性：0-15</span>
            <span>主营集中：0-10</span>
            <span>稀缺资源：0-10</span>
            <span>风险扣分：-30-0</span>
          </div>
          <p>硬筛决定能否进入鳄鱼严选，总分只用于通过硬筛后的候选排序。高分候选仍必须人工复核公告、股权穿透、周期价格和财务真实性。</p>
        </article>

        <article class="logic-block">
          <h3>边界和复核</h3>
          <ul>
            <li>AI 只能基于搜索引擎/Tushare 返回的证据判断，证据 URL 会保留在个股详情里供复核。</li>
            <li>“央企/省国资/地方国资”的判断依赖公开证据，复杂股权穿透仍需人工确认。</li>
            <li>当前没有直接接入商品价格、产能成本和三到五年利润测算，因此不能替代深度行业估值。</li>
            <li>PDF 作者强调集中持仓和长期等待，本页面只做候选池，不处理仓位、融资、买卖点。</li>
          </ul>
        </article>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, onUnmounted, provide, ref, watch } from 'vue'
import { ElMessage, ElTooltip } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { apiValueLowland } from '@/api'
import type { ValueLowlandCandidate, ValueLowlandResponse, ValueLowlandRunStatus } from '@/types'

const HeaderTip = defineComponent({
  props: {
    label: { type: String, required: true },
    tip: { type: String, required: true },
  },
  setup(props) {
    return () => h(
      ElTooltip,
      {
        content: props.tip,
        placement: 'top',
        effect: 'dark',
        popperClass: 'lowland-header-tip-popper',
      },
      {
        default: () => h('span', { class: 'header-tip' }, [
          h('span', props.label),
          h('span', { class: 'header-tip__icon' }, '?'),
        ]),
      },
    )
  },
})

const response = ref<ValueLowlandResponse | null>(null)
const selected = ref<ValueLowlandCandidate | null>(null)
const activeView = ref<'results' | 'logic'>('results')
const selectedSectors = ref<string[]>([])
const sectorPage = ref(1)
const sectorPageSize = 12
const loading = ref(false)
const refreshingBatch = ref(false)
const refreshingProfile = ref(false)
const errorMessage = ref('')
const runStatus = ref<ValueLowlandRunStatus | null>(null)
let statusTimer: number | null = null

const strictItems = computed(() => response.value?.soe_lowland || response.value?.total_rank || [])
const sectorOptions = computed(() => {
  const counts = new Map<string, number>()
  strictItems.value.forEach((item) => {
    const sectorName = getSectorName(item)
    counts.set(sectorName, (counts.get(sectorName) || 0) + 1)
  })
  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => (b.count - a.count) || a.name.localeCompare(b.name, 'zh-Hans-CN'))
})
const pagedSectorOptions = computed(() => {
  const start = (sectorPage.value - 1) * sectorPageSize
  return sectorOptions.value.slice(start, start + sectorPageSize)
})
const filteredItems = computed(() => {
  const selected = new Set(selectedSectors.value)
  if (selected.size === 0) return strictItems.value
  return strictItems.value.filter((item) => selected.has(getSectorName(item)))
})
const refreshStatusLabel = computed(() => {
  const status = runStatus.value?.status || 'idle'
  const labels: Record<string, string> = {
    idle: '空闲',
    pending: '等待中',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
  }
  return labels[status] || status
})
const scoreParts = computed(() => {
  const score = selected.value?.score_breakdown
  if (!score) return []
  return [
    { label: '国资安全', value: formatNumber(score.ownership_score, 1) },
    { label: '低位低估', value: formatNumber(score.low_valuation_score, 1) },
    { label: '业绩改善', value: formatNumber(score.financial_improvement_score, 1) },
    { label: '周期弹性', value: formatNumber(score.cycle_elasticity_score, 1) },
    { label: '主营集中', value: formatNumber(score.business_focus_score, 1) },
    { label: '稀缺资源', value: formatNumber(score.scarcity_score, 1) },
    { label: '风险扣分', value: formatNumber(score.risk_penalty, 1) },
  ]
})

async function loadData() {
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await apiValueLowland.screen({
      limit: 0,
    })
    response.value = result
    selected.value = filteredItems.value[0] || null
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '请求失败'
  } finally {
    loading.value = false
  }
}

async function startBackendRefresh() {
  refreshingBatch.value = true
  errorMessage.value = ''
  try {
    runStatus.value = await apiValueLowland.refresh({
      limit: 0,
      enrich: true,
      force_refresh: false,
    })
    ElMessage.success('后台刷新已启动，完成后会自动读取最新结果')
    startStatusPolling()
  } catch (error) {
    ElMessage.warning(error instanceof Error ? error.message : '后台刷新启动失败')
  } finally {
    refreshingBatch.value = false
  }
}

function startStatusPolling() {
  stopStatusPolling()
  statusTimer = window.setInterval(async () => {
    try {
      runStatus.value = await apiValueLowland.refreshStatus()
      if (!['pending', 'running'].includes(runStatus.value.status)) {
        stopStatusPolling()
        if (runStatus.value.status === 'completed') {
          await loadData()
        } else if (runStatus.value.status === 'failed') {
          ElMessage.warning(runStatus.value.error_message || '价值洼地后台刷新失败')
        }
      }
    } catch {
      stopStatusPolling()
    }
  }, 5000)
}

function stopStatusPolling() {
  if (statusTimer != null) {
    window.clearInterval(statusTimer)
    statusTimer = null
  }
}

async function refreshSelectedProfile() {
  if (!selected.value) return
  refreshingProfile.value = true
  try {
    const profile = await apiValueLowland.refreshProfile(selected.value.code, {
      name: selected.value.name || selected.value.code,
      industry: selected.value.industry,
    })
    selected.value.profile = profile
    ElMessage.success('画像已刷新，重新筛选后会更新综合分')
  } catch (error) {
    ElMessage.warning(error instanceof Error ? error.message : '画像刷新失败')
  } finally {
    refreshingProfile.value = false
  }
}

function selectCandidate(row: ValueLowlandCandidate) {
  selected.value = row
}

function clearSectorFilters() {
  selectedSectors.value = []
}

watch(filteredItems, (items) => {
  if (!selected.value || !items.some((item) => item.code === selected.value?.code)) {
    selected.value = items[0] || null
  }
})

watch(sectorOptions, (options) => {
  const maxPage = Math.max(1, Math.ceil(options.length / sectorPageSize))
  if (sectorPage.value > maxPage) {
    sectorPage.value = maxPage
  }
})

onMounted(() => {
  void loadData()
  apiValueLowland.refreshStatus()
    .then((status) => {
      runStatus.value = status
      if (['pending', 'running'].includes(status.status)) {
        startStatusPolling()
      }
    })
    .catch(() => {})
})

onUnmounted(() => {
  stopStatusPolling()
})

provide('pageRefresh', loadData)

function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function formatNumber(value?: number | null, digits = 2): string {
  if (value == null || Number.isNaN(Number(value))) return '-'
  return Number(value).toFixed(digits)
}

function formatPercent(value?: number | null, digits = 0): string {
  if (value == null) return '-'
  return `${(value * 100).toFixed(digits)}%`
}

function formatPercentValue(value?: number | null): string {
  if (value == null) return '-'
  return `${Number(value).toFixed(1)}%`
}

function formatMarketCap(value?: number | null): string {
  if (value == null) return '-'
  return `${(value / 10000).toFixed(1)}亿`
}

function getSectorName(row: ValueLowlandCandidate): string {
  return row.industry?.trim() || '未分类'
}

function toSortableNumber(value?: number | null): number {
  if (value == null || Number.isNaN(Number(value))) return Number.NEGATIVE_INFINITY
  return Number(value)
}

function compareNumbers(a?: number | null, b?: number | null): number {
  return toSortableNumber(a) - toSortableNumber(b)
}

function sortByMarketCap(a: ValueLowlandCandidate, b: ValueLowlandCandidate): number {
  return compareNumbers(a.total_mv || a.circ_mv, b.total_mv || b.circ_mv)
}

function sortByOwnership(a: ValueLowlandCandidate, b: ValueLowlandCandidate): number {
  return ownershipLabel(a.profile.ownership_type).localeCompare(ownershipLabel(b.profile.ownership_type), 'zh-Hans-CN')
}

function sortByCycle(a: ValueLowlandCandidate, b: ValueLowlandCandidate): number {
  return cycleLabel(a.profile.cycle_type).localeCompare(cycleLabel(b.profile.cycle_type), 'zh-Hans-CN')
}

function ownershipLabel(value: string): string {
  const labels: Record<string, string> = {
    central_soe: '央企',
    provincial_soe: '省国资',
    local_soe: '地方国资',
    private: '民企',
    unknown: '未知',
  }
  return labels[value] || value
}

function ownershipTagType(value: string): 'success' | 'warning' | 'info' {
  if (['central_soe', 'provincial_soe', 'local_soe'].includes(value)) return 'success'
  if (value === 'unknown') return 'warning'
  return 'info'
}

function cycleLabel(value: string): string {
  const labels: Record<string, string> = {
    resource: '资源',
    chemical: '化工',
    military: '军工',
    energy: '能源',
    utility: '公用',
    other: '其他',
  }
  return labels[value] || value
}
</script>

<style scoped>
.value-lowland-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
}

.lowland-toolbar,
.metric-strip,
.lowland-layout {
  width: 100%;
}

.lowland-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  padding: 14px 16px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.toolbar-title {
  font-size: 18px;
  font-weight: 700;
  color: #111827;
}

.toolbar-meta,
.toolbar-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.toolbar-meta {
  margin-top: 6px;
  color: #6b7280;
  font-size: 12px;
}

.page-alert {
  margin: 0;
}

.metric-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
}

.metric-item {
  padding: 12px 14px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.metric-item span {
  display: block;
  color: #6b7280;
  font-size: 12px;
}

.metric-item strong {
  display: block;
  margin-top: 4px;
  color: #111827;
  font-size: 22px;
}

.sector-filter-panel {
  padding: 12px 14px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.sector-filter-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-bottom: 10px;
  color: #374151;
  font-size: 13px;
  font-weight: 600;
}

.sector-filter-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.sector-filter-options :deep(.el-checkbox-button__inner) {
  border: 1px solid #d1d5db;
  border-radius: 6px;
  box-shadow: none;
  font-size: 12px;
}

.sector-filter-options :deep(.el-checkbox-button.is-checked .el-checkbox-button__inner) {
  border-color: #2563eb;
}

.sector-pagination {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-top: 10px;
  color: #6b7280;
  font-size: 12px;
}

.sector-pagination :deep(.el-pagination) {
  --el-pagination-button-width: 26px;
  --el-pagination-button-height: 26px;
}

.lowland-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 14px;
  min-height: 0;
}

.ranking-panel,
.detail-panel {
  min-height: 0;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.ranking-panel {
  padding: 12px;
}

.detail-panel {
  padding: 16px;
  overflow: auto;
}

.loading-box {
  padding: 20px;
}

.stock-cell,
.compact-metrics,
.profile-cell,
.reason-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.stock-code,
.score-text {
  font-weight: 700;
  color: #111827;
}

.header-tip {
  display: inline-flex;
  gap: 4px;
  align-items: center;
  line-height: 1;
  cursor: help;
}

.header-tip__icon {
  display: inline-flex;
  justify-content: center;
  align-items: center;
  width: 14px;
  height: 14px;
  border: 1px solid #9ca3af;
  border-radius: 50%;
  color: #6b7280;
  font-size: 10px;
  font-weight: 700;
}

.stock-name {
  color: #374151;
}

.stock-cell small,
.compact-metrics span,
.profile-cell small {
  color: #6b7280;
  font-size: 12px;
}

.reason-list span {
  color: #374151;
  font-size: 12px;
  line-height: 1.45;
}

.profile-cell > div {
  display: flex;
  gap: 6px;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 14px;
}

.detail-title {
  color: #111827;
  font-size: 18px;
  font-weight: 700;
}

.detail-subtitle {
  margin-top: 4px;
  color: #6b7280;
  font-size: 12px;
}

.score-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.score-part {
  padding: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #f9fafb;
}

.score-part span {
  display: block;
  color: #6b7280;
  font-size: 12px;
}

.score-part strong {
  margin-top: 3px;
  display: block;
  color: #111827;
}

.detail-section {
  margin-top: 18px;
}

.detail-section h4 {
  margin: 0 0 8px;
  color: #111827;
  font-size: 14px;
}

.detail-section p,
.detail-section li {
  color: #374151;
  font-size: 13px;
  line-height: 1.6;
}

.detail-section ul {
  margin: 0;
  padding-left: 18px;
}

.tag-line {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.top-tabs {
  padding: 0 2px;
}

.logic-page {
  padding: 18px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.logic-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.logic-header h2 {
  margin: 0;
  color: #111827;
  font-size: 20px;
}

.logic-header p {
  max-width: 920px;
  margin: 8px 0 0;
  color: #4b5563;
  font-size: 14px;
  line-height: 1.7;
}

.logic-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.logic-block {
  padding: 16px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #f9fafb;
}

.logic-block h3 {
  margin: 0 0 10px;
  color: #111827;
  font-size: 15px;
}

.logic-block p,
.logic-block li {
  color: #374151;
  font-size: 13px;
  line-height: 1.7;
}

.logic-block ul {
  margin: 0;
  padding-left: 18px;
}

.score-model {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}

.score-model span {
  padding: 8px 10px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  color: #374151;
  font-size: 13px;
}

@media (max-width: 1100px) {
  .lowland-toolbar,
  .lowland-layout {
    grid-template-columns: 1fr;
  }

  .lowland-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .metric-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .lowland-layout {
    display: flex;
    flex-direction: column;
  }

  .detail-panel {
    max-height: none;
  }

  .logic-grid {
    grid-template-columns: 1fr;
  }

  .score-model {
    grid-template-columns: 1fr;
  }
}
</style>
