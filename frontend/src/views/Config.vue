<template>
  <div class="config-page">
    <el-card>
      <template #header>
        <span>配置管理</span>
      </template>

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
        <el-alert
          v-if="statusSummary"
          :title="statusSummary.title"
          :description="statusSummary.description"
          :type="statusSummary.type"
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
        <el-divider content-position="left">LLM API 配置 (可选)</el-divider>

        <el-form-item label="GLM API Key">
          <el-input
            v-model="configs.zhipuai_api_key"
            type="password"
            show-password
            placeholder="智谱 GLM-4V-Flash (免费)"
            style="width: 400px"
          />
          <div class="form-tip">
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
          />
          <div class="form-tip">
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
          />
          <div class="form-tip">
            获取地址: <a href="https://ai.google.dev/" target="_blank">https://ai.google.dev/</a>
          </div>
        </el-form-item>

        <!-- 其他配置 -->
        <el-divider content-position="left">其他配置</el-divider>

        <el-form-item label="默认评分器">
          <el-radio-group v-model="configs.default_reviewer">
            <el-radio value="quant">量化评分</el-radio>
            <el-radio value="glm">GLM</el-radio>
            <el-radio value="qwen">通义千问</el-radio>
            <el-radio value="gemini">Gemini</el-radio>
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
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { useConfigStore } from '@/store/config'
import { apiTasks } from '@/api'

const configStore = useConfigStore()
const router = useRouter()

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

onMounted(async () => {
  await loadConfigs()
  await loadStatus()
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
      await apiTasks.startUpdate('quant', false, 1)
      router.push('/update')
      return
    }

    if (configStore.tushareReady) {
      router.push('/tomorrow-star')
    }
  } catch (error) {
    ElMessage.error('保存失败: ' + error)
  } finally {
    saving.value = false
    savingAndInitializing.value = false
  }
}
</script>

<style scoped lang="scss">
.config-page {
  max-width: 800px;

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

  .config-form {
    .status-alert {
      margin-bottom: 20px;
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
}
</style>
