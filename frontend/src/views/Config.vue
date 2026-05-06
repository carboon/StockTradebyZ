<template>
  <div class="config-page">
    <el-card>
      <template #header>
        <span>配置管理</span>
      </template>

      <el-tabs v-model="activeTab">
        <!-- Tab 1: 参数配置 -->
        <el-tab-pane label="参数配置" name="config">
          <el-form :model="configs" label-width="140px" class="config-form">
            <el-alert
              v-if="!configStore.apiAvailable"
              title="后端服务暂不可用"
              :description="configStore.statusError || '当前无法连接后端服务，请确认后端已启动后再重试。'"
              type="error"
              show-icon
              :closable="false"
              class="status-alert"
            />

            <!-- Tushare 配置 -->
            <el-divider content-position="left">Tushare 配置</el-divider>

            <el-form-item label="API Token">
              <el-input
                v-model="configs.tushare_token"
                type="password"
                show-password
                placeholder="请输入 Tushare API Token"
                style="width: 400px"
              />
              <el-button
                type="primary"
                class="verify-button"
                style="margin-left: 12px"
                :loading="verifying"
                @click="verifyTushare"
              >
                验证
              </el-button>
              <div class="form-tip">
                获取地址: <a href="https://tushare.pro/user/token" target="_blank">https://tushare.pro/user/token</a>
              </div>
            </el-form-item>

            <!-- LLM 配置 -->
            <el-divider content-position="left" class="llm-divider">LLM API 配置 (待完善)</el-divider>

            <el-form-item label="GLM API Key">
              <el-input
                v-model="configs.zhipuai_api_key"
                type="password"
                show-password
                placeholder="智谱 GLM-4V-Flash (免费)"
                style="width: 400px"
                disabled
              />
              <div class="form-tip form-tip-disabled">
                获取地址: <a href="https://open.bigmodel.cn/usercenter/apikeys" target="_blank">https://open.bigmodel.cn</a>
              </div>
            </el-form-item>

            <el-form-item label="通义千问 Key">
              <el-input
                v-model="configs.dashscope_api_key"
                type="password"
                show-password
                placeholder="阿里云通义千问 VL"
                style="width: 400px"
                disabled
              />
              <div class="form-tip form-tip-disabled">
                获取地址: <a href="https://dashscope.console.aliyun.com/apiKey" target="_blank">阿里云控制台</a>
              </div>
            </el-form-item>

            <el-form-item label="Gemini Key">
              <el-input
                v-model="configs.gemini_api_key"
                type="password"
                show-password
                placeholder="Google Gemini"
                style="width: 400px"
                disabled
              />
              <div class="form-tip form-tip-disabled">
                获取地址: <a href="https://ai.google.dev/" target="_blank">https://ai.google.dev/</a>
              </div>
            </el-form-item>

            <!-- 其他配置 -->
            <el-divider content-position="left">其他配置</el-divider>

            <el-form-item label="默认评分器">
              <el-radio-group v-model="configs.default_reviewer">
                <el-radio value="quant">量化评分</el-radio>
                <el-radio value="glm" disabled>GLM</el-radio>
                <el-radio value="qwen" disabled>通义千问</el-radio>
                <el-radio value="gemini" disabled>Gemini</el-radio>
              </el-radio-group>
            </el-form-item>

            <el-form-item label="推荐分数阈值">
              <el-input-number
                v-model="configs.min_score_threshold"
                :min="0"
                :max="5"
                :step="0.1"
                :precision="1"
              />
              <span class="form-tip">分数 >= 此值的股票将被推荐</span>
              <el-tooltip
                effect="dark"
                placement="top"
                content="来自对目标股票的趋势结构、价格位置、量价行为、历史异动，四个维度进行的经验评价，详见单股诊断。"
              >
                <el-icon class="question-icon"><InfoFilled /></el-icon>
              </el-tooltip>
            </el-form-item>

            <!-- 保存按钮 -->
            <el-form-item>
              <el-button type="primary" :loading="saving" @click="saveConfigs(false)">
                保存配置
              </el-button>
              <el-button type="success" :loading="savingAndInitializing" @click="saveConfigs(true)">
                保存并初始化
              </el-button>
              <el-button @click="loadConfigs">重置</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- Tab 2: 系统自检 -->
        <el-tab-pane label="系统自检" name="diagnostics">
          <div class="startup-panel">
            <div class="startup-panel__header">
              <div>
                <div class="startup-panel__title">首次启动自检</div>
                <div class="startup-panel__subtitle">先确认本机环境、Token、数据库和初始化状态，再决定下一步。</div>
              </div>
              <div class="startup-panel__actions">
                <el-button :loading="diagnosticsLoading" @click="loadDiagnostics">重新检查</el-button>
                <el-button v-if="diagnosticsPrimaryAction" type="primary" @click="handleDiagnosticsAction">
                  {{ diagnosticsPrimaryAction }}
                </el-button>
              </div>
            </div>

            <div class="startup-checklist">
              <div
                v-for="check in startupChecks"
                :key="check.key"
                class="startup-check"
                :class="`is-${check.status}`"
              >
                <div class="startup-check__main">
                  <div class="startup-check__title-row">
                    <span class="startup-check__title">{{ check.label }}</span>
                    <el-tag :type="checkTagType(check.status)" size="small">{{ checkStatusLabel(check.status) }}</el-tag>
                  </div>
                  <div class="startup-check__summary">{{ check.summary }}</div>
                  <div v-if="check.action" class="startup-check__action">{{ check.action }}</div>
                </div>
              </div>
            </div>
          </div>

          <el-alert
            v-if="statusSummary"
            :title="statusSummary.title"
            :description="statusSummary.description"
            :type="statusSummary.type"
            show-icon
            :closable="false"
            class="status-alert"
          />
          <el-alert
            v-if="initGuide"
            :title="initGuide.title"
            :description="initGuide.description"
            :type="initGuide.type"
            show-icon
            :closable="false"
            class="status-alert"
          />

          <div class="init-guide-panel">
            <div class="init-guide-copy">
              <div class="init-guide-title">首次使用建议路径</div>
              <div class="init-guide-text">
                1. 填写并验证 Tushare Token。2. 点击"保存并初始化"启动全量初始化。3. 系统会跳转到任务中心查看进度；刷新页面后会尽量恢复到当前任务视图。
              </div>
            </div>
            <el-button
              v-if="showTaskCenterShortcut"
              text
              type="primary"
              @click="goToTaskCenter"
            >
              {{ taskCenterShortcutText }}
            </el-button>
          </div>

          <div v-if="nextStepCards.length > 0" class="next-steps-panel">
            <div class="next-steps-panel__title">初始化完成后的推荐入口</div>
            <div class="next-steps-grid">
              <button
                v-for="item in nextStepCards"
                :key="item.title"
                type="button"
                class="next-step-card"
                @click="router.push(item.route)"
              >
                <div class="next-step-card__title">{{ item.title }}</div>
                <div class="next-step-card__desc">{{ item.description }}</div>
              </button>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { InfoFilled } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { useConfigStore } from '@/store/config'
