<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <el-icon :size="36" color="#00B4D8"><TrendCharts /></el-icon>
        <h1>注册账户</h1>
        <p>创建你的 StockTrader 账户</p>
      </div>

      <!-- 后端状态提示（不阻塞输入） -->
      <el-alert
        v-if="!backendStatus.ok"
        :type="backendStatus.type"
        :closable="false"
        class="backend-status-alert"
        show-icon
      >
        <template #title>
          {{ backendStatus.title }}
        </template>
        <template #default>
          {{ backendStatus.message }}
          <el-button link type="primary" @click="checkBackend">重新检查</el-button>
        </template>
      </el-alert>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        @submit.prevent="handleRegister"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="form.username"
            placeholder="3-50个字符"
            :prefix-icon="User"
            size="large"
            :disabled="loading"
          />
        </el-form-item>

        <el-form-item label="显示名称（可选）" prop="displayName">
          <el-input
            v-model="form.displayName"
            placeholder="显示名称"
            size="large"
            :disabled="loading"
          />
        </el-form-item>

        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="至少6个字符"
            :prefix-icon="Lock"
            size="large"
            show-password
            :disabled="loading"
          />
          <div class="field-hint field-hint--warning">安全起见，请不要与个人常用密码设置相同</div>
        </el-form-item>

        <el-form-item label="确认密码" prop="confirmPassword">
          <el-input
            v-model="form.confirmPassword"
            type="password"
            placeholder="再次输入密码"
            :prefix-icon="Lock"
            size="large"
            show-password
            :disabled="loading"
            @keyup.enter="handleRegister"
          />
        </el-form-item>

        <el-form-item :label="registerQuestion" prop="adminWechat">
          <el-input
            v-model="form.adminWechat"
            placeholder="请输入答案"
            size="large"
            :disabled="loading"
          />
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            size="large"
            :loading="loading"
            class="login-btn"
            @click="handleRegister"
          >
            {{ loading ? '注册中...' : '注册' }}
          </el-button>
        </el-form-item>
      </el-form>

      <div class="login-footer">
        <span>已有账户？</span>
        <el-button type="primary" link @click="router.push('/login')">去登录</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { TrendCharts, User, Lock } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { useAuthStore } from '@/store/auth'
import { apiAuth, checkHealth } from '@/api'

const router = useRouter()
const authStore = useAuthStore()
const formRef = ref<FormInstance>()
const loading = ref(false)
const registerQuestionText = ref('系统管理员的微信名是什么')
const HEALTH_CHECK_RETRIES = 3
const HEALTH_CHECK_DELAY_MS = 1000

// 后端健康状态
const backendHealthy = ref(true)

const form = reactive({
  username: '',
  displayName: '',
  password: '',
  confirmPassword: '',
  adminWechat: '',
})

// 后端状态（用于显示提示，但不阻塞注册）
const backendStatus = computed(() => {
  if (backendHealthy.value) {
    return { ok: true, type: 'success' as const, title: '', message: '' }
  }
  return {
    ok: false,
    type: 'warning' as const,
    title: '后端服务连接异常',
    message: '无法连接到后端服务，请确认服务已启动。您可以尝试点击注册，系统会自动重试。',
  }
})
const registerQuestion = computed(() => registerQuestionText.value || '系统管理员的微信名是什么')

async function checkBackend() {
  for (let attempt = 0; attempt <= HEALTH_CHECK_RETRIES; attempt += 1) {
    const result = await checkHealth()
    if (result !== null) {
      backendHealthy.value = true
      ElMessage.success('后端服务连接正常')
      return
    }
    if (attempt < HEALTH_CHECK_RETRIES) {
      await new Promise((resolve) => setTimeout(resolve, HEALTH_CHECK_DELAY_MS))
    }
  }

  backendHealthy.value = false
  ElMessage.warning('后端服务仍不可用')
}

async function refreshBackendState(silent: boolean = false) {
  const result = await checkHealth()
  if (result !== null) {
    backendHealthy.value = true
    if (!silent) {
      ElMessage.success('后端服务连接正常')
    }
    return true
  }

  backendHealthy.value = false
  if (!silent) {
    ElMessage.warning('后端服务仍不可用')
  }
  return false
}

const validateConfirm = (_rule: unknown, value: string, callback: (err?: Error) => void) => {
  if (value !== form.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '用户名长度为3-50个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少6个字符', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    { validator: validateConfirm, trigger: 'blur' },
  ],
  adminWechat: [
    { required: true, message: '请输入答案', trigger: 'blur' },
  ],
}

async function handleRegister() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return

    loading.value = true
    try {
      await authStore.register(
        form.username,
        form.password,
        form.adminWechat,
        form.displayName || undefined,
      )
      ElMessage.success('注册成功')
      router.push('/login')
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '注册失败'
      ElMessage.error(message)
      // 如果是网络错误，更新后端状态
      if (message.includes('fetch') || message.includes('网络') || message.includes('连接') || message.includes('ECONNREFUSED')) {
        void refreshBackendState(true)
      }
    } finally {
      loading.value = false
    }
  })
}

// 注册页挂载时检查后端状态
onMounted(async () => {
  try {
    const prompt = await apiAuth.getRegisterValidationPrompt()
    registerQuestionText.value = prompt.question || registerQuestionText.value
  } catch {
    // ignore and keep default prompt
  }
  await refreshBackendState(true)
  if (!backendHealthy.value) {
    await checkBackend()
  }
})
</script>

<style scoped lang="scss">
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-height: 100vh;
  min-height: 100dvh;
  padding: 24px 16px;
  box-sizing: border-box;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
}

.login-card {
  width: min(92vw, 400px);
  padding: 40px;
  background: white;
  border-radius: 16px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}

.login-header {
  text-align: center;
  margin-bottom: 24px;

  h1 {
    margin: 12px 0 4px;
    font-size: 24px;
    font-weight: 700;
    color: #0f172a;
  }

  p {
    color: #64748b;
    font-size: 14px;
  }
}

.backend-status-alert {
  margin-bottom: 20px;

  :deep(.el-alert__content) {
    display: flex;
    align-items: center;
    gap: 8px;
  }
}

.field-hint {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.5;
  color: #64748b;
}

.field-hint--warning {
  color: #b45309;
}

.login-btn {
  width: 100%;
}

.login-footer {
  text-align: center;
  margin-top: 16px;
  font-size: 14px;
  color: #64748b;
}

@media (max-width: 767px) {
  .login-page {
    align-items: flex-start;
    padding: 24px 12px 32px;
  }

  .login-card {
    width: min(92vw, 420px);
    margin: 0 auto;
    padding: 28px 20px;
    border-radius: 14px;
    box-shadow: 0 16px 36px rgba(0, 0, 0, 0.24);
  }

  .login-header {
    margin-bottom: 20px;

    h1 {
      font-size: 22px;
    }
  }

  .backend-status-alert {
    :deep(.el-alert__content) {
      display: block;
    }
  }

  .login-footer {
    display: flex;
    justify-content: center;
    flex-wrap: wrap;
    gap: 4px;
  }
}
</style>
