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
      <el-button v-if="configStore.apiAvailable" type="primary" @click="goConfig">前往配置</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageLayout from '@/components/common/PageLayout.vue'
import { useConfigStore } from '@/store/config'

const router = useRouter()
const route = useRoute()
const configStore = useConfigStore()

const allowedRoutes = new Set(['/config', '/system-info'])
const isAllowedRoute = computed(() => allowedRoutes.has(route.path))

const hasBlockingIssue = computed(() => {
  if (!configStore.apiAvailable) return true
  return Boolean(configStore.tushareStatus && !configStore.tushareReady)
})
const showStatusGate = computed(() => hasBlockingIssue.value && !isAllowedRoute.value)
const gateTitle = computed(() => {
  return configStore.apiAvailable ? '请先完成 Tushare 配置' : '后端服务暂不可用'
})
const gateDescription = computed(() => {
  if (!configStore.apiAvailable) {
    return '前端已经启动，但当前无法连接后端服务。配置保存、数据更新、诊断分析等功能暂不可用。'
  }
  return '系统已经启动，但当前未完成数据源配置，明日之星、单股诊断、任务执行等功能暂不可用。'
})
const gateMessage = computed(() => {
  if (!configStore.apiAvailable) {
    return configStore.statusError || '请确认后端服务已成功启动，然后重新检查。'
  }
  return configStore.tushareStatus?.message || '请先在配置页填写有效的 TUSHARE_TOKEN，并通过接口验证。'
})

function enforceRouteAccess() {
  if (!configStore.apiAvailable) {
    return
  }
  if (configStore.tushareStatus && !configStore.tushareReady && !isAllowedRoute.value) {
    router.replace('/config')
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
  if (route.path !== '/config') {
    router.replace('/config')
  }
}

onMounted(async () => {
  await refreshStatus()
})

watch(() => route.path, () => {
  enforceRouteAccess()
})
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
