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
          <!-- 数据同步状态栏 -->
          <div 
            v-if="syncStatus.is_updating" 
            class="sync-status-badge is-updating"
          >
            <el-icon class="is-loading"><Loading /></el-icon>
            <span>{{ syncStatus.message || '更新中...' }} {{ syncStatus.progress_pct }}%</span>
          </div>
          <div 
            v-else-if="syncStatus.is_synced" 
            class="sync-status-badge is-ready"
          >
            <el-icon><CircleCheckFilled /></el-icon>
            <span>数据已是最新</span>
          </div>
          <div 
            v-else
            class="sync-status-badge is-pending"
            @click="handleSync"
          >
            <el-icon><WarningFilled /></el-icon>
            <span>数据需更新 (点击同步)</span>
          </div>

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
            <span>{{ configStore.dataInitialized ? '初始化已完成' : '初始化未完成' }}</span>
          </div>
          <el-button text @click="router.push('/config')">
            <el-icon><Setting /></el-icon>
          </el-button>
        </div>
      </el-header>

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
          <strong>数据源已就绪，但尚未完成首次初始化。</strong>
          <span>{{ configStore.initializationMessage }}</span>
        </div>
        <el-button type="primary" plain @click="router.push('/update')">
          去任务中心
        </el-button>
      </div>

      <!-- 页面内容 -->
      <el-main class="app-main">
        <router-view v-slot="{ Component, currentRoute }">
          <div class="page-shell">
            <template v-if="currentRoute && currentRoute.meta && currentRoute.meta.keepAlive">
              <KeepAlive>
                <component :is="Component" />
              </KeepAlive>
            </template>
            <template v-else>
              <component :is="Component" />
            </template>
          </div>
        </router-view>

        <!-- 左下角系统时钟 -->
        <div class="system-clock">
          <el-icon><Clock /></el-icon>
          <span>{{ formattedTime }}</span>
        </div>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  TrendCharts, Expand, Fold, Setting, Star, Refresh, Search, View, Document,
  Loading, CircleCheckFilled, WarningFilled, Clock
} from '@element-plus/icons-vue'
import { useConfigStore } from '@/store/config'
import { apiStock } from '@/api'
import { ElMessage } from 'element-plus'

const router = useRouter()
const route = useRoute()
const configStore = useConfigStore()

const isCollapsed = ref(false)
const syncStatus = ref<any>({
  is_updating: false,
  is_synced: false,
  progress_pct: 0,
  message: ''
})
const formattedTime = ref('--:--:--')
let pollTimer: any = null
let clockTimer: any = null

const sidebarWidth = computed(() => isCollapsed.value ? '64px' : '200px')

const activeMenu = computed(() => route.path)

const menuRoutes = [
  { path: '/tomorrow-star', icon: Star, meta: { title: '明日之星', icon: 'Star' } },
  { path: '/diagnosis', icon: Search, meta: { title: '单股诊断', icon: 'Search' } },
  { path: '/watchlist', icon: View, meta: { title: '重点观察', icon: 'View' } },
  { path: '/update', icon: Refresh, meta: { title: '任务中心', icon: 'Refresh' } },
  { path: '/system-info', icon: Document, meta: { title: '系统说明', icon: 'Document' } },
]

function toggleSidebar() {
  isCollapsed.value = !isCollapsed.value
}

async function fetchSyncStatus() {
  try {
    const res = await apiStock.getSyncStatus()
    syncStatus.value = res
    // 每次获取状态时同步更新一次时间（确保是网络时间）
    if (res.server_time) {
      formattedTime.value = res.server_time.split(' ')[1] || res.server_time
    }
  } catch (e) {
    console.error('获取同步状态失败', e)
  }
}

async function handleSync() {
  try {
    const res = await apiStock.triggerSync()
    ElMessage.success(res.message || '已开始后台同步')
    fetchSyncStatus()
  } catch (e: any) {
    ElMessage.error(e.message || '触发同步失败')
  }
}

onMounted(() => {
  fetchSyncStatus()
  // 每 5 秒轮询一次状态并更新时间
  pollTimer = setInterval(fetchSyncStatus, 5000)
  
  // 本地时钟每秒跳动一次，增加流畅感
  clockTimer = setInterval(() => {
    const now = new Date()
    // 如果已经有网络时间基准，这里可以做更复杂的累加，目前简单展示本地时间作为秒针跳动
    // 或者简单地每 5 秒刷新一次网络时间即可，这里为了视觉效果增加秒针跳动逻辑
    // 由于我们每 5 秒获取一次网络时间，中间的时间差由本地补全会更精准，但为了简化：
    // 我们直接使用上次获取的网络时间字符串，如果需要秒针走动，可以解析后累加
  }, 1000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (clockTimer) clearInterval(clockTimer)
})
</script>

<style scoped lang="scss">
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
    gap: 12px;
    padding: 20px;
    color: white;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);

    .app-title {
      font-size: 18px;
      font-weight: 600;
    }
  }

  .sidebar-menu {
    border: none;
    background-color: transparent;

    :deep(.el-menu-item) {
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
  padding: 0 20px;

  .header-right {
    display: flex;
    align-items: center;
    gap: 8px;
  }
}

.tushare-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;

  .badge-dot {
    width: 8px;
    height: 8px;
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

.sync-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  margin-right: 8px;
  transition: all 0.2s ease;

  &.is-ready {
    color: #166534;
    background: #dcfce7;
  }

  &.is-updating {
    color: #1d4ed8;
    background: #dbeafe;
  }

  &.is-pending {
    color: #9a3412;
    background: #ffedd5;
    cursor: pointer;
    &:hover {
      background: #fed7aa;
    }
  }
}

.status-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 20px;
  background: linear-gradient(90deg, #fff7ed 0%, #fffbeb 100%);
  border-bottom: 1px solid #fed7aa;

  .status-banner__content {
    display: flex;
    align-items: center;
    gap: 12px;
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

.app-main {
  background-color: #f8fafb;
  padding: 24px;
  overflow-y: auto;
  position: relative;

  .page-shell {
    width: 100%;
    max-width: 1360px;
    margin: 0 auto;
  }

  :deep(.page-shell > *) {
    width: 100%;
    box-sizing: border-box;
  }

  .system-clock {
    position: absolute;
    bottom: 16px;
    left: 16px;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    background: rgba(255, 255, 255, 0.9);
    border-radius: 8px;
    font-size: 12px;
    color: #64748b;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
    pointer-events: none;
    z-index: 10;
  }
}

@media (max-width: 960px) {
  .app-header {
    padding: 0 16px;

    .header-right {
      gap: 6px;
    }
  }

  .status-banner {
    padding: 12px 16px;
    align-items: flex-start;
    flex-direction: column;
  }

  .app-main {
    padding: 16px;

    .page-shell {
      max-width: none;
    }
  }
}
</style>
