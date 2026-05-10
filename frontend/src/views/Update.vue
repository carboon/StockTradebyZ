<template>
  <div class="ops-page">
    <el-tabs v-model="activeTab" class="ops-tabs">
      <!-- 管理员总览（阶段4新增） -->
      <el-tab-pane label="总览" name="dashboard">
        <div class="tab-content">
          <el-card v-if="summaryLoading" class="loading-card">
            <el-skeleton :rows="5" animated />
          </el-card>

          <template v-else>
            <!-- 快速操作 -->
            <el-card class="quick-actions-card">
              <template #header>
                <span>快速操作</span>
              </template>
              <div class="quick-actions-grid">
                <el-button
                  type="primary"
                  :disabled="hasActiveBackgroundWork"
                  :loading="startingUpdate"
                  @click="startDataUpdate"
                >
                  更新最新交易日数据
                </el-button>
                <el-button
                  :disabled="hasActiveBackgroundWork"
                  :loading="startingFullUpdate"
                  @click="startFullUpdate"
                >
                  重新执行全量初始化
                </el-button>
                <el-button
                  :loading="checkingFreshness"
                  @click="checkDataFreshness"
                >
                  查询最新数据时效
                </el-button>
                <el-button
                  :loading="checkingIntegrity"
                  @click="checkRecent120Integrity"
                >
                  检查数据完整性
                </el-button>
                <el-button
                  :loading="revalidatingDate"
                  @click="promptRevalidateTradeDate"
                >
                  指定日期重验证
                </el-button>
              </div>
              <div v-if="hasActiveBackgroundWork" class="running-hint">
                <el-icon class="is-loading"><Loading /></el-icon>
                {{ activeWorkHint }}
              </div>
            </el-card>

            <el-card v-if="isMobile" class="mobile-summary-card">
              <template #header>
                <span>移动端摘要</span>
              </template>
              <div class="mobile-summary-list">
                <div
                  v-for="card in dashboardStatusCards"
                  :key="card.label"
                  class="mobile-summary-item"
                  :class="card.type ? `mobile-summary-item--${card.type}` : ''"
                >
                  <div class="mobile-summary-item__top">
                    <span class="mobile-summary-item__label">{{ card.label }}</span>
                    <span class="mobile-summary-item__value">{{ card.value }}</span>
                  </div>
                  <div class="mobile-summary-item__meta">{{ card.meta || '-' }}</div>
                </div>
              </div>
            </el-card>

            <!-- 三段式状态总览 -->
            <el-card class="dashboard-cards">
              <div class="dashboard-cards__grid">
                <div
                  v-for="stage in adminSummary?.pipeline_status"
                  :key="stage.key"
                  class="dashboard-card"
                  :class="`dashboard-card--${stage.status}`"
                >
                  <div class="dashboard-card__label">{{ stage.label }}</div>
                  <div class="dashboard-card__value">{{ stage.value }}</div>
                  <div class="dashboard-card__meta">{{ stage.meta || '-' }}</div>
                  <div class="dashboard-card__detail">{{ stage.detail || '-' }}</div>
                </div>
              </div>
            </el-card>

            <el-card class="dashboard-cards">
              <template #header>
                <span>CSV 拉取进度</span>
              </template>
              <div class="dashboard-cards__grid">
                <div class="dashboard-card dashboard-card--success">
                  <div class="dashboard-card__label">已就绪</div>
                  <div class="dashboard-card__value">{{ Number(adminSummary?.data_production?.raw_ready_count || 0) }}</div>
                  <div class="dashboard-card__meta">已达有效最新交易日</div>
                </div>
                <div class="dashboard-card dashboard-card--warning">
                  <div class="dashboard-card__label">缺失</div>
                  <div class="dashboard-card__value">{{ Number(adminSummary?.data_production?.raw_missing_count || 0) }}</div>
                  <div class="dashboard-card__meta">缺少 CSV 文件</div>
                </div>
                <div class="dashboard-card dashboard-card--warning">
                  <div class="dashboard-card__label">停牌</div>
                  <div class="dashboard-card__value">{{ Number(adminSummary?.data_production?.raw_suspended_count || 0) }}</div>
                  <div class="dashboard-card__meta">当日停牌</div>
                </div>
                <div class="dashboard-card dashboard-card--warning">
                  <div class="dashboard-card__label">长期停牌</div>
                  <div class="dashboard-card__value">{{ Number(adminSummary?.data_production?.raw_long_stale_count || 0) }}</div>
                  <div class="dashboard-card__meta">长期无数据</div>
                </div>
                <div class="dashboard-card dashboard-card--danger">
                  <div class="dashboard-card__label">异常</div>
                  <div class="dashboard-card__value">{{ Number(adminSummary?.data_production?.raw_invalid_count || 0) }}</div>
                  <div class="dashboard-card__meta">CSV 无法识别日期</div>
                </div>
              </div>
            </el-card>

            <!-- 待处理事项 -->
            <el-card v-if="adminSummary?.pending_actions?.length" class="pending-actions-card">
              <template #header>
                <span>待处理事项</span>
              </template>
              <div class="pending-actions-list">
                <div
                  v-for="(action, idx) in adminSummary.pending_actions"
                  :key="idx"
                  class="pending-action-item"
                  :class="`pending-action-item--${action.type}`"
                >
                  <div class="pending-action-item__content">
                    <strong>{{ action.title }}</strong>
                    <span>{{ action.message }}</span>
                  </div>
                  <el-button size="small" :type="action.type === 'error' ? 'danger' : action.type === 'warning' ? 'warning' : 'primary'" @click="handlePendingAction(action)">
                    {{ action.action }}
                  </el-button>
                </div>
              </div>
            </el-card>

            <!-- 当前任务 -->
            <el-card v-if="adminSummary?.current_task" class="current-task-card">
              <template #header>
                <div class="card-header">
                  <span>当前任务</span>
                  <el-tag :type="getTaskStatusType(adminSummary.current_task.status)" size="small">
                    {{ adminSummary.current_task.status }}
                  </el-tag>
                </div>
              </template>
              <div class="current-task-content">
                <div class="current-task-info">
                  <div class="current-task-row">
                    <span class="label">任务类型:</span>
                    <span>{{ getTaskTypeLabel(adminSummary.current_task.task_type) }}</span>
                  </div>
                  <div class="current-task-row">
                    <span class="label">当前阶段:</span>
                    <span>{{ adminSummary.current_task.stage_label || '-' }}</span>
                  </div>
                  <div class="current-task-row">
                    <span class="label">进度:</span>
                    <span>{{ currentTaskProgressPercent }}%</span>
                  </div>
                </div>
                <el-progress
                  :percentage="currentTaskProgressPercent"
                  :stroke-width="12"
                  :status="getProgressStatus(adminSummary.current_task.status)"
                />
                <div class="current-task-summary">
                  {{ adminSummary.current_task.summary || '-' }}
                </div>
                <div v-if="currentTaskProgressLines.length" class="current-task-metrics">
                  <div
                    v-for="line in currentTaskProgressLines"
                    :key="line.label"
                    class="current-task-metrics__row"
                  >
                    <span class="current-task-metrics__label">{{ line.label }}</span>
                    <span class="current-task-metrics__value">{{ line.value }}</span>
                  </div>
                </div>
                <div class="current-task-actions">
                  <el-button size="small" @click="activeTab = 'tasks'">查看详情</el-button>
                  <el-button size="small" @click="activeTab = 'logs'">查看日志</el-button>
                </div>
              </div>
            </el-card>

            <!-- 最近任务结果 -->
            <el-card v-if="adminSummary?.latest_task" class="latest-task-card">
              <template #header>
                <span>最近任务结果</span>
              </template>
              <div class="latest-task-content">
                <div class="latest-task-summary">
                  {{ adminSummary.latest_task_summary || '-' }}
                </div>
                <div v-if="adminSummary.latest_task.completed_at" class="latest-task-time">
                  完成时间: {{ formatDateTime(adminSummary.latest_task.completed_at) }}
                </div>
              </div>
            </el-card>

            <!-- 系统状态 -->
            <el-card class="system-status-card">
              <template #header>
                <div class="card-header">
                  <span>系统状态</span>
                  <el-tag :type="adminSummary?.system_ready ? 'success' : 'warning'" size="small">
                    {{ adminSummary?.system_ready ? '就绪' : '未就绪' }}
                  </el-tag>
                </div>
              </template>
              <div class="system-status-grid">
                <div class="system-status-item">
                  <span class="system-status-item__label">有效最新交易日</span>
                  <span class="system-status-item__value">{{ adminSummary?.latest_trade_date || '-' }}</span>
                </div>
                <div class="system-status-item">
                  <span class="system-status-item__label">交易日历最新开市日</span>
                  <span class="system-status-item__value">{{ String(adminSummary?.data_production?.raw_calendar_latest_trade_date || '-') }}</span>
                </div>
                <div class="system-status-item">
                  <span class="system-status-item__label">数据库最新</span>
                  <span class="system-status-item__value">{{ adminSummary?.latest_db_date || '-' }}</span>
                </div>
                <div class="system-status-item">
                  <span class="system-status-item__label">候选最新</span>
                  <span class="system-status-item__value">{{ adminSummary?.latest_candidate_date || '-' }}</span>
                </div>
                <div class="system-status-item">
                  <span class="system-status-item__label">分析最新</span>
                  <span class="system-status-item__value">{{ adminSummary?.latest_analysis_date || '-' }}</span>
                </div>
                <div class="system-status-item" :class="{ 'has-gap': adminSummary?.data_gap?.has_gap }">
                  <span class="system-status-item__label">数据缺口</span>
                  <span class="system-status-item__value">
                    {{ adminSummary?.data_gap?.has_gap ? `${adminSummary.gap_days} 天` : '无缺口' }}
                  </span>
                </div>
              </div>
            </el-card>

          </template>
        </div>
      </el-tab-pane>

      <!-- 任务管理 -->
      <el-tab-pane label="任务管理" name="tasks">
        <div class="tab-content">
          <el-card class="connectivity-card">
            <div class="connectivity-card__row">
              <div class="connectivity-card__status">
                <span class="connectivity-card__label">任务推送</span>
                <el-tag :type="socketStatusTagType" size="small">{{ socketStatusLabel }}</el-tag>
              </div>
              <div class="connectivity-card__actions">
                <el-button size="small" @click="reconnectSocketsNow">立即重连</el-button>
                <el-button size="small" :loading="diagnosticsLoading" @click="loadDiagnostics">刷新诊断</el-button>
                <el-button size="small" @click="copyDiagnostics">复制诊断摘要</el-button>
              </div>
            </div>
            <div class="connectivity-card__desc">{{ socketStatusDescription }}</div>
          </el-card>

          <div class="progress-overview-grid">
            <el-card class="progress-summary-card progress-summary-card--bootstrap">
              <template #header>
                <div class="card-header">
                  <span>首次初始化进度</span>
                  <el-tag :type="bootstrapStatusTagType" size="small">{{ bootstrapStatusLabel }}</el-tag>
                </div>
              </template>

              <div class="progress-summary-card__body">
                <div class="progress-summary-card__headline">{{ bootstrapOverviewTitle }}</div>
                <div class="progress-summary-card__subline">{{ bootstrapOverviewDetail }}</div>
                <div v-if="bootstrapObservabilityRows.length" class="bootstrap-observability">
                  <div
                    v-for="row in bootstrapObservabilityRows"
                    :key="row.label"
                    class="bootstrap-observability__row"
                  >
                    <span class="bootstrap-observability__label">{{ row.label }}</span>
                    <span class="bootstrap-observability__value">{{ row.value }}</span>
                  </div>
                </div>
                <el-progress
                  :percentage="bootstrapProgressBarValue"
                  :stroke-width="12"
                  :status="bootstrapProgressStatus"
                />
                <div class="progress-summary-card__meta">
                  <span>{{ bootstrapProgressMeta }}</span>
                  <span v-if="bootstrapProgressEta">{{ bootstrapProgressEta }}</span>
                </div>
                <div class="progress-summary-card__actions">
                  <el-button
                    v-if="initializationRunningTask"
                    size="small"
                    type="primary"
                    @click="focusTask(initializationRunningTask, 'logs')"
                  >
                    查看初始化日志
                  </el-button>
                  <el-button
                    v-else
                    size="small"
                    :disabled="!canStartBootstrap"
                    @click="startBootstrap"
                  >
                    {{ bootstrapButtonText }}
                  </el-button>
                </div>
              </div>
            </el-card>

            <el-card class="progress-summary-card progress-summary-card--incremental">
              <template #header>
                <div class="card-header">
                  <span>每日更新进度</span>
                  <el-tag :type="incrementalSummaryTagType" size="small">{{ incrementalSummaryLabel }}</el-tag>
                </div>
              </template>

              <div class="progress-summary-card__body">
                <div class="progress-summary-card__headline">{{ incrementalOverviewTitle }}</div>
                <div class="progress-summary-card__subline">{{ incrementalOverviewDetail }}</div>
                <el-progress
                  :percentage="incrementalSummaryProgressValue"
                  :stroke-width="12"
                  :status="incrementalSummaryProgressStatus"
                />
                <div class="progress-summary-card__meta">
                  <span>{{ incrementalProgressSummary }}</span>
                  <span v-if="incrementalProgressEtaText">{{ incrementalProgressEtaText }}</span>
                </div>
              </div>
            </el-card>
          </div>

          <!-- 首次初始化引导 -->
          <el-card v-if="showBootstrap" class="bootstrap-card">
            <template #header>
              <div class="card-header">
                <span>首次初始化引导</span>
                <el-tag :type="bootstrapStatusTagType" size="small">
                  {{ bootstrapStatusLabel }}
                </el-tag>
              </div>
            </template>

            <div class="bootstrap-content">
              <p class="bootstrap-desc">{{ bootstrapDescription }}</p>

              <div class="bootstrap-notes">
                <div class="bootstrap-note">
                  <span class="bootstrap-note-label">预计耗时</span>
                  <span class="bootstrap-note-value">首次全量初始化通常需要数分钟到十几分钟，期间页面可刷新。</span>
                </div>
                <div class="bootstrap-note">
                  <span class="bootstrap-note-label">刷新恢复</span>
                  <span class="bootstrap-note-value">页面会优先恢复你刚才查看的初始化任务和日志视图。</span>
                </div>
                <div class="bootstrap-note">
                  <span class="bootstrap-note-label">功能限制</span>
                  <span class="bootstrap-note-value">在原始数据、候选结果和分析结果都齐备前，业务页仍可能继续提示未完成初始化。</span>
                </div>
              </div>

              <div class="bootstrap-steps">
                <div
                  v-for="step in bootstrapSteps"
                  :key="step.key"
                  class="bootstrap-step"
                  :class="step.done ? 'is-done' : 'is-pending'"
                >
                  <div class="step-indicator">{{ step.done ? '✓' : step.index }}</div>
                  <div class="step-content">
                    <div class="step-title">{{ step.title }}</div>
                    <div class="step-meta">{{ step.meta }}</div>
                  </div>
                </div>
              </div>

              <div class="bootstrap-actions">
                <el-button
                  type="primary"
                  :disabled="!canStartBootstrap"
                  :loading="bootstrapStarting"
                  @click="startBootstrap"
                >
                  {{ bootstrapButtonText }}
                </el-button>
                <el-button
                  v-if="initializationRunningTask"
                  @click="focusTask(initializationRunningTask, 'logs')"
                >
                  继续查看当前任务
                </el-button>
                <el-button
                  v-if="showRetryBootstrap"
                  @click="retryBootstrap"
                >
                  重新发起初始化
                </el-button>
                <el-button
                  v-if="selectedRecoveryTask"
                  text
                  type="primary"
                  @click="focusTask(selectedRecoveryTask, 'logs')"
                >
                  查看失败详情
                </el-button>
                <el-button
                  v-if="!configStore.tushareReady || !configStore.apiAvailable"
                  text
                  type="primary"
                  @click="goToConfig"
                >
                  去配置页处理
                </el-button>
                <el-button :icon="Refresh" @click="reloadTasks">刷新状态</el-button>
              </div>

              <el-alert
                v-if="recoveryAlert"
                :title="recoveryAlert.title"
                :description="recoveryAlert.description"
                :type="recoveryAlert.type"
                show-icon
                :closable="false"
              />
              <el-alert
                v-if="stalledBootstrapAlert"
                :title="stalledBootstrapAlert.title"
                :description="stalledBootstrapAlert.description"
                type="warning"
                show-icon
                :closable="false"
              />
            </div>
          </el-card>

          <el-card class="diagnostics-card">
            <template #header>
              <div class="card-header">
                <span>本机诊断</span>
                <span class="diagnostics-generated-at">{{ diagnosticsGeneratedAt }}</span>
              </div>
            </template>

            <el-collapse v-model="diagnosticsPanels" class="diagnostics-collapse">
              <el-collapse-item name="diagnostics">
                <template #title>
                  <span class="collapse-title">展开本机诊断详情</span>
                </template>

                <div v-if="diagnosticChecks.length > 0" class="diagnostics-list">
                  <div
                    v-for="check in diagnosticChecks"
                    :key="check.key"
                    class="diagnostic-item"
                  >
                    <div class="diagnostic-item__header">
                      <span class="diagnostic-item__title">{{ check.label }}</span>
                      <el-tag :type="getStatusType(check.status)" size="small">{{ getCheckStatusLabel(check.status) }}</el-tag>
                    </div>
                    <div class="diagnostic-item__summary">{{ check.summary }}</div>
                    <div v-if="check.action" class="diagnostic-item__action">{{ check.action }}</div>
                  </div>
                </div>
                <el-empty v-else description="诊断信息暂不可用" :image-size="60" />
              </el-collapse-item>
            </el-collapse>
          </el-card>

          <el-card v-if="activeDailyUpdateTask || incrementalFallbackActive" class="incremental-progress-card">
            <div class="incremental-progress-card__header">
              <div>
                <div class="incremental-progress-card__title">{{ activeDailyUpdateTitle }}</div>
                <div class="incremental-progress-card__meta">
                  <span class="stage-indicator">{{ activeDailyUpdateStageIndicator }}</span>
                  <span class="stage-divider">/</span>
                  <span>{{ activeDailyUpdateMeta }}</span>
                  <span v-if="activeDailyUpdateEtaText" class="eta-text"> / {{ activeDailyUpdateEtaText }}</span>
                  <span v-if="activeDailyUpdateDetail" class="detail-text"> / {{ activeDailyUpdateDetail }}</span>
                </div>
              </div>
              <div class="incremental-progress-card__counts">
                {{ activeDailyUpdateCounts }}
              </div>
            </div>
            <el-progress
              :percentage="activeDailyUpdateProgressBarValue"
              :stroke-width="10"
              :format="activeDailyUpdateProgressFormat"
              :color="activeDailyUpdateProgressColor"
            />
          </el-card>
          <el-alert
            v-else-if="hasFailedDailyUpdate"
            title="增量更新上次未完成"
            :description="latestDailyUpdateFailureText"
            type="warning"
            show-icon
            :closable="false"
          />

          <!-- 运行中任务 -->
          <el-card class="tasks-card">
            <template #header>
              <div class="card-header">
                <span>运行中任务</span>
                <el-tag v-if="runningTaskBadgeCount > 0" type="warning" size="small">
                  {{ runningTaskBadgeCount }} 个
                </el-tag>
                <el-tag v-else type="info" size="small">无</el-tag>
              </div>
            </template>

            <el-empty v-if="taskCenterRunningTasks.length === 0" description="当前没有运行中任务" :image-size="60" />
            <div v-else class="running-tasks-list">
              <div
                v-for="task in taskCenterRunningTasks"
                :key="task.id"
                class="task-item"
                :class="{ 'is-selected': selectedTask?.id === task.id }"
                @click="selectTask(task)"
              >
                <div class="task-main">
                  <div class="task-header">
                    <span class="task-id">#{{ task.id }}</span>
                    <span class="task-type">{{ getTaskTypeLabel(task.task_type) }}</span>
                    <el-tag :type="getStatusType(task.status)" size="small">{{ task.status }}</el-tag>
                  </div>
                  <div class="task-stage">{{ getTaskStageText(task) }}</div>
                  <div class="task-progress-primary">{{ getTaskProgressPrimary(task) }}</div>
                  <div v-if="getTaskProgressSecondary(task)" class="task-progress-secondary">{{ getTaskProgressSecondary(task) }}</div>
                  <el-progress :percentage="task.progress_meta_json?.percent ?? task.progress" :stroke-width="6" :show-text="false" />
                </div>
                <el-button v-if="task.id >= 0" text type="danger" size="small" @click.stop="cancelTask(task)">取消</el-button>
              </div>
            </div>
          </el-card>

          <!-- 历史任务 -->
          <el-card class="tasks-card">
            <template #header>
              <div class="card-header">
                <span>历史任务</span>
                <el-button text type="danger" size="small" @click="clearTasks">清空</el-button>
              </div>
            </template>

            <div v-if="isMobile" class="history-task-cards">
              <el-empty v-if="recentHistoryTasks.length === 0" description="暂无历史任务" :image-size="60" />
              <div
                v-for="task in recentHistoryTasks"
                :key="task.id"
                class="history-task-card"
                @click="viewTaskDetail(task)"
              >
                <div class="history-task-card__header">
                  <div class="history-task-card__title">
                    <span>#{{ task.id }}</span>
                    <span>{{ getTaskTypeLabel(task.task_type) }}</span>
                  </div>
                  <el-tag :type="getStatusType(task.status)" size="small">{{ task.status }}</el-tag>
                </div>
                <div class="history-task-card__summary">{{ task.summary || '暂无摘要' }}</div>
                <div class="history-task-card__meta">{{ formatDateTime(task.created_at) }}</div>
              </div>
            </div>
            <el-table v-else :data="historyTasks" max-height="300" @row-click="viewTaskDetail">
              <el-table-column prop="id" label="ID" width="60" />
              <el-table-column label="类型" width="100">
                <template #default="{ row }">{{ getTaskTypeLabel(row.task_type) }}</template>
              </el-table-column>
              <el-table-column label="状态" width="80">
                <template #default="{ row }">
                  <el-tag :type="getStatusType(row.status)" size="small">{{ row.status }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="summary" label="摘要" min-width="200" show-overflow-tooltip />
              <el-table-column label="创建时间" width="160">
                <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
              </el-table-column>
            </el-table>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- 日志记录 -->
      <el-tab-pane label="日志记录" name="logs">
        <div class="tab-content">
          <el-card class="logs-card">
            <template #header>
              <div class="card-header">
                <div class="log-controls">
                  <el-radio-group v-model="logFilter" size="small" @change="filterLogs">
                    <el-radio-button value="all">全部日志</el-radio-button>
                    <el-radio-button value="task">当前任务</el-radio-button>
                  </el-radio-group>
                  <el-tag v-if="selectedTask" size="small" type="info">
                    #{{ selectedTask.id }} {{ getTaskTypeLabel(selectedTask.task_type) }}
                  </el-tag>
                  <el-tag v-else-if="logFilter === 'task'" size="small" type="warning">
                    请先选择任务
                  </el-tag>
                </div>
                <div class="log-actions">
                  <el-checkbox v-model="autoScroll">自动滚动</el-checkbox>
                  <el-button text size="small" @click="clearLogsDisplay">清空显示</el-button>
                </div>
              </div>
            </template>

            <div v-if="isMobile" class="mobile-log-summary">
              <div class="mobile-log-summary__hint">
                移动端仅展示最近告警/错误摘要，完整长日志请切换桌面端查看。
              </div>
              <el-empty v-if="recentFailedLogs.length === 0" description="暂无最近告警或错误日志" :image-size="60" />
              <div
                v-for="(log, index) in recentFailedLogs"
                :key="log.id || `${log.task_id}-${index}`"
                class="mobile-log-item"
                :class="`mobile-log-item--${String(log.level || '').toLowerCase()}`"
              >
                <div class="mobile-log-item__header">
                  <span>{{ formatLogTime(log.log_time) }}</span>
                  <span>{{ log.level?.toUpperCase() }}</span>
                </div>
                <div class="mobile-log-item__message">{{ log.message }}</div>
              </div>
            </div>
            <div v-else ref="logRef" class="log-container" @scroll="handleLogScroll">
              <div v-if="filteredLogs.length === 0" class="log-empty">
                <el-icon><Document /></el-icon>
                <p>{{ selectedTask ? '当前仅展示 WARN / ERROR，暂无可显示日志' : '当前仅展示 WARN / ERROR，请选择任务或切换到"全部日志"' }}</p>
              </div>
              <div v-for="(log, index) in filteredLogs" :key="log.id || `${log.task_id}-${index}`" class="log-line" :class="`log-${log.level}`">
                <span class="log-time">{{ formatLogTime(log.log_time) }}</span>
                <span class="log-level">{{ log.level?.toUpperCase() }}</span>
                <span class="log-message">{{ log.message }}</span>
              </div>
            </div>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- 状态管理 -->
      <el-tab-pane label="状态管理" name="status">
        <div class="tab-content">
          <!-- 健康状态总览 -->
          <el-card class="health-card">
            <div class="health-summary">
              <div class="health-item" :class="{ 'is-healthy': dataStatus.rawData.exists }">
                <div class="health-icon">
                  <el-icon><CircleCheck v-if="dataStatus.rawData.exists" /><CircleClose v-else /></el-icon>
                </div>
                <div class="health-info">
                  <div class="health-title">数据状态</div>
                  <div class="health-desc">{{ dataStatus.rawData.exists ? '数据完整' : '缺少原始数据' }}</div>
                </div>
              </div>
              <div class="health-item is-healthy">
                <div class="health-icon">
                  <el-icon><CircleCheck /></el-icon>
                </div>
                <div class="health-info">
                  <div class="health-title">数据库</div>
                  <div class="health-desc">连接正常</div>
                </div>
              </div>
              <div class="health-item" :class="{ 'is-healthy': runningTasksCount === 0 }">
                <div class="health-icon">
                  <el-icon><CircleCheck v-if="runningTasksCount === 0" /><Loading v-else class="is-spinning" /></el-icon>
                </div>
                <div class="health-info">
                  <div class="health-title">任务状态</div>
                  <div class="health-desc">{{ runningTasksCount > 0 ? `${runningTasksCount}个运行中` : '无运行任务' }}</div>
                </div>
              </div>
            </div>
          </el-card>

          <el-card v-if="isMobile" class="mobile-status-card">
            <template #header>
              <span>关键系统状态</span>
            </template>
            <div class="mobile-status-list">
              <div class="mobile-status-row">
                <span>有效最新交易日</span>
                <strong>{{ adminSummary?.latest_trade_date || '-' }}</strong>
              </div>
              <div class="mobile-status-row">
                <span>数据库最新</span>
                <strong>{{ adminSummary?.latest_db_date || '-' }}</strong>
              </div>
              <div class="mobile-status-row">
                <span>候选最新</span>
                <strong>{{ adminSummary?.latest_candidate_date || '-' }}</strong>
              </div>
              <div class="mobile-status-row">
                <span>分析最新</span>
                <strong>{{ adminSummary?.latest_analysis_date || '-' }}</strong>
              </div>
              <div class="mobile-status-row">
                <span>数据缺口</span>
                <strong>{{ adminSummary?.data_gap?.has_gap ? `${adminSummary.gap_days} 天` : '无缺口' }}</strong>
              </div>
            </div>
          </el-card>

          <el-card v-if="adminSummary?.current_task" class="status-task-card">
            <template #header>
              <div class="card-header">
                <span>当前任务进度</span>
                <el-tag :type="getTaskStatusType(adminSummary.current_task.status)" size="small">
                  {{ adminSummary.current_task.status }}
                </el-tag>
              </div>
            </template>

            <div class="status-task-card__body">
              <div class="status-task-card__headline">
                #{{ adminSummary.current_task.id }} {{ getTaskTypeLabel(adminSummary.current_task.task_type || '') }}
              </div>
              <div class="status-task-card__subline">
                {{ adminSummary.current_task.stage_label || adminSummary.current_task.task_stage || '-' }}
              </div>
              <el-progress
                :percentage="currentTaskProgressPercent"
                :stroke-width="12"
                :status="getProgressStatus(adminSummary.current_task.status)"
              />
              <div v-if="currentTaskProgressLines.length" class="current-task-metrics">
                <div
                  v-for="line in currentTaskProgressLines"
                  :key="`status-${line.label}`"
                  class="current-task-metrics__row"
                >
                  <span class="current-task-metrics__label">{{ line.label }}</span>
                  <span class="current-task-metrics__value">{{ line.value }}</span>
                </div>
              </div>
            </div>
          </el-card>

          <!-- 数据详情 -->
          <el-card class="detail-card">
            <template #header>
              <div class="card-header">
                <span>原始数据详情</span>
                <el-button type="primary" size="small" :loading="checkingData" @click="checkDataFresh">
                  检查更新
                </el-button>
              </div>
            </template>

            <div class="detail-grid">
              <div class="detail-item">
                <span class="detail-label">股票数量</span>
                <span class="detail-value">{{ dataStatus.rawData.stockCount || 0 }} <small>只</small></span>
              </div>
              <div class="detail-item">
                <span class="detail-label">K线记录</span>
                <span class="detail-value">{{ dataStatus.rawData.rawRecordCount || 0 }} <small>条</small></span>
              </div>
              <div class="detail-item">
                <span class="detail-label">最新日期</span>
                <span class="detail-value">{{ dataStatus.rawData.latestDate || '-' }}</span>
              </div>
              <div class="detail-item">
                <span class="detail-label">数据来源</span>
                <span class="detail-value">Tushare</span>
              </div>
              <div class="detail-item">
                <span class="detail-label">流动性池</span>
                <span class="detail-value">Top 2000</span>
              </div>
            </div>
          </el-card>

          <!-- 环境信息 -->
          <el-card class="env-summary-card">
            <template #header>
              <span>系统环境</span>
            </template>

            <div class="env-summary-grid">
              <template v-for="section in dataStatus.environment" :key="section.key">
                <div v-if="section.key === 'service'" class="env-section">
                  <div class="env-section-title">{{ section.label }}</div>
                  <div class="env-chips">
                    <el-tag
                      v-for="(value, key) in getPrimitiveItems(section.items)"
                      :key="String(key)"
                      size="small"
                    >
                      {{ formatEnvKey(String(key)) }}: {{ formatEnvValue(value) }}
                    </el-tag>
                  </div>
                </div>
              </template>
            </div>
          </el-card>

          <!-- 更多环境信息（折叠） -->
          <el-collapse class="env-collapse">
            <el-collapse-item name="more">
              <template #title>
                <span class="collapse-title">更多环境信息</span>
              </template>
              <div class="env-details-grid">
                <template v-for="section in dataStatus.environment" :key="section.key">
                  <div v-if="section.key !== 'service' && section.key !== 'data_status'" class="env-detail-section">
                    <div class="env-detail-title">{{ section.label }}</div>
                    <div class="env-detail-items">
                      <div
                        v-for="(value, key) in getPrimitiveItems(section.items)"
                        :key="String(key)"
                        class="env-detail-item"
                      >
                        <span class="env-detail-key">{{ formatEnvKey(String(key)) }}</span>
                        <span class="env-detail-value">{{ formatEnvValue(value) }}</span>
                      </div>
                    </div>
                  </div>
                </template>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted, watch, provide } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import {
  Refresh,
  Loading,
  Document,
  CircleCheck,
  CircleClose,
} from '@element-plus/icons-vue'
import { apiTasks } from '@/api'
import { useConfigStore } from '@/store/config'
import { useNoticeStore } from '@/store/notice'
import { useResponsive } from '@/composables/useResponsive'
import type { AdminSummaryResponse, IncrementalUpdateStatus, Task, TaskDiagnosticCheck, TaskDiagnosticsResponse, TaskLogItem, TaskProgressMeta } from '@/types'
import { loadInitTaskViewState, saveInitTaskViewState, clearInitTaskViewState } from '@/utils/initTaskViewState'
import { formatDuration } from '@/utils'
import { getUserSafeErrorMessage, isInitializationPendingError } from '@/utils/userFacingErrors'

