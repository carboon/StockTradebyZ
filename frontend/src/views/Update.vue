<template>
  <div class="ops-page">
    <el-tabs v-model="activeTab" class="ops-tabs">
      <!-- 任务管理 -->
      <el-tab-pane label="任务管理" name="tasks">
        <div class="tab-content">
          <el-card class="connectivity-card">
            <div class="connectivity-card__row">
              <div class="connectivity-card__status">
                <span class="connectivity-card__label">任务推送</span>
                <el-tag :type="socketStatusTagType" size="small">{{ socketStatusLabel }}</el-tag>
              </div>
              <div class="connectivity-card__actions">
                <el-button size="small" @click="reconnectSocketsNow">立即重连</el-button>
                <el-button size="small" :loading="diagnosticsLoading" @click="loadDiagnostics">刷新诊断</el-button>
                <el-button size="small" @click="copyDiagnostics">复制诊断摘要</el-button>
              </div>
            </div>
            <div class="connectivity-card__desc">{{ socketStatusDescription }}</div>
          </el-card>

          <!-- 首次初始化引导 -->
          <el-card v-if="showBootstrap" class="bootstrap-card">
            <template #header>
              <div class="card-header">
                <span>首次初始化引导</span>
                <el-tag :type="bootstrapStatusTagType" size="small">
                  {{ bootstrapStatusLabel }}
                </el-tag>
              </div>
            </template>

            <div class="bootstrap-content">
              <p class="bootstrap-desc">{{ bootstrapDescription }}</p>

              <div class="bootstrap-notes">
                <div class="bootstrap-note">
                  <span class="bootstrap-note-label">预计耗时</span>
                  <span class="bootstrap-note-value">首次全量初始化通常需要数分钟到十几分钟，期间页面可刷新。</span>
                </div>
                <div class="bootstrap-note">
                  <span class="bootstrap-note-label">刷新恢复</span>
                  <span class="bootstrap-note-value">页面会优先恢复你刚才查看的初始化任务和日志视图。</span>
                </div>
                <div class="bootstrap-note">
                  <span class="bootstrap-note-label">功能限制</span>
                  <span class="bootstrap-note-value">在原始数据、候选结果和分析结果都齐备前，业务页仍可能继续提示未完成初始化。</span>
                </div>
              </div>

              <div class="bootstrap-steps">
                <div
                  v-for="step in bootstrapSteps"
                  :key="step.key"
                  class="bootstrap-step"
                  :class="step.done ? 'is-done' : 'is-pending'"
                >
                  <div class="step-indicator">{{ step.done ? '✓' : step.index }}</div>
                  <div class="step-content">
                    <div class="step-title">{{ step.title }}</div>
                    <div class="step-meta">{{ step.meta }}</div>
                  </div>
                </div>
              </div>

              <div class="bootstrap-actions">
                <el-button
                  type="primary"
                  :disabled="!canStartBootstrap"
                  :loading="bootstrapStarting"
                  @click="startBootstrap"
                >
                  {{ bootstrapButtonText }}
                </el-button>
                <el-button
                  v-if="initializationRunningTask"
                  @click="focusTask(initializationRunningTask, 'logs')"
                >
                  继续查看当前任务
                </el-button>
                <el-button
                  v-if="showRetryBootstrap"
                  @click="retryBootstrap"
                >
                  重新发起初始化
                </el-button>
                <el-button
                  v-if="selectedRecoveryTask"
                  text
                  type="primary"
                  @click="focusTask(selectedRecoveryTask, 'logs')"
                >
                  查看失败详情
                </el-button>
                <el-button
                  v-if="!configStore.tushareReady || !configStore.apiAvailable"
                  text
                  type="primary"
                  @click="goToConfig"
                >
                  去配置页处理
                </el-button>
                <el-button :icon="Refresh" @click="reloadTasks">刷新状态</el-button>
              </div>

              <el-alert
                v-if="recoveryAlert"
                :title="recoveryAlert.title"
                :description="recoveryAlert.description"
                :type="recoveryAlert.type"
                show-icon
                :closable="false"
              />
              <el-alert
                v-if="stalledBootstrapAlert"
                :title="stalledBootstrapAlert.title"
                :description="stalledBootstrapAlert.description"
                type="warning"
                show-icon
                :closable="false"
              />
            </div>
          </el-card>

          <el-card class="diagnostics-card">
            <template #header>
              <div class="card-header">
                <span>本机诊断</span>
                <span class="diagnostics-generated-at">{{ diagnosticsGeneratedAt }}</span>
              </div>
            </template>

            <el-collapse v-model="diagnosticsPanels" class="diagnostics-collapse">
              <el-collapse-item name="diagnostics">
                <template #title>
                  <span class="collapse-title">展开本机诊断详情</span>
                </template>

                <div v-if="diagnosticChecks.length > 0" class="diagnostics-list">
                  <div
                    v-for="check in diagnosticChecks"
                    :key="check.key"
                    class="diagnostic-item"
                  >
                    <div class="diagnostic-item__header">
                      <span class="diagnostic-item__title">{{ check.label }}</span>
                      <el-tag :type="getStatusType(check.status)" size="small">{{ getCheckStatusLabel(check.status) }}</el-tag>
                    </div>
                    <div class="diagnostic-item__summary">{{ check.summary }}</div>
                    <div v-if="check.action" class="diagnostic-item__action">{{ check.action }}</div>
                  </div>
                </div>
                <el-empty v-else description="诊断信息暂不可用" :image-size="60" />
              </el-collapse-item>
            </el-collapse>
          </el-card>

          <el-card v-if="bootstrapFinished" class="action-card">
            <div class="action-buttons">
              <el-button
                type="primary"
                :loading="startingUpdate"
                :disabled="runningTasksCount > 0"
                @click="startDataUpdate"
              >
                更新最新交易日数据
              </el-button>
              <el-button
                :loading="startingFullUpdate"
                :disabled="runningTasksCount > 0"
                @click="startFullUpdate"
              >
                重新获取历史数据
              </el-button>
              <el-button :icon="Refresh" @click="reloadTasks">刷新</el-button>
            </div>
            <div v-if="runningTasksCount > 0" class="running-hint">
              <el-icon class="is-loading"><Loading /></el-icon>
              当前有 {{ runningTasksCount }} 个任务正在运行
            </div>
          </el-card>

          <!-- 运行中任务 -->
          <el-card class="tasks-card">
            <template #header>
              <div class="card-header">
                <span>运行中任务</span>
                <el-tag v-if="runningTasksCount > 0" type="warning" size="small">
                  {{ runningTasksCount }} 个
                </el-tag>
                <el-tag v-else type="info" size="small">无</el-tag>
              </div>
            </template>

            <el-empty v-if="runningTasks.length === 0" description="当前没有运行中任务" :image-size="60" />
            <div v-else class="running-tasks-list">
              <div
                v-for="task in runningTasks"
                :key="task.id"
                class="task-item"
                :class="{ 'is-selected': selectedTask?.id === task.id }"
                @click="selectTask(task)"
              >
                <div class="task-main">
                  <div class="task-header">
                    <span class="task-id">#{{ task.id }}</span>
                    <span class="task-type">{{ getTaskTypeLabel(task.task_type) }}</span>
                    <el-tag :type="getStatusType(task.status)" size="small">{{ task.status }}</el-tag>
                  </div>
                  <div class="task-stage">{{ getStageLabel(task.task_stage) }}</div>
                  <el-progress :percentage="task.progress" :stroke-width="6" :show-text="false" />
                </div>
                <el-button text type="danger" size="small" @click.stop="cancelTask(task)">取消</el-button>
              </div>
            </div>
          </el-card>

          <!-- 历史任务 -->
          <el-card class="tasks-card">
            <template #header>
              <div class="card-header">
                <span>历史任务</span>
                <el-button text type="danger" size="small" @click="clearTasks">清空</el-button>
              </div>
            </template>

            <el-table :data="historyTasks" max-height="300" @row-click="viewTaskDetail">
              <el-table-column prop="id" label="ID" width="60" />
              <el-table-column label="类型" width="100">
                <template #default="{ row }">{{ getTaskTypeLabel(row.task_type) }}</template>
              </el-table-column>
              <el-table-column label="状态" width="80">
                <template #default="{ row }">
                  <el-tag :type="getStatusType(row.status)" size="small">{{ row.status }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="summary" label="摘要" min-width="200" show-overflow-tooltip />
              <el-table-column label="创建时间" width="160">
                <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
              </el-table-column>
            </el-table>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- 日志记录 -->
      <el-tab-pane label="日志记录" name="logs">
        <div class="tab-content">
          <el-card class="logs-card">
            <template #header>
              <div class="card-header">
                <div class="log-controls">
                  <el-radio-group v-model="logFilter" size="small" @change="filterLogs">
                    <el-radio-button value="all">全部日志</el-radio-button>
                    <el-radio-button value="task">当前任务</el-radio-button>
                  </el-radio-group>
                  <el-tag v-if="selectedTask" size="small" type="info">
                    #{{ selectedTask.id }} {{ getTaskTypeLabel(selectedTask.task_type) }}
                  </el-tag>
                  <el-tag v-else-if="logFilter === 'task'" size="small" type="warning">
                    请先选择任务
                  </el-tag>
                </div>
                <div class="log-actions">
                  <el-checkbox v-model="autoScroll">自动滚动</el-checkbox>
                  <el-button text size="small" @click="clearLogsDisplay">清空显示</el-button>
                </div>
              </div>
            </template>

            <div ref="logRef" class="log-container" @scroll="handleLogScroll">
              <div v-if="filteredLogs.length === 0" class="log-empty">
                <el-icon><Document /></el-icon>
                <p>{{ selectedTask ? '该任务暂无日志' : '请选择任务查看日志，或切换到"全部日志"' }}</p>
              </div>
              <div v-for="(log, index) in filteredLogs" :key="log.id || `${log.task_id}-${index}`" class="log-line" :class="`log-${log.level}`">
                <span class="log-time">{{ formatLogTime(log.log_time) }}</span>
                <span class="log-level">{{ log.level?.toUpperCase() }}</span>
                <span class="log-message">{{ log.message }}</span>
              </div>
            </div>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- 状态管理 -->
      <el-tab-pane label="状态管理" name="status">
        <div class="tab-content">
          <!-- 健康状态总览 -->
          <el-card class="health-card">
            <div class="health-summary">
              <div class="health-item" :class="{ 'is-healthy': dataStatus.rawData.exists }">
                <div class="health-icon">
                  <el-icon><CircleCheck v-if="dataStatus.rawData.exists" /><CircleClose v-else /></el-icon>
                </div>
                <div class="health-info">
                  <div class="health-title">数据状态</div>
                  <div class="health-desc">{{ dataStatus.rawData.exists ? '数据完整' : '缺少原始数据' }}</div>
                </div>
              </div>
              <div class="health-item is-healthy">
                <div class="health-icon">
                  <el-icon><CircleCheck /></el-icon>
                </div>
                <div class="health-info">
                  <div class="health-title">数据库</div>
                  <div class="health-desc">连接正常</div>
                </div>
              </div>
              <div class="health-item" :class="{ 'is-healthy': runningTasksCount === 0 }">
                <div class="health-icon">
                  <el-icon><CircleCheck v-if="runningTasksCount === 0" /><Loading v-else class="is-spinning" /></el-icon>
                </div>
                <div class="health-info">
                  <div class="health-title">任务状态</div>
                  <div class="health-desc">{{ runningTasksCount > 0 ? `${runningTasksCount}个运行中` : '无运行任务' }}</div>
                </div>
              </div>
            </div>
          </el-card>

          <!-- 数据详情 -->
          <el-card class="detail-card">
            <template #header>
              <div class="card-header">
                <span>原始数据详情</span>
                <el-button type="primary" size="small" :loading="checkingData" @click="checkDataFresh">
                  检查更新
                </el-button>
              </div>
            </template>

            <div class="detail-grid">
              <div class="detail-item">
                <span class="detail-label">股票数量</span>
                <span class="detail-value">{{ dataStatus.rawData.count || 0 }} <small>只</small></span>
              </div>
              <div class="detail-item">
                <span class="detail-label">最新日期</span>
                <span class="detail-value">{{ dataStatus.rawData.latestDate || '-' }}</span>
              </div>
              <div class="detail-item">
                <span class="detail-label">数据来源</span>
                <span class="detail-value">Tushare</span>
              </div>
              <div class="detail-item">
                <span class="detail-label">流动性池</span>
                <span class="detail-value">Top 2000</span>
              </div>
            </div>
          </el-card>

          <!-- 环境信息 -->
          <el-card class="env-summary-card">
            <template #header>
              <span>系统环境</span>
            </template>

            <div class="env-summary-grid">
              <template v-for="section in dataStatus.environment" :key="section.key">
                <div v-if="section.key === 'service'" class="env-section">
                  <div class="env-section-title">{{ section.label }}</div>
                  <div class="env-chips">
                    <el-tag
                      v-for="(value, key) in getPrimitiveItems(section.items)"
                      :key="String(key)"
                      size="small"
                    >
                      {{ formatEnvKey(String(key)) }}: {{ formatEnvValue(value) }}
                    </el-tag>
                  </div>
                </div>
              </template>
            </div>
          </el-card>

          <!-- 更多环境信息（折叠） -->
          <el-collapse class="env-collapse">
            <el-collapse-item name="more">
              <template #title>
                <span class="collapse-title">更多环境信息</span>
              </template>
              <div class="env-details-grid">
                <template v-for="section in dataStatus.environment" :key="section.key">
                  <div v-if="section.key !== 'service' && section.key !== 'data_status'" class="env-detail-section">
                    <div class="env-detail-title">{{ section.label }}</div>
                    <div class="env-detail-items">
                      <div
                        v-for="(value, key) in getPrimitiveItems(section.items)"
                        :key="String(key)"
                        class="env-detail-item"
                      >
                        <span class="env-detail-key">{{ formatEnvKey(String(key)) }}</span>
                        <span class="env-detail-value">{{ formatEnvValue(value) }}</span>
                      </div>
                    </div>
                  </div>
                </template>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  Refresh,
  Loading,
  Document,
  CircleCheck,
  CircleClose,
} from '@element-plus/icons-vue'
import { apiTasks } from '@/api'
import { useConfigStore } from '@/store/config'
import { useNoticeStore } from '@/store/notice'
import type { Task, TaskDiagnosticCheck, TaskDiagnosticsResponse, TaskLogItem } from '@/types'
import { loadInitTaskViewState, saveInitTaskViewState, clearInitTaskViewState } from '@/utils/initTaskViewState'

