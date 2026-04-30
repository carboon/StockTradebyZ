<template>
  <div class="profile-page">
    <el-card class="profile-card">
      <template #header>
        <div class="card-header">
          <span>账户信息</span>
        </div>
      </template>

      <el-descriptions :column="2" border>
        <el-descriptions-item label="用户名">{{ authStore.user?.username }}</el-descriptions-item>
        <el-descriptions-item label="显示名称">{{ authStore.user?.display_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="角色">
          <el-tag :type="authStore.user?.role === 'admin' ? 'danger' : 'info'" size="small">
            {{ authStore.user?.role === 'admin' ? '管理员' : '普通用户' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="每日配额">{{ authStore.user?.daily_quota }}</el-descriptions-item>
        <el-descriptions-item label="注册时间">{{ formatDate(authStore.user?.created_at) }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 修改密码 -->
    <el-card class="profile-card">
      <template #header>
        <div class="card-header">
          <span>修改密码</span>
        </div>
      </template>

      <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="100px" style="max-width: 400px">
        <el-form-item label="旧密码" prop="old_password">
          <el-input v-model="pwdForm.old_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="pwdForm.new_password" type="password" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="pwdLoading" @click="handleChangePassword">确认修改</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- API Key 管理 -->
    <el-card class="profile-card">
      <template #header>
        <div class="card-header">
          <span>API Key 管理</span>
          <el-button type="primary" size="small" @click="showCreateKeyDialog = true">创建新 Key</el-button>
        </div>
      </template>

      <el-table :data="apiKeys" stripe>
        <el-table-column prop="key_prefix" label="前缀" width="100" />
        <el-table-column prop="name" label="名称" width="200">
          <template #default="{ row }">{{ row.name || '-' }}</template>
        </el-table-column>
        <el-table-column prop="is_active" label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
              {{ row.is_active ? '活跃' : '已吊销' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_used_at" label="最后使用" width="180">
          <template #default="{ row }">{{ row.last_used_at ? formatDate(row.last_used_at) : '未使用' }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button
              v-if="row.is_active"
              type="danger"
              link
              size="small"
              @click="handleRevokeKey(row.id)"
            >
              吊销
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 近7日用量 -->
    <el-card class="profile-card">
      <template #header>
        <div class="card-header">
          <span>近 7 日用量统计</span>
          <el-tag size="small">总计 {{ usageStats.total_calls }} 次</el-tag>
        </div>
      </template>

      <el-table :data="usageStats.stats" stripe>
        <el-table-column prop="date" label="日期" width="120" />
        <el-table-column prop="total_calls" label="调用次数" width="100" />
        <el-table-column label="端点明细">
          <template #default="{ row }">
            <div v-for="(count, endpoint) in row.endpoints" :key="endpoint" class="endpoint-item">
              <span class="endpoint-name">{{ endpoint }}</span>
              <span class="endpoint-count">{{ count }} 次</span>
            </div>
            <span v-if="Object.keys(row.endpoints).length === 0" class="text-muted">无调用</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 创建 Key 对话框 -->
    <el-dialog v-model="showCreateKeyDialog" title="创建 API Key" width="450px">
      <el-form @submit.prevent="handleCreateKey">
        <el-form-item label="名称（可选）">
          <el-input v-model="newKeyName" placeholder="给 Key 取个名字方便识别" />
        </el-form-item>
      </el-form>
      <div v-if="newlyCreatedKey" class="key-display">
        <p class="key-warning">请立即复制保存，此 Key 仅显示一次：</p>
        <el-input :model-value="newlyCreatedKey" readonly>
          <template #append>
            <el-button @click="copyKey">复制</el-button>
          </template>
        </el-input>
      </div>
      <template #footer>
        <el-button @click="showCreateKeyDialog = false">关闭</el-button>
        <el-button type="primary" :loading="createKeyLoading" @click="handleCreateKey">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useAuthStore } from '@/store/auth'
import { apiAuth } from '@/api'
import type { ApiKeyInfo, UsageStatsResponse } from '@/types'

const authStore = useAuthStore()

// --- 密码修改 ---
const pwdFormRef = ref<FormInstance>()
const pwdLoading = ref(false)
const pwdForm = reactive({ old_password: '', new_password: '' })
const pwdRules: FormRules = {
  old_password: [{ required: true, message: '请输入旧密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码至少6个字符', trigger: 'blur' },
  ],
}

async function handleChangePassword() {
  if (!pwdFormRef.value) return
  await pwdFormRef.value.validate(async (valid) => {
    if (!valid) return
    pwdLoading.value = true
    try {
      await apiAuth.changePassword(pwdForm.old_password, pwdForm.new_password)
      ElMessage.success('密码修改成功')
      pwdForm.old_password = ''
      pwdForm.new_password = ''
    } catch (err: unknown) {
      ElMessage.error(err instanceof Error ? err.message : '修改失败')
    } finally {
      pwdLoading.value = false
    }
  })
}

// --- API Key 管理 ---
const apiKeys = ref<ApiKeyInfo[]>([])
const showCreateKeyDialog = ref(false)
const newKeyName = ref('')
const newlyCreatedKey = ref('')
const createKeyLoading = ref(false)

async function loadApiKeys() {
  try {
    apiKeys.value = await apiAuth.listApiKeys()
  } catch { /* ignore */ }
}

async function handleCreateKey() {
  createKeyLoading.value = true
  try {
    const res = await apiAuth.createApiKey(newKeyName.value || undefined)
    newlyCreatedKey.value = res.key
    newKeyName.value = ''
    await loadApiKeys()
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '创建失败')
  } finally {
    createKeyLoading.value = false
  }
}

async function handleRevokeKey(id: number) {
  try {
    await ElMessageBox.confirm('确定要吊销此 API Key 吗？吊销后使用该 Key 的请求将被拒绝。', '确认吊销', {
      type: 'warning',
    })
    await apiAuth.revokeApiKey(id)
    ElMessage.success('API Key 已吊销')
    await loadApiKeys()
  } catch { /* ignore cancel */ }
}

function copyKey() {
  navigator.clipboard.writeText(newlyCreatedKey.value)
  ElMessage.success('已复制到剪贴板')
}

// --- 用量统计 ---
const usageStats = ref<UsageStatsResponse>({ stats: [], total_calls: 0 })

async function loadUsage() {
  try {
    usageStats.value = await apiAuth.getUsage()
  } catch { /* ignore */ }
}

// --- 工具函数 ---
function formatDate(dateStr?: string | null): string {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}

// --- 初始化 ---
onMounted(() => {
  loadApiKeys()
  loadUsage()
})
</script>

<style scoped lang="scss">
.profile-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
}

.key-display {
  margin-top: 16px;

  .key-warning {
    color: #dc2626;
    font-size: 13px;
    margin: 0 0 8px;
  }
}

.endpoint-item {
  display: inline-flex;
  gap: 4px;
  margin-right: 12px;
  font-size: 13px;

  .endpoint-name {
    color: #64748b;
  }

  .endpoint-count {
    font-weight: 600;
  }
}

.text-muted {
  color: #94a3b8;
  font-size: 13px;
}
</style>