const configStore = useConfigStore()
const noticeStore = useNoticeStore()
const route = useRoute()
const router = useRouter()
const { isMobile } = useResponsive()

// Tab状态
const activeTab = ref<'dashboard' | 'tasks' | 'logs' | 'status'>('dashboard')
const logFilter = ref<'all' | 'task'>('task')
const autoScroll = ref(true)
const diagnosticsPanels = ref<string[]>([])

// 数据状态
function createEmptyDataStatus() {
  return {
    rawData: { exists: false, stockCount: 0, rawRecordCount: 0, latestDate: '' },
    candidates: { exists: false, count: 0, latestDate: '' },
    analysis: { exists: false, count: 0, latestDate: '' },
    kline: { exists: false, count: 0, latestDate: '' },
    dbSize: '-',
    environment: [] as Array<{ key: string; label: string; items: Record<string, any> }>,
  }
}

function createEmptyIncrementalStatus(): IncrementalUpdateStatus {
  return {
    status: 'idle',
    running: false,
    task_type: 'incremental_update',
    mode: 'idle',
    target_trade_date: null,
    stage_label: null,
    display_title: '',
    display_detail: '',
    progress: 0,
    current: 0,
    total: 0,
    current_code: '',
    updated_count: 0,
    skipped_count: 0,
    failed_count: 0,
    started_at: '',
    completed_at: '',
    eta_seconds: null,
    elapsed_seconds: 0,
    resume_supported: true,
    initial_completed: 0,
    completed_in_run: 0,
    checkpoint_path: null,
    last_error: null,
    message: '',
  }
}

