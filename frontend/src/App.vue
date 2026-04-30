<template>
  <!-- 登录/注册页：独立布局，无状态检查干扰 -->
  <template v-if="isAuthPage">
    <RouterView />
  </template>

  <!-- 主应用页面：带完整布局和状态提示 -->
  <PageLayout v-else />

  <!-- 模态对话框：仅用于关键系统问题，登录页不显示 -->
  <el-dialog
    v-if="!isAuthPage"
    :model-value="showStatusGate"
    :title="gateTitle"
    width="520px"
    :show-close="true"
    :close-on-click-modal="true"
  >
    <p class="gate-text">{{ gateDescription }}</p>
    <p class="gate-text gate-text-muted">{{ gateMessage }}</p>
    <template #footer>
      <el-button @click="refreshStatus">重新检查</el-button>
      <el-button type="primary" @click="goConfig">{{ gateActionLabel }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { RouterView } from 'vue-router'
import PageLayout from '@/components/common/PageLayout.vue'
import { useConfigStore } from '@/store/config'
import { useNoticeStore } from '@/store/notice'
import { useAuthStore } from '@/store/auth'

const router = useRouter()
const route = useRoute()
const configStore = useConfigStore()
const noticeStore = useNoticeStore()
const authStore = useAuthStore()

// 登录/注册页：使用独立全屏布局，不参与任何状态检查
// 使用 route.name 而不是 route.path，因为路由初始化时 path 可能为空
const isAuthPage = computed(() => {
  const name = route.name as string
  return name === 'Login' || name === 'Register'
})

// 是否已登录
const isLoggedIn = computed(() => authStore.isAuthenticated)

// 系统状态检查的白名单路由（这些路由不会被强制跳转）
const allowedRoutes = new Set(['/config', '/system-info', '/update'])
const isAllowedRoute = computed(() => allowedRoutes.has(route.path))

// 状态类型判定
const gateType = computed<'api-unavailable' | 'tushare-unready' | 'initialization-pending' | null>(() => {
  if (!configStore.apiAvailable) return 'api-unavailable'
  if (configStore.tushareStatus && !configStore.tushareReady) return 'tushare-unready'
  if (configStore.tushareReady && !configStore.dataInitialized) return 'initialization-pending'
  return null
})

// 是否显示模态对话框（登录页或未登录时不显示）
const showStatusGate = computed(() => {
  if (isAuthPage.value || !isLoggedIn.value) return false
  return gateType.value !== null && !isAllowedRoute.value
})

const gateTitle = computed(() => {
  if (gateType.value === 'api-unavailable') return '后端服务暂不可用'
  if (gateType.value === 'tushare-unready') return '请先完成 Tushare 配置'
  if (gateType.value === 'initialization-pending') return '请先完成首次初始化'
  return ''
})

const gateDescription = computed(() => {
  if (gateType.value === 'api-unavailable') {
    return '前端已经启动，但当前无法连接后端服务。配置保存、数据更新、诊断分析等功能暂不可用。'
  }
  if (gateType.value === 'tushare-unready') {
    return '系统已经启动，但当前未完成数据源配置，明日之星、单股诊断、任务执行等功能暂不可用。'
  }
  if (gateType.value === 'initialization-pending') {
    return '数据源已可用，但首次初始化尚未完成。原始数据、候选结果和分析结果都准备好后，业务页才会完全开放。'
  }
  return ''
})

const gateMessage = computed(() => {
  if (gateType.value === 'api-unavailable') {
    return configStore.statusError || '请确认后端服务已成功启动，然后重新检查。'
  }
  if (gateType.value === 'tushare-unready') {
    return configStore.tushareStatus?.message || '请先在配置页填写有效的 TUSHARE_TOKEN，并通过接口验证。'
  }
  if (gateType.value === 'initialization-pending') {
    return configStore.initializationMessage
  }
  return ''
})

const gateActionLabel = computed(() => {
  return gateType.value === 'initialization-pending' ? '前往任务中心' : '前往配置'
})

// 路由强制跳转逻辑（登录页不受影响）
function enforceRouteAccess() {
  // 登录页不参与任何路由强制跳转
  if (isAuthPage.value) return

  if (gateType.value === 'tushare-unready' && !isAllowedRoute.value) {
    router.replace('/config')
    return
  }
  if (gateType.value === 'initialization-pending' && !isAllowedRoute.value) {
    router.replace('/update')
  }
}

async function refreshStatus() {
  // 只对已登录用户检查状态
  if (!isLoggedIn.value) {
    return
  }

  try {
    await configStore.checkTushareStatus()
    enforceRouteAccess()
  } catch (_error) {
    enforceRouteAccess()
  }
}

function goConfig() {
  const target = gateType.value === 'initialization-pending' ? '/update' : '/config'
  if (route.path !== target) {
    router.replace(target)
  }
}

// 初始化：非登录页且已登录时才检查状态
onMounted(async () => {
  if (!isAuthPage.value && isLoggedIn.value) {
    await refreshStatus()
  }
})

// 监听路由和状态变化
watch(() => [route.path, gateType.value], () => {
  enforceRouteAccess()
})

// 通知栏提示（仅已登录用户在非登录页显示）
watch(() => [gateType.value, configStore.statusError, configStore.initializationMessage, isLoggedIn.value], () => {
  // 登录页或未登录时，不显示系统状态通知
  if (isAuthPage.value || !isLoggedIn.value) {
    noticeStore.clearNotice()
    return
  }

  if (gateType.value === 'api-unavailable') {
    noticeStore.setNotice({
      type: 'error',
      title: '后端服务暂不可用',
      message: configStore.statusError || '请确认后端服务已启动，再重新检查。',
      actionLabel: '前往配置',
      actionRoute: '/config',
    })
    return
  }
  if (gateType.value === 'tushare-unready') {
    noticeStore.setNotice({
      type: 'warning',
      title: 'Tushare 尚未就绪',
      message: configStore.tushareStatus?.message || '请先在配置页填写并验证 Token。',
      actionLabel: '去配置',
      actionRoute: '/config',
    })
    return
  }
  if (gateType.value === 'initialization-pending') {
    noticeStore.setNotice({
      type: 'info',
      title: '首次初始化尚未完成',
      message: configStore.initializationMessage,
      actionLabel: '去任务中心',
      actionRoute: '/update',
    })
    return
  }
  noticeStore.clearNotice()
}, { immediate: true })
</script>

<style>
#app {
  width: 100%;
  height: 100vh;
  overflow: hidden;
}

.gate-text {
  margin: 0 0 10px;
  line-height: 1.7;
}

.gate-text-muted {
  color: #64748b;
}
</style>
