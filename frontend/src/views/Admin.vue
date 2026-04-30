<template>
  <div class="admin-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>用户管理</span>
          <el-input
            v-model="searchQuery"
            placeholder="搜索用户名..."
            style="width: 200px"
            clearable
          />
        </div>
      </template>

      <el-table :data="filteredUsers" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="username" label="用户名" width="120" />
        <el-table-column prop="display_name" label="显示名称" width="120">
          <template #default="{ row }">{{ row.display_name || '-' }}</template>
        </el-table-column>
        <el-table-column prop="role" label="角色" width="100">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" size="small">
              {{ row.role === 'admin' ? '管理员' : '用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="is_active" label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
              {{ row.is_active ? '活跃' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="daily_quota" label="日配额" width="80" />
        <el-table-column prop="created_at" label="注册时间" width="170">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="200">
          <template #default="{ row }">
            <el-button size="small" link @click="openEditDialog(row)">编辑</el-button>
            <el-button size="small" link @click="showUsage(row)">用量</el-button>
            <el-button
              v-if="row.is_active"
              size="small"
              type="danger"
              link
              @click="handleDisable(row)"
            >
              禁用
            </el-button>
            <el-button
              v-else
              size="small"
              type="success"
              link
              @click="handleEnable(row)"
            >
              启用
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 编辑用户对话框 -->
    <el-dialog v-model="editDialogVisible" title="编辑用户" width="400px">
      <el-form label-width="80px">
        <el-form-item label="用户名">
          <el-input :model-value="editingUser?.username" disabled />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="editForm.role">
            <el-option label="用户" value="user" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item label="日配额">
          <el-input-number v-model="editForm.daily_quota" :min="0" :max="100000" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSaveEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 用量统计对话框 -->
    <el-dialog v-model="usageDialogVisible" title="用户用量统计" width="500px">
      <div v-if="usageLoading">加载中...</div>
      <div v-else>
        <el-tag style="margin-bottom: 12px">近7日总计 {{ userUsage.total_calls }} 次</el-tag>
        <el-table :data="userUsage.stats" stripe size="small">
          <el-table-column prop="date" label="日期" width="120" />
          <el-table-column prop="total_calls" label="调用次数" width="80" />
          <el-table-column label="端点明细">
            <template #default="{ row }">
              <div v-for="(count, endpoint) in row.endpoints" :key="endpoint" style="font-size: 12px">
                {{ endpoint }}: {{ count }}
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiAuth } from '@/api'
import type { UserListItem, UsageStatsResponse } from '@/types'

const users = ref<UserListItem[]>([])
const searchQuery = ref('')

const filteredUsers = computed(() => {
  if (!searchQuery.value) return users.value
  const q = searchQuery.value.toLowerCase()
  return users.value.filter(u => u.username.toLowerCase().includes(q))
})

async function loadUsers() {
  try {
    users.value = await apiAuth.adminGetUsers()
  } catch { /* ignore */ }
}

// --- 编辑 ---
const editDialogVisible = ref(false)
const editingUser = ref<UserListItem | null>(null)
const editForm = reactive({ role: '', daily_quota: 1000 })

function openEditDialog(user: UserListItem) {
  editingUser.value = user
  editForm.role = user.role
  editForm.daily_quota = user.daily_quota
  editDialogVisible.value = true
}

async function handleSaveEdit() {
  if (!editingUser.value) return
  try {
    await apiAuth.adminUpdateUser(editingUser.value.id, editForm)
    ElMessage.success('用户信息已更新')
    editDialogVisible.value = false
    await loadUsers()
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '更新失败')
  }
}

// --- 启用/禁用 ---
async function handleDisable(user: UserListItem) {
  try {
    await ElMessageBox.confirm(`确定要禁用用户 "${user.username}" 吗？`, '确认', { type: 'warning' })
    await apiAuth.adminDisableUser(user.id)
    ElMessage.success('用户已禁用')
    await loadUsers()
  } catch { /* ignore cancel */ }
}

async function handleEnable(user: UserListItem) {
  try {
    await apiAuth.adminUpdateUser(user.id, { is_active: true })
    ElMessage.success('用户已启用')
    await loadUsers()
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  }
}

// --- 用量 ---
const usageDialogVisible = ref(false)
const usageLoading = ref(false)
const userUsage = ref<UsageStatsResponse>({ stats: [], total_calls: 0 })

async function showUsage(user: UserListItem) {
  usageDialogVisible.value = true
  usageLoading.value = true
  try {
    userUsage.value = await apiAuth.adminGetUsage(user.id)
  } catch { /* ignore */ }
  finally {
    usageLoading.value = false
  }
}

// --- 工具 ---
function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString('zh-CN')
}

onMounted(() => {
  loadUsers()
})
</script>

<style scoped lang="scss">
.admin-page {
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
</style>