const configStore = useConfigStore()
const noticeStore = useNoticeStore()
const router = useRouter()

// Tab状态
const activeTab = ref<'tasks' | 'logs' | 'status'>('tasks')
const logFilter = ref<'all' | 'task'>('task')
const autoScroll = ref(true)
const diagnosticsPanels = ref<string[]>([])

// 数据状态
function createEmptyDataStatus() {
  return {
    rawData: { exists: false, count: 0, latestDate: '' },
    candidates: { exists: false, count: 0, latestDate: '' },
    analysis: { exists: false, count: 0, latestDate: '' },
    kline: { exists: false, count: 0, latestDate: '' },
    dbSize: '-',
    environment: [] as Array<{ key: string; label: string; items: Record<string, any> }>,
  }
}

const dataStatus = ref({
  ...createEmptyDataStatus(),
})

// 任务状态
const runningTasks = ref<Task[]>([])
const historyTasks = ref<Task[]>([])
const selectedTask = ref<Task | null>(null)

// 日志状态
const allLogs = ref<TaskLogItem[]>([])
const selectedTaskLogs = ref<TaskLogItem[]>([])
const logRef = ref<HTMLElement>()

// 加载状态
const dataLoaded = ref(false)
const bootstrapStarting = ref(false)
const startingUpdate = ref(false)
const startingFullUpdate = ref(false)
const checkingData = ref(false)
const diagnosticsLoading = ref(false)
const diagnostics = ref<TaskDiagnosticsResponse | null>(null)

