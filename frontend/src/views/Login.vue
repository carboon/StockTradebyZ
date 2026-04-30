<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <el-icon :size="36" color="#00B4D8"><TrendCharts /></el-icon>
        <h1>StockTrader</h1>
        <p>A股量化选股系统</p>
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
        @submit.prevent="handleLogin"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="form.username"
            placeholder="请输入用户名"
            :prefix-icon="User"
            size="large"
            :disabled="loading"
          />
        </el-form-item>

        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            :prefix-icon="Lock"
            size="large"
            show-password
            :disabled="loading"
            @keyup.enter="handleLogin"
          />
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            size="large"
            :loading="loading"
            class="login-btn"
            @click="handleLogin"
          >
            {{ loading ? '登录中...' : '登录' }}
          </el-button>
        </el-form-item>
      </el-form>

      <div class="login-footer">
        <span>还没有账户？</span>
        <el-button type="primary" link @click="router.push('/register')">立即注册</el-button>
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
import { checkHealth } from '@/api'

const router = useRouter()
const authStore = useAuthStore()
const formRef = ref<FormInstance>()
const loading = ref(false)

// 后端健康状态
const backendHealthy = ref(true)

const form = reactive({
  username: '',
  password: '',
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

// 后端状态（用于显示提示，但不阻塞登录）
const backendStatus = computed(() => {
  if (backendHealthy.value) {
    return { ok: true, type: 'success' as const, title: '', message: '' }
  }
  return {
    ok: false,
    type: 'warning' as const,
    title: '后端服务连接异常',
    message: '无法连接到后端服务，请确认服务已启动。您可以尝试点击登录，系统会自动重试。',
  }
})

async function checkBackend() {
  const result = await checkHealth()
  backendHealthy.value = result !== null
  if (backendHealthy.value) {
    ElMessage.success('后端服务连接正常')
  } else {
    ElMessage.warning('后端服务仍不可用')
  }
}

async function handleLogin() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return

    loading.value = true
    try {
      await authStore.login(form.username, form.password)
      ElMessage.success('登录成功')
      // 登录成功后，如果有 redirect 参数则跳转，否则去首页
      const redirect = router.currentRoute.value.query.redirect as string
      router.push(redirect || '/tomorrow-star')
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '登录失败'
      ElMessage.error(message)
      // 如果是网络错误，更新后端状态
      if (message.includes('fetch') || message.includes('网络') || message.includes('连接') || message.includes('ECONNREFUSED')) {
        backendHealthy.value = false
      }
    } finally {
      loading.value = false
    }
  })
}

// 登录页挂载时检查后端状态
onMounted(async () => {
  await checkBackend()
})
</script>

<style scoped lang="scss">
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100vh;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
}

.login-card {
  width: 400px;
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

.login-btn {
  width: 100%;
}

.login-footer {
  text-align: center;
  margin-top: 16px;
  font-size: 14px;
  color: #64748b;
}
</style>