const dataStatus = ref({
  ...createEmptyDataStatus(),
})
const incrementalStatus = ref<IncrementalUpdateStatus>(createEmptyIncrementalStatus())

// 任务状态
const runningTasks = ref<Task[]>([])
const historyTasks = ref<Task[]>([])
const selectedTask = ref<Task | null>(null)

// 日志状态
const allLogs = ref<TaskLogItem[]>([])
const selectedTaskLogs = ref<TaskLogItem[]>([])
const logRef = ref<HTMLElement>()

// 加载状态
const dataLoaded = ref(false)
const bootstrapStarting = ref(false)
const startingUpdate = ref(false)
const startingFullUpdate = ref(false)
const checkingData = ref(false)
const checkingFreshness = ref(false)
const checkingIntegrity = ref(false)
const revalidatingDate = ref(false)
const diagnosticsLoading = ref(false)
const diagnostics = ref<TaskDiagnosticsResponse | null>(null)

// 管理员总览（阶段4新增）
const adminSummary = ref<AdminSummaryResponse | null>(null)
const summaryLoading = ref(false)

// WebSocket
let ws: WebSocket | null = null
let opsWs: WebSocket | null = null
type SocketState = 'connected' | 'reconnecting' | 'polling' | 'disconnected'
const opsSocketState = ref<SocketState>('disconnected')
const taskSocketState = ref<SocketState>('disconnected')
const socketReconnectAttempts = ref(0)
let opsReconnectTimer: ReturnType<typeof setTimeout> | null = null
let taskReconnectTimer: ReturnType<typeof setTimeout> | null = null
let lastTaskSocketId: number | null = null

// 计算属性
const runningTasksCount = computed(() => runningTasks.value.length)
const isDailyBatchIncremental = computed(() => incrementalStatus.value.mode === 'daily_batch')
const activeDailyUpdateTask = computed(() => runningTasks.value.find((task) => isDailyUpdateTask(task)) || null)
const latestDailyUpdateTask = computed(() => {
  return historyTasks.value.find((task) => isDailyUpdateTask(task)) || null
})
const incrementalFallbackActive = computed(() => !activeDailyUpdateTask.value && incrementalStatus.value.running)
const incrementalFallbackFailed = computed(() => !latestDailyUpdateTask.value && incrementalStatus.value.status === 'failed')
const taskCenterRunningTasks = computed(() => runningTasks.value)
const runningTaskBadgeCount = computed(() => runningTasks.value.length)
const hasActiveBackgroundWork = computed(() => runningTasksCount.value > 0 || incrementalFallbackActive.value)
const hasFailedDailyUpdate = computed(() => {
  return Boolean(
    activeDailyUpdateTask.value?.status === 'failed'
    || latestDailyUpdateTask.value?.status === 'failed'
    || incrementalFallbackFailed.value,
  )
})
const initializationRunningTask = computed(() => runningTasks.value.find((task) => isBootstrapTask(task)) || null)
const latestFailedBootstrapTask = computed(() => {
  if (bootstrapFinished.value) return null
  return historyTasks.value.find((task) => isBootstrapTask(task) && task.status === 'failed') || null
})
const selectedRecoveryTask = computed(() => selectedTask.value || initializationRunningTask.value || latestFailedBootstrapTask.value)
const bootstrapInProgress = computed(() => bootstrapStarting.value || Boolean(initializationRunningTask.value))
const activeWorkHint = computed(() => {
  if (initializationRunningTask.value) {
    return `当前有 ${runningTasksCount.value} 个全量任务正在运行`
  }
  if (activeDailyUpdateTask.value) {
    return `${getTaskTypeLabel(activeDailyUpdateTask.value.task_type)}：${activeDailyUpdateDetail.value || getTaskProgressPrimary(activeDailyUpdateTask.value)}`
  }
  if (incrementalFallbackActive.value) {
    if (isDailyBatchIncremental.value) {
      return `${incrementalStatus.value.display_title || '按交易日批量刷新进行中'}：${incrementalStatus.value.target_trade_date || incrementalStatus.value.current_code || '-'}`
    }
    return `增量更新进行中：${incrementalStatus.value.current}/${incrementalStatus.value.total || '-'}${incrementalStatus.value.total > 0 ? ` (${incrementalProgressLabel.value})` : ''}`
  }
  if (runningTasksCount.value > 0) {
    return `当前有 ${runningTasksCount.value} 个任务正在运行`
  }
  return ''
})

const currentTaskMeta = computed(() => adminSummary.value?.current_task?.progress_meta_json || null)
const currentTaskProgressPercent = computed(() => {
  const metaPercent = currentTaskMeta.value?.percent
  const rawPercent = adminSummary.value?.current_task?.progress ?? 0
  const value = metaPercent ?? rawPercent
  if (value > 0 && value < 1) return 1
  return Math.round(value)
})
const currentTaskProgressLines = computed(() => {
  const task = adminSummary.value?.current_task
  const meta = currentTaskMeta.value
  if (!task) return []

  const lines: Array<{ label: string; value: string }> = []

  // 显示详细的执行进度，区分跳过和实际处理的数量
  if (meta?.current != null || meta?.total != null) {
    const initialCompleted = meta?.initial_completed ?? 0
    const completedInRun = meta?.completed_in_run ?? 0
    const current = meta?.current ?? 0
    const total = meta?.total ?? 0
    const currentCode = meta?.current_code ? ` / 当前 ${meta.current_code}` : ''

    // 如果有初始完成的数量，显示详细的跳过/处理信息
    if (initialCompleted > 0) {
      lines.push({
        label: '执行进度',
        value: `跳过 ${initialCompleted} / 已处理 ${completedInRun} / 总计 ${current}/${total}${currentCode}`,
      })
    } else {
      lines.push({
        label: '执行进度',
        value: `${current} / ${total}${currentCode}`,
      })
    }
  }

  if (meta?.ready_count != null || meta?.incremental_count != null || meta?.full_count != null) {
    lines.push({
      label: '本地分类',
      value: `已完整 ${meta?.ready_count ?? 0} / 增量 ${meta?.incremental_count ?? 0} / 全量 ${meta?.full_count ?? 0}`,
    })
  }

  if (meta?.csv_imported_count != null || meta?.csv_failed_count != null) {
    lines.push({
      label: 'CSV回灌',
      value: `${meta?.csv_imported_count ?? 0} 已导入 / ${meta?.csv_failed_count ?? 0} 失败`,
    })
  }

  if (meta?.eta_seconds != null) {
    lines.push({
      label: '预计剩余',
      value: formatSeconds(meta.eta_seconds),
    })
  }

  if (task.summary) {
    lines.push({
      label: '任务摘要',
      value: task.summary,
    })
  }

  return lines
})

const incrementalProgressPrecise = computed(() => {
  const total = incrementalStatus.value.total
  if (!total || total <= 0) return 0
  return Math.min(100, Math.max(0, (incrementalStatus.value.current / total) * 100))
})

const incrementalProgressBarValue = computed(() => {
  const precise = incrementalProgressPrecise.value
  return precise > 0 && precise < 1 ? 1 : Math.round(precise)
})