import { useNoticeStore } from '@/store/notice'
import { apiTasks } from '@/api'
import { saveInitTaskViewState } from '@/utils/initTaskViewState'
import { getUserSafeErrorMessage, isInitializationPendingError } from '@/utils/userFacingErrors'
import type { TaskDiagnosticCheck, TaskDiagnosticsResponse } from '@/types'

const configStore = useConfigStore()
const noticeStore = useNoticeStore()
const router = useRouter()

const activeTab = ref('config')

const configs = ref({
  tushare_token: '',
  zhipuai_api_key: '',
  dashscope_api_key: '',
  gemini_api_key: '',
  default_reviewer: 'quant',
  min_score_threshold: 4.0,
})

const verifying = ref(false)
const saving = ref(false)
const savingAndInitializing = ref(false)
const diagnosticsLoading = ref(false)
const diagnostics = ref<TaskDiagnosticsResponse | null>(null)

const statusSummary = computed(() => {
  if (!configStore.apiAvailable) return null
  const status = configStore.tushareStatus
  if (!status) return null

  if (!status.configured) {
    return {
      type: 'warning' as const,
      title: 'Tushare 尚未配置',
      description: status.message || '请先配置并验证 TUSHARE_TOKEN，系统业务功能暂不可执行。',
    }
  }

  if (!status.available) {
    return {
      type: 'error' as const,
      title: 'Tushare 当前不可用',
      description: status.message || '当前 Token 验证失败或接口不可达，请修正后再继续。',
    }
  }

  return {
    type: 'success' as const,
    title: 'Tushare 已就绪',
    description: status.message || 'Token 验证通过，可以正常执行数据更新和分析。',
  }
})

