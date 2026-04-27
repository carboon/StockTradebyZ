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
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  TrendCharts, Expand, Fold, Setting, Star, Refresh, Search, View, Document,
} from '@element-plus/icons-vue'
import { useConfigStore } from '@/store/config'
import { useNoticeStore } from '@/store/notice'

const router = useRouter()
const route = useRoute()
const configStore = useConfigStore()
const noticeStore = useNoticeStore()

const isCollapsed = ref(false)

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

function goNoticeRoute() {
  if (noticeStore.notice?.actionRoute) {
    router.push(noticeStore.notice.actionRoute)
  }
}
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
  padding: 0 $space-sm;
  height: 56px;

  .header-right {
    display: flex;
    align-items: center;
    gap: $space-xs;
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
    padding: 0 $space-xs;

    .header-right {
      gap: 6px;
    }
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