const incrementalProgressLabel = computed(() => `${incrementalProgressPrecise.value.toFixed(2)}%`)
const incrementalDisplayProgressText = computed(() => {
  if (isDailyBatchIncremental.value) {
    const target = incrementalStatus.value.target_trade_date || incrementalStatus.value.current_code || '-'
    return `目标交易日 ${target}`
  }
  return `进度 ${incrementalStatus.value.current}/${incrementalStatus.value.total || '-'}${incrementalStatus.value.total > 0 ? ` / ${incrementalProgressLabel.value}` : ''}`
})
const activeDailyUpdateTitle = computed(() => {
  if (activeDailyUpdateTask.value) {
    return getTaskTypeLabel(activeDailyUpdateTask.value.task_type)
  }
  return incrementalStatus.value.display_title || '最新交易日增量更新进行中'
})
const activeDailyUpdateProgressBarValue = computed(() => {
  if (activeDailyUpdateTask.value) {
    const value = activeDailyUpdateTask.value.progress_meta_json?.percent ?? activeDailyUpdateTask.value.progress ?? 0
    if (value > 0 && value < 1) return 1
    return Math.round(value)
  }
  return incrementalProgressBarValue.value
})
const activeDailyUpdateDetail = computed(() => {
  if (activeDailyUpdateTask.value) {
    return getTaskProgressSecondary(activeDailyUpdateTask.value)
  }
  if (incrementalStatus.value.display_detail) return incrementalStatus.value.display_detail
  if (isDailyBatchIncremental.value) {
    return `目标交易日 ${incrementalStatus.value.target_trade_date || incrementalStatus.value.current_code || '-'}`
  }
  return incrementalStatus.value.current_code ? `当前 ${incrementalStatus.value.current_code}` : ''
})
const activeDailyUpdateMeta = computed(() => {
  if (activeDailyUpdateTask.value) {
    return `${getTaskStageText(activeDailyUpdateTask.value)} / ${getTaskProgressPrimary(activeDailyUpdateTask.value)}`
  }
  return incrementalDisplayProgressText.value
})
const activeDailyUpdateEtaText = computed(() => {
  if (activeDailyUpdateTask.value) {
    const eta = activeDailyUpdateTask.value.progress_meta_json?.eta_seconds
    return eta != null ? `预计剩余 ${formatSeconds(eta)}` : ''
  }
  return incrementalStatus.value.eta_seconds != null ? `预计剩余 ${formatSeconds(incrementalStatus.value.eta_seconds)}` : ''
})
const activeDailyUpdateCounts = computed(() => {
  if (activeDailyUpdateTask.value) {
    const meta = activeDailyUpdateTask.value.progress_meta_json
    const ready = meta?.ready_count
    const failed = meta?.failed_count ?? 0
    if (ready != null) {
      return `${ready} 已就绪 / ${failed} 失败`
    }
    if (meta?.current != null && meta?.total != null) {
      return `${meta.current}/${meta.total}`
    }
    return `${activeDailyUpdateProgressBarValue.value}%`
  }
  if (isDailyBatchIncremental.value) {
    return `${incrementalStatus.value.updated_count} 只股票写入 / ${incrementalStatus.value.failed_count} 失败`
  }
  return `${incrementalStatus.value.updated_count} 更新 / ${incrementalStatus.value.skipped_count} 跳过 / ${incrementalStatus.value.failed_count} 失败`
})

	// 新增：阶段指示器 - 显示当前阶段
	const activeDailyUpdateStageIndicator = computed(() => {
	  if (activeDailyUpdateTask.value) {
	    const meta = activeDailyUpdateTask.value.progress_meta_json
	    const stageLabel = getTaskStageText(activeDailyUpdateTask.value)
	    const stageIndex = meta?.stage_index
	    const stageTotal = meta?.stage_total
	    if (stageIndex != null && stageTotal != null) {
	      return `${stageLabel} (${stageIndex}/${stageTotal})`
	    }
	    return stageLabel
	  }
	  // 增量更新模式 - 使用 stage_label 判断阶段
	  const stageLabel = incrementalStatus.value.stage_label || ''
	  if (stageLabel.includes('数据准备') || stageLabel.includes('CSV')) return '数据准备 (1/6)'
	  if (stageLabel.includes('量化初选') || stageLabel.includes('初选')) return '量化初选 (2/6)'
	  if (stageLabel.includes('候选筛选') || stageLabel.includes('筛选')) return '候选筛选 (3/6)'
	  if (stageLabel.includes('评分分析') || stageLabel.includes('评分')) return '评分分析 (4/6)'
	  if (stageLabel.includes('结果导出') || stageLabel.includes('导出')) return '结果导出 (5/6)'
	  if (stageLabel.includes('输出推荐') || stageLabel.includes('推荐')) return '输出推荐 (6/6)'
	  return '准备中'
	})

	// 新增：进度条格式化函数
	const activeDailyUpdateProgressFormat = (percentage: number) => {
	  if (activeDailyUpdateTask.value) {
	    const stageLabel = getTaskStageText(activeDailyUpdateTask.value)
	    return `${stageLabel} ${percentage}%`
	  }
	  return `${percentage}%`
	}

	// 新增：进度条颜色（根据阶段变化）
	const activeDailyUpdateProgressColor = computed(() => {
	  if (activeDailyUpdateTask.value) {
	    const stage = activeDailyUpdateTask.value.progress_meta_json?.stage ?? activeDailyUpdateTask.value.task_stage
	    const stageColors: Record<string, string | undefined> = {
	      queued: '#909399',
	      starting: '#909399',
	      preparing: '#409EFF',
	      data_preparing: '#409EFF',
	      fetch_data: '#409EFF',
	      csv_import: '#409EFF',
	      build_pool: '#67C23A',
	      build_candidates: '#E6A23C',
	      filter_candidates: '#E6A23C',
	      pre_filter: '#F56C6C',
	      score_analysis: '#F56C6C',
	      score_review: '#909399',
	      export_results: '#909399',
	      finalize: '#67C23A',
	      completed: '#67C23A',
	      failed: '#F56C6C',
	    }
	    return stageColors[stage ?? ''] ?? '#409EFF'
	  }
	  return '#409EFF'
	})

const bootstrapProgressValue = computed(() => initializationRunningTask.value?.progress_meta_json?.percent ?? initializationRunningTask.value?.progress ?? 0)
const bootstrapProgressBarValue = computed(() => {
  if (bootstrapFinished.value) return 100
  const value = bootstrapProgressValue.value
  return value > 0 && value < 1 ? 1 : Math.round(value)
})
const bootstrapProgressStatus = computed(() => {
  if (latestFailedBootstrapTask.value) return 'exception'
  if (bootstrapFinished.value) return 'success'
  if (bootstrapInProgress.value) return 'warning'
  return undefined
})
const bootstrapOverviewTitle = computed(() => {
  if (bootstrapFinished.value) return '首次初始化已完成'
  if (initializationRunningTask.value) return `初始化任务 #${initializationRunningTask.value.id} 进行中`
  if (latestFailedBootstrapTask.value) return '首次初始化失败，等待处理'
  return '首次初始化尚未开始'
})
const bootstrapOverviewDetail = computed(() => {
  if (initializationRunningTask.value) {
    return `${getTaskStageText(initializationRunningTask.value)} / ${getTaskProgressPrimary(initializationRunningTask.value)}`
  }
  if (latestFailedBootstrapTask.value) {
    return latestFailedBootstrapTask.value.error_message || latestFailedBootstrapTask.value.summary || '可查看日志定位失败点'
  }
  if (bootstrapFinished.value) {
    return '原始数据、候选结果和分析结果均已就绪'
  }
  return bootstrapDescription.value
})
const bootstrapProgressMeta = computed(() => {
  if (initializationRunningTask.value) {
    const secondary = getTaskProgressSecondary(initializationRunningTask.value)
    return [secondary, `当前进度 ${bootstrapProgressBarValue.value}%`].filter(Boolean).join(' / ')
  }
  if (bootstrapFinished.value) return '系统已可正常使用'
  if (latestFailedBootstrapTask.value) return `失败任务 #${latestFailedBootstrapTask.value.id}`
  return '等待启动'
})
const bootstrapObservabilityRows = computed(() => {
  const meta = initializationRunningTask.value?.progress_meta_json
  if (!meta) return []

  const rows: Array<{ label: string; value: string }> = []

  if (
    meta.ready_count != null
    || meta.incremental_count != null
    || meta.full_count != null
  ) {
    rows.push({
      label: '本地分类',
      value: `已完整 ${meta.ready_count ?? 0} / 增量 ${meta.incremental_count ?? 0} / 全量 ${meta.full_count ?? 0}`,
    })
  }

  if (meta.csv_imported_count != null || meta.csv_failed_count != null) {
    rows.push({
      label: 'CSV回灌',
      value: `${meta.csv_imported_count ?? 0} 已导入 / ${meta.csv_failed_count ?? 0} 失败`,
    })
  }

  return rows
})
const bootstrapProgressEta = computed(() => {
  const eta = initializationRunningTask.value?.progress_meta_json?.eta_seconds
  return eta != null ? `预计剩余 ${formatSeconds(eta)}` : ''
})

const bootstrapFinished = computed(() => {
  return dataLoaded.value
    && dataStatus.value.rawData.exists
    && dataStatus.value.candidates.exists
    && dataStatus.value.analysis.exists
})

const showBootstrap = computed(() => {
  return dataLoaded.value && !configStore.dataInitialized
})

const bootstrapStatusLabel = computed(() => {
  if (bootstrapFinished.value) return '已完成'
  if (bootstrapInProgress.value) return '进行中'
  if (!configStore.apiAvailable) return '服务异常'
  if (latestFailedBootstrapTask.value) return '可恢复'
  if (!configStore.tushareReady) return '待配置'
  return '待执行'
})

const bootstrapStatusTagType = computed(() => {
  if (bootstrapFinished.value) return 'success'
  if (bootstrapInProgress.value) return 'warning'
  if (!configStore.apiAvailable || latestFailedBootstrapTask.value) return 'danger'
  if (!configStore.tushareReady) return 'info'
  return 'primary'
})

const bootstrapDescription = computed(() => {
  if (bootstrapFinished.value) {
    return '首次初始化已完成，原始数据、候选结果和分析结果都已就绪。'
  }
  if (!configStore.apiAvailable) {
    return configStore.statusError || '后端服务暂不可用，请先恢复服务，再回到任务中心继续初始化。'
  }
  if (initializationRunningTask.value) {
    return `初始化任务 #${initializationRunningTask.value.id} 正在执行，当前阶段：${getTaskStageText(initializationRunningTask.value)}。`
  }
  if (latestFailedBootstrapTask.value) {
    return `上一次初始化任务 #${latestFailedBootstrapTask.value.id} 失败。可查看日志定位失败点后重新发起。`
  }
  if (!configStore.tushareReady) {
    return '请先进入配置页填写并验证 Tushare Token；验证通过后才能启动首次初始化。'
  }
  return configStore.initializationMessage || '首次初始化会补齐原始数据、候选结果和分析结果。'
})

const canStartBootstrap = computed(() => {
  return configStore.apiAvailable && configStore.tushareReady && !bootstrapFinished.value && !bootstrapInProgress.value
})

const bootstrapButtonText = computed(() => {
  if (bootstrapFinished.value) return '数据已就绪'
  if (bootstrapInProgress.value) return '初始化进行中'
  if (!configStore.tushareReady || !configStore.apiAvailable) return '先处理配置'
  if (latestFailedBootstrapTask.value) return '重新开始初始化'
  return '开始首次初始化'
})
const incrementalSummaryLabel = computed(() => {
  if (activeDailyUpdateTask.value) return '进行中'
  if (hasFailedDailyUpdate.value) return '失败'
  if (latestDailyUpdateTask.value || incrementalStatus.value.completed_at) return '最近已完成'
  return '待执行'
})
const incrementalSummaryTagType = computed(() => {
  if (activeDailyUpdateTask.value) return 'warning'
  if (hasFailedDailyUpdate.value) return 'danger'
  if (latestDailyUpdateTask.value || incrementalStatus.value.completed_at) return 'success'
  return 'info'
})
const incrementalSummaryProgressValue = computed(() => {
  if (activeDailyUpdateTask.value) return activeDailyUpdateProgressBarValue.value
  if (hasFailedDailyUpdate.value) return Math.max(1, activeDailyUpdateProgressBarValue.value)
  if (latestDailyUpdateTask.value || incrementalStatus.value.completed_at) return 100
  return 0
})
const incrementalSummaryProgressStatus = computed(() => {
  if (activeDailyUpdateTask.value) return 'warning'
  if (hasFailedDailyUpdate.value) return 'exception'
  if (latestDailyUpdateTask.value || incrementalStatus.value.completed_at) return 'success'
  return undefined
})
const incrementalOverviewTitle = computed(() => {
  if (activeDailyUpdateTask.value) return getTaskTypeLabel(activeDailyUpdateTask.value.task_type)
  if (incrementalFallbackActive.value) return incrementalStatus.value.display_title || (isDailyBatchIncremental.value ? '按交易日批量刷新正在执行' : '每日增量更新正在执行')
  if (hasFailedDailyUpdate.value) return '每日增量更新失败'
  if (latestDailyUpdateTask.value || incrementalStatus.value.completed_at) return '最近一次每日更新已完成'
  return '尚未执行每日更新'
})
const incrementalOverviewDetail = computed(() => {
  if (activeDailyUpdateTask.value) {
    return `${getTaskStageText(activeDailyUpdateTask.value)} / ${getTaskProgressPrimary(activeDailyUpdateTask.value)}`
  }
  if (incrementalFallbackActive.value) {
    if (incrementalStatus.value.display_detail) return incrementalStatus.value.display_detail
    if (isDailyBatchIncremental.value) {
      return `目标交易日 ${incrementalStatus.value.target_trade_date || incrementalStatus.value.current_code || '-'}`
    }
    return incrementalStatus.value.current_code ? `当前处理 ${incrementalStatus.value.current_code}` : '正在刷新最新交易日数据'
  }
  if (latestDailyUpdateTask.value?.status === 'failed') {
    return latestDailyUpdateTask.value.error_message || latestDailyUpdateTask.value.summary || '可重新发起更新'
  }
  if (incrementalFallbackFailed.value) {
    return incrementalStatus.value.last_error || incrementalStatus.value.message || '可重新发起更新'
  }
  if (latestDailyUpdateTask.value?.completed_at) {
    return `完成时间 ${formatDateTime(latestDailyUpdateTask.value.completed_at)}`
  }
  if (incrementalStatus.value.completed_at) {
    return `完成时间 ${formatDateTime(incrementalStatus.value.completed_at)}`
  }
  return '每日更新会补齐最新交易日数据与派生结果'
})
const incrementalProgressSummary = computed(() => {
  if (activeDailyUpdateTask.value) {
    return `${getTaskProgressPrimary(activeDailyUpdateTask.value)}${activeDailyUpdateDetail.value ? ` / ${activeDailyUpdateDetail.value}` : ''}`
  }
  if (incrementalFallbackActive.value) {
    if (isDailyBatchIncremental.value) {
      return `${incrementalDisplayProgressText.value} / ${incrementalStatus.value.updated_count} 只股票写入 / ${incrementalStatus.value.failed_count} 失败`
    }
    return `${incrementalStatus.value.current}/${incrementalStatus.value.total || '-'} / ${incrementalProgressLabel.value} / ${incrementalStatus.value.updated_count} 更新 / ${incrementalStatus.value.failed_count} 失败`
  }
  if (latestDailyUpdateTask.value?.status === 'failed') {
    return latestDailyUpdateTask.value.error_message || latestDailyUpdateTask.value.summary || '更新未完成'
  }
  if (incrementalFallbackFailed.value) {
    return incrementalStatus.value.message || '更新未完成'
  }
  if (latestDailyUpdateTask.value?.status === 'completed') {
    return latestDailyUpdateTask.value.summary || `完成时间 ${formatDateTime(latestDailyUpdateTask.value.completed_at)}`
  }
  if (incrementalStatus.value.completed_at) {
    return `${incrementalStatus.value.updated_count} 更新 / ${incrementalStatus.value.skipped_count} 跳过 / ${incrementalStatus.value.failed_count} 失败`
  }
  return '等待触发'
})
const incrementalProgressEtaText = computed(() => {
  return activeDailyUpdateEtaText.value
})
const latestDailyUpdateFailureText = computed(() => {
  if (latestDailyUpdateTask.value?.status === 'failed') {
    return latestDailyUpdateTask.value.error_message || latestDailyUpdateTask.value.summary || '可稍后重新发起，系统会尽量从已完成位置继续。'
  }
  return incrementalStatus.value.last_error || incrementalStatus.value.message || '可稍后重新发起，系统会尽量从已完成位置继续。'
})