const initGuide = computed(() => {
  if (!configStore.apiAvailable) {
    return {
      type: 'error' as const,
      title: '后端未就绪，暂时不能初始化',
      description: configStore.statusError || '请先确认后端服务已启动，再返回此页保存配置和启动初始化。',
    }
  }

  if (!configStore.tushareReady) {
    return {
      type: 'warning' as const,
      title: 'Token 未验证，初始化入口暂不可用',
      description: '只有验证通过后，"保存并初始化"才会启动任务。验证成功后会自动进入任务中心查看进度。',
    }
  }

  if (!configStore.dataInitialized) {
    return {
      type: 'info' as const,
      title: '配置已就绪，下一步请完成首次初始化',
      description: configStore.initializationMessage || '初始化会补齐原始数据、候选结果和分析结果，完成前业务页仍会受限。',
    }
  }

  return {
    type: 'success' as const,
    title: '首次初始化已完成',
    description: '当前配置和初始化结果已就绪；如需查看任务记录或重试历史任务，可进入任务中心。',
  }
})

const showTaskCenterShortcut = computed(() => configStore.tushareReady || configStore.dataInitialized)

const taskCenterShortcutText = computed(() => (
  configStore.dataInitialized ? '查看任务中心' : '去任务中心继续初始化'
))

const startupChecks = computed<TaskDiagnosticCheck[]>(() => {
  if (diagnostics.value?.checks?.length) return diagnostics.value.checks

  return [
    {
      key: 'backend',
      label: '后端服务',
      status: configStore.apiAvailable ? 'success' : 'error',
      summary: configStore.apiAvailable ? '后端接口可访问。' : (configStore.statusError || '当前无法连接后端服务。'),
    },
    {
      key: 'tushare',
      label: 'Tushare 配置',
      status: configStore.tushareReady ? 'success' : 'warning',
      summary: configStore.tushareReady ? 'Token 已验证，可继续初始化。' : '请先填写并验证 Token。',
    },
    {
      key: 'initialization',
      label: '首次初始化',
      status: configStore.dataInitialized ? 'success' : 'info',
      summary: configStore.initializationMessage,
    },
  ]
})

const diagnosticsPrimaryAction = computed(() => {
  if (!configStore.apiAvailable) return '留在配置页处理'
  if (!configStore.tushareReady) return '去任务中心查看准备项'
  if (!configStore.dataInitialized) return '去任务中心初始化'
  return '查看任务中心'
})

const nextStepCards = computed(() => {
  if (!configStore.dataInitialized) return []
  return [
    {
      title: '明日之星',
      description: '先看最新交易日候选股和分析结果，确认系统已经给出的重点标的。',
      route: '/tomorrow-star',
    },
    {
      title: '单股诊断',
      description: '对单只股票补看 K 线、评分细项和历史表现，适合首次核对结果口径。',
      route: '/diagnosis',
    },
    {
      title: '重点观察',
      description: '把准备跟踪的股票加入观察列表，记录仓位和后续操作建议。',
      route: '/watchlist',
    },
  ]
})

onMounted(async () => {
  await loadConfigs()
  await loadStatus()
  await loadDiagnostics()
})

async function loadConfigs() {
  try {
    await configStore.loadConfigs()
    configs.value = {
      tushare_token: configStore.tushareToken || '',
      zhipuai_api_key: configStore.configs.zhipuai_api_key || '',
      dashscope_api_key: configStore.configs.dashscope_api_key || '',
      gemini_api_key: configStore.configs.gemini_api_key || '',
      default_reviewer: configStore.configs.default_reviewer || 'quant',
      min_score_threshold: parseFloat(configStore.configs.min_score_threshold || '4.0'),
    }
  } catch (error) {
    console.error('Failed to load configs:', error)
  }
}

async function loadStatus() {
  try {
    await configStore.checkTushareStatus()
  } catch (error) {
    console.error('Failed to load tushare status:', error)
  }
}