// WebSocket
let ws: WebSocket | null = null
let opsWs: WebSocket | null = null
type SocketState = 'connected' | 'reconnecting' | 'polling' | 'disconnected'
const opsSocketState = ref<SocketState>('disconnected')
const taskSocketState = ref<SocketState>('disconnected')
const socketReconnectAttempts = ref(0)
let opsReconnectTimer: ReturnType<typeof setTimeout> | null = null
let taskReconnectTimer: ReturnType<typeof setTimeout> | null = null
let lastTaskSocketId: number | null = null

// 计算属性
const runningTasksCount = computed(() => runningTasks.value.length)
const initializationRunningTask = computed(() => runningTasks.value.find((task) => isBootstrapTask(task)) || null)
const latestFailedBootstrapTask = computed(() => {
  if (bootstrapFinished.value) return null
  return historyTasks.value.find((task) => isBootstrapTask(task) && task.status === 'failed') || null
})
const selectedRecoveryTask = computed(() => selectedTask.value || initializationRunningTask.value || latestFailedBootstrapTask.value)
const bootstrapInProgress = computed(() => bootstrapStarting.value || Boolean(initializationRunningTask.value))

const bootstrapFinished = computed(() => {
  return dataLoaded.value
    && dataStatus.value.rawData.exists
    && dataStatus.value.candidates.exists
    && dataStatus.value.analysis.exists
})

const showBootstrap = computed(() => {
  return dataLoaded.value && !configStore.dataInitialized
})

const bootstrapStatusLabel = computed(() => {
  if (bootstrapFinished.value) return '已完成'
  if (bootstrapInProgress.value) return '进行中'
  if (!configStore.apiAvailable) return '服务异常'
  if (latestFailedBootstrapTask.value) return '可恢复'
  if (!configStore.tushareReady) return '待配置'
  return '待执行'
})

const bootstrapStatusTagType = computed(() => {
  if (bootstrapFinished.value) return 'success'
  if (bootstrapInProgress.value) return 'warning'
  if (!configStore.apiAvailable || latestFailedBootstrapTask.value) return 'danger'
  if (!configStore.tushareReady) return 'info'
  return 'primary'
})

const bootstrapDescription = computed(() => {
  if (bootstrapFinished.value) {
    return '首次初始化已完成，原始数据、候选结果和分析结果都已就绪。'
  }
  if (!configStore.apiAvailable) {
    return configStore.statusError || '后端服务暂不可用，请先恢复服务，再回到任务中心继续初始化。'
  }
  if (initializationRunningTask.value) {
    return `初始化任务 #${initializationRunningTask.value.id} 正在执行，当前阶段：${getStageLabel(initializationRunningTask.value.task_stage)}。`
  }
  if (latestFailedBootstrapTask.value) {
    return `上一次初始化任务 #${latestFailedBootstrapTask.value.id} 失败。可查看日志定位失败点后重新发起。`
  }
  if (!configStore.tushareReady) {
    return '请先进入配置页填写并验证 Tushare Token；验证通过后才能启动首次初始化。'
  }
  return configStore.initializationMessage || '首次初始化会补齐原始数据、候选结果和分析结果。'
})