const diagnosticChecks = computed<TaskDiagnosticCheck[]>(() => diagnostics.value?.checks || [])
const diagnosticsGeneratedAt = computed(() => {
  if (!diagnostics.value?.generated_at) return '尚未加载'
  return `更新于 ${formatDateTime(diagnostics.value.generated_at)}`
})
const socketStatusLabel = computed(() => {
  if (opsSocketState.value === 'connected' && (!selectedTask.value || taskSocketState.value === 'connected')) return '实时推送中'
  if (opsSocketState.value === 'reconnecting' || taskSocketState.value === 'reconnecting') return '重连中'
  if (opsSocketState.value === 'polling' || taskSocketState.value === 'polling') return '轮询兜底'
  return '已断开'
})
const socketStatusTagType = computed(() => {
  if (socketStatusLabel.value === '实时推送中') return 'success'
  if (socketStatusLabel.value === '重连中') return 'warning'
  if (socketStatusLabel.value === '轮询兜底') return 'info'
  return 'danger'
})
const socketStatusDescription = computed(() => {
  if (socketStatusLabel.value === '实时推送中') return '任务状态和日志会自动推送更新。'
  if (socketStatusLabel.value === '重连中') return '检测到连接中断，系统会自动重连，同时保留轮询刷新。'
  if (socketStatusLabel.value === '轮询兜底') return 'WebSocket 暂不可用，当前退回到定时轮询。任务仍可继续查看。'
  return '当前未连接到任务推送通道，请手动重连或刷新页面。'
})
const stalledBootstrapAlert = computed(() => {
  const task = initializationRunningTask.value
  if (!task?.started_at) return null

  const elapsedMs = Date.now() - new Date(task.started_at).getTime()
  const elapsedMinutes = Math.max(1, Math.floor(elapsedMs / 60000))
  if (elapsedMinutes < 15) return null

  const stage = getTaskStageText(task)
  return {
    title: '初始化耗时明显偏长',
    description: `任务 #${task.id} 已持续约 ${elapsedMinutes} 分钟，当前阶段为“${stage}”。若日志长时间没有新内容，可先复制诊断摘要，再尝试刷新状态或重连推送。`,
  }
})

const bootstrapSteps = computed(() => [
  {
    key: 'config',
    index: 1,
    title: '配置数据源',
    meta: configStore.tushareReady ? 'Tushare 已验证' : '待配置',
    done: configStore.tushareReady,
  },
    {
      key: 'raw',
      index: 2,
      title: '抓取原始数据',
      meta: dataStatus.value.rawData.exists
    ? `${dataStatus.value.rawData.stockCount}只股票`
      : '待抓取',
      done: dataStatus.value.rawData.exists,
    },
  {
    key: 'candidates',
    index: 3,
    title: '生成候选结果',
    meta: dataStatus.value.candidates.exists
      ? `${dataStatus.value.candidates.count}条结果`
      : '待生成',
    done: dataStatus.value.candidates.exists,
  },
  {
    key: 'analysis',
    index: 4,
    title: '生成分析结果',
    meta: dataStatus.value.analysis.exists
      ? `${dataStatus.value.analysis.count}条结果`
      : '待生成',
    done: dataStatus.value.analysis.exists,
  },
])

const showRetryBootstrap = computed(() => {
  return Boolean(configStore.apiAvailable && configStore.tushareReady && latestFailedBootstrapTask.value && !bootstrapInProgress.value)
})

const recoveryAlert = computed(() => {
  if (!showBootstrap.value) return null
  if (!configStore.apiAvailable) {
    return {
      type: 'error' as const,
      title: '后端未就绪',
      description: '先恢复后端服务，再刷新本页继续查看初始化任务。',
    }
  }
  if (!configStore.tushareReady) {
    return {
      type: 'warning' as const,
      title: 'Token 未验证',
      description: '请去配置页完成 Token 验证，验证成功后回到此页启动初始化。',
    }
  }
  if (initializationRunningTask.value) {
    return {
      type: 'info' as const,
      title: '初始化仍在运行',
      description: '可以继续留在任务中心查看日志，或刷新页面后恢复到当前任务。',
    }
  }
  if (latestFailedBootstrapTask.value) {
    return {
      type: 'error' as const,
      title: '初始化失败，可直接恢复',
      description: latestFailedBootstrapTask.value.error_message || latestFailedBootstrapTask.value.summary || '建议先查看失败日志，再点击重新发起初始化。',
    }
  }
  return {
    type: 'info' as const,
    title: '初始化尚未完成',
    description: '请发起首次初始化；如果你刚刷新页面，任务列表会在下方自动恢复。',
  }
})

const filteredLogs = computed(() => {
  const sourceLogs = logFilter.value === 'task' && selectedTask.value
    ? selectedTaskLogs.value
    : allLogs.value

  const visibleLevels = new Set(['warn', 'warning', 'error'])
  return sourceLogs.filter((log) => visibleLevels.has(String(log.level || '').toLowerCase()))
})

const recentHistoryTasks = computed(() => historyTasks.value.slice(0, 5))
const recentFailedLogs = computed(() => filteredLogs.value.slice(-8).reverse())
const dashboardStatusCards = computed(() => {
  const cards: Array<{ label: string; value: string; meta?: string; type?: string }> = []

  cards.push({
    label: '系统状态',
    value: adminSummary.value?.system_ready ? '就绪' : '未就绪',
    meta: adminSummary.value?.latest_trade_date ? `有效最新交易日 ${adminSummary.value.latest_trade_date}` : '等待状态同步',
    type: adminSummary.value?.system_ready ? 'success' : 'warning',
  })

  if (adminSummary.value?.current_task) {
    cards.push({
      label: '当前任务',
      value: `${currentTaskProgressPercent.value}%`,
      meta: adminSummary.value.current_task.stage_label || adminSummary.value.current_task.summary || '-',
      type: getTaskStatusType(adminSummary.value.current_task.status),
    })
  }

  cards.push({
    label: '任务推送',
    value: socketStatusLabel.value,
    meta: socketStatusDescription.value,
    type: socketStatusTagType.value,
  })

  cards.push({
    label: '最近失败',
    value: hasFailedDailyUpdate.value ? '需要处理' : '无关键失败',
    meta: latestDailyUpdateFailureText.value || incrementalStatus.value.display_detail || incrementalStatus.value.message || '最近未发现增量更新失败摘要',
    type: hasFailedDailyUpdate.value ? 'danger' : 'success',
  })

  return cards
})

watch(selectedTask, (newTask) => {
  if (newTask) {
    if (logFilter.value === 'all') {
      logFilter.value = 'task'
    }
  }
  persistViewState()
})

watch(activeTab, (newTab) => {
  persistViewState()
  // 切换到总览标签时加载管理员数据，但不阻塞
  if (newTab === 'dashboard') {
    loadAdminSummary().catch((error) => {
      console.error('Failed to load admin summary on tab switch:', error)
    })
  }
})

watch(
  () => [route.query.tab, route.query.action, route.query.taskId],
  () => {
    void handleRouteAction()
  },
)

// 生命周期
onMounted(async () => {
  const restoredState = loadInitTaskViewState()
  if (restoredState.activeTab) {
    activeTab.value = restoredState.activeTab
  }

  // 先建立 WebSocket 连接和启动轮询
  connectOpsSocket()
  startPoller()

  // 非阻塞加载数据 - 让页面先渲染，数据后台加载
  Promise.all([
    // 检查 Tushare 状态
    configStore.checkTushareStatus().catch((error) => {
      console.error('Failed to check tushare status:', error)
    }),
    // 加载运行中任务和状态
    reloadAll().catch((error) => {
      console.error('Failed to reload all:', error)
    }),
    // 加载管理员总览
    loadAdminSummary().catch((error) => {
      console.error('Failed to load admin summary:', error)
    }),
    // 处理路由 action
    handleRouteAction().catch((error) => {
      console.error('Failed to handle route action:', error)
    }),
  ]).catch(() => {
    // 忽略单个错误，已在上面的 catch 中处理
  })
})

onUnmounted(() => {
  stopPoller()
  clearReconnectTimers()
  disconnectSockets()
})

// 核心方法
async function reloadAll() {
  try {
    const [runningResp, statusResp, incrementalResp] = await Promise.all([
      apiTasks.getRunning(),
      apiTasks.getStatus(),
      apiTasks.getIncrementalStatus(),
    ])

    runningTasks.value = runningResp.tasks
    incrementalStatus.value = incrementalResp

    if (activeTab.value === 'tasks' || activeTab.value === 'logs') {
      try {
        const historyResp = await apiTasks.getAll('completed,failed,cancelled', 20)
        historyTasks.value = historyResp.tasks
      } catch {
        historyTasks.value = []
      }
    }

    if (activeTab.value === 'status') {
      try {
        diagnostics.value = await apiTasks.getDiagnostics()
      } catch (error) {
        console.error('Failed to refresh diagnostics:', error)
      }
    }

    let environmentSections: any[] = []
    if (activeTab.value === 'status') {
      try {
        const envResp = await apiTasks.getEnvironment()
        environmentSections = envResp.sections || []
      } catch (error) {
        console.error('Failed to refresh environment:', error)
      }
    }

    dataStatus.value = {
      ...createEmptyDataStatus(),
      rawData: {
        exists: statusResp.raw_data.exists,
        stockCount: statusResp.raw_data.stock_count || 0,
        rawRecordCount: statusResp.raw_data.raw_record_count || 0,
        latestDate: formatLatestDate(statusResp.raw_data.latest_date),
      },
      candidates: {
        exists: statusResp.candidates?.exists || false,
        count: statusResp.candidates?.count || 0,
        latestDate: formatLatestDate(statusResp.candidates?.latest_date),
      },
      analysis: {
        exists: statusResp.analysis?.exists || false,
        count: statusResp.analysis?.count || 0,
        latestDate: formatLatestDate(statusResp.analysis?.latest_date),
      },
      kline: {
        exists: statusResp.kline?.exists || false,
        count: statusResp.kline?.count || 0,
        latestDate: formatLatestDate(statusResp.kline?.latest_date),
      },
      environment: environmentSections,
    }

    dataLoaded.value = true
    try {
      await configStore.checkTushareStatus()
    } catch (error) {
      console.error('Failed to refresh tushare status:', error)
    }
    await restoreTaskSelection()
    persistViewState()
  } catch (error) {
    console.error('Failed to reload:', error)
    dataLoaded.value = true
  }
}

// 管理员总览相关函数（阶段4新增）
async function loadAdminSummary() {
  summaryLoading.value = true
  try {
    const summary = await apiTasks.getAdminSummary()
    adminSummary.value = summary
  } catch (error) {
    console.error('Failed to load admin summary:', error)
    adminSummary.value = null
  } finally {
    summaryLoading.value = false
  }
}

async function refreshOverview() {
  // 保存当前页签状态，避免刷新后页签被重置
  const currentTab = activeTab.value

  // 显示加载提示但不阻塞
  const loadingMessage = ElMessage.info({
    message: '刷新中...',
    duration: 0,
  })

  try {
    // 并行加载所有数据
    await Promise.all([
      reloadAll(),
      loadAdminSummary(),
    ])
  } catch (error) {
    console.error('Failed to refresh overview:', error)
  } finally {
    loadingMessage.close()
  }

  // 恢复页签状态
  activeTab.value = currentTab
}

// 向布局组件提供刷新函数
provide('pageRefresh', refreshOverview)

function handlePendingAction(action: any) {
  if (action.route) {
    // 解析路由和可能的查询参数
    const [path, query] = action.route.split('?')
    if (query) {
      const params = new URLSearchParams(query)
      const queryParams: Record<string, string> = {}
      params.forEach((value, key) => { queryParams[key] = value })
      router.push({ path, query: queryParams })
    } else {
      router.push(path)
    }
  }
}

async function handleRouteAction() {
  const tab = typeof route.query.tab === 'string' ? route.query.tab : ''
  const action = typeof route.query.action === 'string' ? route.query.action : ''
  const taskId = typeof route.query.taskId === 'string' ? Number(route.query.taskId) : null

  if (tab === 'dashboard' || tab === 'tasks' || tab === 'logs' || tab === 'status') {
    activeTab.value = tab
  }

  if (taskId && Number.isFinite(taskId)) {
    const target = [...runningTasks.value, ...historyTasks.value].find((task) => task.id === taskId)
    if (target) {
      await focusTask(target, tab === 'logs' ? 'logs' : 'tasks')
    }
  }

  if (action === 'init' && canStartBootstrap.value) {
    activeTab.value = 'tasks'
    await startBootstrap()
  }
}

function getTaskStatusType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  const types: Record<string, 'success' | 'warning' | 'danger' | 'info'> = {
    completed: 'success',
    running: 'warning',
    pending: 'info',
    failed: 'danger',
    cancelled: 'info',
  }
  return types[status] || 'info'
}

function getProgressStatus(status: string): 'success' | 'warning' | 'exception' | undefined {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'exception'
  if (status === 'running') return 'warning'
  return undefined
}

async function startBootstrap() {
  if (!canStartBootstrap.value) return

  bootstrapStarting.value = true
  try {
    const result = await apiTasks.startUpdate('quant', false, 1)
    rememberBootstrapTask(result.task)
    ElMessage.success(`初始化任务已启动 #${result.task.id}`)
    await focusTask(result.task, 'logs')
    await reloadAll()
  } catch (error: any) {
    const recovered = await recoverInitializationTask()
    if (!recovered) {
      console.error('startBootstrap failed:', error)
      ElMessage.error(getUserSafeErrorMessage(error, '启动失败'))
    }
  } finally {
    bootstrapStarting.value = false
  }
}

async function retryBootstrap() {
  await startBootstrap()
}

async function startDataUpdate() {
  startingUpdate.value = true
  try {
    const result = await apiTasks.startDailyBatchUpdate()
    if (!result.success) {
      ElMessage.error(result.message || '按交易日批量更新启动失败')
      await reloadAll()
      return
    }
    ElMessage.success(result.message || '按交易日批量更新已启动')
    if (result.task) {
      await focusTask(result.task, 'logs')
    }
    await reloadAll()
  } catch (error: any) {
    console.error('startDataUpdate failed:', error)
    ElMessage.error(getUserSafeErrorMessage(error, '启动失败'))
  } finally {
    startingUpdate.value = false
  }
}

