<template>
  <el-container class="page-layout">
    <!-- 侧边栏 -->
    <el-aside :width="sidebarWidth" class="sidebar">
      <div class="sidebar-header">
        <el-icon :size="28" color="#00B4D8">
          <TrendCharts />
        </el-icon>
        <span class="app-title">StockTrader</span>
      </div>

      <el-menu
        :default-active="activeMenu"
        :collapse="isCollapsed"
        router
        class="sidebar-menu"
      >
        <el-menu-item
          v-for="route in menuRoutes"
          :key="route.path"
          :index="route.path"
        >
          <el-icon>
            <component :is="route.icon" />
          </el-icon>
          <template #title>{{ route.meta.title }}</template>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <!-- 主内容区 -->
    <el-container class="main-container">
      <!-- 顶部栏 -->
      <el-header class="app-header">
        <div class="header-left">
          <el-button
            :icon="isCollapsed ? Expand : Fold"
            text
            @click="toggleSidebar"
          />
        </div>
        <div class="header-right">
          <button
            v-if="headerProgress"
            class="header-progress-card"
            type="button"
            @click="router.push('/update')"
          >
            <div class="header-progress-card__top">
              <div>
                <div v-if="headerProgress.eyebrow" class="header-progress-card__eyebrow">{{ headerProgress.eyebrow }}</div>
                <div class="header-progress-card__title">{{ headerProgress.title }}</div>
                <div class="header-progress-card__subtitle">{{ headerProgress.subtitle }}</div>
              </div>
              <div class="header-progress-card__percent-block">
                <span class="header-progress-card__percent">{{ headerProgress.percent }}%</span>
                <span v-if="headerProgress.percentLabel" class="header-progress-card__percent-label">{{ headerProgress.percentLabel }}</span>
              </div>
            </div>
            <div class="header-progress-card__body">
              <div class="header-progress-card__primary">{{ headerProgress.primary }}</div>
              <div v-if="headerProgress.secondary" class="header-progress-card__secondary">{{ headerProgress.secondary }}</div>
            </div>
            <div class="header-progress-card__bar">
              <span class="header-progress-card__bar-fill" :style="{ width: `${headerProgress.percent}%` }" />
            </div>
          </button>
          <div
            class="tushare-badge"
            :class="configStore.tushareReady ? 'is-ready' : 'is-pending'"
            @click="router.push('/config')"
          >
            <span class="badge-dot" />
            <span>{{ configStore.tushareReady ? 'Tushare 已就绪' : 'Tushare 待配置' }}</span>
          </div>
          <div
            class="tushare-badge"
            :class="configStore.dataInitialized ? 'is-ready' : 'is-pending'"
            @click="router.push('/update')"
          >
            <span class="badge-dot" />
            <span>{{ configStore.dataInitialized ? '首次初始化已完成' : '首次初始化待完成' }}</span>
          </div>
          <el-button text @click="router.push('/config')">
            <el-icon><Setting /></el-icon>
          </el-button>
          <el-dropdown trigger="click" @command="handleUserCommand">
            <el-button text>
              <el-icon><UserIcon /></el-icon>
              <span style="margin-left: 4px">{{ authStore.user?.username || '用户' }}</span>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">个人资料</el-dropdown-item>
                <el-dropdown-item v-if="authStore.isAdmin" command="admin">用户管理</el-dropdown-item>
                <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <div v-if="noticeStore.notice" class="global-notice" :class="`global-notice--${noticeStore.notice.type}`">
        <div class="global-notice__content">
          <strong>{{ noticeStore.notice.title }}</strong>
          <span>{{ noticeStore.notice.message }}</span>
        </div>
        <div class="global-notice__actions">
          <el-button
            v-if="noticeStore.notice.actionRoute"
            size="small"
            text
            @click="goNoticeRoute"
          >
            {{ noticeStore.notice.actionLabel || '去处理' }}
          </el-button>
          <el-button size="small" text @click="noticeStore.clearNotice()">关闭</el-button>
        </div>
      </div>

      <div v-if="!configStore.apiAvailable" class="status-banner">
        <div class="status-banner__content">
          <strong>后端服务暂不可用。</strong>
          <span>{{ configStore.statusError || '请确认后端已启动，再重新检查。' }}</span>
        </div>
        <el-button type="danger" plain @click="router.push('/config')">
          去查看
        </el-button>
      </div>
      <div v-else-if="configStore.tushareStatus && !configStore.tushareReady" class="status-banner">
        <div class="status-banner__content">
          <strong>系统已启动，但行情数据源尚未就绪。</strong>
          <span>{{ configStore.tushareStatus.message || '请先在配置页填写并验证 TUSHARE_TOKEN。' }}</span>
        </div>
        <el-button type="warning" plain @click="router.push('/config')">
          去配置
        </el-button>
      </div>
      <div
        v-else-if="configStore.tushareReady && !configStore.dataInitialized"
        class="status-banner status-banner--info"
      >
        <div class="status-banner__content">
          <strong>数据源已就绪，但首次初始化尚未全部完成。</strong>
          <span>{{ configStore.initializationMessage }}</span>
        </div>
        <el-button type="primary" plain @click="router.push('/update')">
          去任务中心
        </el-button>
      </div>

      <!-- 页面内容 -->
      <el-main class="app-main">
        <router-view v-slot="{ Component, route: currentRoute }">
          <div class="page-shell">
            <template v-if="currentRoute.meta.keepAlive">
              <KeepAlive>
                <component :is="Component" />
              </KeepAlive>
            </template>
            <template v-else>
              <component :is="Component" />
            </template>
          </div>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  TrendCharts, Expand, Fold, Setting, Star, Refresh, Search, View, Document,
  User as UserIcon,
} from '@element-plus/icons-vue'
import { apiTasks } from '@/api'
import { useAuthStore } from '@/store/auth'
import { useConfigStore } from '@/store/config'
import { useNoticeStore } from '@/store/notice'
import type { IncrementalUpdateStatus, Task } from '@/types'
import { formatDuration } from '@/utils'