const canStartBootstrap = computed(() => {
  return configStore.apiAvailable && configStore.tushareReady && !bootstrapFinished.value && !bootstrapInProgress.value
})

const bootstrapButtonText = computed(() => {
  if (bootstrapFinished.value) return '数据已就绪'
  if (bootstrapInProgress.value) return '初始化进行中'
  if (!configStore.tushareReady || !configStore.apiAvailable) return '先处理配置'
  if (latestFailedBootstrapTask.value) return '重新开始初始化'
  return '开始首次初始化'
})

const diagnosticChecks = computed<TaskDiagnosticCheck[]>(() => diagnostics.value?.checks || [])
const diagnosticsGeneratedAt = computed(() => {
  if (!diagnostics.value?.generated_at) return '尚未加载'
  return `更新于 ${formatDateTime(diagnostics.value.generated_at)}`
})
const socketStatusLabel = computed(() => {
  if (opsSocketState.value === 'connected' && (!selectedTask.value || taskSocketState.value === 'connected')) return '实时推送中'
  if (opsSocketState.value === 'reconnecting' || taskSocketState.value === 'reconnecting') return '重连中'
  if (opsSocketState.value === 'polling' || taskSocketState.value === 'polling') return '轮询兜底'
  return '已断开'
})
const socketStatusTagType = computed(() => {
  if (socketStatusLabel.value === '实时推送中') return 'success'
  if (socketStatusLabel.value === '重连中') return 'warning'
  if (socketStatusLabel.value === '轮询兜底') return 'info'
  return 'danger'
})
const socketStatusDescription = computed(() => {
  if (socketStatusLabel.value === '实时推送中') return '任务状态和日志会自动推送更新。'
  if (socketStatusLabel.value === '重连中') return '检测到连接中断，系统会自动重连，同时保留轮询刷新。'
  if (socketStatusLabel.value === '轮询兜底') return 'WebSocket 暂不可用，当前退回到定时轮询。任务仍可继续查看。'
  return '当前未连接到任务推送通道，请手动重连或刷新页面。'
})
const stalledBootstrapAlert = computed(() => {
  const task = initializationRunningTask.value
  if (!task?.started_at) return null

  const elapsedMs = Date.now() - new Date(task.started_at).getTime()
  const elapsedMinutes = Math.max(1, Math.floor(elapsedMs / 60000))
  if (elapsedMinutes < 15) return null

  const stage = getStageLabel(task.task_stage)
  return {
    title: '初始化耗时明显偏长',
    description: `任务 #${task.id} 已持续约 ${elapsedMinutes} 分钟，当前阶段为“${stage}”。若日志长时间没有新内容，可先复制诊断摘要，再尝试刷新状态或重连推送。`,
  }
})

const bootstrapSteps = computed(() => [
  {
    key: 'config',
    index: 1,
    title: '配置数据源',
    meta: configStore.tushareReady ? 'Tushare 已验证' : '待配置',
    done: configStore.tushareReady,
  },
  {
    key: 'raw',
    index: 2,
    title: '抓取原始数据',
    meta: dataStatus.value.rawData.exists
      ? `${dataStatus.value.rawData.count}只股票`
      : '待抓取',
    done: dataStatus.value.rawData.exists,
  },
  {
    key: 'candidates',
    index: 3,
    title: '生成候选结果',
    meta: dataStatus.value.candidates.exists
      ? `${dataStatus.value.candidates.count}条结果`
      : '待生成',
    done: dataStatus.value.candidates.exists,
  },
  {
    key: 'analysis',
    index: 4,
    title: '生成分析结果',
    meta: dataStatus.value.analysis.exists
      ? `${dataStatus.value.analysis.count}条结果`
      : '待生成',
    done: dataStatus.value.analysis.exists,
  },
])

const showRetryBootstrap = computed(() => {
  return Boolean(configStore.apiAvailable && configStore.tushareReady && latestFailedBootstrapTask.value && !bootstrapInProgress.value)
})

const recoveryAlert = computed(() => {
  if (!showBootstrap.value) return null
  if (!configStore.apiAvailable) {
    return {
      type: 'error' as const,
      title: '后端未就绪',
      description: '先恢复后端服务，再刷新本页继续查看初始化任务。',
    }
  }
  if (!configStore.tushareReady) {
    return {
      type: 'warning' as const,
      title: 'Token 未验证',
      description: '请去配置页完成 Token 验证，验证成功后回到此页启动初始化。',
    }
  }
  if (initializationRunningTask.value) {
    return {
      type: 'info' as const,
      title: '初始化仍在运行',
      description: '可以继续留在任务中心查看日志，或刷新页面后恢复到当前任务。',
    }
  }
  if (latestFailedBootstrapTask.value) {
    return {
      type: 'error' as const,
      title: '初始化失败，可直接恢复',
      description: latestFailedBootstrapTask.value.error_message || latestFailedBootstrapTask.value.summary || '建议先查看失败日志，再点击重新发起初始化。',
    }
  }
  return {
    type: 'info' as const,
    title: '初始化尚未完成',
    description: '请发起首次初始化；如果你刚刷新页面，任务列表会在下方自动恢复。',
  }
})

const filteredLogs = computed(() => {
  if (logFilter.value === 'task' && selectedTask.value) {
    return selectedTaskLogs.value
  }
  return allLogs.value
})

watch(selectedTask, (newTask) => {
  if (newTask) {
    if (logFilter.value === 'all') {
      logFilter.value = 'task'
    }
  }
  persistViewState()
})

watch(activeTab, () => {
  persistViewState()
})

// 生命周期
onMounted(async () => {
  const restoredState = loadInitTaskViewState()
  if (restoredState.activeTab) {
    activeTab.value = restoredState.activeTab
  }
  try {
    await configStore.checkTushareStatus()
  } catch (error) {
    console.error('Failed to check tushare status:', error)
  }
  await reloadAll()
  connectOpsSocket()
  startPoller()
})

onUnmounted(() => {
  stopPoller()
  clearReconnectTimers()
  disconnectSockets()
})