async function startFullUpdate() {
  startingFullUpdate.value = true
  try {
    const result = await apiTasks.startRecent120Rebuild()
    if (!result.success) {
      ElMessage.error(result.message || '近120交易日重建启动失败')
      await reloadAll()
      return
    }
    ElMessage.success(result.message || '近120交易日完整重建已启动')
    if (result.task) {
      await focusTask(result.task, 'logs')
    }
    await reloadAll()
  } catch (error: any) {
    console.error('startFullUpdate failed:', error)
    ElMessage.error(isInitializationPendingError(error) ? getUserSafeErrorMessage(error, '系统尚未完成初始化') : getUserSafeErrorMessage(error, '启动失败'))
  } finally {
    startingFullUpdate.value = false
  }
}

async function checkRecent120Integrity() {
  checkingIntegrity.value = true
  try {
    const res = await apiTasks.checkRecent120Integrity()
    const issuePreview = (res.issues || [])
      .slice(0, 12)
      .map((item) => `<li><strong>${item.trade_date}</strong>：${item.issues.join('、')}</li>`)
      .join('')
    const lines = [
      `<strong>检查结果：</strong>${res.success ? '通过' : '存在问题'}`,
      `<strong>窗口：</strong>${res.date_range?.join(' ~ ') || '-'} / ${res.date_count || 0} 个交易日`,
      `<strong>问题日期：</strong>${res.summary?.issue_dates ?? 0}`,
      `<strong>说明：</strong>${res.message || '-'}`,
    ]
    if (issuePreview) {
      lines.push(`<strong>问题样例：</strong><ul>${issuePreview}</ul>`)
    }
    await ElMessageBox.alert(lines.join('<br/>'), '近120交易日数据完整性', {
      dangerouslyUseHTMLString: true,
      confirmButtonText: '关闭',
    })
  } catch (error: any) {
    console.error('checkRecent120Integrity failed:', error)
    ElMessage.error(getUserSafeErrorMessage(error, '完整性检查失败'))
  } finally {
    checkingIntegrity.value = false
  }
}

async function promptRevalidateTradeDate() {
  try {
    const { value } = await ElMessageBox.prompt('请输入交易日，格式 YYYY-MM-DD', '指定日期重验证', {
      confirmButtonText: '开始验证',
      cancelButtonText: '取消',
      inputPattern: /^\d{4}-\d{2}-\d{2}$/,
      inputErrorMessage: '日期格式必须是 YYYY-MM-DD',
    })
    await revalidateTradeDate(value)
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    console.error('promptRevalidateTradeDate failed:', error)
    ElMessage.error(getUserSafeErrorMessage(error, '指定日期重验证失败'))
  }
}

async function revalidateTradeDate(tradeDate: string) {
  revalidatingDate.value = true
  try {
    const res = await apiTasks.revalidateTradeDate(tradeDate)
    const summaryLines = Object.entries(res.summary || {})
      .map(([key, value]) => `<li>${key}: ${value ?? '-'}</li>`)
      .join('')
    const issueLines = (res.issues || []).map((item) => `<li>${item}</li>`).join('')
    const sampleLines = (res.sample_recomputed_current_hot || [])
      .slice(0, 8)
      .map((item) => `<li>${item.code}: B1=${item.b1_passed ?? '-'} / 信号=${item.signal_type || '-'} / 分=${item.score ?? '-'}</li>`)
      .join('')
    const mismatchLines = (res.current_hot_mismatches || [])
      .slice(0, 8)
      .map((item) => `<li>${item.code}: ${(item.fields || []).join('、')}</li>`)
      .join('')
    const lines = [
      `<strong>交易日：</strong>${res.trade_date}`,
      `<strong>结果：</strong>${res.success ? '通过' : '存在差异'}`,
      `<strong>说明：</strong>${res.message || '-'}`,
      summaryLines ? `<strong>统计：</strong><ul>${summaryLines}</ul>` : '',
      issueLines ? `<strong>问题：</strong><ul>${issueLines}</ul>` : '',
      mismatchLines ? `<strong>持久化差异样例：</strong><ul>${mismatchLines}</ul>` : '',
      sampleLines ? `<strong>当前热盘样例重算：</strong><ul>${sampleLines}</ul>` : '',
    ].filter(Boolean)
    await ElMessageBox.alert(lines.join('<br/>'), '指定日期重验证结果', {
      dangerouslyUseHTMLString: true,
      confirmButtonText: '关闭',
    })
  } finally {
    revalidatingDate.value = false
  }
}

async function checkDataFreshness() {
  checkingFreshness.value = true
  try {
    const res = await apiTasks.getDataFreshness()
    const lines = [
      `<strong>查询时间：</strong>${formatDateTime(res.query_time)}`,
      `<strong>最新交易日（日历）：</strong>${res.latest_calendar_trade_date || '-'}`,
      `<strong>最新日线数据日期：</strong>${res.latest_data_date || '-'}`,
      `<strong>当日数据已就绪：</strong>${res.is_latest_data_ready ? '是' : '否'}`,
    ]
    if (res.error) {
      lines.push(`<strong>错误：</strong>${res.error}`)
    }
    await ElMessageBox.alert(lines.join('<br/>'), '最新数据时效', {
      dangerouslyUseHTMLString: true,
      confirmButtonText: '关闭',
    })
  } catch (error: any) {
    console.error('checkDataFreshness failed:', error)
    ElMessage.error(error.response?.data?.detail || error.message || '查询失败')
  } finally {
    checkingFreshness.value = false
  }
}

async function reloadTasks() {
  await refreshOverview()
  ElMessage.success('已刷新')
}

async function loadDiagnostics() {
  diagnosticsLoading.value = true
  try {
    diagnostics.value = await apiTasks.getDiagnostics()
  } catch (error) {
    console.error('Failed to load diagnostics:', error)
    noticeStore.setNotice({
      type: 'warning',
      title: '诊断信息刷新失败',
      message: error instanceof Error ? error.message : '请稍后重试。',
      actionLabel: '去配置',
      actionRoute: '/config',
    })
  } finally {
    diagnosticsLoading.value = false
  }
}

async function copyDiagnostics() {
  const summary = buildDiagnosticsSummary()
  try {
    await navigator.clipboard.writeText(summary)
    ElMessage.success('诊断摘要已复制')
  } catch {
    ElMessage.warning('复制失败，请检查浏览器剪贴板权限')
  }
}

async function selectTask(task: Task) {
  selectedTask.value = task
  await loadTaskLogs(task.id)
  connectTaskSocket(task.id)
}

async function focusTask(task: Task, tab: 'tasks' | 'logs' = 'tasks') {
  activeTab.value = tab
  await selectTask(task)
}

async function loadTaskLogs(taskId: number) {
  try {
    const data = await apiTasks.getLogs(taskId)
    selectedTaskLogs.value = data.logs
    await nextTick()
    scrollToBottom()
  } catch (error) {
    console.error('Failed to load logs:', error)
  }
}

async function cancelTask(task: Task) {
  try {
    const result = await apiTasks.cancel(task.id)
    if (result.status === 'ok') {
      ElMessage.success(result.message || `任务 #${task.id} 已取消`)
      await reloadAll()
    } else {
      ElMessage.warning(result.message || '取消请求已处理')
      await reloadAll()
    }
  } catch (error: any) {
    ElMessage.error(error.message || '取消失败')
    await reloadAll()
  }
}

async function clearTasks() {
  try {
    await ElMessageBox.confirm('确定清空所有已结束任务记录？', '确认操作', {
      type: 'warning',
    })
    await apiTasks.clearTasks()
    ElMessage.success('已清空')
    await reloadAll()
  } catch {
    // cancelled
  }
}

function viewTaskDetail(task: Task) {
  void focusTask(task, 'logs')
}

function filterLogs() {
  nextTick(() => scrollToBottom())
}

function clearLogsDisplay() {
  if (logFilter.value === 'task') {
    selectedTaskLogs.value = []
  } else {
    allLogs.value = []
  }
}

async function checkDataFresh() {
  checkingData.value = true
  try {
    // 检查是否需要更新数据的逻辑
    await apiTasks.getOverview()
    ElMessage.success('数据状态已更新')
    await reloadAll()
  } finally {
    checkingData.value = false
  }
}

function handleLogScroll() {
  const el = logRef.value
  if (!el) return
  const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100
  autoScroll.value = isNearBottom
}

function scrollToBottom() {
  if (autoScroll.value && logRef.value) {
    logRef.value.scrollTop = logRef.value.scrollHeight
  }
}

// WebSocket 连接
function connectTaskSocket(taskId: number) {
  lastTaskSocketId = taskId
  disconnectTaskSocket()
  const wsUrl = buildWebSocketUrl(`/ws/tasks/${taskId}`)
  ws = new WebSocket(wsUrl)
  taskSocketState.value = 'reconnecting'

  ws.onopen = () => {
    taskSocketState.value = 'connected'
    socketReconnectAttempts.value = 0
  }
  ws.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data)
      if (payload.type === 'log') {
        const log: TaskLogItem = {
          id: Date.now(),
          task_id: taskId,
          log_time: payload.timestamp,
          level: payload.log_type || 'info',
          stage: undefined,
          message: payload.message,
        }
        selectedTaskLogs.value.push(log)
        allLogs.value.push(log)
        scrollToBottom()
      }
    } catch {
      // ignore
    }
  }
  ws.onclose = () => {
    if (!lastTaskSocketId) {
      taskSocketState.value = 'disconnected'
      return
    }
    taskSocketState.value = 'polling'
    scheduleTaskReconnect(lastTaskSocketId)
  }
  ws.onerror = () => {
    taskSocketState.value = 'polling'
  }
}

function disconnectTaskSocket() {
  if (ws) {
    ws.onclose = null
    ws.close()
    ws = null
  }
  taskSocketState.value = lastTaskSocketId ? 'polling' : 'disconnected'
}

function connectOpsSocket() {
  disconnectOpsSocket()
  const wsUrl = buildWebSocketUrl('/ws/ops')
  opsWs = new WebSocket(wsUrl)
  opsSocketState.value = 'reconnecting'

  opsWs.onopen = () => {
    opsSocketState.value = 'connected'
    socketReconnectAttempts.value = 0
  }
  opsWs.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data)
      if (message?.payload) {
        applyTaskUpdate(message.payload)
      }
    } catch {
      // ignore
    }
  }
  opsWs.onclose = () => {
    opsSocketState.value = 'polling'
    scheduleOpsReconnect()
  }
  opsWs.onerror = () => {
    opsSocketState.value = 'polling'
  }
}

function disconnectOpsSocket() {
  if (opsWs) {
    opsWs.onclose = null
    opsWs.close()
    opsWs = null
  }
  opsSocketState.value = 'disconnected'
}

function disconnectSockets() {
  disconnectTaskSocket()
  disconnectOpsSocket()
}

function reconnectSocketsNow() {
  clearReconnectTimers()
  connectOpsSocket()
  if (selectedTask.value) {
    connectTaskSocket(selectedTask.value.id)
  }
}

function applyTaskUpdate(task: Task) {
  const runningIndex = runningTasks.value.findIndex((t) => t.id === task.id)
  const isRunning = task.status === 'pending' || task.status === 'running'

  if (isRunning) {
    if (runningIndex >= 0) {
      runningTasks.value[runningIndex] = task
    } else {
      runningTasks.value.unshift(task)
    }
  } else if (runningIndex >= 0) {
    runningTasks.value.splice(runningIndex, 1)
  }

  if (selectedTask.value?.id === task.id) {
    selectedTask.value = task
  }

  // 同步更新 adminSummary 中的 current_task
  if (adminSummary.value) {
    if (isRunning) {
      adminSummary.value.current_task = task
    } else if (adminSummary.value.current_task?.id === task.id) {
      // 当前任务已完成/失败/取消，清空或移到 latest_task
      if (task.status === 'completed') {
        adminSummary.value.latest_task = task
        adminSummary.value.latest_task_summary = task.summary || ''
      }
      adminSummary.value.current_task = null
    }
  }

  if (isBootstrapTask(task) && isRunning) {
    rememberBootstrapTask(task)
  }

  if (bootstrapFinished.value) {
    clearInitTaskViewState()
  } else {
    persistViewState()
  }
}

let poller: ReturnType<typeof setInterval> | null = null

function startPoller() {
  stopPoller()
  // 非实时系统：30秒轮询间隔（配合后端2分钟缓存）
  // 当有运行中任务时仍保持较短间隔以获得及时更新
  const pollInterval = runningTasks.value.length > 0 ? 10000 : 30000

  poller = setInterval(async () => {
    if (document.visibilityState === 'hidden') return
    // WebSocket 连接正常且有运行中任务时，依靠推送而不是轮询
    if (opsWs?.readyState === WebSocket.OPEN && runningTasks.value.length > 0) return

    await reloadAll()
    if (activeTab.value === 'dashboard') {
      await loadAdminSummary()
    }
  }, pollInterval)
}

function stopPoller() {
  if (poller) {
    clearInterval(poller)
    poller = null
  }
}

function scheduleOpsReconnect() {
  if (opsReconnectTimer) return
  socketReconnectAttempts.value += 1
  opsSocketState.value = 'reconnecting'
  opsReconnectTimer = setTimeout(() => {
    opsReconnectTimer = null
    connectOpsSocket()
  }, getReconnectDelay())
}

function scheduleTaskReconnect(taskId: number) {
  if (taskReconnectTimer) return
  socketReconnectAttempts.value += 1
  taskSocketState.value = 'reconnecting'
  taskReconnectTimer = setTimeout(() => {
    taskReconnectTimer = null
    connectTaskSocket(taskId)
  }, getReconnectDelay())
}

function clearReconnectTimers() {
  if (opsReconnectTimer) {
    clearTimeout(opsReconnectTimer)
    opsReconnectTimer = null
  }
  if (taskReconnectTimer) {
    clearTimeout(taskReconnectTimer)
    taskReconnectTimer = null
  }
}

function getReconnectDelay() {
  return Math.min(15000, 1000 * Math.max(1, socketReconnectAttempts.value))
}

function goToConfig() {
  router.push('/config')
}

function isBootstrapTask(task: Task | null | undefined) {
  return Boolean(task && ['full_update', 'recent_120_rebuild'].includes(task.task_type))
}

