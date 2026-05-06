<template>
  <div class="admin-page">
    <el-card>
      <template #header>
        <div class="card-header" :class="{ 'card-header--mobile': isMobile }">
          <span>用户管理</span>
          <el-input
            v-model="searchQuery"
            placeholder="搜索用户名或显示名称..."
            class="search-input"
            clearable
          />
        </div>
      </template>

      <template v-if="isMobile">
        <div v-if="filteredUsers.length" class="user-card-list">
          <el-card
            v-for="user in filteredUsers"
            :key="user.id"
            shadow="hover"
            class="user-card"
          >
            <div class="user-card__header">
              <div>
                <div class="user-card__title">{{ user.username }}</div>
                <div class="user-card__subtitle">{{ user.display_name || '未设置显示名称' }}</div>
              </div>
              <div class="user-card__tags">
                <el-tag :type="user.role === 'admin' ? 'danger' : 'info'" size="small">
                  {{ user.role === 'admin' ? '管理员' : '用户' }}
                </el-tag>
                <el-tag :type="user.is_active ? 'success' : 'danger'" size="small">
                  {{ user.is_active ? '活跃' : '禁用' }}
                </el-tag>
              </div>
            </div>

            <div class="user-card__meta">
              <div class="meta-item">
                <span class="meta-label">日配额</span>
                <span class="meta-value">{{ user.daily_quota }}</span>
              </div>
              <div class="meta-item">
                <span class="meta-label">注册时间</span>
                <span class="meta-value">{{ formatDate(user.created_at) }}</span>
              </div>
            </div>

            <div class="user-card__actions">
              <el-button size="small" @click="openEditDialog(user)">编辑</el-button>
              <el-button size="small" @click="showUsage(user)">用量</el-button>
              <el-button
                v-if="user.is_active"
                size="small"
                type="danger"
                plain
                @click="handleDisable(user)"
              >
                禁用
              </el-button>
              <el-button
                v-else
                size="small"
                type="success"
                plain
                @click="handleEnable(user)"
              >
                启用
              </el-button>
            </div>
          </el-card>
        </div>
        <el-empty v-else description="未找到匹配用户" />
      </template>

      <el-table v-else :data="filteredUsers" stripe>
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
    <el-dialog
      v-model="editDialogVisible"
      title="编辑用户"
      :width="isMobile ? '100%' : '400px'"
      :fullscreen="isMobile"
    >
      <el-form :label-width="isMobile ? undefined : '80px'" :label-position="isMobile ? 'top' : 'right'">
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
    <el-dialog
      v-model="usageDialogVisible"
      title="用户用量统计"
      :width="isMobile ? '100%' : '500px'"
      :fullscreen="isMobile"
    >
      <div v-if="usageLoading">加载中...</div>
      <div v-else>
        <el-tag class="usage-total-tag">近7日总计 {{ userUsage.total_calls }} 次</el-tag>
        <template v-if="isMobile">
          <div v-if="userUsage.stats.length" class="usage-summary-list">
            <el-card
              v-for="stat in userUsage.stats"
              :key="stat.date"
              shadow="never"
              class="usage-summary-card"
            >
              <div class="usage-summary-card__header">
                <span>{{ stat.date }}</span>
                <el-tag size="small" type="info">{{ stat.total_calls }} 次</el-tag>
              </div>
              <div class="usage-summary-card__body">
                <div
                  v-for="(count, endpoint) in stat.endpoints"
                  :key="endpoint"
                  class="usage-endpoint-item"
                >
                  <span class="usage-endpoint-name">{{ endpoint }}</span>
                  <span class="usage-endpoint-count">{{ count }}</span>
                </div>
              </div>
            </el-card>
          </div>
          <el-empty v-else description="暂无用量数据" />
        </template>
        <el-table v-else :data="userUsage.stats" stripe size="small">
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
import { useResponsive } from '@/composables/useResponsive'
import type { UserListItem, UsageStatsResponse } from '@/types'

const users = ref<UserListItem[]>([])
const searchQuery = ref('')
const { isMobile } = useResponsive()

const filteredUsers = computed(() => {
  if (!searchQuery.value) return users.value
  const q = searchQuery.value.toLowerCase()
  return users.value.filter(u =>
    u.username.toLowerCase().includes(q) ||
    (u.display_name ?? '').toLowerCase().includes(q)
  )
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
  gap: 16px;
}

.search-input {
  width: 200px;
}

.user-card-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.user-card {
  border-radius: 14px;
}

.user-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.user-card__title {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.user-card__subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.user-card__tags {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.user-card__meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.meta-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.meta-value {
  font-size: 14px;
  color: var(--el-text-color-primary);
  word-break: break-word;
}

.user-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}

.usage-total-tag {
  margin-bottom: 12px;
}

.usage-summary-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.usage-summary-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  font-weight: 600;
}

.usage-summary-card__body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.usage-endpoint-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
}

.usage-endpoint-name {
  color: var(--el-text-color-secondary);
  word-break: break-all;
}

.usage-endpoint-count {
  flex-shrink: 0;
  color: var(--el-text-color-primary);
}

@media (max-width: 767px) {
  .admin-page {
    gap: 12px;
  }

  .card-header--mobile {
    flex-direction: column;
    align-items: stretch;
  }

  .search-input {
    width: 100%;
  }

  .user-card__header,
  .usage-summary-card__header {
    flex-direction: column;
    align-items: flex-start;
  }

  .user-card__tags {
    justify-content: flex-start;
  }

  .user-card__meta {
    grid-template-columns: 1fr;
  }

  .user-card__actions :deep(.el-button) {
    min-width: 72px;
  }
}
</style>
