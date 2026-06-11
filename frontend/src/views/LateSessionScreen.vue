<template>
  <div class="late-session-page">
    <div class="page-toolbar">
      <div class="toolbar-title">
        <h2>尾盘筛选</h2>
        <el-tag v-if="payload.trade_date" type="info" effect="plain">{{ payload.trade_date }}</el-tag>
        <el-tag v-if="payload.snapshot_time" type="success" effect="plain">
          {{ formatTime(payload.snapshot_time) }}
        </el-tag>
        <el-tag v-else type="warning" effect="plain">
          可生成
        </el-tag>
      </div>
      <div class="toolbar-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button>
        <el-button
          type="primary"
          :icon="Filter"
          :loading="generating"
          @click="generate(false)"
        >
          生成筛选
        </el-button>
        <el-button
          :loading="generating"
          @click="generate(true)"
        >
          强制刷新
        </el-button>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="late-session-tabs">
      <el-tab-pane label="筛选结果" name="results">
        <el-alert
          v-if="payload.message"
          class="page-alert"
          :type="payload.status === 'ok' ? 'success' : payload.status === 'empty' ? 'warning' : 'info'"
          :closable="false"
          show-icon
          :title="payload.message"
        />

        <div class="summary-strip">
          <div class="summary-item">
            <span>实时范围</span>
            <strong>{{ payload.total }}</strong>
          </div>
          <div class="summary-item">
            <span>硬过滤</span>
            <strong>{{ hardPassCount }}</strong>
          </div>
          <div class="summary-item">
            <span>最终标的</span>
            <strong>{{ payload.final_count }}</strong>
          </div>
          <div class="summary-item">
            <span>上证指数</span>
            <strong>{{ formatPercent(payload.market_overview?.benchmark_change_pct) }}</strong>
          </div>
        </div>

        <div v-if="payload.funnel.length" class="funnel-row">
          <div
            v-for="step in payload.funnel"
            :key="step.key"
            class="funnel-step"
          >
            <span>{{ step.label }}</span>
            <strong>{{ step.count }}</strong>
          </div>
        </div>

        <div class="table-shell">
          <div class="table-actions">
            <el-segmented
              v-model="resultFilter"
              :options="filterOptions"
              size="small"
            />
            <div class="table-actions__right">
              <el-button
                size="small"
                type="primary"
                :disabled="selectedCodes.length === 0"
                :loading="addingWatchlist"
                @click="addSelectedToWatchlist"
              >
                加入自选
              </el-button>
            </div>
          </div>

          <el-table
            v-loading="loading || generating"
            :data="filteredItems"
            row-key="code"
            class="result-table"
            @selection-change="handleSelectionChange"
          >
            <el-table-column type="selection" width="46" :selectable="rowSelectable" />
            <el-table-column label="股票" min-width="138" fixed>
              <template #default="{ row }">
                <button type="button" class="stock-link" @click="openDiagnosis(row.code)">
                  <span>{{ row.name || row.code }}</span>
                  <small>{{ row.code }}</small>
                </button>
              </template>
            </el-table-column>
            <el-table-column prop="change_pct" label="涨幅" width="86" sortable>
              <template #default="{ row }">{{ formatPercent(row.change_pct) }}</template>
            </el-table-column>
            <el-table-column prop="volume_ratio" label="量比" width="82" sortable>
              <template #default="{ row }">{{ formatNumber(row.volume_ratio, 2) }}</template>
            </el-table-column>
            <el-table-column prop="turnover_rate" label="换手" width="86" sortable>
              <template #default="{ row }">{{ formatPercent(row.turnover_rate) }}</template>
            </el-table-column>
            <el-table-column prop="circ_mv" label="流通市值" width="110" sortable>
              <template #default="{ row }">{{ formatMarketCap(row.circ_mv) }}</template>
            </el-table-column>
            <el-table-column prop="final_score" label="评分" width="86" sortable>
              <template #default="{ row }">
                <el-tag :type="row.final_pass ? 'success' : row.hard_pass ? 'warning' : 'info'" effect="plain">
                  {{ row.final_score == null ? '-' : formatNumber(row.final_score, 1) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column width="108">
              <template #header>
                <el-tooltip
                  content="成交量形态评分：偏好持续放量或台阶式放量，量能一高一低、不稳定会降分。"
                  placement="top"
                >
                  <span class="column-help">量能</span>
                </el-tooltip>
              </template>
              <template #default="{ row }">{{ patternLabel(row.volume_pattern) }}</template>
            </el-table-column>
            <el-table-column width="116">
              <template #header>
                <el-tooltip
                  content="均线形态评分：参考 5/10/20 日短期均线与 60 日均线，优先多头排列、价格站上关键均线的形态。"
                  placement="top"
                >
                  <span class="column-help">均线</span>
                </el-tooltip>
              </template>
              <template #default="{ row }">{{ patternLabel(row.ma_pattern) }}</template>
            </el-table-column>
            <el-table-column width="116">
              <template #header>
                <el-tooltip
                  content="分时强度评分：判断个股是否跑赢上证指数、14:30 后是否创当日新高、尾盘是否站在分时均价上方。"
                  placement="top"
                >
                  <span class="column-help">分时</span>
                </el-tooltip>
              </template>
              <template #default="{ row }">{{ patternLabel(row.intraday_pattern) }}</template>
            </el-table-column>
            <el-table-column label="题材" min-width="130">
              <template #default="{ row }">
                <div class="topic-list">
                  <el-tag
                    v-for="topic in row.hot_topics || []"
                    :key="topic"
                    size="small"
                    effect="plain"
                  >
                    {{ topic }}
                  </el-tag>
                  <span v-if="!row.hot_topics?.length">-</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="结论" min-width="150">
              <template #default="{ row }">
                <el-tag v-if="row.final_pass" type="success">通过</el-tag>
                <el-tag v-else-if="row.hard_pass" type="warning">待观察</el-tag>
                <el-tag v-else type="info">剔除</el-tag>
                <span v-if="row.reject_reason" class="reject-text">{{ row.reject_reason }}</span>
              </template>
            </el-table-column>
          </el-table>

          <el-empty v-if="!loading && !generating && filteredItems.length === 0" description="暂无筛选结果" />
        </div>
      </el-tab-pane>

      <el-tab-pane label="选股逻辑" name="logic">
        <div class="logic-panel">
          <section>
            <h3>数据口径</h3>
            <p>涨幅、量比、换手率、流通市值只使用生成时刻的实时行情字段；关键实时字段缺失时直接剔除，不使用近日或昨日数据回退。</p>
          </section>
          <section>
            <h3>硬过滤</h3>
            <ol>
              <li>策略建议 14:30 之后生成尾盘快照；系统允许随时生成或强制刷新，但 1 分钟内不可连续刷新。</li>
              <li>涨幅保留 3%-5%，低于 3% 视为当日强度不足，高于 5% 视为追高风险增加。</li>
              <li>量比必须大于等于 1，低于 1 表示成交活性不足。</li>
              <li>换手率保留 5%-10%，过低关注度不足，过高按短线过热处理。</li>
              <li>流通市值保留 50-200 亿，过滤过小冷门股和过大盘子。</li>
            </ol>
          </section>
          <section>
            <h3>评分过滤</h3>
            <ol>
              <li>成交量偏好持续放大或台阶式放量，量能一高一低会降分。</li>
              <li>K 线形态优先 5/10/20 日均线多头，且 60 日均线向上；价格在关键均线下方会降分。</li>
              <li>分时强度要求跑赢上证指数，14:30 后创当日新高、收在分时均价上方会加分。</li>
              <li>行业或题材命中会加分，但不作为硬过滤条件。</li>
            </ol>
          </section>
          <section>
            <h3>结果使用</h3>
            <p>最终标的是硬过滤通过且评分达标的股票；没有筛出结果属于正常状态，说明当日没有同时满足稳健尾盘条件的标的。</p>
          </section>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Filter, Refresh } from '@element-plus/icons-vue'
import { apiAnalysis, isRequestCanceled } from '@/api'
import type { LateSessionScreenItem, LateSessionScreenResponse } from '@/types'

const router = useRouter()

const loading = ref(false)
const generating = ref(false)
const addingWatchlist = ref(false)
const selectedCodes = ref<string[]>([])
const activeTab = ref<'results' | 'logic'>('results')
const resultFilter = ref<'final' | 'hard' | 'all'>('final')
const payload = ref<LateSessionScreenResponse>({
  has_data: false,
  funnel: [],
  items: [],
  total: 0,
  final_count: 0,
})

const filterOptions = [
  { label: '最终标的', value: 'final' },
  { label: '硬过滤', value: 'hard' },
  { label: '全部', value: 'all' },
]

const hardPassCount = computed(() => payload.value.items.filter(item => item.hard_pass).length)
const filteredItems = computed(() => {
  if (resultFilter.value === 'final') return payload.value.items.filter(item => item.final_pass)
  if (resultFilter.value === 'hard') return payload.value.items.filter(item => item.hard_pass)
  return payload.value.items
})

async function loadData() {
  loading.value = true
  try {
    payload.value = await apiAnalysis.getLateSessionData()
  } catch (error) {
    if (!isRequestCanceled(error)) {
      ElMessage.error(error instanceof Error ? error.message : '获取尾盘筛选失败')
    }
  } finally {
    loading.value = false
  }
}

async function generate(force: boolean) {
  generating.value = true
  try {
    payload.value = await apiAnalysis.generateLateSession(force)
    ElMessage.success(payload.value.final_count > 0 ? `筛选完成，得到 ${payload.value.final_count} 只标的` : '筛选完成，暂无最终标的')
  } catch (error) {
    if (!isRequestCanceled(error)) {
      ElMessage.error(error instanceof Error ? error.message : '生成尾盘筛选失败')
    }
  } finally {
    generating.value = false
  }
}

function handleSelectionChange(rows: LateSessionScreenItem[]) {
  selectedCodes.value = rows.map(row => row.code)
}

function rowSelectable(row: LateSessionScreenItem) {
  return row.final_pass
}

async function addSelectedToWatchlist() {
  if (selectedCodes.value.length === 0) return
  addingWatchlist.value = true
  try {
    const result = await apiAnalysis.addLateSessionWatchlist(selectedCodes.value)
    ElMessage.success(`已加入 ${result.added_count} 只，跳过 ${result.skipped_count} 只`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加入自选失败')
  } finally {
    addingWatchlist.value = false
  }
}

function openDiagnosis(code: string) {
  router.push({ path: '/diagnosis', query: { code, source: 'late-session', days: '30' } })
}

function formatNumber(value?: number | null, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return '-'
  return Number(value).toFixed(digits)
}

function formatPercent(value?: number | null) {
  if (value == null || Number.isNaN(Number(value))) return '-'
  return `${Number(value).toFixed(2)}%`
}

function formatMarketCap(value?: number | null) {
  if (value == null || Number.isNaN(Number(value))) return '-'
  return `${(Number(value) / 100000000).toFixed(1)}亿`
}

function formatTime(value: string) {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function patternLabel(value?: string | null) {
  const labels: Record<string, string> = {
    step_up: '台阶放量',
    expanding: '持续放量',
    unstable: '量能不稳',
    bullish_alignment: '多头发散',
    short_bullish: '短线多头',
    below_key_ma: '均线下方',
    neutral: '中性',
    strong_new_high: '尾盘新高',
    relative_strong: '强于指数',
    weak_intraday: '分时偏弱',
    unknown: '-',
  }
  return labels[value || 'unknown'] || value || '-'
}

onMounted(() => {
  loadData()
})
</script>

<style scoped lang="scss">
.late-session-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.toolbar-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;

  h2 {
    margin: 0;
    font-size: 22px;
    font-weight: 700;
    color: #111827;
  }
}

.toolbar-actions,
.table-actions,
.table-actions__right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-alert {
  margin: 0 0 16px;
}

.late-session-tabs {
  :deep(.el-tabs__header) {
    margin-bottom: 14px;
  }
}

.summary-strip,
.funnel-row {
  display: grid;
  gap: 10px;
}

.summary-strip {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.summary-item,
.funnel-step {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px 14px;
}

.summary-item span,
.funnel-step span {
  display: block;
  color: #6b7280;
  font-size: 13px;
}

.summary-item strong,
.funnel-step strong {
  display: block;
  margin-top: 4px;
  color: #111827;
  font-size: 22px;
}

.funnel-row {
  grid-template-columns: repeat(6, minmax(0, 1fr));
}

.table-shell {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px;
}

.logic-panel {
  display: grid;
  gap: 14px;
  max-width: 980px;

  section {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 14px 16px;
  }

  h3 {
    margin: 0 0 8px;
    color: #111827;
    font-size: 16px;
  }

  p,
  ol {
    margin: 0;
    color: #374151;
    line-height: 1.7;
  }

  ol {
    padding-left: 20px;
  }

  li + li {
    margin-top: 4px;
  }
}

.table-actions {
  justify-content: space-between;
  margin-bottom: 12px;
}

.stock-link {
  display: inline-flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  border: 0;
  background: transparent;
  padding: 0;
  color: #0f766e;
  cursor: pointer;

  span {
    font-weight: 600;
  }

  small {
    color: #6b7280;
  }
}

.topic-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.reject-text {
  margin-left: 8px;
  color: #6b7280;
  font-size: 12px;
}

.column-help {
  cursor: help;
  text-decoration: underline dotted;
  text-underline-offset: 3px;
}

@media (max-width: 768px) {
  .page-toolbar,
  .table-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .toolbar-actions,
  .table-actions__right {
    justify-content: flex-start;
    flex-wrap: wrap;
  }

  .summary-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .funnel-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