// 核心方法
async function reloadAll() {
  try {
    const [runningResp, statusResp, envResp, diagnosticsResp] = await Promise.all([
      apiTasks.getRunning(),
      apiTasks.getStatus(),
      apiTasks.getEnvironment(),
      apiTasks.getDiagnostics(),
    ])

    runningTasks.value = runningResp.tasks
    diagnostics.value = diagnosticsResp

    // 获取历史任务（已完成的）
    try {
      const historyResp = await apiTasks.getAll('completed,failed,cancelled', 20)
      historyTasks.value = historyResp.tasks
    } catch {
      historyTasks.value = []
    }

    dataStatus.value = {
      ...createEmptyDataStatus(),
      rawData: {
        exists: statusResp.raw_data.exists,
        count: statusResp.raw_data.count,
        latestDate: formatLatestDate(statusResp.raw_data.latest_date),
      },
      candidates: {
        exists: statusResp.candidates?.exists || false,
        count: statusResp.candidates?.count || 0,
        latestDate: formatLatestDate(statusResp.candidates?.latest_date),
      },
      analysis: {
        exists: statusResp.analysis?.exists || false,
        count: statusResp.analysis?.count || 0,
        latestDate: formatLatestDate(statusResp.analysis?.latest_date),
      },
      kline: {
        exists: statusResp.kline?.exists || false,
        count: statusResp.kline?.count || 0,
        latestDate: formatLatestDate(statusResp.kline?.latest_date),
      },
      environment: envResp.sections || [],
    }

    dataLoaded.value = true
    try {
      await configStore.checkTushareStatus()
    } catch (error) {
      console.error('Failed to refresh tushare status:', error)
    }
    await restoreTaskSelection()
    persistViewState()
  } catch (error) {
    console.error('Failed to reload:', error)
    dataLoaded.value = true
  }
}

async function startBootstrap() {
  if (!canStartBootstrap.value) return

  bootstrapStarting.value = true
  try {
    const result = await apiTasks.startUpdate('quant', false, 1)
    rememberBootstrapTask(result.task)
    ElMessage.success(`初始化任务已启动 #${result.task.id}`)
    await focusTask(result.task, 'logs')
    await reloadAll()
  } catch (error: any) {
    const recovered = await recoverInitializationTask()
    if (!recovered) {
      ElMessage.error(error.message || '启动失败')
    }
  } finally {
    bootstrapStarting.value = false
  }
}

async function retryBootstrap() {
  await startBootstrap()
}

async function startDataUpdate() {
  startingUpdate.value = true
  try {
    const result = await apiTasks.startUpdate('quant', false, 1)
    ElMessage.success(`数据更新任务已启动 #${result.task.id}`)
    await reloadAll()
  } catch (error: any) {
    ElMessage.error(error.message || '启动失败')
  } finally {
    startingUpdate.value = false
  }
}

async function startFullUpdate() {
  startingFullUpdate.value = true
  try {
    const result = await apiTasks.startUpdate('quant', false, 1000)
    ElMessage.success(`历史数据更新任务已启动 #${result.task.id}`)
    await reloadAll()
  } catch (error: any) {
    ElMessage.error(error.message || '启动失败')
  } finally {
    startingFullUpdate.value = false
  }
}

async function reloadTasks() {
  await reloadAll()
  ElMessage.success('已刷新')
}

async function loadDiagnostics() {
  diagnosticsLoading.value = true
  try {
    diagnostics.value = await apiTasks.getDiagnostics()
  } catch (error) {
    console.error('Failed to load diagnostics:', error)
    noticeStore.setNotice({
      type: 'warning',
      title: '诊断信息刷新失败',
      message: error instanceof Error ? error.message : '请稍后重试。',
      actionLabel: '去配置',
      actionRoute: '/config',
    })
  } finally {
    diagnosticsLoading.value = false
  }
}

async function copyDiagnostics() {
  const summary = buildDiagnosticsSummary()
  try {
    await navigator.clipboard.writeText(summary)
    ElMessage.success('诊断摘要已复制')
  } catch {
    ElMessage.warning('复制失败，请检查浏览器剪贴板权限')
  }
}

async function selectTask(task: Task) {
  selectedTask.value = task
  await loadTaskLogs(task.id)
  connectTaskSocket(task.id)
}

async function focusTask(task: Task, tab: 'tasks' | 'logs' = 'tasks') {
  activeTab.value = tab
  await selectTask(task)
}

async function loadTaskLogs(taskId: number) {
  try {
    const data = await apiTasks.getLogs(taskId)
    selectedTaskLogs.value = data.logs
    await nextTick()
    scrollToBottom()
  } catch (error) {
    console.error('Failed to load logs:', error)
  }
}

async function cancelTask(task: Task) {
  try {
    const result = await apiTasks.cancel(task.id)
    if (result.status === 'ok') {
      ElMessage.success(result.message || `任务 #${task.id} 已取消`)
      await reloadAll()
    } else {
      ElMessage.warning(result.message || '取消请求已处理')
      await reloadAll()
    }
  } catch (error: any) {
    ElMessage.error(error.message || '取消失败')
    await reloadAll()
  }
}

async function clearTasks() {
  try {
    await ElMessageBox.confirm('确定清空所有已结束任务记录？', '确认操作', {
      type: 'warning',
    })
    await apiTasks.clearTasks()
    ElMessage.success('已清空')
    await reloadAll()
  } catch {
    // cancelled
  }
}

function viewTaskDetail(task: Task) {
  void focusTask(task, 'logs')
}

function filterLogs() {
  nextTick(() => scrollToBottom())
}

function clearLogsDisplay() {
  if (logFilter.value === 'task') {
    selectedTaskLogs.value = []
  } else {
    allLogs.value = []
  }
}

async function checkDataFresh() {
  checkingData.value = true
  try {
    // 检查是否需要更新数据的逻辑
    await apiTasks.getOverview()
    ElMessage.success('数据状态已更新')
    await reloadAll()
  } finally {
    checkingData.value = false
  }
}

function handleLogScroll() {
  const el = logRef.value
  if (!el) return
  const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100
  autoScroll.value = isNearBottom
}

function scrollToBottom() {
  if (autoScroll.value && logRef.value) {
    logRef.value.scrollTop = logRef.value.scrollHeight
  }
}

