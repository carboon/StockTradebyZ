<template>
  <div class="updating-page">
    <el-card class="updating-card" shadow="never">
      <div class="updating-eyebrow">系统状态</div>
      <h1>更新数据中</h1>
      <p class="updating-message">
        {{ displayMessage }}
      </p>

      <div v-if="activeTask" class="updating-meta">
        <span>任务类型：{{ taskTypeLabel(activeTask.task_type) }}</span>
        <span>状态：{{ activeTask.status }}</span>
        <span v-if="typeof activeTask.progress === 'number'">进度：{{ activeTask.progress }}%</span>
      </div>

      <el-progress
        v-if="activeTask && typeof activeTask.progress === 'number'"
        :percentage="Math.max(0, Math.min(100, activeTask.progress || 0))"
        :stroke-width="12"
        status="warning"
      />

      <div class="updating-actions">
        <el-button :loading="refreshing" @click="refreshState">刷新状态</el-button>
        <el-button v-if="isAdmin" type="primary" @click="router.push('/update')">前往任务中心</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { apiTasks } from '@/api'
import { useAuthStore } from '@/store/auth'
import type { Task } from '@/types'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const refreshing = ref(false)
const activeTask = ref<Task | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null
const DIAGNOSIS_STATE_KEY = 'stocktrade:diagnosis:state:v3'

const isAdmin = computed(() => authStore.isAdmin)
const redirectPath = computed(() => {
  const raw = typeof route.query.redirect === 'string' ? route.query.redirect : ''
  return raw || getDiagnosisRedirectFallback() || '/tomorrow-star'
})
const displayMessage = computed(() => {
  if (!activeTask.value) {
    return '后台任务刚结束，页面会在状态恢复后自动返回。'
  }
  return activeTask.value.summary
    || activeTask.value.progress_meta_json?.stage_label
    || activeTask.value.task_stage
    || '后台正在刷新最新交易日数据，请稍后再访问榜单页面。'
})

function taskTypeLabel(taskType: string) {
  const labels: Record<string, string> = {
    daily_batch_update: '按交易日批量刷新',
    incremental_update: '增量更新',
    full_update: '全量初始化',
    recent_120_rebuild: '近120交易日重建',
  }
  return labels[taskType] || taskType
}

function getDiagnosisRedirectFallback(): string {
  if (typeof window === 'undefined') return ''

  try {
    const raw = sessionStorage.getItem(DIAGNOSIS_STATE_KEY)
    if (!raw) return ''

    const state = JSON.parse(raw)
    const code = typeof state?.stockCode === 'string' ? state.stockCode.trim() : ''
    return code ? `/diagnosis?code=${encodeURIComponent(code)}` : ''
  } catch {
    sessionStorage.removeItem(DIAGNOSIS_STATE_KEY)
    return ''
  }
}

async function refreshState() {
  refreshing.value = true
  try {
    const running = await apiTasks.getRunning()
    const blockedTask = (running.tasks || []).find((task) =>
      ['daily_batch_update', 'incremental_update', 'full_update', 'recent_120_rebuild'].includes(task.task_type),
    ) || null
    activeTask.value = blockedTask
    if (!blockedTask) {
      await router.replace(redirectPath.value)
    }
  } catch (error) {
    ElMessage.error('刷新更新状态失败')
  } finally {
    refreshing.value = false
  }
}

onMounted(async () => {
  await refreshState()
  pollTimer = setInterval(() => {
    void refreshState()
  }, 10000)
})

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<style scoped>
.updating-page {
  min-height: calc(100vh - 120px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
  background:
    radial-gradient(circle at top left, rgba(197, 223, 255, 0.55), transparent 36%),
    linear-gradient(180deg, #f4f7fb 0%, #eef3f7 100%);
}

.updating-card {
  width: min(640px, 100%);
  border-radius: 20px;
}

.updating-eyebrow {
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #5d6b82;
  margin-bottom: 12px;
}

.updating-card h1 {
  margin: 0 0 12px;
  font-size: 32px;
  color: #1b2430;
}

.updating-message {
  margin: 0 0 18px;
  color: #4c5a70;
  line-height: 1.7;
}

.updating-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 18px;
  margin-bottom: 18px;
  color: #5d6b82;
  font-size: 14px;
}

.updating-actions {
  display: flex;
  gap: 12px;
  margin-top: 20px;
}

@media (max-width: 640px) {
  .updating-card h1 {
    font-size: 26px;
  }

  .updating-actions {
    flex-direction: column;
  }
}
</style>