async function loadDiagnostics() {
  diagnosticsLoading.value = true
  try {
    diagnostics.value = await apiTasks.getDiagnostics()
  } catch (error) {
    console.error('Failed to load diagnostics:', error)
    noticeStore.setNotice({
      type: 'warning',
      title: '本机诊断读取失败',
      message: error instanceof Error ? error.message : '请稍后重试，或先确认后端服务是否稳定。',
      actionLabel: '前往配置',
      actionRoute: '/config',
    })
  } finally {
    diagnosticsLoading.value = false
  }
}

function goToTaskCenter() {
  saveInitTaskViewState({ activeTab: 'tasks' })
  router.push('/update')
}

function handleDiagnosticsAction() {
  if (!configStore.apiAvailable) {
    router.push('/config')
    return
  }
  goToTaskCenter()
}

function checkTagType(status: string) {
  const map: Record<string, 'success' | 'warning' | 'danger' | 'info'> = {
    success: 'success',
    warning: 'warning',
    error: 'danger',
    info: 'info',
  }
  return map[status] || 'info'
}

function checkStatusLabel(status: string) {
  const map: Record<string, string> = {
    success: '正常',
    warning: '待处理',
    error: '异常',
    info: '未完成',
  }
  return map[status] || status
}

async function verifyTushare() {
  if (!configStore.apiAvailable) {
    ElMessage.error(configStore.statusError || '后端服务暂不可用')
    return
  }
  if (!configs.value.tushare_token) {
    ElMessage.warning('请先输入 API Token')
    return
  }

  verifying.value = true
  try {
    const result = await configStore.verifyTushareToken(configs.value.tushare_token)
    if (result.valid) {
      ElMessage.success('验证成功，请保存配置')
    } else {
      ElMessage.error('Token 验证失败: ' + result.message)
    }
  } catch (error) {
    ElMessage.error('验证失败: ' + error)
  } finally {
    verifying.value = false
  }
}

async function saveConfigs(startInitialization: boolean) {
  if (!configStore.apiAvailable) {
    ElMessage.error(configStore.statusError || '后端服务暂不可用')
    return
  }
  if (!configs.value.tushare_token) {
    ElMessage.warning('请先填写并验证 Tushare Token')
    return
  }

  if (startInitialization) {
    savingAndInitializing.value = true
  } else {
    saving.value = true
  }

  try {
    const verifyResult = await configStore.verifyTushareToken(configs.value.tushare_token)
    if (!verifyResult.valid) {
      ElMessage.error(`Token 验证失败: ${verifyResult.message}`)
      return
    }

    await configStore.saveEnv({
      ...configs.value,
      min_score_threshold: String(configs.value.min_score_threshold),
    })
    await loadStatus()
    ElMessage.success(startInitialization ? '配置已保存，开始初始化任务' : '配置已保存')

    if (configStore.tushareReady && startInitialization) {
      try {
        const result = await apiTasks.startUpdate('quant', false, 1)
        saveInitTaskViewState({
          activeTab: 'tasks',
          selectedTaskId: result.task.id,
          bootstrapTaskId: result.task.id,
        })
        router.push('/update')
        return
      } catch (startError) {
        try {
          const runningResp = await apiTasks.getRunning()
          const bootstrapTask = runningResp.tasks.find((task) => task.task_type === 'full_update')
          if (bootstrapTask) {
            saveInitTaskViewState({
              activeTab: 'logs',
              selectedTaskId: bootstrapTask.id,
              bootstrapTaskId: bootstrapTask.id,
            })
            ElMessage.warning(`检测到已有初始化任务 #${bootstrapTask.id}，已跳转到任务中心继续查看`)
            router.push('/update')
            return
          }
        } catch (recoverError) {
          console.error('Failed to recover running bootstrap task:', recoverError)
        }
        throw startError
      }
    }

    if (configStore.tushareReady) {
      router.push('/tomorrow-star')
    }
  } catch (error) {
    console.error('saveConfigs failed:', error)
    const message = getUserSafeErrorMessage(error, '保存失败')
    ElMessage.error(isInitializationPendingError(error) ? message : `保存失败: ${message}`)
  } finally {
    saving.value = false
    savingAndInitializing.value = false
  }
}
</script>