// WebSocket 连接
function connectTaskSocket(taskId: number) {
  lastTaskSocketId = taskId
  disconnectTaskSocket()
  const wsUrl = buildWebSocketUrl(`/ws/tasks/${taskId}`)
  ws = new WebSocket(wsUrl)
  taskSocketState.value = 'reconnecting'

  ws.onopen = () => {
    taskSocketState.value = 'connected'
    socketReconnectAttempts.value = 0
  }
  ws.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data)
      if (payload.type === 'log') {
        const log: TaskLogItem = {
          id: Date.now(),
          task_id: taskId,
          log_time: payload.timestamp,
          level: payload.log_type || 'info',
          stage: undefined,
          message: payload.message,
        }
        selectedTaskLogs.value.push(log)
        allLogs.value.push(log)
        scrollToBottom()
      }
    } catch {
      // ignore
    }
  }
  ws.onclose = () => {
    if (!lastTaskSocketId) {
      taskSocketState.value = 'disconnected'
      return
    }
    taskSocketState.value = 'polling'
    scheduleTaskReconnect(lastTaskSocketId)
  }
  ws.onerror = () => {
    taskSocketState.value = 'polling'
  }
}

function disconnectTaskSocket() {
  if (ws) {
    ws.onclose = null
    ws.close()
    ws = null
  }
  taskSocketState.value = lastTaskSocketId ? 'polling' : 'disconnected'
}

function connectOpsSocket() {
  disconnectOpsSocket()
  const wsUrl = buildWebSocketUrl('/ws/ops')
  opsWs = new WebSocket(wsUrl)
  opsSocketState.value = 'reconnecting'

  opsWs.onopen = () => {
    opsSocketState.value = 'connected'
    socketReconnectAttempts.value = 0
  }
  opsWs.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data)
      if (message?.payload) {
        applyTaskUpdate(message.payload)
      }
    } catch {
      // ignore
    }
  }
  opsWs.onclose = () => {
    opsSocketState.value = 'polling'
    scheduleOpsReconnect()
  }
  opsWs.onerror = () => {
    opsSocketState.value = 'polling'
  }
}

function disconnectOpsSocket() {
  if (opsWs) {
    opsWs.onclose = null
    opsWs.close()
    opsWs = null
  }
  opsSocketState.value = 'disconnected'
}

function disconnectSockets() {
  disconnectTaskSocket()
  disconnectOpsSocket()
}

function reconnectSocketsNow() {
  clearReconnectTimers()
  connectOpsSocket()
  if (selectedTask.value) {
    connectTaskSocket(selectedTask.value.id)
  }
}

function applyTaskUpdate(task: Task) {
  const runningIndex = runningTasks.value.findIndex((t) => t.id === task.id)
  const isRunning = task.status === 'pending' || task.status === 'running'

  if (isRunning) {
    if (runningIndex >= 0) {
      runningTasks.value[runningIndex] = task
    } else {
      runningTasks.value.unshift(task)
    }
  } else if (runningIndex >= 0) {
    runningTasks.value.splice(runningIndex, 1)
  }

  if (selectedTask.value?.id === task.id) {
    selectedTask.value = task
  }

  if (isBootstrapTask(task) && isRunning) {
    rememberBootstrapTask(task)
  }

  if (bootstrapFinished.value) {
    clearInitTaskViewState()
  } else {
    persistViewState()
  }
}

let poller: ReturnType<typeof setInterval> | null = null

function startPoller() {
  stopPoller()
  poller = setInterval(async () => {
    if (document.visibilityState === 'hidden') return
    if (opsWs?.readyState === WebSocket.OPEN && runningTasks.value.length > 0) return

    await reloadAll()
  }, 5000)
}

function stopPoller() {
  if (poller) {
    clearInterval(poller)
    poller = null
  }
}

function scheduleOpsReconnect() {
  if (opsReconnectTimer) return
  socketReconnectAttempts.value += 1
  opsSocketState.value = 'reconnecting'
  opsReconnectTimer = setTimeout(() => {
    opsReconnectTimer = null
    connectOpsSocket()
  }, getReconnectDelay())
}

function scheduleTaskReconnect(taskId: number) {
  if (taskReconnectTimer) return
  socketReconnectAttempts.value += 1
  taskSocketState.value = 'reconnecting'
  taskReconnectTimer = setTimeout(() => {
    taskReconnectTimer = null
    connectTaskSocket(taskId)
  }, getReconnectDelay())
}

function clearReconnectTimers() {
  if (opsReconnectTimer) {
    clearTimeout(opsReconnectTimer)
    opsReconnectTimer = null
  }
  if (taskReconnectTimer) {
    clearTimeout(taskReconnectTimer)
    taskReconnectTimer = null
  }
}

function getReconnectDelay() {
  return Math.min(15000, 1000 * Math.max(1, socketReconnectAttempts.value))
}

function goToConfig() {
  router.push('/config')
}

function isBootstrapTask(task: Task | null | undefined) {
  return Boolean(task && task.task_type === 'full_update')
}

function rememberBootstrapTask(task: Task | null | undefined) {
  if (!task) return
  saveInitTaskViewState({
    activeTab: activeTab.value,
    selectedTaskId: task.id,
    bootstrapTaskId: task.id,
  })
}

function persistViewState() {
  if (bootstrapFinished.value) {
    clearInitTaskViewState()
    return
  }

  saveInitTaskViewState({
    activeTab: activeTab.value,
    selectedTaskId: selectedTask.value?.id || null,
    bootstrapTaskId: initializationRunningTask.value?.id || latestFailedBootstrapTask.value?.id || null,
  })
}

async function restoreTaskSelection() {
  const state = loadInitTaskViewState()
  const candidates = [...runningTasks.value, ...historyTasks.value]
  const targetId = state.selectedTaskId || state.bootstrapTaskId

  const target = (
    candidates.find((task) => task.id === targetId) ||
    initializationRunningTask.value ||
    latestFailedBootstrapTask.value ||
    runningTasks.value[0] ||
    null
  )

  if (!target) {
    selectedTask.value = null
    lastTaskSocketId = null
    disconnectTaskSocket()
    return
  }

  if (selectedTask.value?.id === target.id) return
  await selectTask(target)
}

async function recoverInitializationTask() {
  try {
    const runningResp = await apiTasks.getRunning()
    runningTasks.value = runningResp.tasks
    const target = runningTasks.value.find((task) => isBootstrapTask(task))
    if (target) {
      rememberBootstrapTask(target)
      await focusTask(target, 'logs')
      ElMessage.warning(`检测到已有初始化任务 #${target.id}，已恢复到日志视图`)
      return true
    }
  } catch (error) {
    console.error('Failed to recover initialization task:', error)
  }
  return false
}