const router = useRouter()
const route = useRoute()
const configStore = useConfigStore()
const noticeStore = useNoticeStore()
const authStore = useAuthStore()

const isCollapsed = ref(false)
const activeTasks = ref<Task[]>([])
const incrementalStatus = ref<IncrementalUpdateStatus | null>(null)
let progressPoller: ReturnType<typeof setInterval> | null = null

const sidebarWidth = computed(() => isCollapsed.value ? '64px' : '200px')

const activeMenu = computed(() => route.path)
const activeFullTask = computed(() => {
  return activeTasks.value.find((task) => ['full_update', 'tomorrow_star'].includes(task.task_type)) || null
})
const headerProgress = computed(() => {
  const task = activeFullTask.value
  if (task) {
    const meta = task.progress_meta_json
    const current = meta?.current
    const total = meta?.total
    const stageIndex = meta?.stage_index
    const stageTotal = meta?.stage_total
    const secondaryParts: string[] = []
    if (meta?.eta_seconds != null) {
      secondaryParts.push(`预计剩余 ${formatDuration(meta.eta_seconds)}`)
    } else if (task.status === 'running' && task.started_at) {
      secondaryParts.push(`已运行 ${formatDuration(getElapsedSeconds(task.started_at))}`)
    }
    if (meta?.current_code) {
      secondaryParts.push(`当前 ${meta.current_code}`)
    }
    if (meta?.failed_count) {
      secondaryParts.push(`失败 ${meta.failed_count}`)
    }

    const isFetchStage = meta?.stage === 'fetch_data'
    const fetchPercent = current != null && total ? Math.max(0, Math.min(100, Math.round((current / total) * 100))) : null
    if (isFetchStage && (meta?.initial_completed ?? 0) > 0) {
      secondaryParts.push(`已恢复 ${meta?.initial_completed} 只`)
    }

    return {
      eyebrow: isFetchStage ? 'Tushare 数据源' : '',
      title: isFetchStage
        ? '原始数据抓取中'
        : (configStore.dataInitialized ? '全量任务进行中' : '首次初始化进行中'),
      subtitle: isFetchStage
        ? `${configStore.dataInitialized ? '全量更新' : '首次初始化'} / 第 1 步`
        : (meta?.stage_label || getStageLabel(meta?.stage || task.task_stage)),
      percent: Math.max(0, Math.min(100, meta?.percent ?? task.progress ?? 0)),
      percentLabel: '全流程',
      primary: isFetchStage && current != null && total != null
        ? `已抓取 ${current}/${total} 只${fetchPercent != null ? `（抓取完成 ${fetchPercent}%）` : ''}`
        : current != null && total != null
          ? `进度 ${current}/${total}`
          : stageIndex != null && stageTotal != null
            ? `阶段 ${stageIndex}/${stageTotal}`
            : `进度 ${meta?.percent ?? task.progress}%`,
      secondary: secondaryParts.join(' / '),
    }
  }

  if (incrementalStatus.value?.running) {
    const status = incrementalStatus.value
    const secondaryParts: string[] = []
    if (status.eta_seconds != null) {
      secondaryParts.push(`预计剩余 ${formatDuration(status.eta_seconds)}`)
    }
    if (status.current_code) {
      secondaryParts.push(`当前 ${status.current_code}`)
    }
    secondaryParts.push(`${status.updated_count} 更新 / ${status.skipped_count} 跳过 / ${status.failed_count} 失败`)
    return {
      eyebrow: 'Tushare 数据源',
      title: '增量更新进行中',
      subtitle: '最新交易日同步',
      percent: Math.max(0, Math.min(100, status.progress)),
      percentLabel: '增量',
      primary: `进度 ${status.current}/${status.total}`,
      secondary: secondaryParts.join(' / '),
    }
  }

  return null
})