<style scoped lang="scss">
.config-page {
  max-width: 800px;

  .startup-panel {
    display: flex;
    flex-direction: column;
    gap: 16px;
    margin-bottom: 24px;
    padding: 18px;
    border-radius: 14px;
    background: linear-gradient(135deg, #eff6ff 0%, #f8fafc 100%);
    border: 1px solid #dbeafe;
  }

  .startup-panel__header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
  }

  .startup-panel__title {
    font-size: 18px;
    font-weight: 700;
    color: #0f172a;
  }

  .startup-panel__subtitle {
    margin-top: 4px;
    color: #475569;
    line-height: 1.6;
  }

  .startup-panel__actions {
    display: inline-flex;
    gap: 8px;
    flex-shrink: 0;
  }

  .startup-checklist {
    display: grid;
    gap: 12px;
  }

  .startup-check {
    padding: 14px 16px;
    border-radius: 12px;
    border: 1px solid #cbd5e1;
    background: rgba(255, 255, 255, 0.9);
  }

  .startup-check.is-success {
    border-color: #86efac;
  }

  .startup-check.is-warning {
    border-color: #fdba74;
  }

  .startup-check.is-error {
    border-color: #fca5a5;
  }

  .startup-check__title-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 8px;
  }

  .startup-check__title {
    font-weight: 600;
    color: #0f172a;
  }

  .startup-check__summary,
  .startup-check__action {
    line-height: 1.7;
    color: #475569;
  }

  .startup-check__action {
    margin-top: 6px;
    font-size: 13px;
  }

  .status-alert {
    margin-bottom: 20px;
  }

  .init-guide-panel {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    margin: 0 0 24px;
    padding: 16px 18px;
    border-radius: 12px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
  }

  .init-guide-copy {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .init-guide-title {
    font-weight: 600;
    color: var(--color-text-primary);
  }

  .init-guide-text {
    font-size: 13px;
    line-height: 1.7;
    color: var(--color-text-secondary);
  }

  .next-steps-panel {
    margin: 0 0 24px;
    padding: 18px;
    border-radius: 12px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
  }

  .next-steps-panel__title {
    margin-bottom: 14px;
    font-weight: 600;
    color: var(--color-text-primary);
  }

  .next-steps-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px;
  }

  .next-step-card {
    padding: 14px;
    border: 1px solid #dbeafe;
    border-radius: 12px;
    background: #fff;
    text-align: left;
    cursor: pointer;
    transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
  }

  .next-step-card:hover {
    transform: translateY(-1px);
    border-color: #60a5fa;
    box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
  }

  .next-step-card__title {
    margin-bottom: 8px;
    font-weight: 600;
    color: #0f172a;
  }

  .next-step-card__desc {
    font-size: 13px;
    line-height: 1.7;
    color: #475569;
  }

  .config-form {
    .verify-button {
      border-color: #0284c7;
      background: #0284c7;
      color: #fff;

      &:hover,
      &:focus {
        border-color: #0369a1;
        background: #0369a1;
        color: #fff;
      }
    }

    .form-tip {
      margin-left: 12px;
      font-size: 12px;
      color: var(--color-text-light);

      a {
        color: var(--color-primary);
        &:hover {
          text-decoration: underline;
        }
      }
    }
  }

  :deep(.el-divider__text) {
    font-weight: 500;
    color: var(--color-text-primary);
  }

  .llm-divider {
    :deep(.el-divider__text) {
      color: #999;
    }
    :deep(.el-divider__line) {
      border-color: #e0e0e0;
    }
  }

  .form-tip-disabled {
    color: #999;
    opacity: 0.6;

    a {
      color: #999;
    }
  }

  .question-icon {
    margin-left: 8px;
    font-size: 16px;
    color: var(--color-text-light);
    cursor: help;

    &:hover {
      color: var(--color-primary);
    }
  }

  @media (max-width: 768px) {
    .startup-panel__header {
      flex-direction: column;
    }

    .startup-panel__actions {
      width: 100%;
      flex-wrap: wrap;
    }

    .init-guide-panel {
      flex-direction: column;
      align-items: stretch;
    }

    .next-steps-grid {
      grid-template-columns: 1fr;
    }
  }
}
</style>