// 格式化方法
function getTaskTypeLabel(taskType: string): string {
  const labels: Record<string, string> = {
    full_update: '全量更新',
    single_analysis: '单股分析',
    tomorrow_star: '明日之星',
  }
  return labels[taskType] || taskType
}

function getStatusType(status: string): string {
  const types: Record<string, string> = {
    success: 'success',
    warning: 'warning',
    error: 'danger',
    info: 'info',
    completed: 'success',
    running: 'primary',
    failed: 'danger',
    pending: 'warning',
    cancelled: 'info',
  }
  return types[status] || 'info'
}

function getStageLabel(stage?: string | null): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    starting: '启动中',
    preparing: '准备中',
    fetch_data: '抓取数据',
    build_pool: '构建流动池',
    build_candidates: '生成候选',
    pre_filter: '前置过滤',
    score_review: '量化复核',
    finalize: '收尾输出',
    completed: '已完成',
  }
  return stage ? (labels[stage] || stage) : '-'
}

function formatDateTime(dateStr?: string): string {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatLogTime(dateStr?: string): string {
  if (!dateStr) return '--:--:--'
  return new Date(dateStr).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function formatLatestDate(date?: string | number | null): string {
  if (!date) return '-'
  if (typeof date === 'number') {
    return new Date(date * 1000).toLocaleDateString('zh-CN')
  }
  return date
}

function formatEnvKey(key: string): string {
  const keys: Record<string, string> = {
    app_name: '应用名称',
    debug: '调试模式',
    host: '主机',
    port: '端口',
    python_version: 'Python版本',
    platform: '系统平台',
    timezone: '时区',
    data_dir: '数据目录',
    db_dir: '数据库目录',
    raw_data_dir: '原始数据目录',
    review_dir: '评审目录',
    logs_dir: '日志目录',
    tushare_configured: 'Tushare配置',
    zhipuai_configured: '智谱配置',
    dashscope_configured: '通义配置',
    gemini_configured: 'Gemini配置',
    default_reviewer: '默认评审器',
    total_stocks: '股票总数',
    latest_date: '最新日期',
  }
  return keys[key] || key
}

function formatEnvValue(value: any): string {
  if (typeof value === 'boolean') return value ? '已配置' : '未配置'
  if (value == null || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function getPrimitiveItems(items: Record<string, any>): Record<string, any> {
  const result: Record<string, any> = {}
  for (const [key, value] of Object.entries(items)) {
    if (value === null || value === undefined) continue
    if (typeof value === 'boolean' || typeof value === 'number' || typeof value === 'string') {
      result[key] = value
    }
  }
  return result
}

function getCheckStatusLabel(status: string) {
  const labels: Record<string, string> = {
    success: '正常',
    warning: '待处理',
    error: '异常',
    info: '未完成',
  }
  return labels[status] || status
}

function buildDiagnosticsSummary() {
  const lines = [
    `生成时间: ${diagnostics.value?.generated_at || new Date().toISOString()}`,
    `推送状态: ${socketStatusLabel.value}`,
    `运行中任务: ${runningTasks.value.length}`,
  ]
  for (const check of diagnosticChecks.value) {
    lines.push(`[${getCheckStatusLabel(check.status)}] ${check.label}: ${check.summary}`)
    if (check.action) {
      lines.push(`建议: ${check.action}`)
    }
  }
  if (initializationRunningTask.value) {
    lines.push(`初始化任务: #${initializationRunningTask.value.id} / ${getStageLabel(initializationRunningTask.value.task_stage)} / ${initializationRunningTask.value.progress}%`)
  }
  if (latestFailedBootstrapTask.value?.error_message) {
    lines.push(`最近失败: ${latestFailedBootstrapTask.value.error_message}`)
  }
  return lines.join('\n')
}

function buildWebSocketUrl(path: string) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${path}`
}
</script>

<style scoped lang="scss">
.ops-page {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;

  .page-header {
    margin-bottom: 20px;

    h2 {
      margin: 0;
      font-size: 24px;
      font-weight: 600;
    }
  }

  .ops-tabs {
    :deep(.el-tabs__header) {
      margin-bottom: 20px;
    }

    :deep(.el-tabs__nav-wrap::after) {
      display: none;
    }
  }

  .tab-content {
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .connectivity-card,
  .diagnostics-card {
    border-radius: 14px;
  }

  .connectivity-card__row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
  }

  .connectivity-card__status,
  .connectivity-card__actions {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }

  .connectivity-card__label {
    font-weight: 600;
    color: var(--color-text-primary);
  }

  .connectivity-card__desc {
    margin-top: 10px;
    color: var(--color-text-secondary);
    line-height: 1.7;
  }

  .diagnostics-generated-at {
    font-size: 12px;
    color: var(--color-text-light);
  }

  .diagnostics-list {
    display: grid;
    gap: 12px;
  }

  .diagnostic-item {
    padding: 14px 16px;
    border-radius: 12px;
    border: 1px solid #e2e8f0;
    background: #f8fafc;
  }

  .diagnostic-item__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 8px;
  }

  .diagnostic-item__title {
    font-weight: 600;
    color: var(--color-text-primary);
  }

  .diagnostic-item__summary,
  .diagnostic-item__action {
    line-height: 1.7;
    color: var(--color-text-secondary);
  }

  .diagnostic-item__action {
    margin-top: 6px;
    font-size: 13px;
  }

  // 首次初始化卡片
  .bootstrap-card {
    .bootstrap-content {
      display: flex;
      flex-direction: column;
      gap: 20px;
    }

    .bootstrap-desc {
      margin: 0;
      color: var(--color-text-secondary);
      line-height: 1.7;
    }

    .bootstrap-notes {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }

    .bootstrap-note {
      padding: 14px 16px;
      border-radius: 12px;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
    }

    .bootstrap-note-label {
      display: block;
      margin-bottom: 6px;
      font-size: 12px;
      font-weight: 600;
      color: var(--color-text-secondary);
    }

    .bootstrap-note-value {
      font-size: 13px;
      line-height: 1.7;
      color: var(--color-text-primary);
    }

    .bootstrap-steps {
      display: flex;
      gap: 16px;
      justify-content: center;
      flex-wrap: wrap;
    }

    .bootstrap-step {
      display: flex;
      gap: 12px;
      padding: 16px;
      border-radius: 12px;
      border: 1px solid #e5e7eb;
      flex: 1;
      max-width: 300px;

      &.is-done {
        border-color: var(--color-success);
        background: #f0fdf4;
      }

      &.is-pending {
        background: #f8fafc;
      }
    }

    .step-indicator {
      width: 32px;
      height: 32px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      color: #fff;
      background: var(--color-primary);
      flex-shrink: 0;
    }

    .is-done .step-indicator {
      background: var(--color-success);
    }

    .step-title {
      font-weight: 600;
      color: var(--color-text-primary);
    }

    .step-meta {
      margin-top: 4px;
      font-size: 12px;
      color: var(--color-text-secondary);
    }

    .bootstrap-actions {
      display: flex;
      justify-content: center;
      flex-wrap: wrap;
      gap: 12px;
    }
  }

  // 操作卡片
  .action-card {
    .action-buttons {
      display: flex;
      gap: 12px;
      align-items: center;
    }

    .running-hint {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 12px;
      color: var(--color-warning);
      font-size: 14px;
    }
  }

  // 任务卡片
  .tasks-card {
    :deep(.el-card__body) {
      padding: 16px;
    }
  }

  .running-tasks-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .task-item {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 16px;
    border-radius: 10px;
    border: 1px solid #e5e7eb;
    background: #fff;
    cursor: pointer;
    transition: all 0.2s;

    &:hover {
      border-color: var(--color-primary);
      box-shadow: 0 2px 8px rgba(0, 180, 216, 0.15);
    }

    &.is-selected {
      border-color: var(--color-primary);
      background: #f0f9ff;
    }
  }

  .task-main {
    flex: 1;
    min-width: 0;
  }

  .task-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
  }

  .task-id {
    font-weight: 600;
    color: var(--color-text-primary);
  }

  .task-type {
    color: var(--color-text-secondary);
  }

  .task-stage {
    font-size: 13px;
    color: var(--color-text-secondary);
    margin-bottom: 8px;
  }

  // 日志卡片
  .logs-card {
    .log-controls {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .log-actions {
      display: flex;
      align-items: center;
      gap: 12px;
    }
  }

  .log-container {
    height: calc(100vh - 320px);
    min-height: 400px;
    overflow-y: auto;
    background: #0f172a;
    border-radius: 10px;
    padding: 16px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 13px;
    line-height: 1.6;
  }

  .log-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: #64748b;
    gap: 12px;

    .el-icon {
      font-size: 48px;
    }

    p {
      margin: 0;
    }
  }

  .log-line {
    display: grid;
    grid-template-columns: 80px 60px 1fr;
    gap: 12px;
    padding: 6px 8px;
    border-radius: 6px;
    color: #e2e8f0;

    & + .log-line {
      margin-top: 2px;
    }

    &.log-error {
      background: rgba(239, 68, 68, 0.2);
    }

    &.log-warning {
      background: rgba(245, 158, 11, 0.15);
    }

    &.log-success {
      background: rgba(16, 185, 129, 0.15);
    }
  }

  .log-time {
    color: #64748b;
  }

  .log-level {
    color: #94a3b8;
    font-weight: 600;
  }

  // 状态管理
  .health-card {
    .health-summary {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 20px;
    }

    .health-item {
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 16px;
      border-radius: 12px;
      background: #fef2f2;
      border: 1px solid #fecaca;

      &.is-healthy {
        background: #f0fdf4;
        border-color: #bbf7d0;
      }

      .health-icon {
        width: 48px;
        height: 48px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 24px;
        color: #fff;
        background: var(--color-danger);

        .is-spinning {
          animation: spin 1s linear infinite;
        }
      }

      &.is-healthy .health-icon {
        background: var(--color-success);
      }

      .health-info {
        flex: 1;
      }

      .health-title {
        font-weight: 600;
        color: var(--color-text-primary);
        margin-bottom: 4px;
      }

      .health-desc {
        font-size: 13px;
        color: var(--color-text-secondary);
      }
    }
  }

  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }

  .detail-card {
    .detail-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
    }

    .detail-item {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 16px;
      background: var(--color-bg-light);
      border-radius: 10px;

      .detail-label {
        font-size: 13px;
        color: var(--color-text-secondary);
      }

      .detail-value {
        font-size: 20px;
        font-weight: 700;
        color: var(--color-text-primary);

        small {
          font-size: 13px;
          font-weight: 400;
          color: var(--color-text-secondary);
          margin-left: 4px;
        }
      }
    }
  }

  .env-summary-card {
    .env-summary-grid {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .env-section {
      .env-section-title {
        font-weight: 600;
        color: var(--color-text-primary);
        margin-bottom: 12px;
      }

      .env-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
      }
    }
  }

  .env-collapse {
    border: none;

    :deep(.el-collapse-item__header) {
      border-radius: 12px;
      padding: 0 16px;
      background: var(--color-bg-light);
      margin-bottom: 12px;
    }

    :deep(.el-collapse-item__wrap) {
      border: none;
      background: transparent;
    }

    .collapse-title {
      font-weight: 600;
      color: var(--color-text-primary);
    }

    .env-details-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 20px;
    }

    .env-detail-section {
      background: var(--color-bg-light);
      border-radius: 10px;
      padding: 16px;
    }

    .env-detail-title {
      font-weight: 600;
      color: var(--color-text-primary);
      margin-bottom: 12px;
    }

    .env-detail-items {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .env-detail-item {
      display: flex;
      justify-content: space-between;
      padding: 8px 0;
      border-bottom: 1px dashed #e5e7eb;

      &:last-child {
        border-bottom: none;
      }
    }

    .env-detail-key {
      color: var(--color-text-secondary);
    }

    .env-detail-value {
      font-weight: 500;
      color: var(--color-text-primary);
    }
  }
}

@media (max-width: 768px) {
  .ops-page {
    padding: 16px;

    .connectivity-card__row {
      flex-direction: column;
      align-items: flex-start;
    }

    .health-summary {
      grid-template-columns: 1fr;
    }

    .detail-grid {
      grid-template-columns: repeat(2, 1fr);
    }

    .env-details-grid {
      grid-template-columns: 1fr;
    }

    .bootstrap-steps {
      flex-direction: column;
    }

    .bootstrap-notes {
      grid-template-columns: 1fr;
    }

    .action-buttons {
      flex-direction: column;
    }
  }
}

@media (max-width: 480px) {
  .ops-page {
    .detail-grid {
      grid-template-columns: 1fr;
    }

    .connectivity-card__actions {
      width: 100%;
    }
  }
}
</style>
