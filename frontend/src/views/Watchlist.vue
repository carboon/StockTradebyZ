<template>
  <div class="watchlist-page">
    <div class="watchlist-layout">
      <el-card class="list-card top-card">
          <template #header>
            <div class="card-header">
              <span>我的观察</span>
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

          <el-table
            :data="watchlist"
            @row-click="selectStock"
            highlight-current-row
            class="watchlist-table"
            height="420"
          >
          <el-table-column prop="code" label="代码" width="80" />
          <el-table-column prop="name" label="名称" />
            <el-table-column label="操作" width="140" align="center">
              <template #default="{ row }">
                <div class="row-actions">
                  <el-button
                    text
                    type="primary"
                    @click.stop="openEditDialog(row)"
                  >
                    编辑
                  </el-button>
                  <el-button
                    text
                    type="danger"
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

      <template v-if="selectedStock">
        <el-card class="detail-card top-card">
            <template #header>
              <div class="card-header">
                <span>{{ selectedStock.code }} {{ selectedStock.name || '' }}</span>
                <div class="header-actions">
                  <el-button size="small" @click="goToDiagnosis(selectedStock.code)">
                    单股诊断
                  </el-button>
                  <el-button size="small" @click="analyzeNow" :loading="analyzing">
                    立即分析
                  </el-button>
                </div>
              </div>
            </template>

            <!-- K线图 -->
            <div ref="chartRef" class="chart-container" />

            <!-- 趋势分析 -->
            <el-divider />
            <div class="trend-section">
              <h4>趋势分析 (基于技术指标)</h4>
              <el-row :gutter="20" class="position-row">
                <el-col :span="12">
                  <div class="trend-box">
                    <div class="trend-label">买入成本</div>
                    <div class="price-range">
                      <span>{{ selectedStock.entry_price != null ? selectedStock.entry_price.toFixed(2) : '-' }}</span>
                    </div>
                  </div>
                </el-col>
                <el-col :span="12">
                  <div class="trend-box">
                    <div class="trend-label">当前仓位</div>
                    <div class="price-range">
                      <span>{{ formatPositionRatio(selectedStock.position_ratio) }}</span>
                    </div>
                  </div>
                </el-col>
              </el-row>
              <el-row :gutter="20" class="position-row" v-if="analysisHistory.length > 0">
                <el-col :span="8">
                  <div class="trend-box compact">
                    <div class="trend-label">买入动作</div>
                    <el-tag :type="getBuyActionType(analysisHistory[0].buy_action)" size="small">
                      {{ getBuyActionLabel(analysisHistory[0].buy_action) }}
                    </el-tag>
                  </div>
                </el-col>
                <el-col :span="8">
                  <div class="trend-box compact">
                    <div class="trend-label">持仓动作</div>
                    <el-tag :type="getHoldActionType(analysisHistory[0].hold_action)" size="small">
                      {{ getHoldActionLabel(analysisHistory[0].hold_action) }}
                    </el-tag>
                  </div>
                </el-col>
                <el-col :span="8">
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
                <el-col :span="12">
                  <div class="trend-box">
                    <div class="trend-label">当前趋势</div>
                    <el-tag :type="trendData.outlook === 'bullish' ? 'success' : trendData.outlook === 'bearish' ? 'danger' : 'info'" size="large">
                      {{ trendText }}
                    </el-tag>
                  </div>
                </el-col>
                <el-col :span="12">
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

        <el-card class="history-card">
          <template #header>
            <div class="card-header">
              <span>历史分析记录</span>
            </div>
          </template>

          <el-empty v-if="historyRows.length === 0" description="暂无分析记录" :image-size="60" />
          <el-table v-else :data="historyRows" class="history-table">
            <el-table-column prop="analysis_date" label="日期" min-width="130">
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
        </el-card>
      </template>

      <el-empty v-else class="detail-empty" description="请从左侧选择股票" :image-size="120" />
    </div>

    <!-- 添加对话框 -->
    <el-dialog v-model="showAddDialog" title="添加到观察列表" width="400px">
      <el-form :model="addForm" label-width="80px">
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

    <el-dialog v-model="showEditDialog" title="编辑持仓信息" width="400px">
      <el-form :model="editForm" label-width="80px">
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, onActivated, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Delete } from '@element-plus/icons-vue'
import { apiWatchlist, apiStock } from '@/api'
import { ElMessage } from 'element-plus'
import { CandlestickChart, LineChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { KLineData, WatchlistItem, WatchlistAnalysis } from '@/types'
import { use, init, type ECharts } from 'echarts/core'

use([
  CandlestickChart,
  LineChart,
  TooltipComponent,
  GridComponent,
  DataZoomComponent,
  CanvasRenderer,
])

const router = useRouter()
const WATCHLIST_STATE_KEY = 'stocktrade:watchlist:state'
const watchlist = ref<WatchlistItem[]>([])
const selectedStock = ref<WatchlistItem | null>(null)
const analysisHistory = ref<WatchlistAnalysis[]>([])

const showAddDialog = ref(false)
const showEditDialog = ref(false)
const addForm = ref({ code: '', reason: '', entryPrice: '', positionRatio: '' })
const editForm = ref({ id: 0, code: '', reason: '', entryPrice: '', positionRatio: '' })
const analyzing = ref(false)

const chartRef = ref<HTMLElement>()
let chartInstance: ECharts | null = null

const trendData = ref({
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

onMounted(async () => {
  restoreWatchlistState()
  await loadWatchlist()
  window.addEventListener('resize', handleResize)
})

onActivated(async () => {
  chartInstance?.resize()

  if (watchlist.value.length === 0) {
    await loadWatchlist()
  } else if (!selectedStock.value) {
    await restoreSelectedStock()
  }
})

onUnmounted(() => {
  if (chartInstance) {
    chartInstance.dispose()
  }
  window.removeEventListener('resize', handleResize)
})

function handleResize() {
  chartInstance?.resize()
}

async function loadWatchlist() {
  try {
    const data = await apiWatchlist.getAll()
    watchlist.value = data.items || []
    await restoreSelectedStock()
  } catch (error: any) {
    console.error('Failed to load watchlist:', error)
  }
}

function selectStock(row: WatchlistItem) {
  selectedStock.value = row
  persistWatchlistState()
  loadChart(row.code)
  loadAnalysis(row.id)
}

async function loadChart(code: string) {
  try {
    const data = await apiStock.getKline(code, 120)
    await nextTick()
    renderChart(data)

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
  } catch (error: any) {
    ElMessage.error('加载K线图失败: ' + error.message)
  }
}

async function loadAnalysis(id: number) {
  try {
    const data = await apiWatchlist.getAnalysis(id)
    analysisHistory.value = data.analyses || []
    persistWatchlistState()
  } catch (error) {
    console.error('Failed to load analysis:', error)
  }
}

function renderChart(data: KLineData) {
  if (!chartRef.value) return

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
  analyzing.value = true
  try {
    await apiWatchlist.analyze(selectedStock.value.id)
    await loadAnalysis(selectedStock.value.id)
    persistWatchlistState()
    ElMessage.success('分析完成')
  } catch (error: any) {
    ElMessage.error('分析失败: ' + error.message)
  } finally {
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
  const raw = sessionStorage.getItem(WATCHLIST_STATE_KEY)
  if (!raw || selectedStock.value) return

  try {
    const state = JSON.parse(raw)
    const selectedId = state.selectedStockId as number | undefined
    if (!selectedId) return

    const target = watchlist.value.find((item) => item.id === selectedId) || null
    if (!target) return

    selectedStock.value = target
    trendData.value = state.trendData || trendData.value
    analysisHistory.value = state.analysisHistory || []
    await nextTick()
    await loadChart(target.code)
    if (analysisHistory.value.length === 0) {
      await loadAnalysis(target.id)
    }
  } catch {
    sessionStorage.removeItem(WATCHLIST_STATE_KEY)
  }
}

function persistWatchlistState() {
  const state = {
    selectedStockId: selectedStock.value?.id || null,
    analysisHistory: analysisHistory.value,
    trendData: trendData.value,
  }

  sessionStorage.setItem(WATCHLIST_STATE_KEY, JSON.stringify(state))
}

function restoreWatchlistState() {
  const raw = sessionStorage.getItem(WATCHLIST_STATE_KEY)
  if (!raw) return

  try {
    const state = JSON.parse(raw)
    trendData.value = state.trendData || trendData.value
    analysisHistory.value = state.analysisHistory || []
  } catch {
    sessionStorage.removeItem(WATCHLIST_STATE_KEY)
  }
}
</script>

<style scoped lang="scss">
.watchlist-page {
  .watchlist-layout {
    display: grid;
    grid-template-columns: minmax(320px, 380px) minmax(0, 1fr);
    gap: 20px;
    align-items: start;
  }

  .top-card {
    height: 100%;
  }

  .history-card {
    grid-column: 1 / -1;
  }

  .detail-empty {
    grid-column: 2;
    min-height: 420px;
    border-radius: 12px;
    background: #fff;
    border: 1px solid var(--el-border-color-light);
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

    .header-actions {
      display: flex;
      gap: 8px;
    }
  }

  .watchlist-table {
    .row-actions {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      white-space: nowrap;
    }

    :deep(.el-table__row) {
      cursor: pointer;

      &.current-row {
        background-color: #e6f7ff;
      }
    }
  }

  .detail-card {
    .el-divider {
      margin: 20px 0;
    }
  }

  .chart-container {
    height: 350px;
  }

  .trend-section {
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

@media (max-width: 1080px) {
  .watchlist-page {
    .watchlist-layout {
      grid-template-columns: 1fr;
    }

    .history-card,
    .detail-empty {
      grid-column: auto;
    }
  }
}
</style>