const menuRoutes = computed(() => {
  const routes = [
    { path: '/tomorrow-star', icon: Star, meta: { title: '明日之星', icon: 'Star' } },
    { path: '/diagnosis', icon: Search, meta: { title: '单股诊断', icon: 'Search' } },
    { path: '/watchlist', icon: View, meta: { title: '重点观察', icon: 'View' } },
    { path: '/update', icon: Refresh, meta: { title: '任务中心', icon: 'Refresh' } },
    { path: '/system-info', icon: Document, meta: { title: '系统说明', icon: 'Document' } },
  ]
  if (authStore.isAdmin) {
    routes.push({ path: '/admin', icon: Setting, meta: { title: '用户管理', icon: 'Setting' } })
  }
  return routes
})

function handleUserCommand(command: string) {
  if (command === 'profile') {
    router.push('/profile')
  } else if (command === 'admin') {
    router.push('/admin')
  } else if (command === 'logout') {
    authStore.logout()
    router.push('/login')
  }
}

function toggleSidebar() {
  isCollapsed.value = !isCollapsed.value
}

function goNoticeRoute() {
  if (noticeStore.notice?.actionRoute) {
    router.push(noticeStore.notice.actionRoute)
  }
}

function getStageLabel(stage?: string | null): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    starting: '启动中',
    preparing: '准备中',
    fetch_data: '抓取原始数据',
    build_pool: '量化初选',
    build_candidates: '导出候选图表',
    pre_filter: '生成评分结果',
    score_review: '导出 PASS 图表',
    finalize: '输出推荐结果',
    completed: '已完成',
    failed: '执行失败',
    cancelled: '已取消',
  }
  return stage ? (labels[stage] || stage) : '-'
}

function getElapsedSeconds(startedAt?: string): number {
  if (!startedAt) return 0
  const elapsedMs = Date.now() - new Date(startedAt).getTime()
  return elapsedMs > 0 ? Math.floor(elapsedMs / 1000) : 0
}

async function refreshHeaderProgress() {
  if (document.visibilityState === 'hidden') return
  try {
    const [runningResp, incrementalResp] = await Promise.all([
      apiTasks.getRunning(),
      apiTasks.getIncrementalStatus(),
    ])
    activeTasks.value = runningResp.tasks || []
    incrementalStatus.value = incrementalResp
  } catch {
    activeTasks.value = []
    incrementalStatus.value = null
  }
}

onMounted(() => {
  void refreshHeaderProgress()
  progressPoller = setInterval(() => {
    void refreshHeaderProgress()
  }, 5000)
})

onUnmounted(() => {
  if (progressPoller) {
    clearInterval(progressPoller)
    progressPoller = null
  }
})
</script>

<style scoped lang="scss">
// 8px 网格系统
$space-xs: 8px;
$space-sm: 16px;
$space-md: 24px;

.page-layout {
  width: 100%;
  height: 100vh;
}

.sidebar {
  background-color: #1e293b;
  transition: width 0.3s;

  .sidebar-header {
    display: flex;
    align-items: center;
    gap: $space-xs;
    padding: $space-sm $space-xs;
    height: 56px;
    color: white;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);

    .app-title {
      font-size: 16px;
      font-weight: 600;
    }
  }

  .sidebar-menu {
    border: none;
    background-color: transparent;

    :deep(.el-menu-item) {
      height: 44px;
      line-height: 44px;
      color: rgba(255, 255, 255, 0.7);

      &:hover,
      &.is-active {
        background-color: rgba(0, 180, 216, 0.2);
        color: #00B4D8;
      }
    }
  }
}

.main-container {
  display: flex;
  flex-direction: column;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background-color: white;
  border-bottom: 1px solid #e5e7eb;
  padding: 10px $space-sm;
  min-height: 72px;

  .header-right {
    display: flex;
    align-items: center;
    gap: $space-xs;
    justify-content: flex-end;
    flex-wrap: wrap;
  }
}

