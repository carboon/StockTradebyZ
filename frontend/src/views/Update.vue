<template>
  <div class="task-center-page">
    <div class="page-header">
      <div>
        <h2>任务中心</h2>
        <p>面向运维人员，统一查看后台任务、环境信息与运行日志。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="pageLoading" @click="reloadAll">
          刷新
        </el-button>
      </div>
    </div>

    <div v-if="overview.alerts.length > 0" class="alert-stack">
      <el-alert
        v-for="(alert, index) in overview.alerts"
        :key="`${alert.level}-${index}`"
        :title="alert.title"
        :type="getAlertType(alert.level)"
        :description="alert.message"
        :closable="false"
        show-icon
      />
    </div>

    <div class="overview-grid">
      <el-card v-for="card in overview.cards" :key="card.key" class="overview-card">
        <div class="overview-label">{{ card.label }}</div>
        <div class="overview-value" :class="`is-${card.status}`">{{ card.value }}</div>
        <div class="overview-meta">{{ card.meta || '-' }}</div>
      </el-card>
    </div>

    <el-card class="bootstrap-card">
      <template #header>
        <div class="card-header">
          <span>首次初始化引导</span>
          <el-tag :type="bootstrapStatusTagType" size="small">
            {{ bootstrapStatusLabel }}
          </el-tag>
        </div>
      </template>

      <div class="bootstrap-layout">
        <div class="bootstrap-main">
          <div class="bootstrap-title">{{ bootstrapTitle }}</div>
          <div class="bootstrap-description">{{ bootstrapDescription }}</div>

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
        </div>

        <div class="bootstrap-actions">
          <el-button
            type="primary"
            :disabled="!canStartBootstrap"
            :loading="bootstrapStarting"
            @click="startBootstrap"
          >
            启动首次初始化
          </el-button>
          <el-button @click="reloadAll">
            重新检查
          </el-button>
          <div class="bootstrap-hint">{{ bootstrapActionHint }}</div>
        </div>
      </div>
    </el-card>

    <el-tabs v-model="activeTab" class="task-tabs">
      <el-tab-pane label="运行中" name="running">
        <div class="tab-section">
          <el-row :gutter="20">
            <el-col :span="14">
              <el-card>
                <template #header>
                  <div class="card-header">
                    <span>运行中任务</span>
                    <el-tag size="small" type="warning">{{ runningTasks.total }}</el-tag>
                  </div>
                </template>

                <el-empty v-if="runningTasks.total === 0" description="当前没有运行中任务" :image-size="80" />
                <el-table
                  v-else
                  :data="runningTasks.tasks"
                  highlight-current-row
                  @row-click="selectTask"
                >
                  <el-table-column prop="id" label="ID" width="70" />
                  <el-table-column label="任务" min-width="220">
                    <template #default="{ row }">
                      <div class="task-main">
                        <div class="task-title">{{ getTaskTypeLabel(row.task_type) }}</div>
                        <div class="task-summary">{{ row.summary || '-' }}</div>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column prop="task_stage" label="阶段" width="130">
                    <template #default="{ row }">
                      {{ getStageLabel(row.task_stage) }}
                    </template>
                  </el-table-column>
                  <el-table-column prop="progress" label="进度" width="140">
                    <template #default="{ row }">
                      <el-progress :percentage="row.progress" :stroke-width="6" />
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="110" align="center">
                    <template #default="{ row }">
                      <el-button text type="danger" @click.stop="cancelTask(row)">
                        取消
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </el-card>
            </el-col>

            <el-col :span="10">
              <el-card class="log-card">
                <template #header>
                  <div class="card-header">
                    <span>实时日志</span>
                    <el-tag v-if="selectedTask" size="small" type="info">
                      #{{ selectedTask.id }}
                    </el-tag>
                  </div>
                </template>

                <el-empty v-if="!selectedTask" description="请选择左侧任务" :image-size="70" />
                <div v-else ref="logRef" class="log-container">
                  <div v-if="selectedTaskLogs.length === 0" class="log-empty">暂无日志</div>
                  <div
                    v-for="log in selectedTaskLogs"
                    :key="log.id || `${log.log_time}-${log.message}`"
                    class="log-line"
                    :class="`log-${log.level}`"
                  >
                    <span class="log-time">{{ formatLogTime(log.log_time) }}</span>
                    <span class="log-stage">{{ getStageLabel(log.stage) }}</span>
                    <span class="log-message">{{ log.message }}</span>
                  </div>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </div>
      </el-tab-pane>

      <el-tab-pane label="历史任务" name="history">
        <div class="tab-section">
          <el-card>
            <template #header>
              <div class="card-header">
                <span>历史任务</span>
                <div class="inline-actions">
                  <el-select v-model="historyStatus" placeholder="状态筛选" clearable style="width: 140px" @change="loadHistoryTasks">
                    <el-option label="运行中" value="running" />
                    <el-option label="排队中" value="pending" />
                    <el-option label="已完成" value="completed" />
                    <el-option label="失败" value="failed" />
                    <el-option label="已取消" value="cancelled" />
                  </el-select>
                  <el-button text type="danger" :icon="Delete" @click="clearTasks">
                    清空已结束任务
                  </el-button>
                </div>
              </div>
            </template>

            <el-table :data="historyTasks.tasks" @row-click="openTaskDetail">
              <el-table-column prop="id" label="ID" width="70" />
              <el-table-column label="任务类型" width="120">
                <template #default="{ row }">
                  {{ getTaskTypeLabel(row.task_type) }}
                </template>
              </el-table-column>
              <el-table-column label="触发来源" width="100">
                <template #default="{ row }">
                  <el-tag :type="getSourceType(row.trigger_source)" size="small">
                    {{ getSourceLabel(row.trigger_source) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag :type="getStatusType(row.status)" size="small">
                    {{ row.status }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="阶段" width="120">
                <template #default="{ row }">
                  {{ getStageLabel(row.task_stage) }}
                </template>
              </el-table-column>
              <el-table-column label="摘要" min-width="260" show-overflow-tooltip>
                <template #default="{ row }">
                  {{ row.summary || '-' }}
                </template>
              </el-table-column>
              <el-table-column label="创建时间" width="180">
                <template #default="{ row }">
                  {{ formatDateTime(row.created_at) }}
                </template>
              </el-table-column>
              <el-table-column label="耗时" width="110">
                <template #default="{ row }">
                  {{ getDuration(row) }}
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </div>
      </el-tab-pane>

      <el-tab-pane label="环境信息" name="environment">
        <div class="tab-section">
          <el-row :gutter="20">
            <el-col v-for="section in environment.sections" :key="section.key" :span="12">
              <el-card class="env-card">
                <template #header>
                  <span>{{ section.label }}</span>
                </template>
                <div class="env-list">
                  <div v-for="(value, key) in section.items" :key="String(key)" class="env-item">
                    <span class="env-key">{{ formatEnvKey(String(key)) }}</span>
                    <span class="env-value">{{ formatEnvValue(value) }}</span>
                  </div>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </div>
      </el-tab-pane>

      <el-tab-pane label="数据状态" name="status">
        <div class="tab-section">
          <el-row :gutter="20">
            <el-col :span="6" v-for="item in statusItems" :key="item.key">
              <el-card class="status-card">
                <div class="status-item" :class="item.exists ? 'status-ok' : 'status-missing'">
                  <div class="status-icon">
                    <el-icon :size="28">
                      <component :is="item.icon" />
                    </el-icon>
                  </div>
                  <div class="status-label">{{ item.label }}</div>
                  <div class="status-value">{{ item.exists ? '正常' : '缺失' }}</div>
                  <div class="status-meta">{{ item.meta }}</div>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="detailVisible" title="任务详情" size="50%">
      <template v-if="detailTask">
        <div class="detail-grid">
          <div class="detail-item"><span>ID</span><strong>#{{ detailTask.id }}</strong></div>
          <div class="detail-item"><span>类型</span><strong>{{ getTaskTypeLabel(detailTask.task_type) }}</strong></div>
          <div class="detail-item"><span>来源</span><strong>{{ getSourceLabel(detailTask.trigger_source) }}</strong></div>
          <div class="detail-item"><span>状态</span><strong>{{ detailTask.status }}</strong></div>
          <div class="detail-item"><span>阶段</span><strong>{{ getStageLabel(detailTask.task_stage) }}</strong></div>
          <div class="detail-item"><span>进度</span><strong>{{ detailTask.progress }}%</strong></div>
        </div>
        <el-divider />
        <div class="detail-block">
          <h4>任务摘要</h4>
          <p>{{ detailTask.summary || '-' }}</p>
        </div>
        <div class="detail-block">
          <h4>参数</h4>
          <pre>{{ formatJson(detailTask.params_json) }}</pre>
        </div>
        <div class="detail-block">
          <h4>结果</h4>
          <pre>{{ formatJson(detailTask.result_json) }}</pre>
        </div>
        <div class="detail-block" v-if="detailTask.error_message">
          <h4>错误信息</h4>
          <pre>{{ detailTask.error_message }}</pre>
        </div>
        <div class="detail-block">
          <div class="card-header">
            <h4>日志</h4>
            <el-button text @click="loadTaskLogs(detailTask.id)">刷新日志</el-button>
          </div>
          <div class="drawer-log-container">
            <div v-for="log in detailLogs" :key="log.id" class="log-line" :class="`log-${log.level}`">
              <span class="log-time">{{ formatLogTime(log.log_time) }}</span>
              <span class="log-stage">{{ getStageLabel(log.stage) }}</span>
              <span class="log-message">{{ log.message }}</span>
            </div>
          </div>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import {
  DataAnalysis,
  Delete,
  Document,
  FolderOpened,
  Picture,
  Refresh,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { apiTasks } from '@/api'
import type {
  DataStatus,
  Task,
  TaskEnvironmentResponse,
  TaskLogItem,
  TaskOverviewResponse,
  TaskRunningResponse,
  TaskListResponse,
} from '@/types'
import { useConfigStore } from '@/store/config'

const activeTab = ref('running')
const pageLoading = ref(false)
const detailVisible = ref(false)
const historyStatus = ref('')
const RUNNING_POLL_INTERVAL_MS = 5000
const IDLE_POLL_INTERVAL_MS = 30000
const OVERVIEW_REFRESH_INTERVAL_MS = 30000

const overview = ref<TaskOverviewResponse>({ cards: [], alerts: [] })
const runningTasks = ref<TaskRunningResponse>({ tasks: [], total: 0 })
const historyTasks = ref<TaskListResponse>({ tasks: [], total: 0 })
const environment = ref<TaskEnvironmentResponse>({ sections: [] })
const status = ref<DataStatus>({
  raw_data: { exists: false, count: 0 },
  candidates: { exists: false, count: 0 },
  analysis: { exists: false, count: 0 },
  kline: { exists: false, count: 0 },
})

const selectedTask = ref<Task | null>(null)
const selectedTaskLogs = ref<TaskLogItem[]>([])
const detailTask = ref<Task | null>(null)
const detailLogs = ref<TaskLogItem[]>([])
const logRef = ref<HTMLElement>()
const bootstrapStarting = ref(false)
let ws: WebSocket | null = null
let opsWs: WebSocket | null = null
let runningPoller: ReturnType<typeof setInterval> | null = null
const lastOverviewRefreshAt = ref(0)
const opsWsConnected = ref(false)
const configStore = useConfigStore()

const statusItems = computed(() => [
  {
    key: 'raw',
    label: '原始数据',
    icon: Document,
    exists: status.value.raw_data.exists,
    meta: `${status.value.raw_data.count} 只股票`,
  },
  {
    key: 'candidates',
    label: '候选数据',
    icon: DataAnalysis,
    exists: status.value.candidates.exists,
    meta: status.value.candidates.latest_date || '无数据',
  },
  {
    key: 'analysis',
    label: '评分数据',
    icon: FolderOpened,
    exists: status.value.analysis.exists,
    meta: `${status.value.analysis.count} 个日期`,
  },
  {
    key: 'kline',
    label: 'K线资源',
    icon: Picture,
    exists: status.value.kline.exists,
    meta: `${status.value.kline.count} 张图片`,
  },
])
const hasRawData = computed(() => status.value.raw_data.exists)
const hasCandidateData = computed(() => status.value.candidates.exists)
const hasAnalysisData = computed(() => status.value.analysis.exists)
const bootstrapFinished = computed(() => hasRawData.value && hasCandidateData.value && hasAnalysisData.value)
const bootstrapRunning = computed(() => runningTasks.value.tasks.some((task) => ['full_update', 'tomorrow_star'].includes(task.task_type)))
const bootstrapBlockedByConfig = computed(() => !configStore.tushareReady)
const canStartBootstrap = computed(() => !bootstrapBlockedByConfig.value && !bootstrapFinished.value && !bootstrapRunning.value)
const bootstrapStatusLabel = computed(() => {
  if (bootstrapFinished.value) return '已完成'
  if (bootstrapRunning.value) return '进行中'
  if (bootstrapBlockedByConfig.value) return '待配置'
  return '待执行'
})
const bootstrapStatusTagType = computed(() => {
  if (bootstrapFinished.value) return 'success'
  if (bootstrapRunning.value) return 'warning'
  if (bootstrapBlockedByConfig.value) return 'info'
  return 'primary'
})
const bootstrapTitle = computed(() => {
  if (bootstrapFinished.value) return '系统基础数据已经就绪'
  if (bootstrapRunning.value) return '首次初始化任务正在执行'
  if (bootstrapBlockedByConfig.value) return '请先完成 Tushare 配置'
  return '当前尚未完成首次初始化'
})
const bootstrapDescription = computed(() => {
  if (bootstrapFinished.value) {
    return '原始数据、候选结果和评分结果均已生成，明日之星与单股诊断可以正常使用。'
  }
  if (bootstrapRunning.value) {
    return '系统正在抓取行情、构建候选池并生成评分结果。保持当前页面即可查看实时进度。'
  }
  if (bootstrapBlockedByConfig.value) {
    return configStore.tushareStatus?.message || '请先进入配置页填写并验证 TUSHARE_TOKEN。'
  }
  return '首次初始化会顺序完成数据抓取、候选生成与量化复核。完成后，明日之星和单股诊断页面才会展示完整数据。'
})
const bootstrapActionHint = computed(() => {
  if (bootstrapFinished.value) return '无需额外操作。后续系统会根据交易日变化自动判断是否更新。'
  if (bootstrapRunning.value) return '初始化期间可以切换到“运行中”查看任务日志。'
  if (bootstrapBlockedByConfig.value) return '请先前往配置页完成数据源配置，然后回到这里执行初始化。'
  return '建议首次部署后先执行一次初始化，等待任务完成后再使用业务页面。'
})
const bootstrapSteps = computed(() => [
  {
    key: 'config',
    index: 1,
    title: '配置数据源',
    meta: bootstrapBlockedByConfig.value ? '当前未完成' : 'Tushare 已验证通过',
    done: !bootstrapBlockedByConfig.value,
  },
  {
    key: 'raw',
    index: 2,
    title: '抓取原始数据',
    meta: hasRawData.value ? `${status.value.raw_data.count} 只股票` : '尚未生成原始数据',
    done: hasRawData.value,
  },
  {
    key: 'candidate',
    index: 3,
    title: '生成候选结果',
    meta: hasCandidateData.value ? String(status.value.candidates.latest_date || '已生成') : '尚未生成候选结果',
    done: hasCandidateData.value,
  },
  {
    key: 'analysis',
    index: 4,
    title: '生成分析结果',
    meta: hasAnalysisData.value ? `${status.value.analysis.count} 个日期` : '尚未生成评分结果',
    done: hasAnalysisData.value,
  },
])

onMounted(async () => {
  await configStore.checkTushareStatus()
  await reloadAll()
  connectOpsSocket()
  startRunningPoller()
})

onUnmounted(() => {
  stopRunningPoller()
  disconnectTaskSocket()
  disconnectOpsSocket()
})

async function reloadAll() {
  pageLoading.value = true
  try {
    await configStore.checkTushareStatus()
    const [overviewData, runningData, historyData, environmentData, statusData] = await Promise.all([
      apiTasks.getOverview(),
      apiTasks.getRunning(),
      apiTasks.getAll(historyStatus.value || undefined, 50),
      apiTasks.getEnvironment(),
      apiTasks.getStatus(),
    ])

    overview.value = overviewData
    runningTasks.value = runningData
    historyTasks.value = historyData
    environment.value = environmentData
    status.value = statusData
    lastOverviewRefreshAt.value = Date.now()

    if (!selectedTask.value && runningData.tasks.length > 0) {
      await selectTask(runningData.tasks[0])
    }
  } finally {
    pageLoading.value = false
  }
}

async function startBootstrap() {
  if (!canStartBootstrap.value) return

  bootstrapStarting.value = true
  try {
    const result = await apiTasks.startUpdate('quant', false, 1)
    ElMessage.success(`首次初始化任务已启动 #${result.task.id}`)
    activeTab.value = 'running'
    await reloadAll()
    const createdTask = runningTasks.value.tasks.find((task) => task.id === result.task.id)
    if (createdTask) {
      await selectTask(createdTask)
    }
  } catch (error: any) {
    ElMessage.error(error.message || '启动首次初始化失败')
  } finally {
    bootstrapStarting.value = false
  }
}

async function loadHistoryTasks() {
  historyTasks.value = await apiTasks.getAll(historyStatus.value || undefined, 50)
}

async function selectTask(task: Task) {
  selectedTask.value = task
  await loadTaskLogs(task.id, true)
  connectTaskSocket(task.id)
}

async function loadTaskLogs(taskId: number, syncSelected: boolean = false) {
  const data = await apiTasks.getLogs(taskId)
  if (syncSelected && selectedTask.value?.id === taskId) {
    selectedTaskLogs.value = data.logs
    scrollLogsToBottom()
  }
  if (detailTask.value?.id === taskId) {
    detailLogs.value = data.logs
  }
}

async function cancelTask(task: Task) {
  try {
    await apiTasks.cancel(task.id)
    ElMessage.success(`任务 #${task.id} 已取消`)
    await reloadAll()
    if (selectedTask.value?.id === task.id) {
      await loadTaskLogs(task.id, true)
    }
  } catch (error: any) {
    ElMessage.error(error.message || '取消任务失败')
  }
}

async function clearTasks() {
  try {
    await ElMessageBox.confirm(
      '将清空所有已结束任务记录，此操作不可恢复。',
      '确认清空',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
    await apiTasks.clearTasks()
    ElMessage.success('已清空已结束任务')
    await reloadAll()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error(error.message || '清空失败')
    }
  }
}

async function openTaskDetail(task: Task) {
  detailTask.value = task
  detailVisible.value = true
  const data = await apiTasks.getLogs(task.id)
  detailLogs.value = data.logs
}

function startRunningPoller() {
  stopRunningPoller()
  runningPoller = setInterval(async () => {
    try {
      if (document.visibilityState === 'hidden') {
        return
      }

      if (opsWsConnected.value && runningTasks.value.total > 0) {
        return
      }

      const hasRunningTasks = runningTasks.value.total > 0
      const idleTooSoon = !hasRunningTasks && Date.now() - lastOverviewRefreshAt.value < IDLE_POLL_INTERVAL_MS
      if (idleTooSoon) {
        return
      }

      const runningData = await apiTasks.getRunning()
      runningTasks.value = runningData
      const shouldRefreshOverview = hasRunningTasks || Date.now() - lastOverviewRefreshAt.value >= OVERVIEW_REFRESH_INTERVAL_MS
      if (shouldRefreshOverview) {
        overview.value = await apiTasks.getOverview()
        lastOverviewRefreshAt.value = Date.now()
      }

      if (selectedTask.value) {
        const latestTask = runningData.tasks.find((item) => item.id === selectedTask.value?.id)
        if (latestTask) {
          selectedTask.value = latestTask
          await loadTaskLogs(latestTask.id, true)
        } else if (selectedTask.value.status === 'running' || selectedTask.value.status === 'pending') {
          const latestDetail = await apiTasks.get(selectedTask.value.id)
          selectedTask.value = latestDetail
          await loadTaskLogs(latestDetail.id, true)
        }
      }
    } catch (error) {
      console.error('Failed to poll running tasks:', error)
    }
  }, RUNNING_POLL_INTERVAL_MS)
}

function stopRunningPoller() {
  if (runningPoller) {
    clearInterval(runningPoller)
    runningPoller = null
  }
}

function connectTaskSocket(taskId: number) {
  disconnectTaskSocket()

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${window.location.host}/ws/tasks/${taskId}`
  ws = new WebSocket(wsUrl)

  ws.onmessage = async (event) => {
    try {
      const payload = JSON.parse(event.data)
      if (payload.type === 'log') {
        selectedTaskLogs.value.push({
          id: Date.now(),
          task_id: taskId,
          log_time: payload.timestamp,
          level: payload.log_type || 'info',
          stage: undefined,
          message: payload.message,
        })
        scrollLogsToBottom()
      }
    } catch {
      // ignore non-json messages
    }
  }

  ws.onclose = async () => {
    if (selectedTask.value?.id === taskId) {
      await loadTaskLogs(taskId, true)
    }
  }
}

function disconnectTaskSocket() {
  if (ws) {
    ws.close()
    ws = null
  }
}

function connectOpsSocket() {
  disconnectOpsSocket()

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${window.location.host}/ws/ops`
  opsWs = new WebSocket(wsUrl)

  opsWs.onopen = () => {
    opsWsConnected.value = true
  }

  opsWs.onmessage = async (event) => {
    try {
      const message = JSON.parse(event.data)
      if (!message?.type || !message?.payload) return

      const payload = message.payload as Task
      applyOpsTaskUpdate(payload)

      if (selectedTask.value?.id === payload.id) {
        selectedTask.value = { ...selectedTask.value, ...payload }
      }
      if (detailTask.value?.id === payload.id) {
        detailTask.value = { ...detailTask.value, ...payload }
        await loadTaskLogs(payload.id)
      }
      if (selectedTask.value?.id === payload.id) {
        await loadTaskLogs(payload.id, true)
      }
    } catch (error) {
      console.error('Failed to parse ops websocket payload:', error)
    }
  }

  opsWs.onclose = () => {
    opsWsConnected.value = false
  }

  opsWs.onerror = () => {
    opsWsConnected.value = false
  }
}

function disconnectOpsSocket() {
  if (opsWs) {
    opsWs.close()
    opsWs = null
  }
  opsWsConnected.value = false
}

function applyOpsTaskUpdate(task: Task) {
  const runningIndex = runningTasks.value.tasks.findIndex((item) => item.id === task.id)
  const isRunning = task.status === 'pending' || task.status === 'running'

  if (isRunning) {
    if (runningIndex >= 0) {
      runningTasks.value.tasks[runningIndex] = task
    } else {
      runningTasks.value.tasks.unshift(task)
    }
  } else if (runningIndex >= 0) {
    runningTasks.value.tasks.splice(runningIndex, 1)
  }
  runningTasks.value.total = runningTasks.value.tasks.length

  const historyIndex = historyTasks.value.tasks.findIndex((item) => item.id === task.id)
  if (historyIndex >= 0) {
    historyTasks.value.tasks[historyIndex] = task
  } else {
    historyTasks.value.tasks.unshift(task)
  }
  historyTasks.value.total = historyTasks.value.tasks.length

  const overviewRunningCard = overview.value.cards.find((card) => card.key === 'running')
  if (overviewRunningCard) {
    overviewRunningCard.value = String(runningTasks.value.total)
    overviewRunningCard.status = runningTasks.value.total > 0 ? 'warning' : 'success'
  }
}

function scrollLogsToBottom() {
  nextTick(() => {
    if (logRef.value) {
      logRef.value.scrollTop = logRef.value.scrollHeight
    }
  })
}

function getTaskTypeLabel(taskType: string): string {
  const labels: Record<string, string> = {
    full_update: '全量更新',
    single_analysis: '单股分析',
    tomorrow_star: '明日之星',
  }
  return labels[taskType] || taskType
}

function getSourceLabel(source: string): string {
  const labels: Record<string, string> = {
    manual: '手工',
    auto: '自动',
    system: '系统',
  }
  return labels[source] || source
}

function getSourceType(source: string): string {
  const types: Record<string, string> = {
    manual: 'primary',
    auto: 'success',
    system: 'warning',
  }
  return types[source] || 'info'
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
    analysis: '单股分析',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return stage ? (labels[stage] || stage) : '-'
}

function getStatusType(statusName: string): string {
  const types: Record<string, string> = {
    completed: 'success',
    running: 'primary',
    failed: 'danger',
    pending: 'warning',
    cancelled: 'info',
  }
  return types[statusName] || 'info'
}

function getAlertType(level: string): 'success' | 'warning' | 'info' | 'error' {
  const types: Record<string, 'success' | 'warning' | 'info' | 'error'> = {
    success: 'success',
    warning: 'warning',
    info: 'info',
    error: 'error',
  }
  return types[level] || 'info'
}

function formatDateTime(dateStr?: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function formatLogTime(dateStr?: string) {
  if (!dateStr) return '--:--:--'
  return new Date(dateStr).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function getDuration(task: Task): string {
  if (!task.started_at || !task.completed_at) return '-'
  const start = new Date(task.started_at)
  const end = new Date(task.completed_at)
  const seconds = Math.max(0, Math.round((end.getTime() - start.getTime()) / 1000))
  if (seconds < 60) return `${seconds}秒`
  return `${Math.floor(seconds / 60)}分${seconds % 60}秒`
}

function formatEnvKey(key: string) {
  return key.replace(/_/g, ' ')
}

function formatEnvValue(value: unknown) {
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (value == null || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function formatJson(value: unknown) {
  if (!value) return '-'
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}
</script>

<style scoped lang="scss">
.task-center-page {
  display: flex;
  flex-direction: column;
  gap: 18px;

  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;

    h2 {
      margin: 0 0 6px 0;
      font-size: 24px;
    }

    p {
      margin: 0;
      color: var(--color-text-secondary);
    }
  }

  .header-actions,
  .inline-actions {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .alert-stack {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .overview-grid {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 16px;
  }

  .overview-card {
    .overview-label {
      font-size: 13px;
      color: var(--color-text-secondary);
      margin-bottom: 10px;
    }

    .overview-value {
      font-size: 28px;
      font-weight: 700;

      &.is-success {
        color: var(--color-success);
      }

      &.is-warning {
        color: var(--color-warning);
      }

      &.is-danger {
        color: var(--color-danger);
      }

      &.is-info {
        color: var(--color-primary);
      }
    }

    .overview-meta {
      margin-top: 8px;
      font-size: 12px;
      color: var(--color-text-light);
      line-height: 1.6;
    }
  }

  .bootstrap-card {
    .bootstrap-layout {
      display: flex;
      justify-content: space-between;
      gap: 24px;
    }

    .bootstrap-main {
      flex: 1;
      min-width: 0;
    }

    .bootstrap-title {
      font-size: 18px;
      font-weight: 700;
      color: var(--color-text-primary);
    }

    .bootstrap-description {
      margin-top: 8px;
      color: var(--color-text-secondary);
      line-height: 1.7;
    }

    .bootstrap-steps {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 18px;
    }

    .bootstrap-step {
      display: flex;
      gap: 12px;
      align-items: flex-start;
      padding: 14px;
      border-radius: 12px;
      border: 1px solid #e5e7eb;
      background: #fff;

      &.is-done {
        border-color: #bbf7d0;
        background: #f0fdf4;
      }

      &.is-pending {
        background: #f8fafc;
      }
    }

    .step-indicator {
      width: 28px;
      height: 28px;
      border-radius: 999px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 13px;
      font-weight: 700;
      color: #fff;
      background: var(--color-primary);
      flex-shrink: 0;
    }

    .is-done .step-indicator {
      background: var(--color-success);
    }

    .step-content {
      min-width: 0;
    }

    .step-title {
      font-weight: 600;
      color: var(--color-text-primary);
    }

    .step-meta {
      margin-top: 4px;
      font-size: 12px;
      color: var(--color-text-secondary);
      line-height: 1.6;
    }

    .bootstrap-actions {
      width: 260px;
      flex-shrink: 0;
      display: flex;
      flex-direction: column;
      gap: 12px;
      justify-content: center;
      padding: 6px 0;
    }

    .bootstrap-hint {
      font-size: 12px;
      line-height: 1.7;
      color: var(--color-text-light);
    }
  }

  .task-tabs {
    :deep(.el-tabs__header) {
      margin-bottom: 10px;
    }
  }

  .tab-section {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .task-main {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .task-title {
    font-weight: 600;
    color: var(--color-text-primary);
  }

  .task-summary {
    font-size: 12px;
    color: var(--color-text-secondary);
    line-height: 1.5;
  }

  .log-card,
  .drawer-log-container {
    .log-empty {
      color: var(--color-text-light);
      text-align: center;
      padding: 24px 0;
    }
  }

  .log-container,
  .drawer-log-container {
    max-height: 520px;
    overflow-y: auto;
    background: #0f172a;
    border-radius: 10px;
    padding: 12px;
  }

  .log-line {
    display: grid;
    grid-template-columns: 76px 92px 1fr;
    gap: 10px;
    padding: 8px 10px;
    border-radius: 8px;
    color: #e2e8f0;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    line-height: 1.5;

    & + .log-line {
      margin-top: 6px;
    }

    &.log-error {
      background: rgba(239, 68, 68, 0.16);
    }

    &.log-warning {
      background: rgba(245, 158, 11, 0.16);
    }

    &.log-success {
      background: rgba(16, 185, 129, 0.16);
    }

    &.log-info {
      background: rgba(59, 130, 246, 0.12);
    }
  }

  .log-time,
  .log-stage {
    color: #94a3b8;
  }

  .env-card {
    height: 100%;
  }

  .env-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .env-item {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    padding: 10px 12px;
    border-radius: 8px;
    background: var(--color-bg-light);
  }

  .env-key {
    color: var(--color-text-secondary);
  }

  .env-value {
    color: var(--color-text-primary);
    text-align: right;
    word-break: break-all;
  }

  .status-card {
    .status-item {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 8px;
      text-align: center;
    }

    .status-label {
      font-weight: 600;
    }

    .status-value {
      font-size: 18px;
      font-weight: 700;
    }

    .status-meta {
      font-size: 12px;
      color: var(--color-text-light);
      line-height: 1.5;
    }

    .status-ok .status-value {
      color: var(--color-success);
    }

    .status-missing .status-value {
      color: var(--color-danger);
    }
  }

  .detail-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px;
  }

  .detail-item {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 12px 14px;
    border-radius: 8px;
    background: var(--color-bg-light);

    span {
      color: var(--color-text-secondary);
      font-size: 12px;
    }
  }

  .detail-block {
    & + .detail-block {
      margin-top: 18px;
    }

    h4 {
      margin: 0 0 8px 0;
    }

    p,
    pre {
      margin: 0;
      line-height: 1.6;
    }

    pre {
      padding: 12px;
      border-radius: 8px;
      background: var(--color-bg-light);
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }
  }
}

@media (max-width: 1200px) {
  .task-center-page {
    .overview-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
}
</style>
