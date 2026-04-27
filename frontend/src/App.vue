<template>
  <PageLayout />
  <el-dialog
    v-model="showStatusGate"
    :title="gateTitle"
    width="520px"
    :show-close="false"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
  >
    <p class="gate-text">{{ gateDescription }}</p>
    <p class="gate-text gate-text-muted">{{ gateMessage }}</p>
    <template #footer>
      <el-button @click="refreshStatus">重新检查</el-button>
      <el-button v-if="configStore.apiAvailable" type="primary" @click="goConfig">{{ gateActionLabel }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageLayout from '@/components/common/PageLayout.vue'
import { useConfigStore } from '@/store/config'
import { useNoticeStore } from '@/store/notice'

const router = useRouter()
const route = useRoute()
const configStore = useConfigStore()
const noticeStore = useNoticeStore()

const allowedRoutes = new Set(['/config', '/system-info', '/update'])
const isAllowedRoute = computed(() => allowedRoutes.has(route.path))

const gateType = computed<'api-unavailable' | 'tushare-unready' | 'initialization-pending' | null>(() => {
  if (!configStore.apiAvailable) return 'api-unavailable'
  if (configStore.tushareStatus && !configStore.tushareReady) return 'tushare-unready'
  if (configStore.tushareReady && !configStore.dataInitialized) return 'initialization-pending'
  return null
})
const showStatusGate = computed(() => gateType.value !== null && !isAllowedRoute.value)
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

function enforceRouteAccess() {
  if (gateType.value === 'tushare-unready' && !isAllowedRoute.value) {
    router.replace('/config')
    return
  }
  if (gateType.value === 'initialization-pending' && !isAllowedRoute.value) {
    router.replace('/update')
  }
}

async function refreshStatus() {
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

onMounted(async () => {
  await refreshStatus()
})

watch(() => [route.path, gateType.value], () => {
  enforceRouteAccess()
})

watch(() => [gateType.value, configStore.statusError, configStore.initializationMessage], () => {
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