function isDailyUpdateTask(task: Task | null | undefined) {
  return Boolean(task && ['daily_batch_update', 'incremental_update'].includes(task.task_type))
}

function rememberBootstrapTask(task: Task | null | undefined) {
  if (!task) return
  saveInitTaskViewState({
    activeTab: activeTab.value,
    selectedTaskId: task.id,
    bootstrapTaskId: task.id,
  })
}

function persistViewState() {
  if (bootstrapFinished.value) {
    clearInitTaskViewState()
    return
  }

  saveInitTaskViewState({
    activeTab: activeTab.value,
    selectedTaskId: selectedTask.value?.id || null,
    bootstrapTaskId: initializationRunningTask.value?.id || latestFailedBootstrapTask.value?.id || null,
  })
}

async function restoreTaskSelection() {
  const state = loadInitTaskViewState()
  const candidates = [...runningTasks.value, ...historyTasks.value]
  const targetId = state.selectedTaskId || state.bootstrapTaskId

  const target = (
    candidates.find((task) => task.id === targetId) ||
    initializationRunningTask.value ||
    latestFailedBootstrapTask.value ||
    taskCenterRunningTasks.value[0] ||
    null
  )

  if (!target) {
    selectedTask.value = null
    lastTaskSocketId = null
    disconnectTaskSocket()
    return
  }

  if (selectedTask.value?.id === target.id) return
  await selectTask(target)
}

async function recoverInitializationTask() {
  try {
    const runningResp = await apiTasks.getRunning()
    runningTasks.value = runningResp.tasks
    const target = runningTasks.value.find((task) => isBootstrapTask(task))
    if (target) {
      rememberBootstrapTask(target)
      await focusTask(target, 'logs')
      ElMessage.warning(`检测到已有初始化任务 #${target.id}，已恢复到日志视图`)
      return true
    }
  } catch (error) {
    console.error('Failed to recover initialization task:', error)
  }
  return false
}

// 格式化方法
function getTaskTypeLabel(taskType: string | null | undefined): string {
  if (!taskType) return '-'
  const labels: Record<string, string> = {
    full_update: '全量更新',
    recent_120_rebuild: '近120交易日重建',
    daily_batch_update: '按交易日批量刷新',
    incremental_update: '增量更新',
    single_analysis: '单股分析',
    tomorrow_star: '明日之星',
  }
  return labels[taskType] || taskType
}

function getStatusType(status: string): string {
  const types: Record<string, string> = {
    success: 'success',
    warning: 'warning',
    error: 'danger',
    info: 'info',
    completed: 'success',
    running: 'primary',
    failed: 'danger',
    pending: 'warning',
    cancelled: 'info',
  }
  return types[status] || 'info'
}

function getStageLabel(stage?: string | null): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    starting: '启动中',
    preparing: '准备中',
    // 新的6阶段流程
    data_preparing: '数据准备',
    fetch_data: '数据准备',         // 兼容旧名称
    csv_import: 'CSV 回灌',
    build_pool: '量化初选',
    filter_candidates: '候选筛选',  // 新名称
    build_candidates: '候选筛选',   // 兼容旧名称
    score_analysis: '评分分析',     // 新名称
    pre_filter: '评分分析',         // 兼容旧名称
    export_results: '结果导出',     // 新名称
    score_review: '结果导出',       // 兼容旧名称
    finalize: '输出推荐',
    daily_batch_refresh: '按交易日批量刷新',
    recent_120_rebuild: '近120交易日重建',
    diagnosis_cache_prewarm: '预热诊断缓存',
    incremental_update: '增量更新',
    completed: '已完成',
    failed: '执行失败',
    cancelled: '已取消',
  }
  return stage ? (labels[stage] || stage) : '-'
}

function getTaskMeta(task: Task): TaskProgressMeta | undefined {
  return task.progress_meta_json
}

function getTaskStageText(task: Task): string {
  const meta = getTaskMeta(task)
  return meta?.stage_label || getStageLabel(meta?.stage || task.task_stage)
}

function getElapsedSeconds(startedAt?: string): number {
  if (!startedAt) return 0
  const elapsedMs = Date.now() - new Date(startedAt).getTime()
  return elapsedMs > 0 ? Math.floor(elapsedMs / 1000) : 0
}

function formatSeconds(seconds?: number | null): string {
  if (seconds == null) return '-'
  return formatDuration(seconds)
}

function getTaskProgressPrimary(task: Task): string {
  const meta = getTaskMeta(task)
  if (meta?.current != null && meta?.total != null) {
    const current = meta.current
    const total = meta.total
    const initialCompleted = meta?.initial_completed ?? 0
    const completedInRun = meta?.completed_in_run ?? 0

    // 如果有初始完成的数量，显示详细的跳过/处理信息
    if (initialCompleted > 0) {
      return `进度 ${current}/${total} (跳过${initialCompleted}, 处理${completedInRun})`
    }
    return `进度 ${current}/${total}`
  }
  if (meta?.stage_index != null && meta?.stage_total != null) {
    return `阶段 ${meta.stage_index}/${meta.stage_total}`
  }
  return `进度 ${meta?.percent ?? task.progress}%`
}

function getTaskProgressSecondary(task: Task): string {
  const meta = getTaskMeta(task)
  const parts: string[] = []
  if (meta?.eta_seconds != null) {
    parts.push(`预计剩余 ${formatSeconds(meta.eta_seconds)}`)
  } else if (task.status === 'running' && task.started_at) {
    parts.push(`已运行 ${formatSeconds(getElapsedSeconds(task.started_at))}`)
  }
  if (meta?.current_code) {
    parts.push(`当前 ${meta.current_code}`)
  }
  if (meta?.failed_count) {
    parts.push(`失败 ${meta.failed_count}`)
  }
  return parts.join(' / ')
}

