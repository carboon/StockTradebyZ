<template>
  <div class="admin-page">
    <el-card>
      <template #header>
        <div class="card-header" :class="{ 'card-header--mobile': isMobile }">
          <span>用户管理</span>
          <div class="header-controls">
            <el-select v-model="onlineFilter" placeholder="在线状态" clearable class="online-filter">
              <el-option label="全部用户" :value="null" />
              <el-option label="仅在线" :value="true" />
              <el-option label="仅离线" :value="false" />
            </el-select>
            <el-input
              v-model="searchQuery"
              placeholder="搜索用户名或显示名称..."
              class="search-input"
              clearable
            />
          </div>
        </div>
      </template>

      <div class="admin-data-actions" :class="{ 'admin-data-actions--mobile': isMobile }">
        <div class="data-action-group">
          <div class="data-action-group__title">用户信息</div>
          <div class="data-action-group__buttons">
            <el-button type="primary" plain @click="handleExportUsers">导出用户CSV</el-button>
            <el-button :loading="userImporting" @click="triggerUserImport">导入用户CSV</el-button>
          </div>
        </div>
        <div class="data-action-group">
          <div class="data-action-group__title">重点观察信息</div>
          <div class="data-action-group__buttons">
            <el-button type="success" plain @click="handleExportWatchlist">导出观察CSV</el-button>
            <el-button :loading="watchlistImporting" @click="triggerWatchlistImport">导入观察CSV</el-button>
          </div>
        </div>
        <input
          ref="userImportInput"
          class="hidden-file-input"
          type="file"
          accept=".csv,text/csv"
          @change="handleUserImportChange"
        />
        <input
          ref="watchlistImportInput"
          class="hidden-file-input"
          type="file"
          accept=".csv,text/csv"
          @change="handleWatchlistImportChange"
        />
      </div>

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
                <el-tag :type="user.is_online ? 'success' : 'info'" size="small">
                  {{ user.is_online ? '在线' : '离线' }}
                </el-tag>
              </div>
            </div>

            <div class="user-card__meta">
              <div class="meta-item">
                <span class="meta-label">注册时间</span>
                <span class="meta-value">{{ formatDate(user.created_at) }}</span>
              </div>
              <div class="meta-item">
                <span class="meta-label">最后登录</span>
                <span class="meta-value">{{ user.last_login_at ? formatDate(user.last_login_at) : '从未登录' }}</span>
              </div>
              <div class="meta-item">
                <span class="meta-label">近10天API请求</span>
                <span class="meta-value">{{ user.recent_visit_count }} 次</span>
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
        <el-table-column prop="is_online" label="在线" width="70">
          <template #default="{ row }">
            <el-tag :type="row.is_online ? 'success' : 'info'" size="small">
              {{ row.is_online ? '在线' : '离线' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_login_at" label="最后登录" width="170">
          <template #default="{ row }">{{ row.last_login_at ? formatDate(row.last_login_at) : '从未登录' }}</template>
        </el-table-column>
        <el-table-column prop="recent_visit_count" label="近10天API请求" width="120" align="center">
          <template #default="{ row }">{{ row.recent_visit_count }} 次</template>
        </el-table-column>
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
const onlineFilter = ref<boolean | null>(null)
const userImportInput = ref<HTMLInputElement | null>(null)
const watchlistImportInput = ref<HTMLInputElement | null>(null)
const userImporting = ref(false)
const watchlistImporting = ref(false)
const { isMobile } = useResponsive()

const filteredUsers = computed(() => {
  let result = users.value

  // 按在线状态筛选
  if (onlineFilter.value !== null) {
    result = result.filter(u => u.is_online === onlineFilter.value)
  }

  // 按搜索关键词筛选
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    result = result.filter(u =>
      u.username.toLowerCase().includes(q) ||
      (u.display_name ?? '').toLowerCase().includes(q)
    )
  }

  return result
})

async function loadUsers() {
  try {
    users.value = await apiAuth.adminGetUsers()
  } catch { /* ignore */ }
}

function buildDownloadName(prefix: string): string {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, '0')
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
  return `${prefix}_${stamp}.csv`
}

function downloadBlob(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => window.URL.revokeObjectURL(url), 0)
}

function triggerUserImport() {
  userImportInput.value?.click()
}

function triggerWatchlistImport() {
  watchlistImportInput.value?.click()
}

async function handleExportUsers() {
  try {
    const blob = await apiAuth.adminExportUsers()
    downloadBlob(blob, buildDownloadName('users_export'))
    ElMessage.success('用户 CSV 已开始下载')
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '导出失败')
  }
}

async function handleExportWatchlist() {
  try {
    const blob = await apiAuth.adminExportWatchlist()
    downloadBlob(blob, buildDownloadName('watchlist_export'))
    ElMessage.success('重点观察 CSV 已开始下载')
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '导出失败')
  }
}

async function handleUserImportChange(event: Event) {
  const input = event.target as HTMLInputElement | null
  const file = input?.files?.[0]
  if (!file) return
  userImporting.value = true
  try {
    const result = await apiAuth.adminImportUsers(file)
    ElMessage.success(`用户导入完成：新增 ${result.inserted_count} 条，更新 ${result.updated_count} 条`)
    await loadUsers()
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '用户导入失败')
  } finally {
    userImporting.value = false
    if (input) {
      input.value = ''
    }
  }
}

async function handleWatchlistImportChange(event: Event) {
  const input = event.target as HTMLInputElement | null
  const file = input?.files?.[0]
  if (!file) return
  watchlistImporting.value = true
  try {
    const result = await apiAuth.adminImportWatchlist(file)
    ElMessage.success(`重点观察导入完成：新增 ${result.inserted_count} 条，更新 ${result.updated_count} 条`)
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '重点观察导入失败')
  } finally {
    watchlistImporting.value = false
    if (input) {
      input.value = ''
    }
  }
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

.header-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.admin-data-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.data-action-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 14px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.72), rgba(248, 250, 252, 0.95));
}

.data-action-group__title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.data-action-group__buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.hidden-file-input {
  display: none;
}

.online-filter {
  width: 120px;
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

  .header-controls {
    flex-direction: column;
    width: 100%;
  }

  .admin-data-actions {
    grid-template-columns: 1fr;
  }

  .data-action-group__buttons :deep(.el-button) {
    width: 100%;
  }

  .online-filter {
    width: 100%;
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