.header-progress-card {
  appearance: none;
  width: 340px;
  padding: 12px 14px;
  border: 1px solid #bae6fd;
  border-radius: 16px;
  background: linear-gradient(135deg, #ecfeff 0%, #eff6ff 100%);
  box-shadow: 0 10px 24px rgba(14, 165, 233, 0.12);
  cursor: pointer;
  text-align: left;
  font: inherit;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;

  &:hover {
    transform: translateY(-1px);
    border-color: #38bdf8;
    box-shadow: 0 12px 28px rgba(14, 165, 233, 0.18);
  }

  .header-progress-card__top {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: $space-xs;
  }

  .header-progress-card__eyebrow {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 999px;
    background: rgba(8, 145, 178, 0.1);
    color: #0f766e;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.02em;
  }

  .header-progress-card__title {
    margin-top: 6px;
    font-size: 15px;
    font-weight: 700;
    color: #0f172a;
  }

  .header-progress-card__subtitle {
    margin-top: 4px;
    font-size: 12px;
    color: #0f766e;
  }

  .header-progress-card__percent-block {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 2px;
  }

  .header-progress-card__percent {
    flex-shrink: 0;
    font-size: 18px;
    font-weight: 800;
    color: #0369a1;
  }

  .header-progress-card__percent-label {
    font-size: 10px;
    font-weight: 700;
    color: #0f766e;
    letter-spacing: 0.04em;
  }

  .header-progress-card__body {
    margin-top: 10px;
  }

  .header-progress-card__primary {
    font-size: 14px;
    font-weight: 700;
    line-height: 1.5;
    color: #0f172a;
  }

  .header-progress-card__secondary {
    margin-top: 4px;
    font-size: 12px;
    line-height: 1.6;
    color: #334155;
  }

  .header-progress-card__bar {
    margin-top: 10px;
    height: 8px;
    border-radius: 999px;
    background: rgba(14, 165, 233, 0.12);
    overflow: hidden;
  }

  .header-progress-card__bar-fill {
    display: block;
    height: 100%;
    border-radius: inherit;
    background: linear-gradient(90deg, #0ea5e9 0%, #2563eb 100%);
  }
}

.tushare-badge {
  display: inline-flex;
  align-items: center;
  gap: $space-xs;
  padding: $space-xs $space-sm;
  border-radius: 999px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;

  .badge-dot {
    width: $space-xs;
    height: $space-xs;
    border-radius: 999px;
  }

  &.is-ready {
    color: #166534;
    background: #dcfce7;

    .badge-dot {
      background: #16a34a;
    }
  }

  &.is-pending {
    color: #9a3412;
    background: #ffedd5;

    .badge-dot {
      background: #f97316;
    }
  }
}

.status-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $space-sm;
  padding: $space-xs $space-sm;
  background: linear-gradient(90deg, #fff7ed 0%, #fffbeb 100%);
  border-bottom: 1px solid #fed7aa;
  min-height: 44px;

  .status-banner__content {
    display: flex;
    align-items: center;
    gap: $space-xs;
    color: #9a3412;
    font-size: 13px;
  }

  &.status-banner--info {
    background: linear-gradient(90deg, #eff6ff 0%, #ecfeff 100%);
    border-bottom: 1px solid #bfdbfe;

    .status-banner__content {
      color: #1d4ed8;
    }
  }
}

.global-notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $space-sm;
  padding: 10px $space-sm;
  border-bottom: 1px solid #dbeafe;
  background: linear-gradient(90deg, #eff6ff 0%, #f8fafc 100%);

  .global-notice__content {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    line-height: 1.6;
  }

  .global-notice__actions {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
  }

  &.global-notice--warning {
    background: linear-gradient(90deg, #fff7ed 0%, #fffbeb 100%);
    border-bottom-color: #fed7aa;
  }

  &.global-notice--error {
    background: linear-gradient(90deg, #fef2f2 0%, #fff7ed 100%);
    border-bottom-color: #fecaca;
  }

  &.global-notice--success {
    background: linear-gradient(90deg, #ecfdf5 0%, #f0fdf4 100%);
    border-bottom-color: #bbf7d0;
  }
}

.app-main {
  background-color: #f8fafb;
  padding: $space-md;
  overflow-y: auto;

  .page-shell {
    width: 100%;
    max-width: 1360px;
    margin: 0 auto;
  }

  :deep(.page-shell > *) {
    width: 100%;
    box-sizing: border-box;
  }
}

@media (max-width: 960px) {
  .app-header {
    padding: 10px $space-xs;
    align-items: flex-start;

    .header-right {
      gap: 6px;
      width: 100%;
    }
  }

  .header-progress-card {
    width: 100%;
  }

  .status-banner {
    padding: $space-xs $space-xs;
    align-items: flex-start;
    flex-direction: column;
  }

  .app-main {
    padding: $space-sm;

    .page-shell {
      max-width: none;
    }
  }
}
</style>