function formatDateTime(dateStr?: string): string {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatLogTime(dateStr?: string): string {
  if (!dateStr) return '--:--:--'
  return new Date(dateStr).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function formatLatestDate(date?: string | number | null): string {
  if (!date) return '-'
  if (typeof date === 'number') {
    return new Date(date * 1000).toLocaleDateString('zh-CN')
  }
  return date
}

function formatEnvKey(key: string): string {
  const keys: Record<string, string> = {
    app_name: '应用名称',
    debug: '调试模式',
    host: '主机',
    port: '端口',
    python_version: 'Python版本',
    platform: '系统平台',
    timezone: '时区',
    data_dir: '数据目录',
    db_dir: '数据库目录',
    raw_data_dir: '原始数据目录',
    review_dir: '评审目录',
    logs_dir: '日志目录',
    tushare_configured: 'Tushare配置',
    zhipuai_configured: '智谱配置',
    dashscope_configured: '通义配置',
    gemini_configured: 'Gemini配置',
    default_reviewer: '默认评审器',
    total_stocks: '股票总数',
    latest_date: '最新日期',
  }
  return keys[key] || key
}

function formatEnvValue(value: any): string {
  if (typeof value === 'boolean') return value ? '已配置' : '未配置'
  if (value == null || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function getPrimitiveItems(items: Record<string, any>): Record<string, any> {
  const result: Record<string, any> = {}
  for (const [key, value] of Object.entries(items)) {
    if (value === null || value === undefined) continue
    if (typeof value === 'boolean' || typeof value === 'number' || typeof value === 'string') {
      result[key] = value
    }
  }
  return result
}

function getCheckStatusLabel(status: string) {
  const labels: Record<string, string> = {
    success: '正常',
    warning: '待处理',
    error: '异常',
    info: '未完成',
  }
  return labels[status] || status
}

function buildDiagnosticsSummary() {
  const lines = [
    `生成时间: ${diagnostics.value?.generated_at || new Date().toISOString()}`,
    `推送状态: ${socketStatusLabel.value}`,
    `运行中任务: ${taskCenterRunningTasks.value.length}`,
  ]
  if (incrementalStatus.value.running) {
    lines.push(
      `${incrementalStatus.value.display_title || '增量更新'}: ${incrementalProgressSummary.value}${incrementalStatus.value.eta_seconds != null ? ` / 预计剩余 ${formatSeconds(incrementalStatus.value.eta_seconds)}` : ''}`
    )
  }
  for (const check of diagnosticChecks.value) {
    lines.push(`[${getCheckStatusLabel(check.status)}] ${check.label}: ${check.summary}`)
    if (check.action) {
      lines.push(`建议: ${check.action}`)
    }
  }
  if (initializationRunningTask.value) {
    lines.push(`初始化任务: #${initializationRunningTask.value.id} / ${getTaskStageText(initializationRunningTask.value)} / ${initializationRunningTask.value.progress}%`)
  }
  if (latestFailedBootstrapTask.value?.error_message) {
    lines.push(`最近失败: ${latestFailedBootstrapTask.value.error_message}`)
  }
  return lines.join('\n')
}

function buildWebSocketUrl(path: string) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${path}`
}
</script>

<style scoped lang="scss">
.ops-page {
  padding: 16px;
  max-width: none;
  margin: 0 auto;

  .page-header {
    margin-bottom: 20px;

    h2 {
      margin: 0;
      font-size: 24px;
      font-weight: 600;
    }
  }

  .ops-tabs {
    :deep(.el-tabs__header) {
      margin-bottom: 20px;
    }

    :deep(.el-tabs__nav-wrap::after) {
      display: none;
    }
  }

  .tab-content {
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .connectivity-card,
  .diagnostics-card {
    border-radius: 14px;
  }

  .progress-overview-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 20px;
  }

  .progress-summary-card {
    border-radius: 14px;

    &.progress-summary-card--bootstrap {
      border: 1px solid #c7d2fe;
      background: linear-gradient(135deg, #eef2ff 0%, #f8fafc 100%);
    }

    &.progress-summary-card--incremental {
      border: 1px solid #bfdbfe;
      background: linear-gradient(135deg, #eff6ff 0%, #f8fafc 100%);
    }
  }

  .progress-summary-card__body {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .progress-summary-card__headline {
    font-size: 16px;
    font-weight: 700;
    color: var(--color-text-primary);
  }

  .progress-summary-card__subline {
    min-height: 44px;
    font-size: 13px;
    line-height: 1.7;
    color: var(--color-text-secondary);
  }

  .bootstrap-observability {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .bootstrap-observability__row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 12px;
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.7);
    border: 1px solid rgba(148, 163, 184, 0.2);
  }

  .bootstrap-observability__label {
    flex-shrink: 0;
    font-size: 12px;
    font-weight: 600;
    color: #475569;
  }

  .bootstrap-observability__value {
    text-align: right;
    font-size: 12px;
    line-height: 1.6;
    color: #0f172a;
  }

  .progress-summary-card__meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
    font-size: 12px;
    color: #64748b;
  }

  .progress-summary-card__actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }

  .connectivity-card__row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
  }

  .connectivity-card__status,
  .connectivity-card__actions {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }

  .connectivity-card__label {
    font-weight: 600;
    color: var(--color-text-primary);
  }

  .connectivity-card__desc {
    margin-top: 10px;
    color: var(--color-text-secondary);
    line-height: 1.7;
  }

  .diagnostics-generated-at {
    font-size: 12px;
    color: var(--color-text-light);
  }

  .diagnostics-list {
    display: grid;
    gap: 12px;
  }

  .diagnostic-item {
    padding: 14px 16px;
    border-radius: 12px;
    border: 1px solid #e2e8f0;
    background: #f8fafc;
  }

  .diagnostic-item__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 8px;
  }

  .diagnostic-item__title {
    font-weight: 600;
    color: var(--color-text-primary);
  }

  .diagnostic-item__summary,
  .diagnostic-item__action {
    line-height: 1.7;
    color: var(--color-text-secondary);
  }

  .diagnostic-item__action {
    margin-top: 6px;
    font-size: 13px;
  }

  // 首次初始化卡片
  .bootstrap-card {
    .bootstrap-content {
      display: flex;
      flex-direction: column;
      gap: 20px;
    }

    .bootstrap-desc {
      margin: 0;
      color: var(--color-text-secondary);
      line-height: 1.7;
    }

    .bootstrap-notes {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }

    .bootstrap-note {
      padding: 14px 16px;
      border-radius: 12px;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
    }

    .bootstrap-note-label {
      display: block;
      margin-bottom: 6px;
      font-size: 12px;
      font-weight: 600;
      color: var(--color-text-secondary);
    }

    .bootstrap-note-value {
      font-size: 13px;
      line-height: 1.7;
      color: var(--color-text-primary);
    }

    .bootstrap-steps {
      display: flex;
      gap: 16px;
      justify-content: center;
      flex-wrap: wrap;
    }

    .bootstrap-step {
      display: flex;
      gap: 12px;
      padding: 16px;
      border-radius: 12px;
      border: 1px solid #e5e7eb;
      flex: 1;
      max-width: 300px;

      &.is-done {
        border-color: var(--color-success);
        background: #f0fdf4;
      }

      &.is-pending {
        background: #f8fafc;
      }
    }

    .step-indicator {
      width: 32px;
      height: 32px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      color: #fff;
      background: var(--color-primary);
      flex-shrink: 0;
    }

    .is-done .step-indicator {
      background: var(--color-success);
    }

    .step-title {
      font-weight: 600;
      color: var(--color-text-primary);
    }

    .step-meta {
      margin-top: 4px;
      font-size: 12px;
      color: var(--color-text-secondary);
    }

    .bootstrap-actions {
      display: flex;
      justify-content: center;
      flex-wrap: wrap;
      gap: 12px;
    }
  }

  // 操作卡片
  .action-card {
    .action-buttons {
      display: flex;
      gap: 12px;
      align-items: center;
    }

    .running-hint {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 12px;
      color: var(--color-warning);
      font-size: 14px;
    }
  }

  .incremental-progress-card {
    border: 1px solid #bfdbfe;
    background: linear-gradient(135deg, #eff6ff 0%, #f8fafc 100%);

    .incremental-progress-card__header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 14px;
    }

    .incremental-progress-card__title {
      font-size: 15px;
      font-weight: 700;
      color: #1d4ed8;
    }

    .incremental-progress-card__meta,
    .incremental-progress-card__counts {
      margin-top: 6px;
      font-size: 13px;
      line-height: 1.7;
      color: #475569;
    }

    .incremental-progress-card__counts {
      margin-top: 0;
      text-align: right;
      white-space: nowrap;
    }

    // 阶段指示器样式
    .stage-indicator {
      font-weight: 600;
      color: #1d4ed8;
      padding: 2px 8px;
      background: rgba(59, 130, 246, 0.1);
      border-radius: 4px;
      margin-right: 4px;
    }

    .stage-divider {
      margin: 0 4px;
      color: #94a3b8;
    }

    .eta-text {
      color: #059669;
    }

    .detail-text {
      color: #64748b;
    }
  }

  // 任务卡片
  .tasks-card {
    :deep(.el-card__body) {
      padding: 16px;
    }
  }

  .running-tasks-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .task-item {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 16px;
    border-radius: 10px;
    border: 1px solid #e5e7eb;
    background: #fff;
    cursor: pointer;
    transition: all 0.2s;

    &:hover {
      border-color: var(--color-primary);
      box-shadow: 0 2px 8px rgba(0, 180, 216, 0.15);
    }

    &.is-selected {
      border-color: var(--color-primary);
      background: #f0f9ff;
    }
  }

  .task-main {
    flex: 1;
    min-width: 0;
  }

  .task-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
  }

  .task-id {
    font-weight: 600;
    color: var(--color-text-primary);
  }

  .task-type {
    color: var(--color-text-secondary);
  }

  .task-stage {
    font-size: 13px;
    color: var(--color-text-secondary);
    margin-bottom: 6px;
  }

  .task-progress-primary {
    font-size: 13px;
    font-weight: 600;
    color: var(--color-text-primary);
    margin-bottom: 4px;
  }

  .task-progress-secondary {
    font-size: 12px;
    color: #64748b;
    margin-bottom: 8px;
  }

  // 日志卡片
  .logs-card {
    .log-controls {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .log-actions {
      display: flex;
      align-items: center;
      gap: 12px;
    }
  }

  .log-container {
    height: calc(100vh - 320px);
    min-height: 400px;
    overflow-y: auto;
    background: #0f172a;
    border-radius: 10px;
    padding: 16px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 13px;
    line-height: 1.6;
  }

  .log-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: #64748b;
    gap: 12px;

    .el-icon {
      font-size: 48px;
    }

    p {
      margin: 0;
    }
  }

  .log-line {
    display: grid;
    grid-template-columns: 80px 60px 1fr;
    gap: 12px;
    padding: 6px 8px;
    border-radius: 6px;
    color: #e2e8f0;

    & + .log-line {
      margin-top: 2px;
    }

    &.log-error {
      background: rgba(239, 68, 68, 0.2);
    }

    &.log-warning {
      background: rgba(245, 158, 11, 0.15);
    }

    &.log-success {
      background: rgba(16, 185, 129, 0.15);
    }
  }

  .log-time {
    color: #64748b;
  }

  .log-level {
    color: #94a3b8;
    font-weight: 600;
  }

  @media (max-width: 767px) {
    .log-container {
      height: auto;
      min-height: 280px;
      max-height: none;
    }
  }

  // 状态管理
  .health-card {
    .health-summary {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 20px;
    }

    .health-item {
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 16px;
      border-radius: 12px;
      background: #fef2f2;
      border: 1px solid #fecaca;

      &.is-healthy {
        background: #f0fdf4;
        border-color: #bbf7d0;
      }

      .health-icon {
        width: 48px;
        height: 48px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 24px;
        color: #fff;
        background: var(--color-danger);

        .is-spinning {
          animation: spin 1s linear infinite;
        }
      }

      &.is-healthy .health-icon {
        background: var(--color-success);
      }

      .health-info {
        flex: 1;
      }

      .health-title {
        font-weight: 600;
        color: var(--color-text-primary);
        margin-bottom: 4px;
      }

      .health-desc {
        font-size: 13px;
        color: var(--color-text-secondary);
      }
    }
  }

  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }

  .detail-card {
    .detail-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
    }

    .detail-item {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 16px;
      background: var(--color-bg-light);
      border-radius: 10px;

      .detail-label {
        font-size: 13px;
        color: var(--color-text-secondary);
      }

      .detail-value {
        font-size: 20px;
        font-weight: 700;
        color: var(--color-text-primary);

        small {
          font-size: 13px;
          font-weight: 400;
          color: var(--color-text-secondary);
          margin-left: 4px;
        }
      }
    }
  }

  .env-summary-card {
    .env-summary-grid {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .env-section {
      .env-section-title {
        font-weight: 600;
        color: var(--color-text-primary);
        margin-bottom: 12px;
      }

      .env-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
      }
    }
  }

  .env-collapse {
    border: none;

    :deep(.el-collapse-item__header) {
      border-radius: 12px;
      padding: 0 16px;
      background: var(--color-bg-light);
      margin-bottom: 12px;
    }

    :deep(.el-collapse-item__wrap) {
      border: none;
      background: transparent;
    }

    .collapse-title {
      font-weight: 600;
      color: var(--color-text-primary);
    }

    .env-details-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 20px;
    }

    .env-detail-section {
      background: var(--color-bg-light);
      border-radius: 10px;
      padding: 16px;
    }

    .env-detail-title {
      font-weight: 600;
      color: var(--color-text-primary);
      margin-bottom: 12px;
    }

    .env-detail-items {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .env-detail-item {
      display: flex;
      justify-content: space-between;
      padding: 8px 0;
      border-bottom: 1px dashed #e5e7eb;

      &:last-child {
        border-bottom: none;
      }
    }

    .env-detail-key {
      color: var(--color-text-secondary);
    }

    .env-detail-value {
      font-weight: 500;
      color: var(--color-text-primary);
    }
  }
}

// 阶段4：管理员总览样式
.dashboard-cards {
  .dashboard-cards__grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 16px;
  }
}

.dashboard-card {
  padding: 20px;
  border-radius: 12px;
  border: 1px solid #e5e7eb;
  background: #fff;
  cursor: pointer;
  transition: all 0.2s;

  &:hover {
    border-color: var(--color-primary);
    box-shadow: 0 4px 12px rgba(0, 180, 216, 0.15);
  }

  &--success {
    background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);
    border-color: #86efac;

    .dashboard-card__label {
      color: #166534;
    }

    .dashboard-card__value {
      color: #15803d;
    }
  }

  &--warning {
    background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
    border-color: #fcd34d;

    .dashboard-card__label {
      color: #92400e;
    }

    .dashboard-card__value {
      color: #b45309;
    }
  }

  &--danger {
    background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%);
    border-color: #fca5a5;

    .dashboard-card__label {
      color: #991b1b;
    }

    .dashboard-card__value {
      color: #dc2626;
    }
  }

  &--info {
    background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
    border-color: #93c5fd;

    .dashboard-card__label {
      color: #1e40af;
    }

    .dashboard-card__value {
      color: #2563eb;
    }
  }

  .dashboard-card__label {
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 8px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .dashboard-card__value {
    font-size: 28px;
    font-weight: 700;
    margin-bottom: 4px;
  }

  .dashboard-card__meta {
    font-size: 12px;
    opacity: 0.8;
  }

  .dashboard-card__detail {
    margin-top: 12px;
    font-size: 12px;
    line-height: 1.7;
    opacity: 0.9;
  }
}

.pending-actions-card {
  .pending-actions-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .pending-action-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 16px;
    border-radius: 10px;
    border: 1px solid #e5e7eb;
    background: #f8fafc;

    &--error {
      background: #fef2f2;
      border-color: #fecaca;
    }

    &--warning {
      background: #fffbeb;
      border-color: #fde68a;
    }

    &--info {
      background: #eff6ff;
      border-color: #bfdbfe;
    }

    .pending-action-item__content {
      display: flex;
      flex-direction: column;
      gap: 4px;

      strong {
        font-weight: 600;
        color: var(--color-text-primary);
      }

      span {
        font-size: 13px;
        color: var(--color-text-secondary);
      }
    }
  }
}

.current-task-card {
  .current-task-content {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .current-task-info {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;

    .current-task-row {
      display: flex;
      flex-direction: column;
      gap: 4px;

      .label {
        font-size: 12px;
        color: var(--color-text-secondary);
      }

      span:not(.label) {
        font-weight: 600;
        color: var(--color-text-primary);
      }
    }
  }

  .current-task-summary {
    padding: 12px;
    background: #f8fafc;
    border-radius: 8px;
    font-size: 13px;
    line-height: 1.6;
    color: var(--color-text-secondary);
  }

  .current-task-actions {
    display: flex;
    gap: 8px;
  }
}

.current-task-metrics {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.current-task-metrics__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f8fafc;
}

.current-task-metrics__label {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}

.current-task-metrics__value {
  text-align: right;
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-text-primary);
}

.status-task-card {
  .status-task-card__body {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .status-task-card__headline {
    font-size: 15px;
    font-weight: 700;
    color: var(--color-text-primary);
  }

  .status-task-card__subline {
    font-size: 13px;
    color: var(--color-text-secondary);
  }
}

.latest-task-card {
  .latest-task-content {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .latest-task-summary {
    padding: 12px;
    background: #f0fdf4;
    border-radius: 8px;
    font-size: 13px;
    line-height: 1.6;
    color: #166534;
  }

  .latest-task-time {
    font-size: 12px;
    color: var(--color-text-secondary);
  }
}

.system-status-card {
  .system-status-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
  }

  .system-status-item {
    display: flex;
    justify-content: space-between;
    padding: 12px;
    background: #f8fafc;
    border-radius: 8px;

    &.has-gap {
      background: #fffbeb;
      border: 1px solid #fde68a;
    }

    .system-status-item__label {
      font-size: 13px;
      color: var(--color-text-secondary);
    }

    .system-status-item__value {
      font-weight: 600;
      color: var(--color-text-primary);
    }
  }
}

.overview-header {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 16px;
  padding: 0;
}

.quick-actions-card {
  .quick-actions-grid {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
  }

  .running-hint {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 12px;
    color: var(--color-warning);
    font-size: 14px;
  }
}

.mobile-summary-card {
  .mobile-summary-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .mobile-summary-item {
    padding: 14px;
    border-radius: 12px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;

    &--success {
      background: #f0fdf4;
      border-color: #bbf7d0;
    }

    &--warning {
      background: #fffbeb;
      border-color: #fde68a;
    }

    &--danger {
      background: #fef2f2;
      border-color: #fecaca;
    }
  }

  .mobile-summary-item__top {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 8px;
  }

  .mobile-summary-item__label {
    font-size: 13px;
    font-weight: 600;
    color: #475569;
  }

  .mobile-summary-item__value {
    font-size: 14px;
    font-weight: 700;
    color: #0f172a;
    text-align: right;
  }

  .mobile-summary-item__meta {
    font-size: 12px;
    line-height: 1.6;
    color: #64748b;
  }
}

.loading-card {
  padding: 40px;
}

.history-task-cards {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.history-task-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border-radius: 12px;
  border: 1px solid #e5e7eb;
  background: #fff;
}

.history-task-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.history-task-card__title {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
}

.history-task-card__summary {
  font-size: 13px;
  line-height: 1.6;
  color: #475569;
}

.history-task-card__meta {
  font-size: 12px;
  color: #94a3b8;
}

.mobile-log-summary {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.mobile-log-summary__hint {
  font-size: 12px;
  line-height: 1.6;
  color: #64748b;
}

.mobile-log-item {
  padding: 12px;
  border-radius: 10px;
  background: #111827;
  border: 1px solid #1f2937;
  color: #e5e7eb;

  &--error {
    border-color: rgba(239, 68, 68, 0.45);
  }

  &--warn,
  &--warning {
    border-color: rgba(245, 158, 11, 0.45);
  }
}

.mobile-log-item__header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 11px;
  color: #94a3b8;
}

.mobile-log-item__message {
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
}

.mobile-status-card {
  .mobile-status-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .mobile-status-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px;
    border-radius: 10px;
    background: #f8fafc;
    font-size: 13px;
    color: #475569;

    strong {
      color: #0f172a;
      text-align: right;
    }
  }
}

@media (max-width: 768px) {
  .ops-page {
    padding: 16px;

    .ops-tabs {
      :deep(.el-tabs__header) {
        margin-bottom: 16px;
      }

      :deep(.el-tabs__nav) {
        width: 100%;
      }

      :deep(.el-tabs__item) {
        padding: 0 12px;
        font-size: 13px;
      }
    }

    .tab-content {
      gap: 16px;
    }

    .card-header {
      align-items: flex-start;
      flex-direction: column;
    }

    .quick-actions-card {
      .quick-actions-grid {
        flex-direction: column;
      }

      :deep(.el-button) {
        width: 100%;
        min-height: 44px;
        margin-left: 0;
      }
    }

    .dashboard-cards__grid,
    .system-status-grid {
      grid-template-columns: 1fr;
    }

    .progress-overview-grid {
      grid-template-columns: 1fr;
    }

    .connectivity-card__row {
      flex-direction: column;
      align-items: flex-start;
    }

    .connectivity-card__actions,
    .log-controls,
    .log-actions,
    .current-task-actions {
      width: 100%;
      flex-wrap: wrap;
    }

    .connectivity-card__actions :deep(.el-button),
    .current-task-actions :deep(.el-button) {
      margin-left: 0;
    }

    .current-task-info,
    .detail-grid {
      grid-template-columns: 1fr;
    }

    .progress-summary-card__meta {
      flex-direction: column;
      align-items: flex-start;
    }

    .bootstrap-observability__row {
      flex-direction: column;
      align-items: flex-start;
    }

    .bootstrap-observability__value {
      text-align: left;
    }

    .current-task-metrics__row {
      flex-direction: column;
      align-items: flex-start;
    }

    .current-task-metrics__value {
      text-align: left;
    }

    .health-summary {
      grid-template-columns: 1fr;
    }

    .env-details-grid {
      grid-template-columns: 1fr;
    }

    .bootstrap-steps {
      flex-direction: column;
    }

    .bootstrap-notes {
      grid-template-columns: 1fr;
    }

    .action-buttons {
      flex-direction: column;
    }

    .incremental-progress-card__header {
      flex-direction: column;
    }

    .incremental-progress-card__counts {
      text-align: left;
      white-space: normal;
    }

    .log-line {
      grid-template-columns: 1fr;
      gap: 4px;
    }

    .system-status-item {
      flex-direction: column;
      align-items: flex-start;
    }
  }
}

@media (max-width: 480px) {
  .ops-page {
    .detail-grid {
      grid-template-columns: 1fr;
    }

    .connectivity-card__actions {
      width: 100%;
    }
  }
}
</style>
