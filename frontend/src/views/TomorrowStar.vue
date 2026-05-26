<template>
  <div class="tomorrow-star-page">
    <el-tabs v-model="activeTab" class="page-tabs">
      <el-tab-pane
        v-for="tab in analysisTabs"
        :key="tab.name"
        :label="tab.label"
        :name="tab.name"
      >
        <el-alert
          v-if="showInitializationAlert"
          class="page-alert"
          type="info"
          :closable="false"
          show-icon
          title="尚未完成首次初始化"
          :description="configStore.initializationMessage"
        />

        <div v-if="activeShowInitializationEmpty" class="page-empty">
          <el-empty :description="activeEmptyDescription" :image-size="120">
            <el-button type="primary" @click="router.push('/update')">
              前往任务中心初始化
            </el-button>
            <el-button @click="refreshStatusAndRetry">
              重新检查状态
            </el-button>
          </el-empty>
        </div>

        <template v-else>
          <el-card v-if="tab.name === 'tomorrow-star' && incrementalUpdate.running" class="update-progress-card" shadow="never">
            <div class="progress-content">
              <div class="progress-info">
                <el-icon class="is-loading"><Loading /></el-icon>
                <span class="progress-text">增量更新中...</span>
                <span class="progress-detail">
                  {{ incrementalUpdate.updated_count }} 更新 / {{ incrementalUpdate.skipped_count }} 跳过 / {{ incrementalUpdate.failed_count }} 失败
                </span>
                <span v-if="incrementalUpdate.current_code" class="current-code">
                  当前: {{ incrementalUpdate.current_code }}
                </span>
              </div>
              <el-progress
                :percentage="incrementalUpdate.progress"
                :stroke-width="12"
                :show-text="true"
              />
            </div>
          </el-card>
          <el-alert
            v-else-if="tab.name === 'tomorrow-star' && authStore.isAdmin && incrementalUpdate.status === 'failed'"
            class="page-alert"
            type="warning"
            :closable="false"
            show-icon
            title="增量更新上次未完成"
                :description="incrementalUpdate.last_error || incrementalUpdate.message || '可前往任务中心重新发起，系统会尽量从已完成位置继续。'"
          />

          <div v-if="isMobile" class="mobile-layout">
            <el-card class="mobile-section-card">
              <template #header>
                <div class="card-header">
                  <div class="title-section">
                    <span>历史信息</span>
                    <el-tag v-if="activeSelectedDate" size="small" type="info" effect="plain">
                      已选 {{ activeViewingDateDisplay }}
                    </el-tag>
                  </div>
                </div>
              </template>

              <div class="table-header-tip mobile-tip">
                <span class="tip-item">· 点击日期刷新对应 Top 5</span>
              </div>

              <div v-if="activeDisplayHistoryData.length > 0" class="mobile-history-list">
                <button
                  v-for="row in activeDisplayHistoryData"
                  :key="row.rawDate"
                  type="button"
                  class="mobile-history-item"
                  :class="{ active: activeSelectedDate === row.rawDate }"
                  @click="selectDate(row)"
                >
                  <div class="mobile-history-item__header">
                    <span class="mobile-history-item__date">{{ row.date }}</span>
                    <div class="mobile-history-item__status">
                      <el-tag
                        v-if="row.rawDate === activeLatestDate"
                        type="success"
                        size="small"
                        class="status-tag"
                      >
                        最新
                      </el-tag>
                    </div>
                  </div>
                  <div class="mobile-history-item__meta">
                    <span v-if="!isCurrentHotTab">候选数 {{ row.count === '-' ? '-' : row.count }}</span>
                    <span v-if="isCurrentHotTab">趋势启动数 {{ row.pass === '-' ? '-' : row.pass }}</span>
                    <span v-if="isCurrentHotTab">B1通过数 {{ row.b1PassCount === '-' ? '-' : row.b1PassCount }}</span>
                    <span v-if="!isCurrentHotTab">明日之星 {{ row.tomorrowStarCount === '-' ? '-' : row.tomorrowStarCount }}</span>
                  </div>
                </button>
              </div>
              <el-empty v-else description="暂无历史信息" :image-size="90" />

              <div class="pagination-wrap mobile-pagination">
                <div class="mobile-pagination__summary">
                  第 {{ activeHistoryPage }} / {{ activeHistoryPageCount }} 页
                </div>
                <el-pagination
                  v-model:current-page="activeHistoryPage"
                  :page-size="activeHistoryPageSize"
                  layout="prev, pager, next"
                  :total="activeTotalHistoryCount"
                  :hide-on-single-page="false"
                  background
                  size="small"
                />
              </div>
            </el-card>

            <el-card
              class="mobile-section-card"
              v-loading="activeCandidateLoading"
              element-loading-text="正在刷新候选数据..."
            >
              <template #header>
                <div class="card-header">
                  <div class="title-section">
                    <span>{{ activeMobileAnalysisTitle }}</span>
                    <el-tag size="small" type="success" class="date-tag">
                      {{ activeViewingDateDisplay }}
                    </el-tag>
                  </div>
                  <div class="header-actions">
                    <el-tag v-if="activeShowCachedHint" type="info" size="small" effect="plain">
                      已展示缓存结果
                    </el-tag>
                    <el-radio-group
                      v-if="showBoardFilter"
                      v-model="currentHotBoardFilter"
                      size="small"
                      class="board-filter"
                    >
                      <el-radio-button value="all">全部</el-radio-button>
                      <el-radio-button value="sci-tech">科创板</el-radio-button>
                      <el-radio-button value="others">其他板块</el-radio-button>
                    </el-radio-group>
                    <el-radio-group
                      v-if="showBoardFilter"
                      v-model="currentHotRiskFilter"
                      size="small"
                      class="board-filter"
                    >
                      <el-radio-button value="all">全部标的</el-radio-button>
                      <el-radio-button value="risk-only">风险标的</el-radio-button>
                    </el-radio-group>
                    <el-button
                      type="primary"
                      size="small"
                      :icon="Refresh"
                      :loading="activeLoadingLatest"
                      @click="refreshCurrentCandidates"
                    >
                      刷新
                    </el-button>
                  </div>
                </div>
              </template>

              <div class="candidate-concept-filter candidate-concept-filter--mobile">
                <el-autocomplete
                  v-model="candidateConceptQuery"
                  placeholder="输入概念关键词，例如 PCB、光模块"
                  clearable
                  :fetch-suggestions="fetchCandidateConceptSuggestions"
                  @keyup.enter="applyCandidateConceptFilter()"
                  @clear="clearCandidateConceptFilter"
                >
                  <template #default="{ item }">
                    <div class="candidate-concept-suggestion">
                      <span>{{ item.value }}</span>
                      <small>{{ item.label }}</small>
                    </div>
                  </template>
                  <template #append>
                    <el-button :icon="Search" :loading="candidateConceptLoading" @click="applyCandidateConceptFilter()" />
                  </template>
                </el-autocomplete>
                <el-button
                  v-if="candidateConceptQuery.trim()"
                  size="small"
                  :loading="candidateConceptLoading"
                  @click="refreshCandidateConceptAsync"
                >
                  异步刷新
                </el-button>
              </div>

              <div v-if="activeConceptFilterSummary" class="candidate-concept-filter__summary candidate-concept-filter__summary--mobile">
                {{ activeConceptFilterSummary }}
              </div>

              <div class="table-header-tip mobile-tip">
                <span class="tip-item">{{ activeMobileAnalysisTip }}</span>
              </div>

              <div v-if="activeMobileAnalysisRows.length > 0" class="mobile-analysis-list">
                <button
                  v-for="row in activeMobileAnalysisRows"
                  :key="row.code"
                  type="button"
                  class="mobile-analysis-item"
                  @click="viewStock(row.code, activeStockSource)"
                >
                  <div class="mobile-analysis-item__header">
                    <div>
                      <div class="mobile-analysis-item__code">{{ row.code }}</div>
                      <div class="mobile-analysis-item__name">{{ getAnalysisResultName(row) }}</div>
                    </div>
                    <el-tag :type="getScoreType(row.total_score)" size="small">
                      {{ typeof row.total_score === 'number' ? row.total_score.toFixed(1) : '-' }}
                    </el-tag>
                  </div>
                  <div class="mobile-analysis-item__meta">
                    <el-tag :type="getSignalTypeTag(row.signal_type)" size="small">
                      {{ getSignalTypeLabel(row.signal_type) }}
                    </el-tag>
                    <el-tag
                      v-if="isCurrentHotTab && isRiskCandidate(row)"
                      :type="getRiskFlagTagType(getRiskFlagLevel(row))"
                      size="small"
                    >
                      {{ getRiskFlagLabel(getRiskFlagLevel(row)) }}
                    </el-tag>
                    <el-tag v-if="isCurrentHotTab" :type="getBooleanTagType(getAnalysisB1Passed(row))" size="small">
                      B1 {{ getBooleanTagLabel(getAnalysisB1Passed(row)) }}
                    </el-tag>
                    <el-tag v-if="isCurrentHotTab" type="info" size="small">
                      活跃 {{ formatActivePoolRank(row.active_pool_rank) }}
                    </el-tag>
                    <el-tag v-if="activeConceptFilterApplied" type="warning" size="small">
                      相关 {{ formatCandidateConceptRelevance(row.code) }}
                    </el-tag>
                    <el-tooltip
                      v-if="showAnalysisPrefilter && getAnalysisPrefilterPassed(row) === false && getAnalysisPrefilterSummary(getAnalysisPrefilterLike(row))"
                      :content="getAnalysisPrefilterSummary(getAnalysisPrefilterLike(row))"
                      placement="top"
                    >
                      <el-tag :type="getAnalysisPrefilterTagType(getAnalysisPrefilterPassed(row))" size="small">
                        前置 {{ getAnalysisPrefilterLabel(getAnalysisPrefilterPassed(row)) }}
                      </el-tag>
                    </el-tooltip>
                    <el-tag
                      v-else-if="showAnalysisPrefilter"
                      :type="getAnalysisPrefilterTagType(getAnalysisPrefilterPassed(row))"
                      size="small"
                    >
                      前置 {{ getAnalysisPrefilterLabel(getAnalysisPrefilterPassed(row)) }}
                    </el-tag>
                    <div v-if="getRowPullbackQualityLabel(row) || getRowPullbackNegativeFlags(row).length > 0" class="analysis-pullback-tags">
                      <el-tag
                        v-if="getRowPullbackQualityLabel(row)"
                        :type="getPullbackQualityTagType(getRowPullbackQuality(row))"
                        size="small"
                        effect="plain"
                      >
                        回调 {{ getRowPullbackQualityLabel(row) }}
                      </el-tag>
                      <el-tag
                        v-for="flag in getRowPullbackNegativeFlags(row)"
                        :key="`${row.code}-${flag}`"
                        :type="getPullbackNegativeFlagTagType(flag)"
                        size="small"
                        effect="plain"
                      >
                        {{ getPullbackNegativeFlagLabel(flag) }}
                      </el-tag>
                    </div>
                    <span v-if="showAnalysisComment" class="mobile-analysis-item__comment">{{ getAnalysisResultComment(row) }}</span>
                  </div>
                </button>
              </div>
              <el-empty v-else :description="activeMobileAnalysisEmptyDescription" :image-size="90">
                <div v-if="showTomorrowStarMarketRegimeNotice" class="market-regime-empty">
                  <div class="market-regime-empty__title">今日未展示候选股票</div>
                  <div class="market-regime-empty__summary">{{ activeMarketRegimeSummary }}</div>
                  <ul v-if="activeMarketRegimeDetails.length > 0" class="market-regime-empty__list">
                    <li v-for="detail in activeMarketRegimeDetails" :key="detail">{{ detail }}</li>
                  </ul>
                  <div class="market-regime-empty__hint">
                    当前策略会先判断整体市场环境；当大环境偏弱时，会暂停输出候选股票，避免把低质量机会展示给用户。
                  </div>
                </div>
              </el-empty>

              <div v-if="showActiveAnalysisPagination" class="pagination-wrap mobile-pagination">
                <div class="mobile-pagination__summary">
                  第 {{ activeMobileAnalysisPage }} / {{ activeMobileAnalysisPageCount }} 页
                </div>
                <el-pagination
                  v-model:current-page="activeMobileAnalysisPage"
                  :page-size="activeMobileAnalysisPageSize"
                  layout="prev, pager, next"
                  :total="activeMobileAnalysisTotal"
                  :hide-on-single-page="false"
                  background
                  size="small"
                />
              </div>
            </el-card>
          </div>

          <div v-else class="top-grid" :class="{ 'is-current-hot': isCurrentHotTab }">
            <div class="history-column">
              <el-card class="history-card matched-height">
                <template #header>
                  <div class="card-header">
                    <span>历史记录</span>
                  </div>
                </template>

                <div class="table-header-tip">
                  <span class="tip-item">· 点击日期查看对应数据</span>
                  <span class="tip-item">· 右侧跟随左侧选择</span>
                </div>

                <el-table
                  :data="activeDisplayHistoryData"
                  @row-click="selectDate"
                  class="history-table"
                  :height="activeHistoryTableHeight"
                  highlight-current-row
                  :current-row-key="activeSelectedDate"
                  row-key="rawDate"
                >
                  <el-table-column prop="date" label="时间" :min-width="isCurrentHotTab ? 150 : 108" />
                  <el-table-column v-if="!isCurrentHotTab" prop="count" label="候选" width="54" align="center">
                    <template #default="{ row }">
                      {{ row.count === '-' ? '-' : row.count }}
                    </template>
                  </el-table-column>
                  <el-table-column v-if="isCurrentHotTab" prop="pass" label="启动" min-width="82" align="center">
                    <template #default="{ row }">
                      <el-button
                        v-if="row.pass !== '-' && row.pass > 0"
                        type="success"
                        size="small"
                        text
                        @click.stop="showSignalReturns(row, 'trend_start')"
                      >
                        {{ row.pass }}
                      </el-button>
                      <span v-else>-</span>
                    </template>
                  </el-table-column>
                  <el-table-column v-if="isCurrentHotTab" prop="b1PassCount" min-width="82" label="B1" align="center">
                    <template #default="{ row }">
                      <el-tag v-if="row.b1PassCount !== '-'" :type="row.b1PassCount > 0 ? 'success' : 'info'" size="small">
                        {{ row.b1PassCount }}
                      </el-tag>
                      <span v-else>-</span>
                    </template>
                  </el-table-column>
                  <el-table-column v-if="!isCurrentHotTab" prop="tomorrowStarCount" label="星" width="46" align="center">
                    <template #default="{ row }">
                      <el-button
                        v-if="row.tomorrowStarCount !== '-' && row.tomorrowStarCount > 0"
                        type="success"
                        size="small"
                        text
                        @click.stop="showSignalReturns(row, 'tomorrow_star')"
                      >
                        {{ row.tomorrowStarCount }}
                      </el-button>
                      <span v-else>-</span>
                    </template>
                  </el-table-column>
                </el-table>

                <div class="pagination-wrap">
                  <span class="pagination-total">共 {{ activeTotalHistoryCount }} 日</span>
                  <el-pagination
                    v-model:current-page="activeHistoryPage"
                    :page-size="activeHistoryPageSize"
                    layout="prev, pager, next"
                    :total="activeTotalHistoryCount"
                    :hide-on-single-page="false"
                    background
                    size="small"
                  />
                </div>
              </el-card>
            </div>

            <div class="content-column">
              <el-card
                class="candidates-card matched-height"
                v-loading="activeCandidateLoading"
                element-loading-text="正在刷新候选数据..."
              >
                <template #header>
                  <div class="card-header">
                    <div class="title-section">
                      <span>{{ activeCandidateTitle }}</span>
                      <el-tag size="small" type="success" class="date-tag">
                        {{ activeViewingDateDisplay }}
                      </el-tag>
                    </div>
                    <div class="header-actions">
                      <el-tag v-if="activeShowCachedHint" type="info" size="small" effect="plain">
                        已展示缓存结果
                      </el-tag>
                      <el-radio-group
                        v-if="showBoardFilter"
                        v-model="currentHotBoardFilter"
                        size="small"
                        class="board-filter"
                      >
                        <el-radio-button value="all">全部</el-radio-button>
                        <el-radio-button value="sci-tech">科创板</el-radio-button>
                        <el-radio-button value="others">其他板块</el-radio-button>
                      </el-radio-group>
                      <el-radio-group
                        v-if="showBoardFilter"
                        v-model="currentHotRiskFilter"
                        size="small"
                        class="board-filter"
                      >
                        <el-radio-button value="all">全部标的</el-radio-button>
                        <el-radio-button value="risk-only">风险标的</el-radio-button>
                      </el-radio-group>
                      <el-button
                        type="primary"
                        size="small"
                        :icon="Refresh"
                        :loading="activeLoadingLatest"
                        @click="refreshCurrentCandidates"
                      >
                        刷新
                      </el-button>
                    </div>
                  </div>
                </template>

                <div class="candidate-concept-filter">
                  <el-autocomplete
                    v-model="candidateConceptQuery"
                    placeholder="输入概念关键词，例如 PCB、光模块"
                    clearable
                    :fetch-suggestions="fetchCandidateConceptSuggestions"
                    @keyup.enter="applyCandidateConceptFilter()"
                    @clear="clearCandidateConceptFilter"
                  >
                    <template #default="{ item }">
                      <div class="candidate-concept-suggestion">
                        <span>{{ item.value }}</span>
                        <small>{{ item.label }}</small>
                      </div>
                    </template>
                    <template #append>
                      <el-button :icon="Search" :loading="candidateConceptLoading" @click="applyCandidateConceptFilter()">
                        检索
                      </el-button>
                    </template>
                  </el-autocomplete>
                  <el-button
                    v-if="candidateConceptQuery.trim()"
                    text
                    size="small"
                    :disabled="candidateConceptLoading"
                    @click="clearCandidateConceptFilter"
                  >
                    清除
                  </el-button>
                  <el-button
                    v-if="candidateConceptQuery.trim()"
                    size="small"
                    :loading="candidateConceptLoading"
                    @click="refreshCandidateConceptAsync"
                  >
                    异步刷新
                  </el-button>
                </div>

                <div v-if="activeConceptFilterSummary" class="candidate-concept-filter__summary">
                  {{ activeConceptFilterSummary }}
                </div>

                <div
                  v-if="showTomorrowStarIndustryFilter"
                  class="industry-filter-panel"
                  role="group"
                  aria-label="板块过滤"
                >
                  <button
                    type="button"
                    class="industry-filter-chip"
                    :class="{ active: selectedTomorrowStarIndustries.length === 0 }"
                    :aria-pressed="selectedTomorrowStarIndustries.length === 0"
                    @click="clearTomorrowStarIndustryFilter"
                  >
                    全部:{{ tomorrowStarMergedCandidates.length }}
                  </button>
                  <button
                    v-for="option in tomorrowStarIndustryOptions"
                    :key="option.name"
                    type="button"
                    class="industry-filter-chip"
                    :class="{ active: selectedTomorrowStarIndustries.includes(option.name) }"
                    :aria-pressed="selectedTomorrowStarIndustries.includes(option.name)"
                    @click="toggleTomorrowStarIndustry(option.name)"
                  >
                    {{ option.name }}:{{ option.count }}
                  </button>
                </div>

                <div v-if="activeCandidateSortLabel" class="sort-hint">
                  当前排序：{{ activeCandidateSortLabel }}
                </div>

                <div v-if="isCurrentHotTab && currentHotRiskRegime" class="risk-regime-banner">
                  <div class="risk-regime-banner__header">
                    <span class="risk-regime-banner__title">过热转弱预警</span>
                    <div class="risk-regime-banner__tags">
                      <el-tag :type="getRiskRegimeTagType(currentHotRiskRegime.level)" size="small">
                        {{ getRiskRegimeLabel(currentHotRiskRegime.level) }}
                      </el-tag>
                      <el-tag v-if="currentHotRiskRegime.triggered" type="danger" size="small" effect="plain">
                        已触发
                      </el-tag>
                      <el-tag
                        v-if="currentHotRiskRegime.ai_review?.result?.confirmed_level"
                        :type="getRiskRegimeTagType(currentHotRiskRegime.ai_review?.result?.confirmed_level)"
                        size="small"
                        effect="plain"
                      >
                        AI {{ getRiskRegimeLabel(currentHotRiskRegime.ai_review?.result?.confirmed_level) }}
                      </el-tag>
                    </div>
                  </div>
                  <p class="risk-regime-banner__summary">
                    {{ currentHotRiskRegime.summary || '暂无明确市场级过热转弱信号。' }}
                  </p>
                  <div class="risk-regime-banner__meta">
                    <span>总分 {{ formatRiskRegimeScore(currentHotRiskRegime.score) }}</span>
                    <span>风险占比 {{ formatRatioPct(currentHotRiskRegime.risk_ratio) }}</span>
                    <span>趋势启动 {{ formatRatioPct(currentHotRiskRegime.trend_start_ratio) }}</span>
                    <span>AI置信 {{ formatAiConfidence(currentHotRiskRegime.ai_review?.result?.confidence) }}</span>
                  </div>
                  <div class="risk-regime-banner__hint">
                    该预警基于全市场活跃股票样本，不基于你的自选热盘。
                  </div>
                </div>

                <div class="table-header-tip">
                  <template v-if="tab.name === 'tomorrow-star'">
                    <span class="tip-item">· 筛选逻辑：通过 B1 策略筛选候选股票</span>
                    <span class="tip-item">· 条件：KDJ 低位 + 知行线结构通过 + 周线多头排列 + 最大量日非阴线</span>
                  </template>
                  <template v-else>
                    <span class="tip-item">· 当前热盘关注当日强势活跃标的AI标的，右侧支持科创板 / 其他板块过滤，点击历史日期可回看对应热力股票池</span>
                  </template>
                </div>

                <el-table
                  v-if="activeDisplayLatestCandidates.length > 0"
                  :data="activeDisplayLatestCandidates"
                  stripe
                  class="candidates-table"
                  :height="activeCandidateTableHeight"
                  table-layout="fixed"
                  size="small"
                  @sort-change="handleCandidateSortChange"
                >
                  <el-table-column prop="code" label="代码" width="68" sortable="custom" :sort-orders="candidateSortOrders" />
                  <el-table-column prop="name" label="名称" width="76" sortable="custom" :sort-orders="candidateSortOrders" show-overflow-tooltip>
                    <template #default="{ row }">
                      <span class="stock-name-cell">{{ row.name || row.code }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column v-if="isCurrentHotTab" label="B1" width="58" align="center" sortable="custom" prop="b1_passed" :sort-orders="candidateSortOrders">
                    <template #default="{ row }">
                      <el-tag :type="getBooleanTagType(row.b1_passed)" size="small">
                        {{ getBooleanTagLabel(row.b1_passed) }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column v-if="isCurrentHotTab" prop="signal_type" label="信号" width="88" align="center" sortable="custom" :sort-orders="candidateSortOrders">
                    <template #default="{ row }">
                      <el-tag :type="getSignalTypeTag(row.signal_type)" size="small">
                        {{ getSignalTypeLabel(row.signal_type) }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column v-if="isCurrentHotTab" label="风险" width="78" align="center">
                    <template #default="{ row }">
                      <el-tag
                        v-if="isRiskCandidate(row)"
                        :type="getRiskFlagTagType(getRiskFlagLevel(row))"
                        size="small"
                      >
                        {{ getRiskFlagLabel(getRiskFlagLevel(row)) }}
                      </el-tag>
                      <span v-else>-</span>
                    </template>
                  </el-table-column>
                  <el-table-column v-if="!isCurrentHotTab" prop="tomorrow_star_pass" label="星" width="58" align="center">
                    <template #default="{ row }">
                      <el-tag :type="getBooleanTagType(row.tomorrow_star_pass)" size="small">
                        {{ getBooleanTagLabel(row.tomorrow_star_pass) }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column v-if="!isCurrentHotTab" prop="industry" label="板块" width="92" sortable="custom" :sort-orders="candidateSortOrders" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{ getCandidateIndustryLabel(row) }}
                    </template>
                  </el-table-column>
                  <el-table-column v-if="!isCurrentHotTab" prop="signal_type" label="信号" width="78" align="center" sortable="custom" :sort-orders="candidateSortOrders">
                    <template #default="{ row }">
                      <el-tag :type="getSignalTypeTag(row.signal_type)" size="small">
                        {{ getSignalTypeLabel(row.signal_type) }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column
                    v-if="activeConceptFilterApplied"
                    label="相关"
                    width="64"
                    align="center"
                  >
                    <template #default="{ row }">
                      <el-tooltip
                        v-if="getCandidateConceptReason(row.code)"
                        :content="getCandidateConceptReason(row.code)"
                        placement="top"
                      >
                        <el-tag size="small" type="warning">
                          {{ formatCandidateConceptRelevance(row.code) }}
                        </el-tag>
                      </el-tooltip>
                      <span v-else>{{ formatCandidateConceptRelevance(row.code) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column v-if="!isCurrentHotTab" prop="total_score" label="评分" width="58" align="right" sortable="custom" :sort-orders="candidateSortOrders">
                    <template #default="{ row }">
                      <el-tag :type="getScoreType(row.total_score)" size="small">
                        {{ typeof row.total_score === 'number' ? row.total_score.toFixed(1) : '-' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column v-if="isCurrentHotTab" prop="total_score" label="评分" width="62" align="right" sortable="custom" :sort-orders="candidateSortOrders">
                    <template #default="{ row }">
                      <el-tag :type="getScoreType(row.total_score)" size="small">
                        {{ typeof row.total_score === 'number' ? row.total_score.toFixed(1) : '-' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column v-if="isCurrentHotTab" prop="active_pool_rank" label="活跃" width="62" align="center" sortable="custom" :sort-orders="candidateSortOrders">
                    <template #default="{ row }">
                      {{ formatActivePoolRank(row.active_pool_rank) }}
                    </template>
                  </el-table-column>
                  <el-table-column prop="open_price" label="开盘" width="60" align="right" sortable="custom" :sort-orders="candidateSortOrders">
                    <template #default="{ row }">
                      {{ typeof row.open_price === 'number' ? row.open_price.toFixed(2) : '-' }}
                    </template>
                  </el-table-column>
                  <el-table-column prop="close_price" label="收盘" width="60" align="right" sortable="custom" :sort-orders="candidateSortOrders">
                    <template #default="{ row }">
                      {{ typeof row.close_price === 'number' ? row.close_price.toFixed(2) : '-' }}
                    </template>
                  </el-table-column>
                  <el-table-column prop="change_pct" label="涨跌" width="62" align="right" sortable="custom" :sort-orders="candidateSortOrders">
                    <template #default="{ row }">
                      <span :class="typeof row.change_pct === 'number' ? (row.change_pct > 0 ? 'text-up' : row.change_pct < 0 ? 'text-down' : '') : ''">
                        {{ typeof row.change_pct === 'number' ? row.change_pct.toFixed(2) + '%' : '-' }}
                      </span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="turnover_rate" label="换手" width="60" align="right" sortable="custom" :sort-orders="candidateSortOrders">
                    <template #default="{ row }">
                      {{ formatTurnoverRate(row.turnover_rate) }}
                    </template>
                  </el-table-column>
                  <el-table-column prop="volume_ratio" label="量比" width="50" align="right" sortable="custom" :sort-orders="candidateSortOrders">
                    <template #default="{ row }">
                      {{ formatVolumeRatio(row.volume_ratio) }}
                    </template>
                  </el-table-column>
                  <el-table-column v-if="!isCurrentHotTab" prop="active_pool_rank" label="活跃" width="54" align="center" sortable="custom" :sort-orders="candidateSortOrders">
                    <template #default="{ row }">
                      {{ formatActivePoolRank(row.active_pool_rank) }}
                    </template>
                  </el-table-column>
                  <el-table-column prop="kdj_j" label="KDJ" width="52" align="right" sortable="custom" :sort-orders="candidateSortOrders">
                    <template #default="{ row }">
                      {{ typeof row.kdj_j === 'number' ? row.kdj_j.toFixed(1) : '-' }}
                    </template>
                  </el-table-column>
                  <el-table-column v-if="isCurrentHotTab" label="板块" width="160" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{ getCurrentHotBoardLabel(row) }}
                    </template>
                  </el-table-column>
                  <el-table-column v-else prop="consecutive_days" width="50" align="center" sortable="custom" :sort-orders="candidateSortOrders">
                    <template #header>
                      <el-tooltip content="连续通过B1规则筛选的天数" placement="top">
                        <span class="table-header-help">连续</span>
                      </el-tooltip>
                    </template>
                    <template #default="{ row }">
                      {{ (row.consecutive_days || 1) > 1 ? row.consecutive_days : '否' }}
                    </template>
                  </el-table-column>
                  <el-table-column label="备注" min-width="180" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{ getCandidateInlineNote(row) }}
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="56" align="center">
                    <template #default="{ row }">
                      <el-button text type="primary" size="small" @click="viewStock(row.code, activeStockSource)">
                        详情
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <div v-else-if="showTomorrowStarMarketRegimeNotice" class="market-regime-empty market-regime-empty--desktop">
                  <div class="market-regime-empty__title">今日未展示候选股票</div>
                  <div class="market-regime-empty__summary">{{ activeMarketRegimeSummary }}</div>
                  <ul v-if="activeMarketRegimeDetails.length > 0" class="market-regime-empty__list">
                    <li v-for="detail in activeMarketRegimeDetails" :key="detail">{{ detail }}</li>
                  </ul>
                  <div class="market-regime-empty__hint">
                    当前策略会先判断整体市场环境；当大环境偏弱时，会暂停输出候选股票，避免把低质量机会展示给用户。
                  </div>
                </div>
                <el-empty v-else description="暂无候选股票" :image-size="90" />

                <div v-if="activeDisplayLatestCandidates.length > 0" class="pagination-wrap">
                  <el-pagination
                    v-model:current-page="activeCandidatePage"
                    :page-size="activeCandidatePageSize"
                    layout="total, prev, pager, next"
                    :total="activeTotalLatestCandidates"
                    :hide-on-single-page="false"
                    background
                  />
                </div>
              </el-card>
            </div>
          </div>
        </template>
      </el-tab-pane>

      <el-tab-pane v-if="canUseMiddayAnalysis" label="中盘分析" name="midday-analysis">
        <div v-if="isMobile" class="mobile-layout">
          <el-card class="mobile-section-card midday-card" v-loading="loadingMidday">
            <template #header>
              <div class="card-header">
                <div class="title-section">
                  <span>中盘分析</span>
                  <el-tag size="small" type="warning" class="date-tag">
                    {{ middayTradeDateDisplay || '当前交易日' }}
                  </el-tag>
                </div>
                <div class="header-actions">
                  <el-radio-group
                    v-model="middaySource"
                    size="small"
                    class="source-switch"
                  >
                    <el-radio-button value="tomorrow-star">明日之星候选</el-radio-button>
                    <el-radio-button value="current-hot">当前热盘</el-radio-button>
                  </el-radio-group>
                  <el-tag
                    v-if="middayTaskRunning"
                    size="small"
                    type="warning"
                    effect="plain"
                  >
                    生成中
                  </el-tag>
                  <el-button
                    v-if="authStore.isAdmin"
                    size="small"
                    :loading="loadingMiddayAction"
                    @click="runMiddayAdminAction('prefetch')"
                  >
                    预下载
                  </el-button>
                  <el-button
                    v-if="authStore.isAdmin"
                    type="primary"
                    size="small"
                    :loading="loadingMiddayAction"
                    @click="runMiddayAdminAction('generate')"
                  >
                    手动生成
                  </el-button>
                  <el-button
                    size="small"
                    :icon="Refresh"
                    :loading="loadingMidday || loadingMiddayAction"
                    @click="refreshMiddayView"
                  >
                    刷新
                  </el-button>
                </div>
              </div>
            </template>

            <div class="table-header-tip mobile-tip">
              <span class="tip-item">· 仅展示当前交易日盘中候选与评分结果</span>
              <span class="tip-item">· 管理员调试入口，生成后用于制定下午交易预案</span>
            </div>

            <div class="midday-meta midday-meta--mobile">
              <el-tag size="small" effect="plain">数据源 {{ middaySourceLabel }}</el-tag>
              <el-tag size="small" effect="plain">交易日 {{ middayTradeDateDisplay || '-' }}</el-tag>
              <el-tag size="small" effect="plain">快照 {{ middaySnapshotTimeDisplay || '-' }}</el-tag>
              <el-tag size="small" effect="plain">候选日期 {{ middaySourcePickDateDisplay || '-' }}</el-tag>
            </div>

            <div v-if="middayMarketOverviewSummary" class="midday-market-overview midday-market-overview--mobile">
              <div class="midday-market-overview__summary">{{ middayMarketOverviewSummary }}</div>
              <div class="midday-market-overview__items">
                <span
                  v-for="item in middayMarketOverviewItems"
                  :key="item.name"
                  class="midday-market-chip"
                >
                  {{ item.summary || item.name }}
                </span>
              </div>
            </div>

            <div v-if="middayRows.length > 0 && middayCanViewData" class="mobile-analysis-list">
              <button
                v-for="row in middayRows"
                :key="row.code"
                type="button"
                class="mobile-analysis-item"
                @click="viewStock(row.code, 'midday-analysis')"
              >
                <div class="mobile-analysis-item__header">
                  <div>
                    <div class="mobile-analysis-item__code">{{ row.code }}</div>
                    <div class="mobile-analysis-item__name">{{ row.name }}</div>
                  </div>
                  <el-tag :type="getMiddayTrendStartTagType(row)" size="small">
                    {{ formatMiddayTrendStartScore(row) }}
                  </el-tag>
                </div>
                <div class="mobile-analysis-item__meta">
                  <div class="midday-mobile-tags">
                    <el-tag :type="getBooleanTagType(row.b1_passed)" size="small">
                      B1 {{ getBooleanTagLabel(row.b1_passed) }}
                    </el-tag>
                    <el-tag :type="getSignalTypeTag(row.signal_type ?? undefined)" size="small">
                      {{ getSignalTypeLabel(row.signal_type ?? undefined) }}
                    </el-tag>
                    <el-tag :type="getVerdictTagType(row.verdict)" size="small">
                      {{ getVerdictLabel(row.verdict) }}
                    </el-tag>
                    <el-tag :type="getTrendReversalTagType(row)" size="small">
                      反转 {{ getTrendReversalLabel(row) }}
                    </el-tag>
                    <el-tag
                      v-if="row.exit_plan?.action || row.exit_plan?.action_label"
                      :type="getExitPlanActionType(row.exit_plan?.action)"
                      size="small"
                    >
                      {{ getExitPlanActionLabel(row.exit_plan) }}
                    </el-tag>
                  </div>
                  <div v-if="getMiddayPlanBrief(row) !== '-'" class="midday-mobile-plan">
                    {{ getMiddayPlanBrief(row) }}
                  </div>
                  <div class="midday-mobile-prices">
                    <span>开 {{ formatPlanPrice(row.open_price) }}</span>
                    <span>11:30 {{ formatPlanPrice(row.midday_price) }}</span>
                    <span>现 {{ formatPlanPrice(getMiddayLatestPrice(row)) }}</span>
                  </div>
                  <div class="midday-mobile-prices">
                    <span>热度 {{ formatActivePoolRank(row.active_pool_rank) }}</span>
                    <span>换手 {{ formatTurnoverRate(row.turnover_rate) }}</span>
                    <span>量比 {{ formatVolumeRatio(row.volume_ratio) }}</span>
                  </div>
                  <div v-if="getMiddayRelativeMarketBrief(row) !== '-'" class="midday-mobile-relative">
                    {{ getMiddayRelativeMarketBrief(row) }}
                  </div>
                  <div v-if="getMiddayPreviousAnalysisBrief(row) !== '-'" class="midday-mobile-prev">
                    {{ getMiddayPreviousAnalysisBrief(row) }}
                  </div>
                  <span class="mobile-analysis-item__comment">{{ getMiddayRowComment(row) }}</span>
                </div>
              </button>
            </div>
            <el-empty v-else description="暂无数据" :image-size="90">
              <div v-if="middayEmptyMessage" class="midday-empty-note">
                {{ middayEmptyMessage }}
              </div>
            </el-empty>
          </el-card>
        </div>

        <div v-else class="midday-layout">
          <el-card class="candidates-card midday-card" v-loading="loadingMidday">
            <template #header>
              <div class="card-header">
                <div class="title-section">
                  <span>中盘分析</span>
                  <el-tag size="small" type="warning" class="date-tag">
                    {{ middayTradeDateDisplay || '当前交易日' }}
                  </el-tag>
                </div>
                <div class="header-actions">
                  <el-radio-group
                    v-model="middaySource"
                    size="small"
                    class="source-switch"
                  >
                    <el-radio-button value="tomorrow-star">明日之星候选</el-radio-button>
                    <el-radio-button value="current-hot">当前热盘</el-radio-button>
                  </el-radio-group>
                  <el-tag
                    v-if="middayTaskRunning"
                    size="small"
                    type="warning"
                    effect="plain"
                  >
                    生成中
                  </el-tag>
                  <el-button
                    v-if="authStore.isAdmin"
                    size="small"
                    :loading="loadingMiddayAction"
                    @click="runMiddayAdminAction('prefetch')"
                  >
                    预下载
                  </el-button>
                  <el-button
                    v-if="authStore.isAdmin"
                    type="primary"
                    size="small"
                    :loading="loadingMiddayAction"
                    @click="runMiddayAdminAction('generate')"
                  >
                    手动生成
                  </el-button>
                  <el-button
                    v-if="authStore.isAdmin"
                    size="small"
                    :icon="Refresh"
                    :loading="loadingMidday || loadingMiddayAction"
                    @click="runMiddayAdminAction('refresh')"
                  >
                    刷新
                  </el-button>
                  <el-button
                    v-else
                    size="small"
                    :icon="Refresh"
                    :loading="loadingMidday"
                    @click="refreshMiddayView"
                  >
                    刷新
                  </el-button>
                </div>
              </div>
            </template>

            <div class="table-header-tip">
              <span class="tip-item">· 仅展示当前交易日盘中候选与评分结果</span>
              <span class="tip-item">· 管理员调试入口，生成后用于制定下午交易预案</span>
            </div>

            <div class="midday-meta">
              <el-tag size="small" effect="plain">数据源 {{ middaySourceLabel }}</el-tag>
              <el-tag size="small" effect="plain">交易日 {{ middayTradeDateDisplay || '-' }}</el-tag>
              <el-tag size="small" effect="plain">快照 {{ middaySnapshotTimeDisplay || '-' }}</el-tag>
              <el-tag size="small" effect="plain">候选日期 {{ middaySourcePickDateDisplay || '-' }}</el-tag>
            </div>

            <div v-if="middayMarketOverviewSummary" class="midday-market-overview">
              <div class="midday-market-overview__summary">{{ middayMarketOverviewSummary }}</div>
              <div class="midday-market-overview__items">
                <span
                  v-for="item in middayMarketOverviewItems"
                  :key="item.name"
                  class="midday-market-chip"
                >
                  {{ item.summary || item.name }}
                </span>
              </div>
            </div>

            <el-empty v-if="middayShowEmpty" description="暂无数据" :image-size="100">
              <div v-if="middayEmptyMessage" class="midday-empty-note">
                {{ middayEmptyMessage }}
              </div>
            </el-empty>
            <template v-else>
              <el-table
                :data="middayRows"
                stripe
                class="candidates-table midday-table"
                height="520"
                table-layout="auto"
                @sort-change="handleMiddaySortChange"
              >
                <el-table-column prop="code" label="代码" min-width="100" sortable="custom" />
                <el-table-column prop="name" label="名称" min-width="120" show-overflow-tooltip sortable="custom" />
                <el-table-column label="B1" min-width="100" align="center" prop="b1_passed" sortable="custom">
                  <template #default="{ row }">
                    <el-tag :type="getBooleanTagType(row.b1_passed)" size="small">
                      {{ getBooleanTagLabel(row.b1_passed) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="score" label="趋势启动分" min-width="110" align="right" sortable="custom">
                  <template #default="{ row }">
                    <el-tag :type="getMiddayTrendStartTagType(row)" size="small">
                      {{ formatMiddayTrendStartScore(row) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="signal_type" label="信号类型" min-width="120" align="center" sortable="custom">
                  <template #default="{ row }">
                    <el-tag :type="getSignalTypeTag(row.signal_type)" size="small">
                      {{ getSignalTypeLabel(row.signal_type) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="verdict" label="结论" min-width="100" align="center" sortable="custom">
                  <template #default="{ row }">
                    <el-tag :type="getVerdictTagType(row.verdict)" size="small">
                      {{ getVerdictLabel(row.verdict) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="趋势反转" min-width="110" align="center">
                  <template #default="{ row }">
                    <el-tag :type="getTrendReversalTagType(row)" size="small">
                      {{ getTrendReversalLabel(row) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="open_price" label="开盘价" min-width="100" align="right" sortable="custom">
                  <template #default="{ row }">
                    {{ formatPlanPrice(row.open_price) }}
                  </template>
                </el-table-column>
                <el-table-column prop="midday_price" label="11:30价" min-width="100" align="right" sortable="custom">
                  <template #default="{ row }">
                    {{ formatPlanPrice(row.midday_price) }}
                  </template>
                </el-table-column>
                <el-table-column prop="latest_price" label="当前价" min-width="100" align="right" sortable="custom">
                  <template #default="{ row }">
                    {{ formatPlanPrice(getMiddayLatestPrice(row)) }}
                  </template>
                </el-table-column>
                <el-table-column prop="change_pct" label="11:30涨跌" min-width="110" align="right" sortable="custom">
                  <template #default="{ row }">
                    <span :class="typeof row.change_pct === 'number' ? (row.change_pct > 0 ? 'text-up' : row.change_pct < 0 ? 'text-down' : '') : ''">
                      {{ typeof row.change_pct === 'number' ? `${row.change_pct.toFixed(2)}%` : '-' }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column prop="latest_change_pct" label="当前涨跌" min-width="110" align="right" sortable="custom">
                  <template #default="{ row }">
                    <span :class="typeof row.latest_change_pct === 'number' ? (row.latest_change_pct > 0 ? 'text-up' : row.latest_change_pct < 0 ? 'text-down' : '') : ''">
                      {{ typeof row.latest_change_pct === 'number' ? `${row.latest_change_pct.toFixed(2)}%` : '-' }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column prop="active_pool_rank" label="热度" min-width="80" align="center" sortable="custom">
                  <template #default="{ row }">
                    {{ formatActivePoolRank(row.active_pool_rank) }}
                  </template>
                </el-table-column>
                <el-table-column prop="turnover_rate" label="换手率" min-width="100" align="right" sortable="custom">
                  <template #default="{ row }">
                    {{ formatTurnoverRate(row.turnover_rate) }}
                  </template>
                </el-table-column>
                <el-table-column prop="volume_ratio" label="量比" min-width="90" align="right" sortable="custom">
                  <template #default="{ row }">
                    {{ formatVolumeRatio(row.volume_ratio) }}
                  </template>
                </el-table-column>
                <el-table-column label="大盘对照" min-width="170" show-overflow-tooltip prop="relative_market_strength_pct" sortable="custom">
                  <template #default="{ row }">
                    {{ getMiddayRelativeMarketBrief(row) }}
                  </template>
                </el-table-column>
                <el-table-column label="昨日结论" min-width="180" show-overflow-tooltip>
                  <template #default="{ row }">
                    {{ getMiddayPreviousAnalysisBrief(row) }}
                  </template>
                </el-table-column>
                <el-table-column label="上午走势状态" min-width="150" show-overflow-tooltip>
                  <template #default="{ row }">
                    {{ getMiddayMorningStateLabel(row) }}
                  </template>
                </el-table-column>
                <el-table-column label="持仓建议" min-width="190" show-overflow-tooltip>
                  <template #default="{ row }">
                    <div class="midday-plan-action">
                      <el-tag
                        v-if="row.exit_plan?.action || row.exit_plan?.action_label"
                        :type="getExitPlanActionType(row.exit_plan?.action)"
                        size="small"
                      >
                        {{ getExitPlanActionLabel(row.exit_plan) }}
                      </el-tag>
                      <span>{{ getMiddayAfternoonActionLabel(row) }}</span>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="执行参考" min-width="280" show-overflow-tooltip>
                  <template #default="{ row }">
                    {{ getMiddayPlanDetail(row) }}
                  </template>
                </el-table-column>
                <el-table-column label="基金经理视角补充" min-width="260" show-overflow-tooltip>
                  <template #default="{ row }">
                    {{ getMiddayManagerNote(row) }}
                  </template>
                </el-table-column>
                <el-table-column label="说明" min-width="220" show-overflow-tooltip>
                  <template #default="{ row }">
                    {{ getMiddayRowComment(row) }}
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="90" align="center" fixed="right">
                  <template #default="{ row }">
                    <el-button text type="primary" size="small" @click="viewStock(row.code, 'midday-analysis')">
                      详情
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
            </template>
          </el-card>
        </div>
      </el-tab-pane>

      <el-tab-pane label="收盘分析" name="closing-analysis">
        <div class="closing-layout">
          <el-card class="candidates-card closing-card" v-loading="loadingClosingReport">
            <template #header>
              <div class="card-header">
                <div class="title-section">
                  <span>收盘分析</span>
                  <el-tag size="small" type="info" class="date-tag">
                    {{ closingReport?.trade_date || '待生成' }}
                  </el-tag>
                </div>
                <div class="header-actions">
                  <el-button
                    size="small"
                    :icon="Refresh"
                    :loading="loadingClosingReport"
                    @click="loadClosingReport(true)"
                  >
                    刷新
                  </el-button>
                  <el-button
                    type="primary"
                    size="small"
                    :loading="generatingClosingReport"
                    @click="handleGenerateClosingReport"
                  >
                    {{ authStore.isAdmin && closingReport?.has_report ? '重新生成' : '生成报告' }}
                  </el-button>
                </div>
              </div>
            </template>

            <el-empty v-if="!closingReport?.has_report" description="暂无收盘分析" :image-size="100">
              <div class="midday-empty-note">
                {{ closingReport?.message || '点击生成后，会基于最新日线数据形成当日报告。' }}
              </div>
            </el-empty>

            <template v-else>
              <div class="table-header-tip">
                <span class="tip-item">· 普通用户每日只生成一份，已有报告会直接展示</span>
                <span class="tip-item">· 管理员重新生成前会二次确认并覆盖当日报告</span>
              </div>

              <div class="closing-summary-grid">
                <div class="closing-summary-card">
                  <span class="closing-summary-card__label">大盘走势</span>
                  <strong>{{ closingReport.market?.trend || '-' }}</strong>
                  <span>{{ closingReport.market?.summary || '-' }}</span>
                </div>
                <div class="closing-summary-card">
                  <span class="closing-summary-card__label">平均涨跌</span>
                  <strong :class="(closingReport.market?.avg_change_pct || 0) >= 0 ? 'text-up' : 'text-down'">
                    {{ formatClosingPct(closingReport.market?.avg_change_pct) }}
                  </strong>
                  <span>统计 {{ closingReport.market?.total_count || 0 }} 只股票</span>
                </div>
                <div class="closing-summary-card">
                  <span class="closing-summary-card__label">涨跌家数</span>
                  <strong>{{ closingReport.market?.up_count || 0 }} / {{ closingReport.market?.down_count || 0 }}</strong>
                  <span>上涨 / 下跌</span>
                </div>
              </div>

              <div class="closing-flow-grid">
                <el-table :data="closingReport.sector_flow?.inflow_top3 || []" stripe>
                  <el-table-column prop="sector_name" label="资金流入板块 TOP3" min-width="160" />
                  <el-table-column label="净流入" width="120" align="right">
                    <template #default="{ row }">
                      <span class="text-up">{{ formatClosingMoney(row.net_mf_amount) }}</span>
                    </template>
                  </el-table-column>
                </el-table>
                <el-table :data="closingReport.sector_flow?.outflow_top3 || []" stripe>
                  <el-table-column prop="sector_name" label="资金流出板块 TOP3" min-width="160" />
                  <el-table-column label="净流出" width="120" align="right">
                    <template #default="{ row }">
                      <span class="text-down">{{ formatClosingMoney(row.net_mf_amount) }}</span>
                    </template>
                  </el-table-column>
                </el-table>
              </div>

              <el-tabs
                v-if="closingReport.candidate_buckets.length > 0 || closingReport.tomorrow_prediction"
                v-model="closingActiveBucket"
                class="closing-candidate-tabs"
              >
                <el-tab-pane
                  v-for="bucket in closingReport.candidate_buckets"
                  :key="bucket.source_pick_date"
                  :label="getClosingBucketTitle(bucket)"
                  :name="bucket.source_pick_date"
                >
                  <div class="closing-candidate-grid">
                    <div>
                      <h4>明显上涨（≥ 5%）</h4>
                      <el-table :data="bucket.rising" stripe height="360">
                        <el-table-column prop="code" label="代码" min-width="100" />
                        <el-table-column prop="name" label="名称" min-width="120" show-overflow-tooltip />
                        <el-table-column label="板块" min-width="160" show-overflow-tooltip>
                          <template #default="{ row }">{{ getClosingSectorNames(row) }}</template>
                        </el-table-column>
                        <el-table-column label="候选日价" width="95" align="right">
                          <template #default="{ row }">{{ formatPlanPrice(row.base_close) }}</template>
                        </el-table-column>
                        <el-table-column label="收盘价" width="95" align="right">
                          <template #default="{ row }">{{ formatPlanPrice(row.latest_close) }}</template>
                        </el-table-column>
                        <el-table-column label="涨跌幅" width="100" align="right">
                          <template #default="{ row }"><span class="text-up">{{ formatClosingPct(row.change_pct) }}</span></template>
                        </el-table-column>
                      </el-table>
                    </div>
                    <div>
                      <h4>明显下跌（≤ -5%）</h4>
                      <el-table :data="bucket.falling" stripe height="360">
                        <el-table-column prop="code" label="代码" min-width="100" />
                        <el-table-column prop="name" label="名称" min-width="120" show-overflow-tooltip />
                        <el-table-column label="板块" min-width="160" show-overflow-tooltip>
                          <template #default="{ row }">{{ getClosingSectorNames(row) }}</template>
                        </el-table-column>
                        <el-table-column label="候选日价" width="95" align="right">
                          <template #default="{ row }">{{ formatPlanPrice(row.base_close) }}</template>
                        </el-table-column>
                        <el-table-column label="收盘价" width="95" align="right">
                          <template #default="{ row }">{{ formatPlanPrice(row.latest_close) }}</template>
                        </el-table-column>
                        <el-table-column label="涨跌幅" width="100" align="right">
                          <template #default="{ row }"><span class="text-down">{{ formatClosingPct(row.change_pct) }}</span></template>
                        </el-table-column>
                      </el-table>
                    </div>
                  </div>
                </el-tab-pane>
                <el-tab-pane label="明日预测" name="tomorrow-prediction">
                  <div class="closing-prediction-header">
                    <div>
                      <h4>明日预测 TOP10</h4>
                      <span>{{ closingReport.tomorrow_prediction?.message || '基于今日候选池、板块资金流、B1评分和AI消息面过滤。' }}</span>
                    </div>
                    <el-tag
                      size="small"
                      :type="closingReport.tomorrow_prediction?.status === 'ready' ? 'success' : 'warning'"
                      effect="plain"
                    >
                      {{ closingReport.tomorrow_prediction?.status === 'ready' ? 'AI已过滤' : '本地预筛' }}
                    </el-tag>
                  </div>
                  <el-table
                    :data="closingReport.tomorrow_prediction?.selected || []"
                    stripe
                    height="520"
                    table-layout="auto"
                    class="closing-prediction-table"
                  >
                    <el-table-column prop="rank" label="#" width="56" align="center" />
                    <el-table-column prop="code" label="代码" min-width="90" />
                    <el-table-column prop="name" label="名称" min-width="110" show-overflow-tooltip />
                    <el-table-column label="B1评价" min-width="180" show-overflow-tooltip>
                      <template #default="{ row }">{{ getClosingPredictionB1(row) }}</template>
                    </el-table-column>
                    <el-table-column label="所属板块" min-width="140" show-overflow-tooltip>
                      <template #default="{ row }">{{ getClosingSectorNames(row) }}</template>
                    </el-table-column>
                    <el-table-column label="收盘/涨跌" min-width="120" align="right">
                      <template #default="{ row }">
                        {{ formatPlanPrice(row.close_price) }}
                        <span :class="(row.change_pct || 0) >= 0 ? 'text-up' : 'text-down'">
                          {{ formatClosingPct(row.change_pct) }}
                        </span>
                      </template>
                    </el-table-column>
                    <el-table-column label="换手/量比" min-width="120" align="right">
                      <template #default="{ row }">
                        {{ formatTurnoverRate(row.turnover_rate) }} / {{ formatVolumeRatio(row.volume_ratio) }}
                      </template>
                    </el-table-column>
                    <el-table-column label="利好消息" min-width="240" show-overflow-tooltip>
                      <template #default="{ row }">{{ getClosingPredictionBullish(row) }}</template>
                    </el-table-column>
                    <el-table-column label="AI点评" min-width="280" show-overflow-tooltip>
                      <template #default="{ row }">{{ row.ai_comment || row.decision_reason || '-' }}</template>
                    </el-table-column>
                  </el-table>
                </el-tab-pane>
              </el-tabs>
              <el-empty v-else description="暂无前日候选回看数据" :image-size="80" />
            </template>
          </el-card>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 信号收益率分析弹窗 -->
    <el-dialog
      v-model="signalReturnDialogVisible"
      :title="signalReturnData ? `历史信号收益分析 (${signalReturnData.pick_date} - ${signalReturnData.signal_label})` : '历史信号收益分析'"
      width="min(1120px, calc(100vw - 24px))"
      :close-on-click-modal="true"
      :close-on-press-escape="true"
      class="signal-return-dialog"
    >
      <div v-loading="signalReturnLoading" class="signal-return-content">
        <div v-if="signalReturnError" class="error-message">
          {{ signalReturnError }}
        </div>
        <div v-else-if="signalReturnData && signalReturnData.stocks.length > 0" class="signal-return-body">
          <div class="signal-return-chart-panel">
            <div class="signal-return-chart-header">
              <div class="signal-return-chart-heading">
                <div class="signal-return-chart-title">
                  {{ signalReturnSelectedStock ? `${signalReturnSelectedStock.code} ${signalReturnSelectedStock.name || ''}` : '收益率对比' }}
                </div>
                <div class="signal-return-chart-subtitle">
                  {{ signalReturnChartSubtitle }}
                </div>
              </div>
              <div v-if="signalReturnData.stocks.length > 1" class="signal-return-selector">
                <button
                  v-for="item in signalReturnData.stocks"
                  :key="item.code"
                  type="button"
                  class="signal-return-selector__button"
                  :class="{ 'is-active': item.code === signalReturnSelectedCode }"
                  @click="selectSignalReturnStock(item.code)"
                >
                  <span class="selector-code">{{ item.code }}</span>
                  <span class="selector-name">{{ item.name || '未命名' }}</span>
                </button>
              </div>
            </div>

            <div v-if="signalReturnSelectedStock" class="signal-return-summary">
              <div class="signal-return-summary__item">
                <span class="summary-label">买入日</span>
                <span class="summary-value">{{ formatDateShort(signalReturnSelectedStock.buy_date) }}</span>
              </div>
              <div class="signal-return-summary__item">
                <span class="summary-label">买入价</span>
                <span class="summary-value">{{ formatPrice(signalReturnSelectedStock.buy_price) }}</span>
              </div>
              <div class="signal-return-summary__item">
                <span class="summary-label">当前收益</span>
                <span class="summary-value" :class="getReturnClass(signalReturnSelectedStock.current_return)">
                  {{ formatReturn(signalReturnSelectedStock.current_return) }}
                </span>
              </div>
              <div class="signal-return-summary__item">
                <span class="summary-label">对照基准</span>
                <span class="summary-value">
                  {{ signalReturnHasBenchmark ? signalReturnBenchmarkLabel : '暂未取到大A基准' }}
                </span>
              </div>
            </div>

            <div
              v-if="signalReturnSelectedStock && signalReturnSelectedStock.timeline.length > 0"
              ref="signalReturnChartRef"
              class="signal-return-chart"
            />
            <div v-else class="signal-return-chart-empty">
              暂无收益率曲线数据
            </div>

            <div
              v-if="signalReturnSelectedStock && signalReturnSelectedStock.events.length > 0"
              class="signal-return-events"
            >
              <div
                v-for="event in signalReturnSelectedStock.events"
                :key="`${signalReturnSelectedStock.code}-${event.key}-${event.trade_date}`"
                class="signal-return-event"
              >
                <span class="signal-return-event__label">{{ event.label }}</span>
                <span class="signal-return-event__date">{{ formatDateShort(event.trade_date) }}</span>
                <span class="signal-return-event__price">价 {{ formatPrice(event.price) }}</span>
                <span class="signal-return-event__return" :class="getReturnClass(event.return_pct)">
                  {{ formatReturn(event.return_pct) }}
                </span>
              </div>
            </div>
          </div>

          <div class="signal-return-table-wrap">
            <div class="signal-return-table-tip">
              <span>点击表格行切换上方曲线</span>
              <span v-if="signalReturnSelectedStock">
                当前查看：{{ signalReturnSelectedStock.code }} {{ signalReturnSelectedStock.name || '' }}
              </span>
            </div>

            <el-table
              :data="signalReturnData.stocks"
              stripe
              size="small"
              row-key="code"
              class="signal-return-table"
              :max-height="320"
              :row-class-name="getSignalReturnRowClassName"
              @row-click="handleSignalReturnRowClick"
            >
              <el-table-column prop="code" label="代码" width="88" align="center" />
              <el-table-column prop="name" label="名称" width="110" align="center" show-overflow-tooltip />
              <el-table-column prop="buy_price" label="买入价" width="78" align="right">
                <template #default="{ row }">
                  {{ row.buy_price ? row.buy_price.toFixed(2) : '-' }}
                </template>
              </el-table-column>
              <el-table-column label="5日" width="76" align="right">
                <template #default="{ row }">
                  <span :class="getReturnClass(row.day5_return)">
                    {{ formatReturn(row.day5_return) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="10日" width="76" align="right">
                <template #default="{ row }">
                  <span :class="getReturnClass(row.day10_return)">
                    {{ formatReturn(row.day10_return) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="15日" width="76" align="right">
                <template #default="{ row }">
                  <span :class="getReturnClass(row.day15_return)">
                    {{ formatReturn(row.day15_return) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="至今" width="76" align="right">
                <template #default="{ row }">
                  <span :class="getReturnClass(row.current_return)">
                    {{ formatReturn(row.current_return) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column header-align="center">
                <template #header>
                  <el-tooltip content="持有期间最高收益幅度（按最高价）" placement="top">
                    <span class="signal-return-header-help">Max收益</span>
                  </el-tooltip>
                </template>
                <el-table-column label="幅度" width="82" align="right">
                  <template #default="{ row }">
                    <span :class="getReturnClass(row.max_return)">
                      {{ formatReturn(row.max_return) }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="日期" width="72" align="center">
                  <template #default="{ row }">
                    {{ formatDateShort(row.max_return_date) }}
                  </template>
                </el-table-column>
              </el-table-column>
              <el-table-column header-align="center">
                <template #header>
                  <el-tooltip content="持有期间最大亏损幅度（按最低价）" placement="top">
                    <span class="signal-return-header-help">Max亏损</span>
                  </el-tooltip>
                </template>
                <el-table-column label="幅度" width="82" align="right">
                  <template #default="{ row }">
                    <el-tooltip content="持有期间曾出现的最大亏损幅度（按最低价计算）" placement="top">
                      <span :class="getReturnClass(row.max_loss)">
                        {{ formatReturn(row.max_loss) }}
                      </span>
                    </el-tooltip>
                  </template>
                </el-table-column>
                <el-table-column label="日期" width="72" align="center">
                  <template #default="{ row }">
                    {{ formatDateShort(row.max_loss_date) }}
                  </template>
                </el-table-column>
              </el-table-column>
              <el-table-column header-align="center">
                <template #header>
                  <el-tooltip content="买入后首次转为 Fail，按其下一交易日开盘卖出，相对买入价的幅度变化" placement="top">
                    <span class="signal-return-header-help">Fail信号首次出现时卖出</span>
                  </el-tooltip>
                </template>
                <el-table-column label="幅度" width="86" align="right">
                  <template #default="{ row }">
                    <el-tooltip content="转为 fail 次日开盘价卖出的收益" placement="top">
                      <span :class="getReturnClass(row.fail_return)">
                        {{ formatReturn(row.fail_return) }}
                      </span>
                    </el-tooltip>
                  </template>
                </el-table-column>
                <el-table-column label="日期" width="78" align="center">
                  <template #default="{ row }">
                    {{ formatDateShort(row.fail_sell_date) }}
                  </template>
                </el-table-column>
              </el-table-column>
            </el-table>
          </div>
        </div>
        <div v-else class="empty-message">
          暂无数据
        </div>
      </div>
      <template #footer>
        <div class="signal-return-footer">
          <el-button size="small" @click="closeSignalReturnDialog">关闭</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onActivated, onDeactivated, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, Loading, Search } from '@element-plus/icons-vue'
import { apiAnalysis, apiCustomConcepts, apiTasks, isRequestCanceled } from '@/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { ECharts } from 'echarts/core'
import type {
  Candidate,
  AnalysisResult,
  CurrentHotAnalysisResult,
  CurrentHotCandidate,
  IncrementalUpdateStatus,
  ExitPlan,
  IntradayAnalysisItem,
  IntradayMarketOverviewItem,
  IntradayAnalysisResponse,
  IntradayAnalysisStatusResponse,
  ClosingAnalysisReportResponse,
  ClosingCandidateMoveBucket,
  ClosingCandidateMoveItem,
  ClosingTomorrowPredictionItem,
  RiskRegimeSummary,
  TomorrowStarHistoryItem,
  TomorrowStarWindowStatusResponse,
  SignalReturnAnalysisResponse,
  CandidateConceptMatchItem,
  CandidateConceptMatchRequestItem,
  CandidateConceptMatchResponse,
} from '@/types'
import { useAuthStore } from '@/store/auth'
import { useConfigStore } from '@/store/config'
import { getUserSafeErrorMessage, isInitializationPendingError } from '@/utils/userFacingErrors'
import { buildSignalReturnChartOption, loadKLineChartRuntime } from '@/utils/klineChart'
import { mapWithConcurrency } from '@/utils/limitedConcurrency'
import { useResponsive } from '@/composables/useResponsive'
import {
  registerPoll,
  startPoll,
  stopPoll,
  unregisterPoll,
  activatePagePolls,
  deactivatePagePolls,
} from '@/composables/usePollingManager'

type DataTabKey = 'tomorrow-star' | 'current-hot'
type MiddaySourceKey = DataTabKey
type BoardFilter = 'all' | 'sci-tech' | 'others'
type CurrentHotRiskFilter = 'all' | 'risk-only'
type SortOrder = 'ascending' | 'descending' | null
type CandidateSortProp =
  | 'code'
  | 'name'
  | 'open_price'
  | 'close_price'
  | 'change_pct'
  | 'turnover_rate'
  | 'volume_ratio'
  | 'active_pool_rank'
  | 'kdj_j'
  | 'industry'
  | 'b1_passed'
  | 'signal_type'
  | 'total_score'
  | 'consecutive_days'
type CandidateSortState = {
  prop: CandidateSortProp | ''
  order: SortOrder
}
type MiddaySortProp =
  | 'code'
  | 'name'
  | 'open_price'
  | 'midday_price'
  | 'latest_price'
  | 'change_pct'
  | 'latest_change_pct'
  | 'turnover_rate'
  | 'volume_ratio'
  | 'active_pool_rank'
  | 'benchmark_change_pct'
  | 'relative_market_strength_pct'
  | 'score'
  | 'verdict'
  | 'signal_type'
  | 'b1_passed'
type MiddaySortState = {
  prop: MiddaySortProp | ''
  order: SortOrder
}
type AnalysisDisplayRow = Candidate | AnalysisResult | CurrentHotAnalysisResult | CurrentHotCandidate

const analysisTabs: Array<{ name: DataTabKey; label: string }> = [
  { name: 'tomorrow-star', label: '明日之星' },
  { name: 'current-hot', label: '当前热盘' },
]

const router = useRouter()
const authStore = useAuthStore()
const configStore = useConfigStore()
const { isMobile } = useResponsive()
const activeTab = ref('tomorrow-star')

let loadDataRequestId = 0
let candidatesRequestId = 0
let currentHotLoadDataRequestId = 0
let currentHotCandidatesRequestId = 0
const REFRESH_CHECK_INTERVAL_MS = 60_000
const TOMORROW_STAR_CACHE_KEY = 'stocktrade:tomorrow-star:cache:v13'
const TOMORROW_STAR_LEGACY_CACHE_KEYS = [
  'stocktrade:tomorrow-star:cache:v12',
  'stocktrade:tomorrow-star:cache:v11',
  'stocktrade:tomorrow-star:cache:v10',
]
const INCREMENTAL_POLL_INTERVAL_MS = 10_000
/** 增量更新轮询的 key（属于 tomorrow-star 页面） */
const INCREMENTAL_POLL_KEY = 'tomorrow-star:incremental'
const HISTORY_FALLBACK_CONCURRENCY = 2
const requestControllers = new Map<string, AbortController>()

const loading = ref(false)
const loadingLatest = ref(false)
const checkingFreshness = ref(false)
const currentHotLoading = ref(false)
const currentHotLoadingLatest = ref(false)
const loadingMidday = ref(false)
const loadingMiddayAction = ref(false)
const loadingClosingReport = ref(false)
const generatingClosingReport = ref(false)
const currentHotLoaded = ref(false)
const currentHotHydratedFromCache = ref(false)
const currentHotBoardFilter = ref<BoardFilter>('all')
const currentHotRiskFilter = ref<CurrentHotRiskFilter>('all')
const selectedTomorrowStarIndustries = ref<string[]>([])
const middaySource = ref<MiddaySourceKey>('tomorrow-star')

const middayStatus = ref<IntradayAnalysisStatusResponse>({
  has_data: false,
  window_open: false,
  status: 'not_ready',
  message: '',
})
const middayData = ref<IntradayAnalysisResponse>({
  has_data: false,
  window_open: false,
  status: 'not_ready',
  message: '',
  items: [],
  total: 0,
})
const middayLoaded = ref(false)
const middaySort = ref<MiddaySortState>({ prop: '', order: null })
const closingReportLoaded = ref(false)
const closingReport = ref<ClosingAnalysisReportResponse | null>(null)
const closingActiveBucket = ref('')

type HistoryRow = {
  date: string
  rawDate: string
  count: number | '-'
  pass: number | '-'
  b1PassCount: number | '-'
  consecutiveCandidateCount: number | '-'
  tomorrowStarCount: number | '-'
  status: 'pending' | 'running' | 'success' | 'failed' | 'missing' | 'market_regime_blocked'
  analysisCount: number | '-'
  errorMessage?: string | null
  isLatest?: boolean
  marketRegimeBlocked?: boolean
  marketRegimeInfo?: {
    passed?: boolean
    summary?: string | null
    details?: Array<string | {
      ts_code?: string | null
      name?: string | null
      passed?: boolean | null
      close?: number | null
      ema_fast?: number | null
      ema_slow?: number | null
      return_lookback?: number | null
    }> | null
  } | null
}

type HistoryLikeItem = {
  date?: string
  pick_date?: string
  count?: number
  pass?: number
  candidate_count?: number
  analysis_count?: number
  trend_start_count?: number
  b1_pass_count?: number
  consecutive_candidate_count?: number
  tomorrow_star_count?: number
  status?: string
  error_message?: string | null
  is_latest?: boolean
  market_regime_blocked?: boolean
  market_regime_info?: {
    passed?: boolean
    summary?: string | null
    details?: Array<string | {
      ts_code?: string | null
      name?: string | null
      passed?: boolean | null
      close?: number | null
      ema_fast?: number | null
      ema_slow?: number | null
      return_lookback?: number | null
    }> | null
  } | null
}

const historyData = ref<HistoryRow[]>([])
const selectedDate = ref<string | null>(null)
const latestDate = ref<string>('')
const latestDataDate = ref<string>('')
const lastHistorySignature = ref<string>('')
const lastRefreshCheckAt = ref<number>(0)
const hydratedFromCache = ref(false)
const freshnessVersion = ref<string>('')

// 历史记录分页（左侧）
const historyPage = ref(1)
const historyPageSize = computed(() => (isMobile.value ? 5 : 15))
const activeHistoryTableHeight = computed(() => (isMobile.value ? undefined : 620))
const activeCandidateTableHeight = computed(() => (isMobile.value ? undefined : 700))

// 信号收益率分析弹窗
const signalReturnDialogVisible = ref(false)
const signalReturnLoading = ref(false)
const signalReturnData = ref<SignalReturnAnalysisResponse | null>(null)
const signalReturnError = ref<string | null>(null)
const signalReturnSelectedCode = ref('')
const signalReturnChartRef = ref<HTMLElement | null>(null)
let signalReturnChartInstance: ECharts | null = null
const signalReturnSelectedStock = computed(() => {
  const stocks = signalReturnData.value?.stocks || []
  if (stocks.length === 0) return null
  return stocks.find((item) => item.code === signalReturnSelectedCode.value) || stocks[0]
})
const signalReturnHasBenchmark = computed(() => (
  signalReturnSelectedStock.value?.timeline?.some((item) => item.benchmark_return_pct != null) ?? false
))
const signalReturnBenchmarkLabel = computed(() => signalReturnData.value?.benchmark?.name || '大A基准')
const signalReturnChartSubtitle = computed(() => {
  const stock = signalReturnSelectedStock.value
  if (!stock) return '按交易日展示收益率变化'
  if (signalReturnHasBenchmark.value) {
    return `按交易日对比 ${stock.name || stock.code} 与 ${signalReturnBenchmarkLabel.value} 的收益率变化`
  }
  return `按交易日展示 ${stock.name || stock.code} 的收益率变化`
})

// 最新数据（右侧显示）
const latestCandidates = ref<Candidate[]>([])
const latestAnalysisResults = ref<AnalysisResult[]>([])
const latestCandidatePage = ref(1)
const candidatePageSize = 18
const candidateSort = ref<CandidateSortState>({ prop: '', order: null })

// 当前查看的日期（默认为最新）
const viewingDate = ref<string | null>(null)

// 按日期缓存的数据（避免重复请求）
const candidatesCache = ref<Map<string, { candidates: Candidate[], results: AnalysisResult[], timestamp: number }>>(new Map())
const CACHE_TTL_MS = 5 * 60 * 1000  // 缓存5分钟

const currentHotHistoryData = ref<HistoryRow[]>([])
const currentHotSelectedDate = ref<string | null>(null)
const currentHotLatestDate = ref<string>('')
const currentHotLatestDataDate = ref<string>('')
const currentHotLastHistorySignature = ref<string>('')
const currentHotHistoryPage = ref(1)
const currentHotLatestCandidates = ref<CurrentHotCandidate[]>([])
const currentHotAnalysisResults = ref<CurrentHotAnalysisResult[]>([])
const currentHotRiskRegime = ref<RiskRegimeSummary | null>(null)
const currentHotCandidatePage = ref(1)
const currentHotAnalysisPage = ref(1)
const currentHotCandidatePageSize = 18
const currentHotCandidateSort = ref<CandidateSortState>({ prop: '', order: null })
const currentHotViewingDate = ref<string | null>(null)
const currentHotCandidatesCache = ref<Map<string, { candidates: CurrentHotCandidate[], results: CurrentHotAnalysisResult[], riskRegime?: RiskRegimeSummary | null, timestamp: number }>>(new Map())
const candidateSortOrders: Array<Exclude<SortOrder, null>> = ['descending', 'ascending']
const candidateConceptQuery = ref('')
const candidateConceptLoading = ref(false)
const candidateConceptResult = ref<CandidateConceptMatchResponse | null>(null)
const candidateConceptLocalCache = ref<Map<string, CandidateConceptMatchResponse>>(new Map())
let candidateConceptRequestId = 0

type CandidateConceptSuggestion = {
  value: string
  label: string
}

// 增量更新状态
const incrementalUpdate = ref<IncrementalUpdateStatus>({
  status: 'idle',
  running: false,
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
})

const showCachedHint = computed(() => hydratedFromCache.value && !incrementalUpdate.value.running)
const showInitializationAlert = computed(() => authStore.isAdmin && configStore.tushareReady && !configStore.dataInitialized)
const showInitializationEmpty = computed(() => showInitializationAlert.value && historyData.value.length === 0 && latestCandidates.value.length === 0)
const currentHotShowInitializationEmpty = computed(() => showInitializationAlert.value && currentHotHistoryData.value.length === 0 && currentHotLatestCandidates.value.length === 0)
const canUseMiddayAnalysis = computed(() => authStore.isAuthenticated)
const middayMarketOverviewSummary = computed(() => middayData.value.market_overview?.summary || '暂无大盘中盘总览')
const middayMarketOverviewItems = computed<IntradayMarketOverviewItem[]>(() => middayData.value.market_overview?.items || [])
const middayRows = computed<IntradayAnalysisItem[]>(() => {
  const rows = [...(middayData.value.items || [])]
  if (!middaySort.value.prop || !middaySort.value.order) {
    return rows.sort(compareMiddayTrendStartRows)
  }
  return rows.sort((a, b) => compareMiddayRows(a, b, middaySort.value))
})
const middayCanViewData = computed(() => Boolean(middayData.value.has_data && middayRows.value.length > 0))
const middayShowEmpty = computed(() => !loadingMidday.value && !middayCanViewData.value)
const middayTaskRunning = computed(() => loadingMiddayAction.value)
const middaySourceLabel = computed(() => middaySource.value === 'current-hot' ? '当前热盘' : '明日之星候选')
const middayTradeDateDisplay = computed(() => formatDateString(middayData.value.trade_date || middayStatus.value.trade_date || ''))
const middaySnapshotTimeDisplay = computed(() => formatDateTime(middayData.value.snapshot_time || middayStatus.value.snapshot_time || ''))
const middaySourcePickDateDisplay = computed(() => formatDateString(middayData.value.source_pick_date || middayStatus.value.source_pick_date || ''))
const middayEmptyMessage = computed(() => middayData.value.message || middayStatus.value.message || '暂无数据')
const activeDataTab = computed<DataTabKey>(() => (activeTab.value === 'current-hot' ? 'current-hot' : 'tomorrow-star'))
const isCurrentHotTab = computed(() => activeDataTab.value === 'current-hot')
const activeShowInitializationEmpty = computed(() => (isCurrentHotTab.value ? currentHotShowInitializationEmpty.value : showInitializationEmpty.value))
const activeEmptyDescription = computed(() => (isCurrentHotTab.value ? '当前热盘尚无可用数据' : '明日之星尚无可用数据'))
const activeShowCachedHint = computed(() => (isCurrentHotTab.value ? currentHotHydratedFromCache.value : showCachedHint.value))
const activeLoadingLatest = computed(() => (isCurrentHotTab.value ? currentHotLoadingLatest.value : loadingLatest.value))
const activeCandidateLoading = computed(() => (
  isCurrentHotTab.value
    ? currentHotLoading.value || currentHotLoadingLatest.value
    // freshness 检查只做轻量后台探测，不再遮罩右侧内容
    : loading.value || loadingLatest.value
))
const activeCandidateTitle = computed(() => (
  isCurrentHotTab.value
    ? (currentHotRiskFilter.value === 'risk-only' ? '风险标的' : '热力股票池')
    : '候选股票'
))
const activeStockSource = computed<'tomorrow-star' | 'current-hot'>(() => (isCurrentHotTab.value ? 'current-hot' : 'tomorrow-star'))
const showBoardFilter = computed(() => isCurrentHotTab.value)
const showAnalysisComment = computed(() => !isCurrentHotTab.value)
const currentHotAnalysisByCode = computed(() => {
  const resultMap = new Map<string, CurrentHotAnalysisResult>()
  currentHotAnalysisResults.value.forEach((result) => {
    resultMap.set(result.code, result)
  })
  return resultMap
})
const tomorrowStarAnalysisByCode = computed(() => {
  const resultMap = new Map<string, AnalysisResult>()
  latestAnalysisResults.value.forEach((result) => {
    resultMap.set(result.code, result)
  })
  return resultMap
})

function mergeTomorrowStarCandidateAnalysis(candidate: Candidate): Candidate {
  const analysis = tomorrowStarAnalysisByCode.value.get(candidate.code)
  if (!analysis) return candidate
  return {
    ...candidate,
    name: candidate.name || analysis.name,
    b1_passed: candidate.b1_passed ?? (analysis.verdict === 'PASS'),
    turnover_rate: candidate.turnover_rate ?? analysis.turnover_rate,
    volume_ratio: candidate.volume_ratio ?? analysis.volume_ratio,
    active_pool_rank: candidate.active_pool_rank ?? analysis.active_pool_rank,
    verdict: candidate.verdict ?? analysis.verdict,
    total_score: candidate.total_score ?? analysis.total_score,
    signal_type: candidate.signal_type ?? analysis.signal_type,
    comment: candidate.comment ?? analysis.comment,
    tomorrow_star_pass: candidate.tomorrow_star_pass ?? analysis.tomorrow_star_pass,
    prefilter_passed: candidate.prefilter_passed ?? analysis.prefilter_passed,
    prefilter_summary: candidate.prefilter_summary ?? analysis.prefilter_summary,
    prefilter_blocked_by: candidate.prefilter_blocked_by ?? analysis.prefilter_blocked_by,
    pullback_quality: candidate.pullback_quality ?? analysis.pullback_quality,
    pullback_negative_flags: candidate.pullback_negative_flags ?? analysis.pullback_negative_flags,
  }
}

function mergeCurrentHotCandidateAnalysis(candidate: CurrentHotCandidate): CurrentHotCandidate {
  const analysis = currentHotAnalysisByCode.value.get(candidate.code)
  if (!analysis) return candidate
  return {
    ...candidate,
    b1_passed: candidate.b1_passed ?? analysis.b1_passed,
    turnover_rate: candidate.turnover_rate ?? analysis.turnover_rate,
    volume_ratio: candidate.volume_ratio ?? analysis.volume_ratio,
    active_pool_rank: candidate.active_pool_rank ?? analysis.active_pool_rank,
    verdict: candidate.verdict ?? analysis.verdict,
    total_score: candidate.total_score ?? analysis.total_score,
    signal_type: candidate.signal_type ?? analysis.signal_type,
    comment: candidate.comment ?? analysis.comment,
    sector_names: candidate.sector_names?.length ? candidate.sector_names : analysis.sector_names,
    board_group: candidate.board_group ?? analysis.board_group,
    prefilter_passed: candidate.prefilter_passed ?? analysis.prefilter_passed,
    prefilter_summary: candidate.prefilter_summary ?? analysis.prefilter_summary,
    prefilter_blocked_by: candidate.prefilter_blocked_by ?? analysis.prefilter_blocked_by,
    pullback_quality: candidate.pullback_quality ?? analysis.pullback_quality,
    pullback_negative_flags: candidate.pullback_negative_flags ?? analysis.pullback_negative_flags,
  }
}
const activeCandidateSortLabel = computed(() => {
  const state = isCurrentHotTab.value ? currentHotCandidateSort.value : candidateSort.value
  if (!state.prop || !state.order) return ''
  const labels: Record<CandidateSortProp, string> = {
    code: '代码',
    name: '名称',
    open_price: '开盘',
    close_price: '收盘',
    change_pct: '涨跌',
    turnover_rate: '换手',
    volume_ratio: '量比',
    active_pool_rank: '活跃排名',
    kdj_j: 'KDJ',
    industry: '板块',
    b1_passed: 'B1',
    signal_type: '信号',
    total_score: '评分',
    consecutive_days: '连续候选',
  }
  const direction = state.order === 'ascending' ? '从低到高' : '从高到低'
  if (state.prop === 'active_pool_rank') {
    return `${labels[state.prop]} ${state.order === 'ascending' ? '从低到高' : '从高到低'}`
  }
  const prefix = isCurrentHotTab.value ? '' : '星通过置顶，'
  return `${prefix}${labels[state.prop]} ${direction}`
})

// 历史记录分页数据
const totalHistoryCount = computed(() => historyData.value.length)
const historyPageCount = computed(() => Math.max(1, Math.ceil(totalHistoryCount.value / historyPageSize.value)))
const displayHistoryData = computed(() => {
  if (historyPage.value > historyPageCount.value) {
    historyPage.value = historyPageCount.value
  }
  const start = (historyPage.value - 1) * historyPageSize.value
  return historyData.value.slice(start, start + historyPageSize.value)
})

const totalCurrentHotHistoryCount = computed(() => currentHotHistoryData.value.length)
const currentHotHistoryPageCount = computed(() => Math.max(1, Math.ceil(totalCurrentHotHistoryCount.value / historyPageSize.value)))
const displayCurrentHotHistoryData = computed(() => {
  if (currentHotHistoryPage.value > currentHotHistoryPageCount.value) {
    currentHotHistoryPage.value = currentHotHistoryPageCount.value
  }
  const start = (currentHotHistoryPage.value - 1) * historyPageSize.value
  return currentHotHistoryData.value.slice(start, start + historyPageSize.value)
})

const tomorrowStarMergedCandidates = computed(() => latestCandidates.value.map(mergeTomorrowStarCandidateAnalysis))
const tomorrowStarIndustryOptions = computed(() => {
  const counts = new Map<string, number>()
  tomorrowStarMergedCandidates.value.forEach((candidate) => {
    getCandidateSectorNames(candidate, { prioritizeSelected: false }).forEach((sectorName) => {
      counts.set(sectorName, (counts.get(sectorName) || 0) + 1)
    })
  })

  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => (b.count - a.count) || a.name.localeCompare(b.name, 'zh-Hans-CN'))
})
const showTomorrowStarIndustryFilter = computed(() => !isCurrentHotTab.value && tomorrowStarIndustryOptions.value.length > 0)
const tomorrowStarFilteredCandidates = computed(() => {
  const selected = new Set(selectedTomorrowStarIndustries.value)
  if (selected.size === 0) return tomorrowStarMergedCandidates.value
  return tomorrowStarMergedCandidates.value.filter((candidate) => (
    getCandidateSectorNames(candidate, { prioritizeSelected: false }).some((sectorName) => selected.has(sectorName))
  ))
})
const candidateConceptMatchMap = computed(() => {
  const map = new Map<string, CandidateConceptMatchItem>()
  ;(candidateConceptResult.value?.matches || []).forEach((item) => {
    map.set(item.code, item)
  })
  return map
})
const activeConceptQuery = computed(() => candidateConceptQuery.value.trim())
const activeConceptFilterApplied = computed(() => Boolean(activeConceptQuery.value && candidateConceptResult.value))
const activeConceptFilterSummary = computed(() => {
  if (!activeConceptFilterApplied.value || !candidateConceptResult.value) return ''
  const sourceLabel = candidateConceptResult.value.source === 'stale_cache'
    ? '缓存更新中'
    : (candidateConceptResult.value.cache_hit ? '缓存' : 'AI')
  return `${candidateConceptResult.value.query} · 命中 ${candidateConceptResult.value.matched_count} 只 · ${sourceLabel}`
})
const tomorrowStarConceptFilteredCandidates = computed(() => {
  if (!activeConceptFilterApplied.value) return tomorrowStarFilteredCandidates.value
  return tomorrowStarFilteredCandidates.value.filter((candidate) => candidateConceptMatchMap.value.has(candidate.code))
})
const totalLatestCandidates = computed(() => tomorrowStarConceptFilteredCandidates.value.length)
const displayLatestCandidates = computed(() => {
  const pageCount = Math.max(1, Math.ceil(totalLatestCandidates.value / candidatePageSize))
  if (latestCandidatePage.value > pageCount) {
    latestCandidatePage.value = pageCount
  }
  const start = (latestCandidatePage.value - 1) * candidatePageSize
  const sorted = sortTomorrowStarCandidates(tomorrowStarConceptFilteredCandidates.value)
  return sorted.slice(start, start + candidatePageSize)
})

const currentHotBaseFilteredCandidates = computed(() => {
  return [...currentHotLatestCandidates.value]
    .map(mergeCurrentHotCandidateAnalysis)
    .filter((candidate) => matchesBoardFilter(candidate.code, currentHotBoardFilter.value))
    .filter((candidate) => currentHotRiskFilter.value === 'all' || isRiskCandidate(candidate))
})
const currentHotFilteredCandidates = computed(() => {
  const rows = activeConceptFilterApplied.value
    ? currentHotBaseFilteredCandidates.value.filter((candidate) => candidateConceptMatchMap.value.has(candidate.code))
    : currentHotBaseFilteredCandidates.value
  return [...rows].sort(compareCurrentHotCandidates)
})
const totalCurrentHotCandidates = computed(() => currentHotFilteredCandidates.value.length)
const displayCurrentHotLatestCandidates = computed(() => {
  const pageCount = Math.max(1, Math.ceil(totalCurrentHotCandidates.value / currentHotCandidatePageSize))
  if (currentHotCandidatePage.value > pageCount) {
    currentHotCandidatePage.value = pageCount
  }
  const start = (currentHotCandidatePage.value - 1) * currentHotCandidatePageSize
  return currentHotFilteredCandidates.value.slice(start, start + currentHotCandidatePageSize)
})
const activeConceptUniverseCandidates = computed(() => (
  isCurrentHotTab.value
    ? currentHotLatestCandidates.value.map(mergeCurrentHotCandidateAnalysis)
    : tomorrowStarMergedCandidates.value
))
const activeConceptUniverseSignature = computed(() => (
  activeConceptUniverseCandidates.value
    .map((candidate) => `${candidate.code}:${candidate.signal_type || ''}:${typeof candidate.total_score === 'number' ? candidate.total_score : ''}`)
    .sort()
    .join('|')
))

// 当前查看的日期显示
const viewingDateDisplay = computed(() => {
  if (viewingDate.value) {
    return formatDateString(viewingDate.value)
  }
  return latestDate.value ? formatDateString(latestDate.value) : ''
})

const currentHotViewingDateDisplay = computed(() => {
  if (currentHotViewingDate.value) {
    return formatDateString(currentHotViewingDate.value)
  }
  return currentHotLatestDate.value ? formatDateString(currentHotLatestDate.value) : ''
})

function getCandidateDefaultSort(a: Candidate, b: Candidate): number {
  const consecutiveDiff = (b.consecutive_days || 1) - (a.consecutive_days || 1)
  if (consecutiveDiff !== 0) return consecutiveDiff
  const aKdj = toFiniteNumber(a.kdj_j) ?? Number.POSITIVE_INFINITY
  const bKdj = toFiniteNumber(b.kdj_j) ?? Number.POSITIVE_INFINITY
  if (aKdj !== bKdj) return aKdj - bKdj
  return a.code.localeCompare(b.code)
}

function getCurrentHotDefaultSort(a: CurrentHotCandidate, b: CurrentHotCandidate): number {
  const signalDiff = getSignalPriority(a.signal_type ?? undefined) - getSignalPriority(b.signal_type ?? undefined)
  if (signalDiff !== 0) return signalDiff

  const b1Diff = getB1PassPriority(a.b1_passed) - getB1PassPriority(b.b1_passed)
  if (b1Diff !== 0) return b1Diff

  const scoreDiff = getScoreSortValue(a.total_score ?? undefined) - getScoreSortValue(b.total_score ?? undefined)
  if (scoreDiff !== 0) return scoreDiff

  return a.code.localeCompare(b.code)
}

function getCandidateSortState(): CandidateSortState {
  return isCurrentHotTab.value ? currentHotCandidateSort.value : candidateSort.value
}

function getCandidateSortableValue(row: Candidate | CurrentHotCandidate, prop: CandidateSortProp): number | string | boolean | null {
  if (prop === 'code') return row.code
  if (prop === 'name') return row.name || ''
  if (prop === 'industry') return 'industry' in row ? getCandidateIndustryLabel(row as Candidate) : ''
  if (prop === 'b1_passed') return row.b1_passed ?? null
  if (prop === 'signal_type' && 'signal_type' in row) return getSignalSortableValue(row.signal_type)
  if (prop === 'total_score' && 'total_score' in row) return toFiniteNumber(row.total_score)
  if (prop === 'consecutive_days') {
    return 'consecutive_days' in row ? toFiniteNumber(row.consecutive_days) ?? 1 : null
  }
  if (prop === 'active_pool_rank' && 'active_pool_rank' in row) {
    const rank = toFiniteNumber(row.active_pool_rank)
    return rank === null ? null : -rank
  }
  return toFiniteNumber(row[prop as keyof (Candidate | CurrentHotCandidate)] as number | string | null | undefined)
}

function compareNullableValues(
  aValue: number | string | boolean | null,
  bValue: number | string | boolean | null,
  order: Exclude<SortOrder, null>,
): number {
  const direction = order === 'ascending' ? 1 : -1
  const aMissing = aValue === null || aValue === ''
  const bMissing = bValue === null || bValue === ''
  if (aMissing || bMissing) {
    if (aMissing && bMissing) return 0
    return aMissing ? 1 : -1
  }

  if (typeof aValue === 'string' || typeof bValue === 'string') {
    return String(aValue).localeCompare(String(bValue), 'zh-Hans-CN') * direction
  }

  if (typeof aValue === 'boolean' || typeof bValue === 'boolean') {
    const diff = (aValue === true ? 1 : 0) - (bValue === true ? 1 : 0)
    return diff * direction
  }

  const numericDiff = Number(aValue) - Number(bValue)
  if (numericDiff === 0) return 0
  return numericDiff * direction
}

function compareByCandidateSort(
  a: Candidate | CurrentHotCandidate,
  b: Candidate | CurrentHotCandidate,
  fallback: () => number,
): number {
  const sortState = getCandidateSortState()
  if (!sortState.prop || !sortState.order) {
    if (activeConceptFilterApplied.value) {
      const aRelevance = getCandidateConceptRelevanceValue(a.code) ?? -1
      const bRelevance = getCandidateConceptRelevanceValue(b.code) ?? -1
      if (aRelevance !== bRelevance) return bRelevance - aRelevance
    }
    return fallback()
  }

  const diff = compareNullableValues(
    getCandidateSortableValue(a, sortState.prop),
    getCandidateSortableValue(b, sortState.prop),
    sortState.order,
  )
  return diff !== 0 ? diff : fallback()
}

function sortTomorrowStarCandidates(rows: Candidate[]): Candidate[] {
  return [...rows].sort((a, b) => {
    const starDiff = getTomorrowStarPassPriority(a.tomorrow_star_pass) - getTomorrowStarPassPriority(b.tomorrow_star_pass)
    if (starDiff !== 0) return starDiff
    return compareByCandidateSort(a, b, () => getCandidateDefaultSort(a, b))
  })
}

type CandidateSectorLike = Pick<Candidate, 'industry' | 'sector_names'>

function getCandidateSectorNames(
  candidate: CandidateSectorLike,
  options: { prioritizeSelected?: boolean } = {},
): string[] {
  const normalizedNames = Array.isArray(candidate.sector_names)
    ? candidate.sector_names
      .map((item) => String(item || '').trim())
      .filter((item) => item.length > 0)
    : []
  const uniqueNames = normalizedNames.filter((item, index) => normalizedNames.indexOf(item) === index)

  if (uniqueNames.length === 0) {
    const industry = typeof candidate.industry === 'string' ? candidate.industry.trim() : ''
    return industry ? [industry] : []
  }

  if (!options.prioritizeSelected || selectedTomorrowStarIndustries.value.length === 0 || uniqueNames.length < 2) {
    return uniqueNames
  }

  const selectedOrder = new Map(
    selectedTomorrowStarIndustries.value.map((item, index) => [item, index] as const)
  )

  return [...uniqueNames].sort((a, b) => {
    const aOrder = selectedOrder.get(a)
    const bOrder = selectedOrder.get(b)
    if (aOrder !== undefined && bOrder !== undefined) return aOrder - bOrder
    if (aOrder !== undefined) return -1
    if (bOrder !== undefined) return 1
    return uniqueNames.indexOf(a) - uniqueNames.indexOf(b)
  })
}

function getCandidateIndustryLabel(candidate: CandidateSectorLike): string {
  const sectorNames = getCandidateSectorNames(candidate, { prioritizeSelected: true })
  return sectorNames.length > 0 ? sectorNames.join(' / ') : '-'
}

function toggleTomorrowStarIndustry(industry: string) {
  const value = industry.trim()
  if (!value) return
  const current = selectedTomorrowStarIndustries.value
  selectedTomorrowStarIndustries.value = current.includes(value)
    ? current.filter((item) => item !== value)
    : [...current, value]
  latestCandidatePage.value = 1
  persistTomorrowStarCache()
}

function clearTomorrowStarIndustryFilter() {
  selectedTomorrowStarIndustries.value = []
  latestCandidatePage.value = 1
  persistTomorrowStarCache()
}

function getCandidateConceptMatch(code: string): CandidateConceptMatchItem | null {
  return candidateConceptMatchMap.value.get(code) || null
}

function formatCandidateConceptRelevance(code: string): string {
  const match = getCandidateConceptMatch(code)
  if (!match || typeof match.relevance_score !== 'number') return '-'
  return `${Math.round(match.relevance_score)}`
}

function getCandidateConceptRelevanceValue(code: string): number | null {
  const match = getCandidateConceptMatch(code)
  return typeof match?.relevance_score === 'number' ? match.relevance_score : null
}

function getCandidateConceptReason(code: string): string {
  const match = getCandidateConceptMatch(code)
  if (!match) return ''
  const roleText = Array.isArray(match.role_tags) && match.role_tags.length > 0 ? `角色:${match.role_tags.join('/')}` : ''
  const chainText = match.chain_position ? `位置:${match.chain_position}` : ''
  return [roleText, chainText, match.reason].filter((item) => typeof item === 'string' && item.trim()).join(' | ')
}

async function fetchCandidateConceptSuggestions(
  query: string,
  callback: (items: CandidateConceptSuggestion[]) => void,
) {
  try {
    const response = await apiCustomConcepts.suggestQueries(query.trim(), 10)
    callback((response.items || []).map((item) => ({
      value: item.query,
      label: item.label && item.label !== item.query ? `${item.source} · ${item.label}` : item.source,
    })))
  } catch (error) {
    console.error('Failed to load concept query suggestions:', error)
    callback([])
  }
}

function buildCandidateConceptCacheKey(query: string, items: CandidateConceptMatchRequestItem[]): string {
  const normalizedQuery = query.trim().toLowerCase()
  const codes = items.map((item) => item.code).sort().join(',')
  return `${activeDataTab.value}:${activeViewingDateDisplay.value}:${normalizedQuery}:${codes}`
}

function isSameOrAfterDate(value?: string | null, targetDate?: string | null): boolean {
  if (!value) return false
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return false
  if (!targetDate) return false
  const target = new Date(`${targetDate}T00:00:00`)
  if (Number.isNaN(target.getTime())) return false
  return formatDate(date) >= formatDate(target)
}

function isFreshCandidateConceptResult(result: CandidateConceptMatchResponse): boolean {
  return result.source !== 'stale_cache' && isSameOrAfterDate(result.data_updated_at, activeLatestDate.value)
}

function buildCandidateConceptPayloadItems(): CandidateConceptMatchRequestItem[] {
  return activeConceptUniverseCandidates.value.map((candidate) => ({
    code: candidate.code,
    name: candidate.name || null,
    industry: 'industry' in candidate ? candidate.industry || null : null,
    sector_names: getCandidateSectorNames(candidate, { prioritizeSelected: false }),
    signal_type: candidate.signal_type || null,
    total_score: typeof candidate.total_score === 'number' ? candidate.total_score : null,
    comment: candidate.comment || null,
  }))
}

async function applyCandidateConceptFilter(forceRefresh: boolean = false, asyncRefresh: boolean = false) {
  const query = candidateConceptQuery.value.trim()
  if (!query) {
    candidateConceptResult.value = null
    latestCandidatePage.value = 1
    currentHotCandidatePage.value = 1
    return
  }

  const payloadItems = buildCandidateConceptPayloadItems()
  if (payloadItems.length === 0) {
    ElMessage.warning('当前没有可供检索的候选股票')
    return
  }

  const cacheKey = buildCandidateConceptCacheKey(query, payloadItems)
  if (!forceRefresh) {
    const cached = candidateConceptLocalCache.value.get(cacheKey)
    if (cached && isFreshCandidateConceptResult(cached)) {
      candidateConceptResult.value = cached
      latestCandidatePage.value = 1
      currentHotCandidatePage.value = 1
      return
    } else if (cached) {
      candidateConceptLocalCache.value.delete(cacheKey)
    }
  }

  const requestId = ++candidateConceptRequestId
  candidateConceptLoading.value = true
  try {
    const response = await apiCustomConcepts.matchCandidates(query, payloadItems, forceRefresh, asyncRefresh)
    if (requestId !== candidateConceptRequestId) return
    if (isFreshCandidateConceptResult(response)) {
      candidateConceptLocalCache.value.set(cacheKey, response)
    }
    candidateConceptResult.value = response
    if (response.refresh_scheduled) {
      ElMessage.info('请耐心等待，大约需要1分钟后，用原始问题再次查询。')
    }
    latestCandidatePage.value = 1
    currentHotCandidatePage.value = 1
  } catch (error) {
    if (requestId !== candidateConceptRequestId) return
    ElMessage.error(getUserSafeErrorMessage(error, '候选相关性过滤失败'))
  } finally {
    if (requestId === candidateConceptRequestId) {
      candidateConceptLoading.value = false
    }
  }
}

async function refreshCandidateConceptAsync() {
  await applyCandidateConceptFilter(false, true)
}

function clearCandidateConceptFilter() {
  candidateConceptQuery.value = ''
  candidateConceptResult.value = null
  latestCandidatePage.value = 1
  currentHotCandidatePage.value = 1
}

function compareCurrentHotCandidates(a: CurrentHotCandidate, b: CurrentHotCandidate): number {
  return compareByCandidateSort(a, b, () => getCurrentHotDefaultSort(a, b))
}

function handleCandidateSortChange({ prop, order }: { prop: string, order: SortOrder }) {
  const nextState: CandidateSortState = {
    prop: (prop || '') as CandidateSortProp | '',
    order,
  }
  if (isCurrentHotTab.value) {
    currentHotCandidateSort.value = nextState
    currentHotCandidatePage.value = 1
    return
  }
  candidateSort.value = nextState
  latestCandidatePage.value = 1
}

function normalizeCandidateSortState(value: unknown): CandidateSortState {
  if (!value || typeof value !== 'object') return { prop: '', order: null }
  const item = value as Partial<CandidateSortState>
  const validProps: CandidateSortProp[] = [
    'code',
    'name',
    'open_price',
    'close_price',
    'change_pct',
    'turnover_rate',
    'volume_ratio',
    'active_pool_rank',
    'kdj_j',
    'industry',
    'b1_passed',
    'signal_type',
    'total_score',
    'consecutive_days',
  ]
  const prop = validProps.includes(item.prop as CandidateSortProp) ? item.prop as CandidateSortProp : ''
  const order = item.order === 'ascending' || item.order === 'descending' ? item.order : null
  return { prop, order }
}

function getSignalPriority(signalType?: string): number {
  return signalType === 'trend_start' ? 0 : 1
}

function getSignalSortableValue(signalType?: string | null): number {
  const value = getSignalPriority(signalType ?? undefined)
  return signalType ? value : 99
}

function getB1PassPriority(pass?: boolean | null): number {
  if (pass === true) return 0
  if (pass === false) return 1
  return 2
}

function getTomorrowStarPassPriority(pass?: boolean | null): number {
  if (pass === true) return 0
  if (pass === false) return 1
  return 2
}

function getScoreSortValue(score?: number): number {
  return typeof score === 'number' ? -score : 9999
}

function compareTomorrowStarAnalysisResults(
  a: { tomorrow_star_pass?: boolean | null, signal_type?: string, total_score?: number, code: string },
  b: { tomorrow_star_pass?: boolean | null, signal_type?: string, total_score?: number, code: string },
): number {
  const tomorrowStarDiff = getTomorrowStarPassPriority(a.tomorrow_star_pass) - getTomorrowStarPassPriority(b.tomorrow_star_pass)
  if (tomorrowStarDiff !== 0) return tomorrowStarDiff

  const signalDiff = getSignalPriority(a.signal_type) - getSignalPriority(b.signal_type)
  if (signalDiff !== 0) return signalDiff

  const scoreDiff = getScoreSortValue(a.total_score) - getScoreSortValue(b.total_score)
  if (scoreDiff !== 0) return scoreDiff

  return a.code.localeCompare(b.code)
}

const topAnalysisResults = computed(() => {
  const rows = activeConceptFilterApplied.value
    ? latestAnalysisResults.value.filter((result) => candidateConceptMatchMap.value.has(result.code))
    : latestAnalysisResults.value
  return [...rows]
    .sort(compareTomorrowStarAnalysisResults)
    .slice(0, 5)
})

const mobileTomorrowStarSearchApplied = computed(() => !isCurrentHotTab.value && activeConceptFilterApplied.value)
const showActiveAnalysisPagination = computed(() => (
  isCurrentHotTab.value
    ? totalCurrentHotCandidates.value > currentHotCandidatePageSize
    : (mobileTomorrowStarSearchApplied.value && totalLatestCandidates.value > candidatePageSize)
))
const activeMobileAnalysisRows = computed(() => {
  if (isCurrentHotTab.value) {
    return displayCurrentHotLatestCandidates.value
  }
  return mobileTomorrowStarSearchApplied.value ? displayLatestCandidates.value : topAnalysisResults.value
})
const activeMobileAnalysisTitle = computed(() => (
  isCurrentHotTab.value
    ? (currentHotRiskFilter.value === 'risk-only' ? '风险标的' : '热力股票池')
    : (mobileTomorrowStarSearchApplied.value ? '检索结果' : '分析结果 Top 5')
))
const activeMobileAnalysisTip = computed(() => (
  isCurrentHotTab.value
    ? '· 已合并评分与信号，默认按趋势启动、B1通过、评分排序'
    : (mobileTomorrowStarSearchApplied.value ? '· 展示当前检索命中的候选股票' : '· 仅展示评分最高的 5 只股票')
))
const activeMobileAnalysisEmptyDescription = computed(() => (
  isCurrentHotTab.value
    ? (currentHotRiskFilter.value === 'risk-only' ? '暂无风险标的' : '暂无热力股票池')
    : (mobileTomorrowStarSearchApplied.value ? '暂无检索结果' : '暂无 Top 5 分析结果')
))
const activeMobileAnalysisPage = computed({
  get: () => (
    isCurrentHotTab.value
      ? currentHotCandidatePage.value
      : (mobileTomorrowStarSearchApplied.value ? latestCandidatePage.value : 1)
  ),
  set: (value: number) => {
    if (isCurrentHotTab.value) {
      currentHotCandidatePage.value = value
      return
    }
    if (mobileTomorrowStarSearchApplied.value) {
      latestCandidatePage.value = value
    }
  },
})
const activeMobileAnalysisPageSize = computed(() => (
  isCurrentHotTab.value
    ? currentHotCandidatePageSize
    : (mobileTomorrowStarSearchApplied.value ? candidatePageSize : topAnalysisResults.value.length || 5)
))
const activeMobileAnalysisPageCount = computed(() => (
  isCurrentHotTab.value
    ? Math.max(1, Math.ceil(totalCurrentHotCandidates.value / currentHotCandidatePageSize))
    : (mobileTomorrowStarSearchApplied.value ? Math.max(1, Math.ceil(totalLatestCandidates.value / candidatePageSize)) : 1)
))
const activeMobileAnalysisTotal = computed(() => (
  isCurrentHotTab.value
    ? totalCurrentHotCandidates.value
    : (mobileTomorrowStarSearchApplied.value ? totalLatestCandidates.value : topAnalysisResults.value.length)
))
const activeDisplayHistoryData = computed(() => (isCurrentHotTab.value ? displayCurrentHotHistoryData.value : displayHistoryData.value))
const showAnalysisPrefilter = computed(() => !isCurrentHotTab.value)
const activeSelectedDate = computed(() => (isCurrentHotTab.value ? currentHotSelectedDate.value : selectedDate.value))
const activeLatestDate = computed(() => (isCurrentHotTab.value ? currentHotLatestDate.value : latestDate.value))
const activeViewingDateDisplay = computed(() => (isCurrentHotTab.value ? currentHotViewingDateDisplay.value : viewingDateDisplay.value))
const activeDisplayLatestCandidates = computed(() => (isCurrentHotTab.value ? displayCurrentHotLatestCandidates.value : displayLatestCandidates.value))
const activeTotalLatestCandidates = computed(() => (isCurrentHotTab.value ? totalCurrentHotCandidates.value : totalLatestCandidates.value))
const activeCandidatePageSize = computed(() => (isCurrentHotTab.value ? currentHotCandidatePageSize : candidatePageSize))
const activeHistoryPageSize = computed(() => historyPageSize.value)
const activeTotalHistoryCount = computed(() => (isCurrentHotTab.value ? totalCurrentHotHistoryCount.value : totalHistoryCount.value))
const activeHistoryPageCount = computed(() => (isCurrentHotTab.value ? currentHotHistoryPageCount.value : historyPageCount.value))
const activeHistoryPage = computed({
  get: () => (isCurrentHotTab.value ? currentHotHistoryPage.value : historyPage.value),
  set: (value: number) => {
    if (isCurrentHotTab.value) {
      currentHotHistoryPage.value = value
      return
    }
    historyPage.value = value
  },
})
const activeCandidatePage = computed({
  get: () => (isCurrentHotTab.value ? currentHotCandidatePage.value : latestCandidatePage.value),
  set: (value: number) => {
    if (isCurrentHotTab.value) {
      currentHotCandidatePage.value = value
      return
    }
    latestCandidatePage.value = value
  },
})
const activeTomorrowStarHistoryRow = computed(() => {
  if (isCurrentHotTab.value) return null
  const targetDate = viewingDate.value || selectedDate.value || latestDate.value
  if (!targetDate) return null
  return historyData.value.find((item) => item.rawDate === targetDate) || null
})
const showTomorrowStarMarketRegimeNotice = computed(() => {
  const row = activeTomorrowStarHistoryRow.value
  return Boolean(
    row
    && row.marketRegimeBlocked
    && latestCandidates.value.length === 0
    && latestAnalysisResults.value.length === 0
  )
})
const activeMarketRegimeSummary = computed(() => {
  const summary = activeTomorrowStarHistoryRow.value?.marketRegimeInfo?.summary?.trim()
  return summary || '当前整体市场环境未达到策略要求，因此本日不展示候选股票。'
})
const activeMarketRegimeDetails = computed(() => {
  const details = activeTomorrowStarHistoryRow.value?.marketRegimeInfo?.details
  if (!Array.isArray(details)) return []
  return details
    .map((item) => {
      if (typeof item === 'string') {
        return item.trim()
      }
      if (!item || typeof item !== 'object') {
        return ''
      }

      const name = String(item.name || item.ts_code || '市场指标').trim()
      const reasons: string[] = []
      if (typeof item.close === 'number' && typeof item.ema_fast === 'number' && item.close <= item.ema_fast) {
        reasons.push(`收盘点位 ${item.close.toFixed(2)} 低于短期均线 ${item.ema_fast.toFixed(2)}`)
      }
      if (typeof item.ema_fast === 'number' && typeof item.ema_slow === 'number' && item.ema_fast <= item.ema_slow) {
        reasons.push(`短期均线 ${item.ema_fast.toFixed(2)} 未站上长期均线 ${item.ema_slow.toFixed(2)}`)
      }
      if (typeof item.return_lookback === 'number' && item.return_lookback <= 0) {
        reasons.push(`近 20 日收益率 ${(item.return_lookback * 100).toFixed(2)}% 未转正`)
      }
      return reasons.length > 0 ? `${name}：${reasons.join('；')}` : `${name} 未满足市场环境要求`
    })
    .filter(Boolean)
})

function beginRequest(key: string): AbortSignal {
  requestControllers.get(key)?.abort()
  const controller = new AbortController()
  requestControllers.set(key, controller)
  return controller.signal
}

function finishRequest(key: string, signal?: AbortSignal) {
  const controller = requestControllers.get(key)
  if (controller && (!signal || controller.signal === signal)) {
    requestControllers.delete(key)
  }
}

function cancelAllPageRequests() {
  requestControllers.forEach((controller) => controller.abort())
  requestControllers.clear()
}

function isSciTechBoardCode(code?: string | null): boolean {
  return /^688\d{3}$/.test(String(code || ''))
}

function matchesBoardFilter(code: string, filter: BoardFilter): boolean {
  if (filter === 'all') return true
  const isSciTechBoard = isSciTechBoardCode(code)
  return filter === 'sci-tech' ? isSciTechBoard : !isSciTechBoard
}

function normalizeHistoryStatus(status?: string | null): HistoryRow['status'] {
  const value = String(status || '').toLowerCase()
  if (value === 'market_regime_blocked') return 'market_regime_blocked'
  if (value === 'success' || value === 'completed' || value === 'done') return 'success'
  if (value === 'running' || value === 'processing' || value === 'in_progress') return 'running'
  if (value === 'failed' || value === 'error') return 'failed'
  if (value === 'pending' || value === 'queued') return 'pending'
  return 'missing'
}

function getHistoryCount(item: HistoryLikeItem): number | '-' {
  if (typeof item.count === 'number') return item.count
  if (typeof item.candidate_count === 'number') return item.candidate_count
  return '-'
}

function getHistoryPassCount(item: HistoryLikeItem): number | '-' {
  if (typeof item.pass === 'number') return item.pass
  if (typeof item.trend_start_count === 'number') return item.trend_start_count
  return '-'
}

function getHistoryB1PassCount(item: HistoryLikeItem): number | '-' {
  if (typeof item.b1_pass_count === 'number') return item.b1_pass_count
  return '-'
}

function getHistoryTomorrowStarCount(item: HistoryLikeItem): number | '-' {
  if (typeof item.tomorrow_star_count === 'number') return item.tomorrow_star_count
  return '-'
}

function normalizeHistoryRow(
  item: HistoryLikeItem,
  fallbackLatestDate: string,
): HistoryRow | null {
  const rawDate = formatDateString(item.date || item.pick_date || '')
  if (!rawDate) return null

  const count = getHistoryCount(item)
  const pass = getHistoryPassCount(item)
  const b1PassCount = getHistoryB1PassCount(item)
  const consecutiveCandidateCount = typeof item.consecutive_candidate_count === 'number' ? item.consecutive_candidate_count : '-'
  const tomorrowStarCount = getHistoryTomorrowStarCount(item)
  const analysisCount = typeof item.analysis_count === 'number' ? item.analysis_count : '-'
  const inferredStatus =
    item.status
    || (
      count !== '-'
      || pass !== '-'
      || analysisCount !== '-'
        ? 'success'
        : 'missing'
    )

  return {
    date: rawDate,
    rawDate,
    count,
    pass,
    b1PassCount,
    consecutiveCandidateCount,
    tomorrowStarCount,
    status: normalizeHistoryStatus(inferredStatus),
    analysisCount,
    errorMessage: item.error_message || null,
    isLatest: Boolean(item.is_latest || (fallbackLatestDate && rawDate === fallbackLatestDate)),
    marketRegimeBlocked: Boolean(item.market_regime_blocked),
    marketRegimeInfo: item.market_regime_info || null,
  }
}

function normalizeHistoryRows(
  dates: string[],
  history: TomorrowStarHistoryItem[],
  windowStatus?: TomorrowStarWindowStatusResponse | null,
): HistoryRow[] {
  const latest = formatDateString(windowStatus?.latest_date || dates[0] || '')
  const normalizedMap = new Map<string, HistoryRow>()

  const statusItems = [
    ...(windowStatus?.items || []),
    ...(windowStatus?.history || []),
    ...(windowStatus?.runs || []),
  ]

  statusItems.forEach((item) => {
    const row = normalizeHistoryRow(item, latest)
    if (row) normalizedMap.set(row.rawDate, row)
  })

  history.forEach((item) => {
    const row = normalizeHistoryRow(item, latest)
    if (!row) return
    const existing = normalizedMap.get(row.rawDate)
    normalizedMap.set(row.rawDate, {
      ...(existing || row),
      ...row,
      status: existing?.status || row.status,
      errorMessage: existing?.errorMessage || row.errorMessage,
      isLatest: Boolean(existing?.isLatest || row.isLatest),
    })
  })

  dates.forEach((date) => {
    const rawDate = formatDateString(date)
    if (!rawDate || normalizedMap.has(rawDate)) return
    normalizedMap.set(rawDate, {
      date: rawDate,
      rawDate,
      count: '-',
      pass: '-',
      b1PassCount: '-',
      consecutiveCandidateCount: '-',
      tomorrowStarCount: '-',
      status: 'missing',
      analysisCount: '-',
      errorMessage: null,
      isLatest: rawDate === latest,
    })
  })

  return [...normalizedMap.values()].sort((a, b) => b.rawDate.localeCompare(a.rawDate))
}

function prioritizeHistoryDates(dates: string[], latest: string, pageSize: number): string[] {
  const normalizedDates = dates.map(formatDateString).filter(Boolean)
  const firstScreen = new Set(normalizedDates.slice(0, pageSize))
  if (latest) firstScreen.add(latest)

  return [
    ...normalizedDates.filter((date) => firstScreen.has(date)),
    ...normalizedDates.filter((date) => !firstScreen.has(date)),
  ]
}

function createMissingHistoryRow(date: string, latest: string): HistoryRow {
  const rawDate = formatDateString(date)
  return {
    date: rawDate,
    rawDate,
    count: '-',
    pass: '-',
    b1PassCount: '-',
    consecutiveCandidateCount: '-',
    tomorrowStarCount: '-',
    status: 'missing',
    analysisCount: '-',
    errorMessage: null,
    isLatest: rawDate === latest,
  }
}

async function loadTomorrowStarFallbackHistory(dates: string[], signal: AbortSignal): Promise<HistoryRow[]> {
  const prioritizedDates = prioritizeHistoryDates(dates, latestDate.value, historyPageSize.value)
  const rows = await mapWithConcurrency(prioritizedDates, HISTORY_FALLBACK_CONCURRENCY, async (date) => {
    try {
      const [candidatesData, resultsData] = await Promise.all([
        apiAnalysis.getCandidates(date, { signal }),
        apiAnalysis.getResults(date, { signal }),
      ])
      const candidates = candidatesData.candidates || []
      const results = resultsData.results || []
      const passCount = results.filter((r) => r.signal_type === 'trend_start').length
      const rawDate = formatDateString(date)

      return {
        date: rawDate,
        rawDate,
        count: candidates.length,
        pass: passCount,
        b1PassCount: '-',
        consecutiveCandidateCount: '-',
        tomorrowStarCount: '-',
        status: 'success',
        analysisCount: results.length,
        errorMessage: null,
        isLatest: rawDate === latestDate.value,
      } satisfies HistoryRow
    } catch {
      return createMissingHistoryRow(date, latestDate.value)
    }
  })
  return rows.sort((a, b) => b.rawDate.localeCompare(a.rawDate))
}

async function loadCurrentHotFallbackHistory(dates: string[], signal: AbortSignal): Promise<HistoryRow[]> {
  const prioritizedDates = prioritizeHistoryDates(dates, currentHotLatestDate.value, historyPageSize.value)
  const rows = await mapWithConcurrency(prioritizedDates, HISTORY_FALLBACK_CONCURRENCY, async (date) => {
    try {
      const [candidatesData, resultsData] = await Promise.all([
        apiAnalysis.getCurrentHotCandidates(date, { signal }),
        apiAnalysis.getCurrentHotResults(date, { signal }),
      ])
      const candidates = candidatesData.candidates || []
      const results = resultsData.results || []
      const passCount = results.filter((r) => r.signal_type === 'trend_start').length
      const b1PassCount = candidates.filter((candidate) => candidate.b1_passed === true).length
      const rawDate = formatDateString(date)

      return {
        date: rawDate,
        rawDate,
        count: candidates.length,
        pass: passCount,
        b1PassCount,
        consecutiveCandidateCount: '-',
        tomorrowStarCount: '-',
        status: 'success',
        analysisCount: results.length,
        errorMessage: null,
        isLatest: rawDate === currentHotLatestDate.value,
      } satisfies HistoryRow
    } catch {
      return createMissingHistoryRow(date, currentHotLatestDate.value)
    }
  })
  return rows.sort((a, b) => b.rawDate.localeCompare(a.rawDate))
}

async function loadData(_skipLatestLoad: boolean = false) {
  if (loading.value) return

  const requestId = ++loadDataRequestId
  const signal = beginRequest('loadData')
  const previousSelectedDate = selectedDate.value
  const previousViewingDate = viewingDate.value
  loading.value = true
  try {
    const aggData = await apiAnalysis.getAggregate({ signal })
    if (requestId !== loadDataRequestId) return

    const dates = aggData.dates || []
    const history = aggData.history || []
    const windowStatus = aggData.window_status || null

    if (dates.length > 0) {
      latestDate.value = formatDateString(windowStatus?.latest_date || dates[0])
    } else {
      latestDate.value = formatDateString(windowStatus?.latest_date || '')
    }

    if (history.length > 0 || windowStatus) {
      historyData.value = normalizeHistoryRows(dates, history, windowStatus)
    } else {
      historyData.value = await loadTomorrowStarFallbackHistory(dates, signal)
      if (requestId !== loadDataRequestId) return
    }

    lastHistorySignature.value = buildHistorySignature(dates, historyData.value)
    lastRefreshCheckAt.value = Date.now()
    hydratedFromCache.value = false

    // 从聚合响应中直接填充候选和分析结果
    if (aggData.candidates && aggData.candidates.candidates && aggData.candidates.candidates.length > 0) {
      latestCandidates.value = aggData.candidates.candidates
      latestCandidatePage.value = 1
      candidateSort.value = { prop: '', order: null }

      if (aggData.candidates.pick_date) {
        const newPickDate = formatDate(aggData.candidates.pick_date)
        latestDataDate.value = newPickDate
        viewingDate.value = newPickDate
      } else {
        latestDataDate.value = ''
      }
    } else {
      latestCandidates.value = []
      latestCandidatePage.value = 1
      if (!aggData.candidates?.pick_date) {
        latestDataDate.value = ''
      }
    }

    if (aggData.results) {
      latestAnalysisResults.value = aggData.results.results || []
    } else {
      latestAnalysisResults.value = []
    }

    // 缓存最新候选+结果
    if (latestDataDate.value && (latestCandidates.value.length > 0 || latestAnalysisResults.value.length > 0)) {
      candidatesCache.value.set(latestDataDate.value, {
        candidates: latestCandidates.value,
        results: latestAnalysisResults.value,
        timestamp: Date.now(),
      })
    }

    // 更新增量状态
    if (aggData.freshness) {
      freshnessVersion.value = aggData.freshness.freshness_version || ''
      if (aggData.freshness.incremental_update) {
        incrementalUpdate.value = aggData.freshness.incremental_update
      }
    }

    if (dates.length === 0) {
      selectedDate.value = null
      viewingDate.value = null
      latestCandidates.value = []
      latestAnalysisResults.value = []
      latestDataDate.value = ''
      persistTomorrowStarCache()
      return
    }

    const hasPreviousSelectedDate = !!previousSelectedDate && historyData.value.some((item) => item.rawDate === previousSelectedDate)
    selectedDate.value = hasPreviousSelectedDate ? previousSelectedDate : latestDate.value

    const hasPreviousViewingDate = !!previousViewingDate && historyData.value.some((item) => item.rawDate === previousViewingDate)
    viewingDate.value = hasPreviousViewingDate ? previousViewingDate : (latestDataDate.value || latestDate.value)

    persistTomorrowStarCache()
  } catch (error: any) {
    if (isRequestCanceled(error)) return
    console.error('Failed to load data:', error)
    const message = getUserSafeErrorMessage(error, '加载数据失败')
    ElMessage.error(isInitializationPendingError(error) ? message : `加载数据失败: ${message}`)
  } finally {
    finishRequest('loadData', signal)
    if (requestId === loadDataRequestId) {
      loading.value = false
    }
  }
}

async function loadCurrentHotData(skipLatestLoad: boolean = false) {
  if (currentHotLoading.value) return

  const requestId = ++currentHotLoadDataRequestId
  const signal = beginRequest('currentHotLoadData')
  const previousSelectedDate = currentHotSelectedDate.value
  const previousViewingDate = currentHotViewingDate.value
  currentHotLoading.value = true
  try {
    const datesData = await apiAnalysis.getCurrentHotDates({ signal })
    if (requestId !== currentHotLoadDataRequestId) return

    const dates = datesData.dates || []
    const history = datesData.history || []
    const windowStatus = datesData.window_status || null

    currentHotLatestDate.value = dates.length > 0
      ? formatDateString(windowStatus?.latest_date || dates[0])
      : formatDateString(windowStatus?.latest_date || '')

    if (history.length > 0 || windowStatus) {
      currentHotHistoryData.value = normalizeHistoryRows(dates, history, windowStatus)
    } else {
      currentHotHistoryData.value = await loadCurrentHotFallbackHistory(dates, signal)
      if (requestId !== currentHotLoadDataRequestId) return
    }

    currentHotLastHistorySignature.value = buildHistorySignature(dates, currentHotHistoryData.value)
    currentHotHydratedFromCache.value = false
    currentHotLoaded.value = true

    if (dates.length === 0) {
      currentHotSelectedDate.value = null
      currentHotViewingDate.value = null
      currentHotLatestCandidates.value = []
      currentHotAnalysisResults.value = []
      currentHotRiskRegime.value = null
      currentHotLatestDataDate.value = ''
      persistTomorrowStarCache()
      return
    }

    const hasPreviousSelectedDate = !!previousSelectedDate && currentHotHistoryData.value.some((item) => item.rawDate === previousSelectedDate)
    currentHotSelectedDate.value = hasPreviousSelectedDate ? previousSelectedDate : currentHotLatestDate.value

    const hasPreviousViewingDate = !!previousViewingDate && currentHotHistoryData.value.some((item) => item.rawDate === previousViewingDate)
    currentHotViewingDate.value = hasPreviousViewingDate ? previousViewingDate : currentHotLatestDate.value

    if (!skipLatestLoad && requestId === currentHotLoadDataRequestId) {
      await loadCurrentHotLatestCandidates()
    }

    persistTomorrowStarCache()
  } catch (error) {
    if (isRequestCanceled(error)) return
    console.error('Failed to load current-hot data:', error)
    ElMessage.error(getUserSafeErrorMessage(error, '加载当前热盘数据失败'))
  } finally {
    finishRequest('currentHotLoadData', signal)
    if (requestId === currentHotLoadDataRequestId) {
      currentHotLoading.value = false
    }
  }
}

async function loadCurrentHotLatestCandidates() {
  const requestId = ++currentHotCandidatesRequestId
  const signal = beginRequest('currentHotLatestCandidates')
  currentHotLoadingLatest.value = true
  try {
    const candidatesData = await apiAnalysis.getCurrentHotCandidates(undefined, { signal })
    if (requestId !== currentHotCandidatesRequestId) return
    const candidates = candidatesData.candidates || []
    currentHotLatestCandidates.value = candidates
    currentHotRiskRegime.value = candidatesData.risk_regime || null
    currentHotCandidatePage.value = 1
    currentHotAnalysisPage.value = 1
    currentHotCandidateSort.value = { prop: '', order: null }

    if (candidatesData.pick_date) {
      const newPickDate = formatDate(candidatesData.pick_date)
      currentHotLatestDataDate.value = newPickDate
      currentHotViewingDate.value = newPickDate

      if (newPickDate && newPickDate !== currentHotLatestDate.value) {
        await loadCurrentHotData(true)
        if (requestId !== currentHotCandidatesRequestId) return
        try {
          const resultsData = await apiAnalysis.getCurrentHotResults(undefined, { signal })
          if (requestId !== currentHotCandidatesRequestId) return
          currentHotAnalysisResults.value = resultsData.results || []
          currentHotCandidatesCache.value.set(newPickDate, {
            candidates,
            results: resultsData.results || [],
            riskRegime: candidatesData.risk_regime || resultsData.risk_regime || null,
            timestamp: Date.now(),
          })
        } catch {
          currentHotAnalysisResults.value = []
        }
        persistTomorrowStarCache()
        return
      }
    } else {
      currentHotLatestDataDate.value = ''
    }

    try {
      const resultsData = await apiAnalysis.getCurrentHotResults(undefined, { signal })
      if (requestId !== currentHotCandidatesRequestId) return
      currentHotAnalysisResults.value = resultsData.results || []
      if (currentHotLatestDataDate.value) {
        currentHotCandidatesCache.value.set(currentHotLatestDataDate.value, {
          candidates,
          results: resultsData.results || [],
          riskRegime: candidatesData.risk_regime || resultsData.risk_regime || null,
          timestamp: Date.now(),
        })
      }
    } catch {
      currentHotAnalysisResults.value = []
    }

    persistTomorrowStarCache()
  } catch (error) {
    if (isRequestCanceled(error)) return
    console.error('Failed to load current-hot candidates:', error)
    ElMessage.error(getUserSafeErrorMessage(error, '加载当前热盘候选股票失败'))
  } finally {
    finishRequest('currentHotLatestCandidates', signal)
    currentHotLoadingLatest.value = false
  }
}

async function selectCurrentHotDate(row: HistoryRow) {
  currentHotSelectedDate.value = row.rawDate
  currentHotViewingDate.value = row.rawDate
  currentHotCandidatePage.value = 1
  currentHotAnalysisPage.value = 1
  currentHotCandidateSort.value = { prop: '', order: null }
  persistTomorrowStarCache()

  if (row.status !== 'success') {
    currentHotLatestCandidates.value = []
    currentHotAnalysisResults.value = []
    currentHotRiskRegime.value = null
    currentHotLatestDataDate.value = row.rawDate
    if (row.status === 'running') {
      ElMessage.info(`${row.rawDate} 正在生成中，稍后再查看`)
    } else if (row.status === 'failed') {
      ElMessage.warning(isInitializationPendingError({ message: row.errorMessage || '' }) ? '系统尚未完成初始化' : (row.errorMessage || `${row.rawDate} 生成失败`))
    } else {
      ElMessage.info(`${row.rawDate} 暂无可展示结果`)
    }
    persistTomorrowStarCache()
    return
  }

  const cached = currentHotCandidatesCache.value.get(row.rawDate)
  const now = Date.now()
  if (cached && (now - cached.timestamp) < CACHE_TTL_MS) {
    currentHotLatestCandidates.value = cached.candidates
    currentHotAnalysisResults.value = cached.results
    currentHotRiskRegime.value = cached.riskRegime || null
    currentHotLatestDataDate.value = row.rawDate
    persistTomorrowStarCache()
    return
  }

  const requestId = ++currentHotCandidatesRequestId
  const signal = beginRequest('currentHotLatestCandidates')
  currentHotLoadingLatest.value = true
  try {
    const [candidatesData, resultsData] = await Promise.all([
      apiAnalysis.getCurrentHotCandidates(row.rawDate, { signal }),
      apiAnalysis.getCurrentHotResults(row.rawDate, { signal }),
    ])
    if (requestId !== currentHotCandidatesRequestId) return

    const candidates = candidatesData.candidates || []
    const results = resultsData.results || []

    currentHotLatestCandidates.value = candidates
    currentHotAnalysisResults.value = results
    currentHotRiskRegime.value = candidatesData.risk_regime || resultsData.risk_regime || null
    currentHotLatestDataDate.value = row.rawDate
    currentHotCandidatePage.value = 1
    currentHotAnalysisPage.value = 1

    currentHotCandidatesCache.value.set(row.rawDate, {
      candidates,
      results,
      riskRegime: candidatesData.risk_regime || resultsData.risk_regime || null,
      timestamp: now,
    })
    persistTomorrowStarCache()
  } catch (error) {
    if (isRequestCanceled(error)) return
    console.error('Failed to load current-hot selected date data:', error)
    ElMessage.error(getUserSafeErrorMessage(error, '加载当前热盘数据失败'))
  } finally {
    finishRequest('currentHotLatestCandidates', signal)
    currentHotLoadingLatest.value = false
  }
}

async function selectDate(row: HistoryRow) {
  if (activeDataTab.value === 'current-hot') {
    await selectCurrentHotDate(row)
    return
  }

  selectedDate.value = row.rawDate
  viewingDate.value = row.rawDate
  latestCandidatePage.value = 1
  candidateSort.value = { prop: '', order: null }
  persistTomorrowStarCache()

  if (row.status !== 'success') {
    latestCandidates.value = []
    latestAnalysisResults.value = []
    latestDataDate.value = row.rawDate
    if (row.status === 'running') {
      ElMessage.info(`${row.rawDate} 正在生成中，稍后再查看`)
    } else if (row.status === 'failed') {
      ElMessage.warning(isInitializationPendingError({ message: row.errorMessage || '' }) ? '系统尚未完成初始化' : (row.errorMessage || `${row.rawDate} 生成失败`))
    } else {
      ElMessage.info(`${row.rawDate} 暂无可展示结果`)
    }
    persistTomorrowStarCache()
    return
  }

  // 先检查缓存
  const cached = candidatesCache.value.get(row.rawDate)
  const now = Date.now()
  if (cached && (now - cached.timestamp) < CACHE_TTL_MS) {
    // 使用缓存数据，立即显示
    latestCandidates.value = cached.candidates
    latestAnalysisResults.value = cached.results
    latestDataDate.value = row.rawDate
    console.log(`使用缓存数据: ${row.rawDate}`)
    persistTomorrowStarCache()
    return
  }

  // 加载选中日期的数据到右侧显示
  const requestId = ++candidatesRequestId
  const signal = beginRequest('latestCandidates')
  loadingLatest.value = true
  try {
    const [candidatesData, resultsData] = await Promise.all([
      apiAnalysis.getCandidates(row.rawDate, { signal }),
      apiAnalysis.getResults(row.rawDate, { signal })
    ])
    if (requestId !== candidatesRequestId) return

    const candidates = candidatesData.candidates || []
    const results = resultsData.results || []

    latestCandidates.value = candidates
    latestAnalysisResults.value = results
    latestDataDate.value = row.rawDate
    latestCandidatePage.value = 1

    // 存入缓存
    candidatesCache.value.set(row.rawDate, {
      candidates,
      results,
      timestamp: now
    })
    persistTomorrowStarCache()
  } catch (error) {
    if (isRequestCanceled(error)) return
    console.error('Failed to load selected date data:', error)
    ElMessage.error(getUserSafeErrorMessage(error, '加载数据失败'))
  } finally {
    finishRequest('latestCandidates', signal)
    loadingLatest.value = false
  }
}

// 信号收益率分析相关函数
async function showSignalReturns(row: HistoryRow, signalType: 'trend_start' | 'tomorrow_star') {
  // 检查是否有数据可以点击
  const count = signalType === 'tomorrow_star' ? row.tomorrowStarCount : row.pass
  if (count === '-' || count === 0) {
    ElMessage.info('该日期暂无相关信号数据')
    return
  }

  signalReturnDialogVisible.value = true
  signalReturnLoading.value = true
  signalReturnError.value = null

  const source = isCurrentHotTab.value ? 'current_hot' : 'tomorrow_star'

  try {
    const response = await apiAnalysis.getSignalReturns(source, signalType, row.rawDate)
    signalReturnData.value = response
    signalReturnSelectedCode.value = response.stocks[0]?.code || ''
  } catch (error) {
    console.error('Failed to load signal returns:', error)
    signalReturnError.value = getUserSafeErrorMessage(error, '加载收益率数据失败')
    ElMessage.error(signalReturnError.value)
  }
  signalReturnLoading.value = false
  await nextTick()
  await renderSignalReturnChart()
}

function closeSignalReturnDialog() {
  signalReturnDialogVisible.value = false
  signalReturnSelectedCode.value = ''
  signalReturnData.value = null
  signalReturnError.value = null
  disposeSignalReturnChart()
}

function selectSignalReturnStock(code: string) {
  if (!code || signalReturnSelectedCode.value === code) return
  signalReturnSelectedCode.value = code
  void renderSignalReturnChart()
}

function handleSignalReturnRowClick(row: { code: string }) {
  selectSignalReturnStock(row.code)
}

function getSignalReturnRowClassName({ row }: { row: { code: string } }) {
  return row.code === signalReturnSelectedCode.value ? 'signal-return-row--active' : ''
}

async function renderSignalReturnChart() {
  if (!signalReturnDialogVisible.value) return
  if (!signalReturnChartRef.value) return
  if (!signalReturnSelectedStock.value || signalReturnSelectedStock.value.timeline.length === 0) {
    signalReturnChartInstance?.clear()
    return
  }

  const { initChart } = await loadKLineChartRuntime()
  if (!signalReturnChartInstance) {
    signalReturnChartInstance = initChart(signalReturnChartRef.value)
  }

  signalReturnChartInstance.setOption(
    buildSignalReturnChartOption({
      stock: signalReturnSelectedStock.value,
      benchmark: signalReturnData.value?.benchmark || null,
    }),
    true,
  )
  signalReturnChartInstance.resize()
}

function disposeSignalReturnChart() {
  if (signalReturnChartInstance) {
    signalReturnChartInstance.dispose()
    signalReturnChartInstance = null
  }
}

function handleWindowResize() {
  signalReturnChartInstance?.resize()
}

function formatReturn(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  const sign = value >= 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  return value.toFixed(2)
}

function getReturnClass(value: number | null | undefined): string {
  if (value === null || value === undefined) return ''
  // 中国股市习惯：红涨绿跌
  return value >= 0 ? 'return-up' : 'return-down'
}

function formatDateShort(dateStr: string | null | undefined): string {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return `${(date.getMonth() + 1).toString().padStart(2, '0')}-${date.getDate().toString().padStart(2, '0')}`
}

async function refreshCurrentCandidates() {
  if (activeDataTab.value === 'current-hot') {
    await refreshCurrentHotCandidates()
    return
  }

  if (loading.value) {
    console.log('正在刷新中，忽略此次刷新请求')
    return
  }

  // 清除缓存，强制从后端重新加载
  candidatesCache.value.clear()

  // 强制检查新鲜度并重新加载数据
  await ensureFreshDataAndLoad(true)

  // 刷新当前查看的日期的数据
  const dateToRefresh = viewingDate.value || latestDate.value
  if (dateToRefresh) {
    const requestId = ++candidatesRequestId
    const signal = beginRequest('latestCandidates')
    loadingLatest.value = true
    try {
      const [candidatesData, resultsData] = await Promise.all([
        apiAnalysis.getCandidates(dateToRefresh, { signal }),
        apiAnalysis.getResults(dateToRefresh, { signal })
      ])
      if (requestId !== candidatesRequestId) return

      const candidates = candidatesData.candidates || []
      const results = resultsData.results || []

      latestCandidates.value = candidates
      latestAnalysisResults.value = results
      latestDataDate.value = dateToRefresh
      latestCandidatePage.value = 1
      candidateSort.value = { prop: '', order: null }

      // 更新缓存
      candidatesCache.value.set(dateToRefresh, {
        candidates,
        results,
        timestamp: Date.now()
      })

      ElMessage.success(`已刷新 ${dateToRefresh} 的数据`)
    } catch (error) {
      if (isRequestCanceled(error)) return
      console.error('Failed to refresh current candidates:', error)
      ElMessage.error(getUserSafeErrorMessage(error, '刷新失败'))
    } finally {
      finishRequest('latestCandidates', signal)
      loadingLatest.value = false
    }
  }
}

async function refreshCurrentHotCandidates() {
  if (currentHotLoading.value) {
    return
  }

  currentHotCandidatesCache.value.clear()
  await loadCurrentHotData(true)

  const dateToRefresh = currentHotViewingDate.value || currentHotLatestDate.value
  if (!dateToRefresh) return

  const requestId = ++currentHotCandidatesRequestId
  const signal = beginRequest('currentHotLatestCandidates')
  currentHotLoadingLatest.value = true
  try {
    const [candidatesData, resultsData] = await Promise.all([
      apiAnalysis.getCurrentHotCandidates(dateToRefresh, { signal }),
      apiAnalysis.getCurrentHotResults(dateToRefresh, { signal }),
    ])
    if (requestId !== currentHotCandidatesRequestId) return

    const candidates = candidatesData.candidates || []
    const results = resultsData.results || []

    currentHotLatestCandidates.value = candidates
    currentHotAnalysisResults.value = results
    currentHotLatestDataDate.value = dateToRefresh
    currentHotCandidatePage.value = 1
    currentHotAnalysisPage.value = 1
    currentHotCandidateSort.value = { prop: '', order: null }

    currentHotCandidatesCache.value.set(dateToRefresh, {
      candidates,
      results,
      timestamp: Date.now(),
    })

    persistTomorrowStarCache()
    ElMessage.success(`已刷新 ${dateToRefresh} 的当前热盘数据`)
  } catch (error) {
    if (isRequestCanceled(error)) return
    console.error('Failed to refresh current-hot candidates:', error)
    ElMessage.error(getUserSafeErrorMessage(error, '刷新当前热盘失败'))
  } finally {
    finishRequest('currentHotLatestCandidates', signal)
    currentHotLoadingLatest.value = false
  }
}

async function checkIncrementalStatus() {
  const signal = beginRequest('incrementalStatus')
  try {
    const status = await apiTasks.getIncrementalStatus({ signal })
    incrementalUpdate.value = status
  } catch (error) {
    if (isRequestCanceled(error)) return
    console.error('Failed to check incremental status:', error)
  } finally {
    finishRequest('incrementalStatus', signal)
  }
}

async function incrementalPollCallback() {
  await checkIncrementalStatus()

  // 如果更新完成，停止轮询并刷新数据
  if (!incrementalUpdate.value.running) {
    stopIncrementalPolling()
    await loadData()
  }
}

function startIncrementalPolling() {
  // 注册（如果尚未注册）并启动
  registerPoll(INCREMENTAL_POLL_KEY, incrementalPollCallback, INCREMENTAL_POLL_INTERVAL_MS)
  startPoll(INCREMENTAL_POLL_KEY)
}

function stopIncrementalPolling() {
  stopPoll(INCREMENTAL_POLL_KEY)
}

async function ensureFreshDataAndLoad(forceReload: boolean = false) {
  if (authStore.isAdmin && !configStore.tushareReady) return
  if (checkingFreshness.value || incrementalUpdate.value.running || loading.value) return

  const hasLoadedData = historyData.value.length > 0
  const missingVisibleRightPanelData = Boolean(
    historyData.value.length > 0
    && viewingDate.value
    && latestCandidates.value.length === 0
    && latestAnalysisResults.value.length === 0
  )
  const shouldSkipServerCheck = !forceReload
    && hasLoadedData
    && !missingVisibleRightPanelData
    && (Date.now() - lastRefreshCheckAt.value < REFRESH_CHECK_INTERVAL_MS)

  if (shouldSkipServerCheck) return

  // 如果有缓存数据且不是强制刷新，先做轻量级新鲜度检查
  if (!forceReload && hasLoadedData && !missingVisibleRightPanelData) {
    checkingFreshness.value = true
    const signal = beginRequest('freshness')
    try {
      const freshness = await apiAnalysis.getFreshness({ signal })
      lastRefreshCheckAt.value = Date.now()
      const nextFreshnessVersion = freshness.freshness_version || ''

      // 更新增量更新状态
      if (freshness.incremental_update) {
        incrementalUpdate.value = freshness.incremental_update
        if (freshness.incremental_update.running) {
          startIncrementalPolling()
        }
      }

      // 新鲜度未变且已有数据，直接返回
      if (
        hydratedFromCache.value
        && freshnessVersion.value
        && nextFreshnessVersion
        && freshnessVersion.value === nextFreshnessVersion
      ) {
        checkingFreshness.value = false
        return
      }

      freshnessVersion.value = nextFreshnessVersion

      // 增量更新正在运行时不重新加载
      if (freshness.incremental_update?.running) {
        checkingFreshness.value = false
        return
      }
    } catch (error: any) {
      if (isRequestCanceled(error)) return
      console.error('Failed to check freshness:', error)
    } finally {
      finishRequest('freshness', signal)
      checkingFreshness.value = false
    }
  }

  // 需要刷新数据 - 使用聚合接口一次加载全部
  await loadData()
}

async function loadMiddayData(forceRefresh: boolean = false) {
  if (!canUseMiddayAnalysis.value) return
  if (loadingMidday.value && !forceRefresh) return

  const signal = beginRequest('middayData')
  loadingMidday.value = true
  try {
    const [status, data] = middaySource.value === 'current-hot'
      ? await Promise.all([
        apiAnalysis.getCurrentHotMiddayStatus({ signal }),
        apiAnalysis.getCurrentHotMiddayCurrent({ signal }),
      ])
      : await Promise.all([
        apiAnalysis.getMiddayStatus({ signal }),
        apiAnalysis.getMiddayCurrent({ signal }),
      ])
    middayStatus.value = status
    middayData.value = data
    middayLoaded.value = true
  } catch (error) {
    if (isRequestCanceled(error)) return
    console.error('Failed to load intraday analysis:', error)
    ElMessage.error(getUserSafeErrorMessage(error, '加载中盘分析失败'))
  } finally {
    finishRequest('middayData', signal)
    loadingMidday.value = false
  }
}

async function refreshMiddayView() {
  await loadMiddayData(true)
}

async function loadClosingReport(forceRefresh: boolean = false) {
  if (loadingClosingReport.value && !forceRefresh) return

  loadingClosingReport.value = true
  try {
    const response = await apiAnalysis.getClosingReport()
    closingReport.value = response
    closingReportLoaded.value = true
    if (response.candidate_buckets?.length && !response.candidate_buckets.some((bucket) => bucket.source_pick_date === closingActiveBucket.value)) {
      closingActiveBucket.value = response.candidate_buckets[0].source_pick_date
    } else if (!response.candidate_buckets?.length && response.tomorrow_prediction) {
      closingActiveBucket.value = 'tomorrow-prediction'
    }
  } catch (error) {
    console.error('Failed to load closing analysis report:', error)
    ElMessage.error(getUserSafeErrorMessage(error, '加载收盘分析失败'))
  } finally {
    loadingClosingReport.value = false
  }
}

async function generateClosingReport(force: boolean = false) {
  if (generatingClosingReport.value) return

  generatingClosingReport.value = true
  try {
    const response = await apiAnalysis.generateClosingReport(force)
    closingReport.value = response
    closingReportLoaded.value = true
    if (response.candidate_buckets?.length && !response.candidate_buckets.some((bucket) => bucket.source_pick_date === closingActiveBucket.value)) {
      closingActiveBucket.value = response.candidate_buckets[0].source_pick_date
    } else if (!response.candidate_buckets?.length && response.tomorrow_prediction) {
      closingActiveBucket.value = 'tomorrow-prediction'
    }
    ElMessage.success(response.message || (response.generated ? '收盘分析已生成' : '当日收盘分析已存在'))
  } catch (error) {
    console.error('Failed to generate closing analysis report:', error)
    ElMessage.error(getUserSafeErrorMessage(error, '生成收盘分析失败'))
  } finally {
    generatingClosingReport.value = false
  }
}

async function handleGenerateClosingReport() {
  if (authStore.isAdmin && closingReport.value?.has_report) {
    try {
      await ElMessageBox.confirm(
        '当日收盘分析已经生成。确认后会基于当前最新日线数据强制重算并覆盖原报告。',
        '确认重新生成收盘分析',
        {
          confirmButtonText: '确认重算',
          cancelButtonText: '取消',
          type: 'warning',
        },
      )
      await generateClosingReport(true)
    } catch {
      ElMessage.info('已取消重新生成')
    }
    return
  }
  await generateClosingReport(false)
}

async function runMiddayAdminAction(action: 'generate' | 'refresh' | 'prefetch') {
  if (loadingMiddayAction.value) return

  loadingMiddayAction.value = true
  try {
    const isCurrentHotSource = middaySource.value === 'current-hot'
    const response = action === 'refresh'
      ? (
        isCurrentHotSource
          ? await apiAnalysis.refreshCurrentHotMidday()
          : await apiAnalysis.refreshMidday()
      )
      : action === 'prefetch'
        ? (
          isCurrentHotSource
            ? await apiAnalysis.prefetchCurrentHotMidday()
            : await apiAnalysis.prefetchMidday()
        )
        : (
          isCurrentHotSource
            ? await apiAnalysis.generateCurrentHotMidday()
            : await apiAnalysis.generateMidday()
        )
    ElMessage.success(
      response.message || (
        action === 'refresh'
          ? '中盘分析已刷新'
          : action === 'prefetch'
            ? '中盘分时数据已预下载'
            : '中盘分析已生成'
      ),
    )
    await loadMiddayData(true)
  } catch (error) {
    console.error(`Failed to ${action} intraday analysis:`, error)
    ElMessage.error(getUserSafeErrorMessage(
      error,
      action === 'refresh'
        ? '刷新中盘分析失败'
        : action === 'prefetch'
          ? '预下载中盘分时数据失败'
          : '生成中盘分析失败',
    ))
  } finally {
    loadingMiddayAction.value = false
  }
}

function viewStock(code: string, source: 'tomorrow-star' | 'current-hot' | 'midday-analysis' = 'tomorrow-star') {
  router.push({ path: '/diagnosis', query: { code, source, days: '30' } })
}

function getAnalysisResultName(result: AnalysisDisplayRow): string {
  if ('name' in result && typeof result.name === 'string' && result.name.trim()) {
    return result.name.trim()
  }
  const candidates = isCurrentHotTab.value ? currentHotLatestCandidates.value : latestCandidates.value
  const matchedCandidate = candidates.find((candidate) => candidate.code === result.code)
  if (typeof matchedCandidate?.name === 'string' && matchedCandidate.name.trim()) {
    return matchedCandidate.name.trim()
  }
  return result.code
}

function getAnalysisResultComment(result: AnalysisDisplayRow): string {
  if (typeof result.comment === 'string' && result.comment.trim()) {
    return result.comment.trim()
  }
  const b1Passed = getAnalysisB1Passed(result)
  const parts = [
    result.signal_type ? getSignalTypeLabel(result.signal_type) : '',
    result.verdict ? getVerdictLabel(result.verdict) : '',
    typeof result.total_score === 'number' ? `评分 ${result.total_score.toFixed(1)}` : '',
    b1Passed === true ? 'B1通过' : (b1Passed === false ? 'B1未通过' : ''),
  ].filter((item) => item && item.trim())
  return parts.length > 0 ? parts.join(' · ') : '暂无简要分析'
}

type PullbackFieldLike = {
  code: string
  pullback_quality?: string | null
  pullback_negative_flags?: string[] | null
}

function getMatchedAnalysisResult(code: string): AnalysisResult | CurrentHotAnalysisResult | undefined {
  return isCurrentHotTab.value
    ? currentHotAnalysisByCode.value.get(code)
    : tomorrowStarAnalysisByCode.value.get(code)
}

function getPullbackFields(row: PullbackFieldLike): { quality?: string | null, flags: string[] } {
  const matched = getMatchedAnalysisResult(row.code)
  const quality = row.pullback_quality ?? matched?.pullback_quality
  const flags = Array.isArray(row.pullback_negative_flags) && row.pullback_negative_flags.length > 0
    ? row.pullback_negative_flags
    : (Array.isArray(matched?.pullback_negative_flags) ? matched?.pullback_negative_flags : [])
  return {
    quality,
    flags: flags
      .map((item) => String(item || '').trim())
      .filter((item) => item.length > 0),
  }
}

function getPullbackQualityLabel(value?: string | null): string {
  switch (value) {
    case 'contracting':
      return '缩量回调'
    case 'neutral':
      return '中性回调'
    case 'abnormal_bear':
      return '异常阴量'
    case 'expanding_selloff':
      return '下跌上量'
    case 'insufficient_data':
      return '样本不足'
    case 'disabled':
      return '未启用'
    default:
      return typeof value === 'string' ? value : ''
  }
}

function getPullbackQualityTagType(value?: string | null): string {
  switch (value) {
    case 'contracting':
      return 'success'
    case 'abnormal_bear':
      return 'warning'
    case 'expanding_selloff':
      return 'danger'
    default:
      return 'info'
  }
}

function getPullbackNegativeFlagLabel(value: string): string {
  switch (value) {
    case 'down_volume_increasing':
      return '下跌逐步上量'
    case 'abnormal_bear_bar':
      return '异常放量阴线'
    default:
      return value
  }
}

function getPullbackNegativeFlagTagType(value: string): string {
  return value === 'down_volume_increasing' ? 'danger' : 'warning'
}

function getRowPullbackQuality(row: PullbackFieldLike): string | null {
  return getPullbackFields(row).quality ?? null
}

function getRowPullbackQualityLabel(row: PullbackFieldLike): string {
  return getPullbackQualityLabel(getRowPullbackQuality(row))
}

function getRowPullbackNegativeFlags(row: PullbackFieldLike): string[] {
  return getPullbackFields(row).flags
}

function getRowPullbackSummary(row: PullbackFieldLike): string {
  const qualityLabel = getRowPullbackQualityLabel(row)
  const flags = getRowPullbackNegativeFlags(row).map(getPullbackNegativeFlagLabel)
  const parts: string[] = []
  if (qualityLabel) {
    parts.push(`回调:${qualityLabel}`)
  }
  if (flags.length > 0) {
    parts.push(`负面:${flags.join('/')}`)
  }
  return parts.join('；')
}

type CandidateNoteLike = (Candidate | CurrentHotCandidate) & AnalysisPrefilterLike

function getCandidatePrefilterNote(row: CandidateNoteLike): string {
  if (row.prefilter_passed !== false) {
    return ''
  }
  const summary = getAnalysisPrefilterSummary(row)
  return summary ? `前置:${summary}` : '前置:未通过'
}

function getCandidateInlineNote(row: Candidate | CurrentHotCandidate): string {
  const pullbackSummary = getRowPullbackSummary(row)
  const prefilterNote = getCandidatePrefilterNote(row as CandidateNoteLike)
  const riskSummary = getRiskFlagSummary(row as AnalysisDisplayRow)
  const fallbackSummary = getAnalysisResultComment(row as AnalysisDisplayRow)
  if (isCurrentHotTab.value) {
    const comment = typeof row.comment === 'string' ? row.comment.trim() : ''
    return [riskSummary, pullbackSummary, comment || fallbackSummary, prefilterNote]
      .filter((item) => typeof item === 'string' && item.trim())
      .join('；') || '暂无简要分析'
  }
  const comment = typeof row.comment === 'string' ? row.comment.trim() : ''
  return [pullbackSummary, comment || fallbackSummary, prefilterNote]
    .filter((item) => typeof item === 'string' && item.trim())
    .join('；') || '暂无简要分析'
}

function getAnalysisB1Passed(result: AnalysisDisplayRow): boolean | null | undefined {
  return 'b1_passed' in result ? result.b1_passed : undefined
}

type AnalysisPrefilterLike = {
  prefilter_passed?: boolean | null
  prefilter_summary?: string | null
  prefilter_blocked_by?: string[] | null
}

function getAnalysisPrefilterLike(result: AnalysisDisplayRow): AnalysisPrefilterLike {
  if ('prefilter_passed' in result || 'prefilter_summary' in result || 'prefilter_blocked_by' in result) {
    return {
      prefilter_passed: 'prefilter_passed' in result ? result.prefilter_passed : undefined,
      prefilter_summary: 'prefilter_summary' in result ? result.prefilter_summary : undefined,
      prefilter_blocked_by: 'prefilter_blocked_by' in result ? result.prefilter_blocked_by : undefined,
    }
  }
  return {}
}

function getAnalysisPrefilterPassed(result: AnalysisDisplayRow): boolean | null | undefined {
  return getAnalysisPrefilterLike(result).prefilter_passed
}

function getAnalysisPrefilterTagType(value?: boolean | null): string {
  if (value === true) return 'success'
  if (value === false) return 'danger'
  return 'info'
}

function getAnalysisPrefilterLabel(value?: boolean | null): string {
  if (value === true) return '是'
  if (value === false) return '否'
  return '-'
}

function getAnalysisPrefilterSummary(result: AnalysisPrefilterLike): string {
  if (typeof result.prefilter_summary === 'string' && result.prefilter_summary.trim()) {
    return result.prefilter_summary.trim()
  }
  if (Array.isArray(result.prefilter_blocked_by) && result.prefilter_blocked_by.length > 0) {
    return result.prefilter_blocked_by.join(' / ')
  }
  if (result.prefilter_passed === false) {
    return '前置过滤未通过'
  }
  return ''
}

function getCurrentHotBoardLabel(candidate: CurrentHotCandidate): string {
  if (Array.isArray(candidate.sector_names) && candidate.sector_names.length > 0) {
    const sectorNames = candidate.sector_names
      .map((item) => String(item || '').trim())
      .filter((item) => item && item !== '当前热盘')
    if (sectorNames.length > 0) {
      return sectorNames.join(' / ')
    }
  }
  const label = [candidate.board_name, candidate.board, candidate.sector_name]
    .find((item) => typeof item === 'string' && item.trim())
  if (typeof label === 'string' && label.trim()) {
    return label.trim()
  }
  if (candidate.board_group === 'kechuang') return '科创板'
  return isSciTechBoardCode(candidate.code) ? '科创板' : '其他板块'
}

function formatTurnoverRate(value?: number | null): string {
  const numericValue = toFiniteNumber(value)
  return numericValue === null ? '-' : `${numericValue.toFixed(2)}%`
}

function formatVolumeRatio(value?: number | null): string {
  const numericValue = toFiniteNumber(value)
  return numericValue === null ? '-' : numericValue.toFixed(2)
}

function formatActivePoolRank(value?: number | null): string {
  const numericValue = toFiniteNumber(value)
  return numericValue === null ? '-' : String(Math.round(numericValue))
}

function toFiniteNumber(value?: number | string | null): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function formatDate(date: string | Date): string {
  const d = typeof date === 'string' ? new Date(date) : date
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function formatDateString(dateStr: string): string {
  if (!dateStr) return ''
  if (/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
    return dateStr
  }
  if (/^\d{8}$/.test(dateStr)) {
    return `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`
  }
  return dateStr
}

function formatDateTime(dateTimeStr: string): string {
  if (!dateTimeStr) return ''
  const date = new Date(dateTimeStr)
  if (Number.isNaN(date.getTime())) return dateTimeStr
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

function getScoreType(score?: number | null): string {
  if (!score) return 'info'
  if (score >= 4.0) return 'success'
  if (score >= 3.5) return 'warning'
  return 'danger'
}

function getRiskFlagLevel(row: AnalysisDisplayRow | null | undefined): string | null {
  if (!row || !('risk_flag' in row) || !row.risk_flag) return null
  return row.risk_flag.level || null
}

function getRiskFlagLabel(level?: string | null): string {
  if (level === 'high') return '高风险'
  if (level === 'medium') return '观察'
  return '低风险'
}

function getRiskFlagTagType(level?: string | null): 'danger' | 'warning' | 'info' {
  if (level === 'high') return 'danger'
  if (level === 'medium') return 'warning'
  return 'info'
}

function isRiskCandidate(row: AnalysisDisplayRow | null | undefined): boolean {
  if (!row || !('risk_flag' in row) || !row.risk_flag) return false
  return ['high', 'medium'].includes(row.risk_flag?.level || '')
}

function getRiskFlagSummary(row: AnalysisDisplayRow | null | undefined): string {
  if (!row || !('risk_flag' in row) || !row.risk_flag) return ''
  return row.risk_flag.summary?.trim() || ''
}

function getRiskRegimeLabel(level?: string | null): string {
  if (level === 'high') return '高警惕'
  if (level === 'medium') return '转弱观察'
  return '正常'
}

function getRiskRegimeTagType(level?: string | null): 'danger' | 'warning' | 'info' {
  if (level === 'high') return 'danger'
  if (level === 'medium') return 'warning'
  return 'info'
}

function formatRiskRegimeScore(value?: number | null): string {
  return typeof value === 'number' ? value.toFixed(1) : '-'
}

function formatRatioPct(value?: number | null): string {
  return typeof value === 'number' ? `${(value * 100).toFixed(0)}%` : '-'
}

function formatAiConfidence(value?: number | null): string {
  return typeof value === 'number' ? `${Math.round(value)}%` : '-'
}

function getSignalTypeLabel(signalType?: string | null): string {
  const signalMap: Record<string, string> = {
    'trend_start': '趋势启动',
    'rebound': '反弹延续',
    'distribution_risk': '风险释放',
  }
  return signalMap[signalType || ''] || signalType || '-'
}

function getSignalTypeTag(signalType?: string | null): string {
  if (signalType === 'trend_start') return 'success'
  if (signalType === 'rebound') return 'warning'
  if (signalType === 'distribution_risk') return 'danger'
  return 'info'
}

function getBooleanTagType(value?: boolean | null): string {
  if (value === true) return 'success'
  if (value === false) return 'info'
  return 'warning'
}

function getBooleanTagLabel(value?: boolean | null): string {
  if (value === true) return '通过'
  if (value === false) return '未过'
  return '-'
}

function getVerdictTagType(verdict?: string | null): string {
  if (verdict === 'PASS') return 'success'
  if (verdict === 'WATCH') return 'warning'
  if (verdict === 'FAIL') return 'danger'
  return 'info'
}

function getVerdictLabel(verdict?: string | null): string {
  if (verdict === 'PASS') return '通过'
  if (verdict === 'WATCH') return '观察'
  if (verdict === 'FAIL') return '失败'
  return '-'
}

function isMiddayTrendReversal(row: IntradayAnalysisItem): boolean {
  return row.b1_passed === true && row.verdict === 'PASS' && row.signal_type === 'trend_start'
}

function getTrendReversalTagType(row: IntradayAnalysisItem): string {
  return isMiddayTrendReversal(row) ? 'success' : 'info'
}

function getTrendReversalLabel(row: IntradayAnalysisItem): string {
  return isMiddayTrendReversal(row) ? '是' : '否'
}

function getExitPlanActionLabel(plan?: ExitPlan | null): string {
  if (!plan) return '-'
  if (plan.action_label) {
    const raw = plan.action_label.trim()
    const normalized: Record<string, string> = {
      hold: '继续持有',
      wash_observe: '谨慎持有',
      hold_cautious: '谨慎持有',
      take_profit_partial: '分批止盈',
      trim: '先减仓',
      exit: '退出观望',
    }
    return normalized[raw] || raw
  }
  const labels: Record<string, string> = {
    hold: '继续持有',
    wash_observe: '谨慎持有',
    hold_cautious: '谨慎持有',
    take_profit_partial: '分批止盈',
    trim: '先减仓',
    exit: '退出观望',
  }
  return labels[plan.action || ''] || plan.action || '-'
}

function getExitPlanActionType(action?: string | null): string {
  const types: Record<string, string> = {
    hold: 'success',
    wash_observe: 'warning',
    hold_cautious: 'warning',
    take_profit_partial: 'primary',
    trim: 'warning',
    exit: 'danger',
  }
  return types[action || ''] || 'info'
}

function getMiddayLatestPrice(row: IntradayAnalysisItem): number | null {
  return toFiniteNumber(row.latest_price ?? row.close_price)
}

function getMiddayMorningStateLabel(row: IntradayAnalysisItem): string {
  const state = row.exit_plan?.morning_state
  const map: Record<string, string> = {
    wash_observe: '上午有回落但承接尚在，偏向震荡观察',
    breakdown_risk: '上午跌破关键结构，走势偏弱',
    distribution_risk: '上午冲高回落偏重，疑似资金兑现',
    strong_push: '上午推进顺畅，强势特征明确',
    normal_pullback: '上午正常回踩，等待下午确认方向',
  }
  return map[state || ''] || state || '-'
}

function getMiddayAfternoonActionLabel(row: IntradayAnalysisItem): string {
  const action = row.exit_plan?.afternoon_action
  const map: Record<string, string> = {
    hold_if_reclaim: '下午若重新站稳关键线，可继续持有，暂不急于加仓',
    exit: '下午若继续走弱，建议退出观望，先保护净值',
    trim: '下午优先减仓，降低回撤暴露',
    trim_if_break_low: '若跌破上午低点，建议先减仓，再观察是否回收',
    hold: '下午可继续持有，重点观察量能和承接是否延续',
  }
  return map[action || ''] || getExitPlanActionLabel(row.exit_plan)
}

function formatPlanPrice(value?: number | string | null): string {
  const numeric = toFiniteNumber(value)
  return numeric === null ? '-' : numeric.toFixed(2)
}

function formatClosingMoney(value?: number | null): string {
  const numeric = toFiniteNumber(value)
  if (numeric === null) return '-'
  const abs = Math.abs(numeric)
  if (abs >= 10000) return `${(numeric / 10000).toFixed(2)}亿`
  return `${numeric.toFixed(2)}万`
}

function formatClosingPct(value?: number | null): string {
  const numeric = toFiniteNumber(value)
  return numeric === null ? '-' : `${numeric.toFixed(2)}%`
}

function getClosingBucketTitle(bucket: ClosingCandidateMoveBucket): string {
  return `${bucket.label} ${bucket.source_pick_date}`
}

function getClosingSectorNames(row: ClosingCandidateMoveItem | ClosingTomorrowPredictionItem): string {
  return row.sector_names?.length ? row.sector_names.join(' / ') : '-'
}

function getClosingPredictionB1(row: ClosingTomorrowPredictionItem): string {
  const parts = [
    row.b1_passed === true ? 'B1通过' : row.b1_passed === false ? 'B1未通过' : 'B1未知',
    typeof row.b1_score === 'number' ? `评分 ${row.b1_score.toFixed(1)}` : '',
    row.verdict ? `结论 ${getVerdictLabel(row.verdict)}` : '',
    row.b1_comment || '',
  ].filter(Boolean)
  return parts.length ? parts.join('；') : '-'
}

function getClosingPredictionBullish(row: ClosingTomorrowPredictionItem): string {
  if (row.bullish_news?.length) return row.bullish_news.join('；')
  if (row.local_reasons?.length) return row.local_reasons.slice(0, 3).join('；')
  return '-'
}

function formatKeyLevels(levels?: Record<string, number | null> | null): string {
  if (!levels) return '-'
  const labelMap: Record<string, string> = {
    support: '支撑',
    pressure: '压力',
    resistance: '压力',
    structure_line: '结构线',
    trailing_stop: '移动止盈',
    stop_loss: '止损',
    morning_low: '上午低点',
    morning_high: '上午高点',
    reclaim_line: '收复线',
  }
  const entries = Object.entries(levels)
    .filter(([, value]) => toFiniteNumber(value) !== null)
    .map(([key, value]) => `${labelMap[key] || key} ${formatPlanPrice(value)}`)
  return entries.length > 0 ? entries.join(' / ') : '-'
}

function getMiddayPlanDetail(row: IntradayAnalysisItem): string {
  const plan = row.exit_plan
  if (!plan) return '-'
  const parts = [
    formatKeyLevels(plan.key_levels) !== '-' ? `关键价位：${formatKeyLevels(plan.key_levels)}` : '',
    getMiddayAfternoonActionLabel(row),
    plan.reason?.trim() ? `原因：${plan.reason.trim()}` : '',
  ].filter((item) => item && item !== '-')
  return parts.length > 0 ? parts.join('；') : '-'
}

function getMiddayPlanBrief(row: IntradayAnalysisItem): string {
  const plan = row.exit_plan
  if (!plan) return '-'
  const parts = [
    getMiddayMorningStateLabel(row),
    getMiddayAfternoonActionLabel(row),
    formatKeyLevels(plan.key_levels) !== '-' ? formatKeyLevels(plan.key_levels) : '',
  ].filter((item) => item && item !== '-')
  return parts.length > 0 ? parts.join(' · ') : '-'
}

function getMiddayRelativeMarketBrief(row: IntradayAnalysisItem): string {
  const status = row.relative_market_status?.trim()
  const strength = toFiniteNumber(row.relative_market_strength_pct)
  const benchmarkName = row.benchmark_name?.trim()
  const benchmarkChange = toFiniteNumber(row.benchmark_change_pct)
  if (!status) return '-'
  const parts = [status]
  if (strength !== null) parts.push(`超额 ${strength >= 0 ? '+' : ''}${strength.toFixed(2)}%`)
  if (benchmarkName && benchmarkChange !== null) parts.push(`${benchmarkName} ${benchmarkChange >= 0 ? '+' : ''}${benchmarkChange.toFixed(2)}%`)
  return parts.join(' · ')
}

function getMiddayPreviousAnalysisBrief(row: IntradayAnalysisItem): string {
  const prev = row.previous_analysis
  if (!prev) return '-'
  const parts = [
    prev.verdict ? `昨日 ${getVerdictLabel(prev.verdict)}` : '',
    typeof prev.score === 'number' ? `评分 ${prev.score.toFixed(1)}` : '',
    prev.signal_type ? getSignalTypeLabel(prev.signal_type) : '',
  ].filter(Boolean)
  const comment = prev.comment?.trim()
  if (parts.length === 0 && !comment) return '-'
  return comment ? `${parts.join(' / ')} · ${comment}` : parts.join(' / ')
}

function getMiddayManagerNote(row: IntradayAnalysisItem): string {
  return row.manager_note?.trim() || '-'
}

function getMiddayPositionSuggestion(row: IntradayAnalysisItem): string {
  const action = row.exit_plan?.afternoon_action || row.exit_plan?.action || ''
  const relativeStrength = toFiniteNumber(row.relative_market_strength_pct)
  const latestChange = toFiniteNumber(row.latest_change_pct)
  const signal = row.signal_type || ''
  const verdict = row.verdict || ''

  if (action === 'exit') return '持仓建议：下午继续走弱时以退出观望为主，不建议加仓。'
  if (action === 'trim' || action === 'trim_if_break_low') return '持仓建议：以控制回撤为主，先减仓，不建议逆势加仓。'
  if (action === 'hold_if_reclaim') return '持仓建议：先观察是否收复关键线，收复后可继续持有，未收复前不急于加仓。'
  if (action === 'hold' && relativeStrength !== null && relativeStrength >= 1 && latestChange !== null && latestChange > 0) {
    return '持仓建议：可继续持有，若下午继续强于大盘且放量稳定，可考虑小幅顺势加仓。'
  }
  if (verdict === 'PASS' && signal === 'trend_start') {
    return '持仓建议：以持有观察为主，只有下午继续转强并确认承接时，才考虑小幅加仓。'
  }
  return '持仓建议：先持有观察，以下午量价和关键位表现决定是否加仓或减仓。'
}

function getMiddayTrendStartScore(row: IntradayAnalysisItem): number | null {
  const change = toFiniteNumber(row.latest_change_pct) ?? toFiniteNumber(row.change_pct)
  if (change === null) return null
  const volumeRatio = toFiniteNumber(row.volume_ratio) ?? 1
  const volumeBoost = Math.max(volumeRatio - 1, 0)
  const b1Boost = row.b1_passed === true ? 15 : 0
  if (change <= -5) {
    return Number((change * 10 - volumeBoost * 6 + b1Boost * 0.2).toFixed(2))
  }
  const positiveBase = change > 0 ? change * 10 + volumeBoost * 8 + b1Boost : change * 10 + volumeBoost * 2
  return Number(positiveBase.toFixed(2))
}

function formatMiddayTrendStartScore(row: IntradayAnalysisItem): string {
  const score = getMiddayTrendStartScore(row)
  return score === null ? '-' : score.toFixed(1)
}

function getMiddayTrendStartTagType(row: IntradayAnalysisItem): string {
  const score = getMiddayTrendStartScore(row)
  if (score === null) return 'info'
  if (score >= 50) return 'success'
  if (score >= 20) return 'warning'
  if (score <= -50) return 'danger'
  return 'info'
}

function compareMiddayTrendStartRows(a: IntradayAnalysisItem, b: IntradayAnalysisItem): number {
  const aScore = getMiddayTrendStartScore(a)
  const bScore = getMiddayTrendStartScore(b)
  if (aScore !== null || bScore !== null) {
    if (aScore === null) return 1
    if (bScore === null) return -1
    if (aScore !== bScore) return bScore - aScore
  }
  return a.code.localeCompare(b.code)
}

function getMiddayRowComment(row: IntradayAnalysisItem): string {
  const reason = row.exit_plan?.reason?.trim()
  const suggestion = getMiddayPositionSuggestion(row)
  if (reason) return `${suggestion} 原因：${reason}`
  if (row.manager_note?.trim()) return `${suggestion} ${row.manager_note.trim()}`
  if (isMiddayTrendReversal(row)) return `${suggestion} 当前B1通过且趋势启动，重点观察下午能否继续强于大盘。`
  if (row.signal_type === 'distribution_risk') return `${suggestion} 盘中有兑现迹象，重点盯紧量价是否继续转弱。`
  if (row.signal_type === 'rebound') return `${suggestion} 当前更像反弹延续，暂不宜把反弹直接当成主升。`
  return suggestion
}

function getMiddaySortableValue(row: IntradayAnalysisItem, prop: MiddaySortProp): number | string | boolean | null {
  if (prop === 'code') return row.code
  if (prop === 'name') return row.name || ''
  if (prop === 'verdict') return getVerdictLabel(row.verdict)
  if (prop === 'signal_type') return getSignalTypeLabel(row.signal_type)
  if (prop === 'b1_passed') return row.b1_passed ?? null
  if (prop === 'latest_price') return getMiddayLatestPrice(row)
  if (prop === 'score') return getMiddayTrendStartScore(row)
  return toFiniteNumber(row[prop as keyof IntradayAnalysisItem] as number | string | null | undefined)
}

function compareMiddayRows(a: IntradayAnalysisItem, b: IntradayAnalysisItem, state: MiddaySortState): number {
  if (!state.prop || !state.order) return 0
  const diff = compareNullableValues(
    getMiddaySortableValue(a, state.prop),
    getMiddaySortableValue(b, state.prop),
    state.order,
  )
  return diff !== 0 ? diff : compareMiddayTrendStartRows(a, b)
}

function handleMiddaySortChange({ prop, order }: { prop: string, order: SortOrder }) {
  const validProps: MiddaySortProp[] = [
    'code',
    'name',
    'open_price',
    'midday_price',
    'latest_price',
    'change_pct',
    'latest_change_pct',
    'benchmark_change_pct',
    'relative_market_strength_pct',
    'score',
    'verdict',
    'signal_type',
    'b1_passed',
  ]
  middaySort.value = {
    prop: validProps.includes(prop as MiddaySortProp) ? prop as MiddaySortProp : '',
    order,
  }
}

function buildHistorySignature(dates: string[], history: Array<HistoryLikeItem | HistoryRow>): string {
  const resolveCount = (item: HistoryLikeItem | HistoryRow): number | '-' => {
    if (typeof item.count === 'number') return item.count
    if ('candidate_count' in item && typeof item.candidate_count === 'number') return item.candidate_count
    return '-'
  }
  const resolvePass = (item: HistoryLikeItem | HistoryRow): number | '-' => {
    if (typeof item.pass === 'number') return item.pass
    if ('trend_start_count' in item && typeof item.trend_start_count === 'number') return item.trend_start_count
    return '-'
  }

  if (history.length > 0) {
    return JSON.stringify(
      history.map((item) => ({
        date: formatDateString(('rawDate' in item ? item.rawDate : item.date) || ''),
        count: resolveCount(item),
        pass: resolvePass(item),
        b1PassCount: (
          'b1PassCount' in item
            ? item.b1PassCount
            : (typeof item.b1_pass_count === 'number' ? item.b1_pass_count : '-')
        ),
        consecutiveCandidateCount: 'consecutiveCandidateCount' in item
          ? item.consecutiveCandidateCount
          : (typeof item.consecutive_candidate_count === 'number' ? item.consecutive_candidate_count : '-'),
        tomorrowStarCount: (
          'tomorrowStarCount' in item
            ? item.tomorrowStarCount
            : (typeof item.tomorrow_star_count === 'number' ? item.tomorrow_star_count : '-')
        ),
        status: 'status' in item ? item.status : undefined,
      }))
    )
  }
  return JSON.stringify(dates.map((date) => formatDateString(date)))
}

async function checkForRefresh(forceLoad: boolean = false) {
  if (loading.value) return

  const now = Date.now()
  if (!forceLoad && now - lastRefreshCheckAt.value < REFRESH_CHECK_INTERVAL_MS) return

  // 直接用聚合接口刷新，避免额外的 getDates 请求
  await loadData()
}

async function refreshStatusAndRetry() {
  if (!authStore.isAdmin) {
    await ensureFreshDataAndLoad(true)
    return
  }
  await configStore.checkTushareStatus()
  if (configStore.dataInitialized) {
    await ensureFreshDataAndLoad(true)
  }
}

function persistTomorrowStarCache() {
  if (typeof window === 'undefined') return

  // Only persist lightweight UI filter/pagination state.
  // Heavy data (candidates, analysisResults, historyData, etc.) is fetched via API on mount.
  const payload = {
    selectedDate: selectedDate.value,
    viewingDate: viewingDate.value,
    latestDate: latestDate.value,
    latestDataDate: latestDataDate.value,
    historyPage: historyPage.value,
    latestCandidatePage: latestCandidatePage.value,
    candidateSort: candidateSort.value,
    selectedTomorrowStarIndustries: selectedTomorrowStarIndustries.value,
    freshnessVersion: freshnessVersion.value,
    currentHotSelectedDate: currentHotSelectedDate.value,
    currentHotViewingDate: currentHotViewingDate.value,
    currentHotLatestDate: currentHotLatestDate.value,
    currentHotLatestDataDate: currentHotLatestDataDate.value,
    currentHotHistoryPage: currentHotHistoryPage.value,
    currentHotCandidatePage: currentHotCandidatePage.value,
    currentHotAnalysisPage: currentHotAnalysisPage.value,
    currentHotCandidateSort: currentHotCandidateSort.value,
    currentHotBoardFilter: currentHotBoardFilter.value,
    currentHotRiskFilter: currentHotRiskFilter.value,
    cachedAt: Date.now(),
  }

  sessionStorage.setItem(TOMORROW_STAR_CACHE_KEY, JSON.stringify(payload))
}

function hydrateTomorrowStarCache() {
  if (typeof window === 'undefined') return

  const cacheKey = [TOMORROW_STAR_CACHE_KEY, ...TOMORROW_STAR_LEGACY_CACHE_KEYS]
    .find((key) => sessionStorage.getItem(key))
  const raw = cacheKey ? sessionStorage.getItem(cacheKey) : null
  if (!raw) return

  try {
    const payload = JSON.parse(raw)

    // Restore lightweight UI state only — heavy data is fetched via API
    selectedDate.value = payload.selectedDate || null
    viewingDate.value = payload.viewingDate || null
    latestDate.value = payload.latestDate || ''
    latestDataDate.value = payload.latestDataDate || ''
    historyPage.value = Math.max(1, Number(payload.historyPage) || 1)
    latestCandidatePage.value = Math.max(1, Number(payload.latestCandidatePage) || 1)
    candidateSort.value = normalizeCandidateSortState(payload.candidateSort)
    selectedTomorrowStarIndustries.value = Array.isArray(payload.selectedTomorrowStarIndustries)
      ? payload.selectedTomorrowStarIndustries
        .map((item: unknown) => String(item || '').trim())
        .filter((item: string) => item.length > 0)
      : []
    freshnessVersion.value = payload.freshnessVersion || ''
    currentHotSelectedDate.value = payload.currentHotSelectedDate || null
    currentHotViewingDate.value = payload.currentHotViewingDate || null
    currentHotLatestDate.value = payload.currentHotLatestDate || ''
    currentHotLatestDataDate.value = payload.currentHotLatestDataDate || ''
    currentHotHistoryPage.value = Math.max(1, Number(payload.currentHotHistoryPage) || 1)
    currentHotCandidatePage.value = Math.max(1, Number(payload.currentHotCandidatePage) || 1)
    currentHotAnalysisPage.value = Math.max(1, Number(payload.currentHotAnalysisPage) || 1)
    currentHotCandidateSort.value = normalizeCandidateSortState(payload.currentHotCandidateSort)
    currentHotBoardFilter.value = payload.currentHotBoardFilter || 'all'
    currentHotRiskFilter.value = payload.currentHotRiskFilter || 'all'

    // Data arrays are NOT restored from cache — they will be fetched from API
    hydratedFromCache.value = false
    currentHotHydratedFromCache.value = false
    currentHotLoaded.value = false
  } catch {
    if (cacheKey) {
      sessionStorage.removeItem(cacheKey)
    }
  }
}

async function refreshAfterStatusReady(forceReload: boolean = false) {
  if (!authStore.isAdmin) {
    if (hydratedFromCache.value && !forceReload) {
      await checkForRefresh(true)
      return
    }
    await ensureFreshDataAndLoad(forceReload)
    return
  }

  try {
    await configStore.checkTushareStatus()
  } catch {
    return
  }
  if (hydratedFromCache.value && !forceReload) {
    await checkForRefresh(true)
    return
  }
  await ensureFreshDataAndLoad(forceReload)
}

onMounted(() => {
  window.addEventListener('resize', handleWindowResize)
  hydrateTomorrowStarCache()

  if (historyData.value.length === 0) {
    void loadData()
    if (authStore.isAdmin) {
      void configStore.checkTushareStatus().catch(() => undefined)
    }
  } else {
    void refreshAfterStatusReady(false)
  }

  // 检查增量更新状态
  void checkIncrementalStatus()
  if (canUseMiddayAnalysis.value) {
    void loadMiddayData()
  }
})

onActivated(() => {
  // 通知轮询管理器本页面已激活，恢复属于本页面的轮询
  activatePagePolls('tomorrow-star')

  // 从其他页面返回时，若内存中已有主数据，则优先复用当前视图，
  // 只做轻量状态检查，避免右侧列表反复重拉造成“又刷新了一次”的体感。
  const hasPrimaryData = historyData.value.length > 0 || latestCandidates.value.length > 0
  if (hasPrimaryData) {
    void checkIncrementalStatus()
  } else {
    void refreshAfterStatusReady()
    void checkIncrementalStatus()
  }
  if (activeTab.value === 'midday-analysis' && canUseMiddayAnalysis.value) {
    void loadMiddayData(true)
  } else if (activeTab.value === 'current-hot') {
    if (currentHotLoaded.value) {
      void loadCurrentHotData(true)
    } else {
      void loadCurrentHotData()
    }
  }
})

watch(activeTab, (value) => {
  if (value === 'midday-analysis' && !canUseMiddayAnalysis.value) {
    activeTab.value = 'tomorrow-star'
    return
  }
  if (value === 'midday-analysis' && !middayLoaded.value) {
    void loadMiddayData()
    return
  }
  if (value === 'current-hot' && !currentHotLoaded.value) {
    void loadCurrentHotData()
    return
  }
  if (value === 'closing-analysis' && !closingReportLoaded.value) {
    void loadClosingReport()
  }
})

watch(middaySource, () => {
  if (activeTab.value === 'midday-analysis' && canUseMiddayAnalysis.value) {
    void loadMiddayData()
  }
})

watch(canUseMiddayAnalysis, (allowed) => {
  if (!allowed && activeTab.value === 'midday-analysis') {
    activeTab.value = 'tomorrow-star'
  }
})

watch(currentHotBoardFilter, () => {
  currentHotCandidatePage.value = 1
  currentHotAnalysisPage.value = 1
})

watch(currentHotRiskFilter, () => {
  currentHotCandidatePage.value = 1
  currentHotAnalysisPage.value = 1
})

watch([activeDataTab, activeConceptUniverseSignature], () => {
  if (!candidateConceptQuery.value.trim()) return
  void applyCandidateConceptFilter()
})

watch(tomorrowStarIndustryOptions, (options) => {
  const available = new Set(options.map((option) => option.name))
  const nextSelected = selectedTomorrowStarIndustries.value.filter((item) => available.has(item))
  if (nextSelected.length !== selectedTomorrowStarIndustries.value.length) {
    selectedTomorrowStarIndustries.value = nextSelected
  }
  latestCandidatePage.value = 1
})

watch(signalReturnDialogVisible, (visible) => {
  if (visible) return
  signalReturnSelectedCode.value = ''
  signalReturnData.value = null
  signalReturnError.value = null
  disposeSignalReturnChart()
})

onDeactivated(() => {
  deactivatePagePolls('tomorrow-star')
  cancelAllPageRequests()
  loading.value = false
  loadingLatest.value = false
  checkingFreshness.value = false
  disposeSignalReturnChart()
})

onUnmounted(() => {
  unregisterPoll(INCREMENTAL_POLL_KEY)
  cancelAllPageRequests()
  window.removeEventListener('resize', handleWindowResize)
  disposeSignalReturnChart()
})
</script>

<style scoped lang="scss">
// 8px 网格系统
$space-xs: 8px;
$space-sm: 16px;
$space-md: 24px;
$space-lg: 32px;

.tomorrow-star-page {
  padding: 0;
  margin: 0;

  .page-alert {
    margin-bottom: $space-sm;
  }

  .page-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 560px;
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
  }

  .update-progress-card {
    margin-bottom: $space-sm;
    border: 1px solid #409eff;
    background: #f0f9ff;

    :deep(.el-card__body) {
      padding: $space-sm;
    }

    .progress-content {
      .progress-info {
        display: flex;
        align-items: center;
        gap: $space-xs;
        margin-bottom: $space-xs;

        .progress-text {
          font-weight: 500;
          color: #409eff;
          font-size: 14px;
        }

        .progress-detail {
          color: #606266;
          font-size: 13px;
        }

        .current-code {
          margin-left: auto;
          color: #909399;
          font-size: 12px;
        }
      }
    }
  }

  // 统一卡片样式
  .el-card {
    border-radius: 8px;

    :deep(.el-card__header) {
      padding: $space-xs $space-sm;
      border-bottom: 1px solid #ebeef5;
    }

    :deep(.el-card__body) {
      padding: $space-sm;
    }
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 32px;

    .title-section {
      display: flex;
      align-items: center;
      gap: $space-xs;
      font-size: 14px;
      font-weight: 500;

      .date-tag {
        font-size: 12px;
      }
    }

    .header-actions {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: $space-xs;
      min-width: 0;
    }
  }

  .top-grid {
    display: grid;
    grid-template-columns: clamp(208px, 13vw, 240px) minmax(0, 1fr);
    gap: 16px;
    align-items: stretch;
    min-height: calc(100vh - 174px);

    &.is-current-hot {
      grid-template-columns: clamp(360px, 22vw, 420px) minmax(0, 1fr);
    }
  }

  .history-column,
  .content-column {
    min-width: 0;
    display: flex;
  }

  .board-filter,
  .source-switch {
    :deep(.el-radio-group__item),
    :deep(.el-radio-button__inner) {
      border-radius: 4px;
    }
  }

  .industry-filter-panel {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: $space-xs;
    padding: 8px;
    border: 1px solid #ebeef5;
    border-radius: 6px;
    background: #fafafa;
  }

  .candidate-concept-filter {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: $space-xs;

    :deep(.el-input),
    :deep(.el-autocomplete) {
      flex: 1 1 auto;
    }
  }

  .candidate-concept-suggestion {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;

    small {
      color: #909399;
      font-size: 12px;
    }
  }

  .candidate-concept-filter__summary {
    margin: -4px 0 $space-xs;
    font-size: 12px;
    color: #909399;
  }

  .candidate-concept-filter--mobile {
    margin-bottom: 8px;
  }

  .candidate-concept-filter__summary--mobile {
    margin-top: 0;
  }

  .industry-filter-chip {
    flex: 0 0 auto;
    border: 1px solid #dcdfe6;
    border-radius: 4px;
    background: #fff;
    color: #606266;
    font-size: 12px;
    line-height: 20px;
    padding: 0 8px;
    cursor: pointer;
    white-space: nowrap;
    transition: color 0.15s ease, border-color 0.15s ease, background-color 0.15s ease;

    &:hover {
      color: #409eff;
      border-color: #a0cfff;
      background: #ecf5ff;
    }

    &.active {
      color: #1d4ed8;
      border-color: #409eff;
      background: #ecf5ff;
      font-weight: 600;
    }
  }

  .mobile-layout {
    display: flex;
    flex-direction: column;
    gap: $space-sm;
  }

  .mobile-section-card {
    .mobile-tip {
      margin-bottom: $space-sm;
    }
  }

  .mobile-history-list,
  .mobile-analysis-list {
    display: flex;
    flex-direction: column;
    gap: $space-xs;
  }

  .mobile-history-item,
  .mobile-analysis-item {
    width: 100%;
    padding: 12px;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    background: #fff;
    text-align: left;
    cursor: pointer;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
  }

  .mobile-history-item.active {
    border-color: #409eff;
    box-shadow: 0 0 0 1px rgba(64, 158, 255, 0.12);
    background: #f7fbff;
  }

  .mobile-history-item__header,
  .mobile-analysis-item__header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: $space-xs;
  }

  .mobile-history-item__date,
  .mobile-analysis-item__code {
    font-size: 14px;
    font-weight: 600;
    color: #1f2937;
  }

  .mobile-history-item__status {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 4px;
  }

  .mobile-history-item__meta,
  .mobile-analysis-item__meta {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-top: 10px;
    font-size: 13px;
    color: #606266;
  }

  .market-regime-empty {
    margin: 16px auto 0;
    padding: 16px;
    max-width: 720px;
    border: 1px solid #f3d19e;
    border-radius: 12px;
    background: linear-gradient(180deg, #fff9ef 0%, #fffdf8 100%);
    color: #7c4a03;
    text-align: left;
  }

  .market-regime-empty--desktop {
    margin: 20px 0 0;
    min-height: 400px;
    display: flex;
    flex-direction: column;
    justify-content: center;
  }

  .market-regime-empty__title {
    font-size: 16px;
    font-weight: 600;
    color: #9a3412;
  }

  .market-regime-empty__summary {
    margin-top: 10px;
    font-size: 14px;
    line-height: 1.7;
  }

  .market-regime-empty__list {
    margin: 12px 0 0;
    padding-left: 18px;
    line-height: 1.8;
  }

  .market-regime-empty__hint {
    margin-top: 12px;
    font-size: 13px;
    line-height: 1.7;
    color: #92400e;
  }

  .mobile-analysis-item__name {
    margin-top: 4px;
    font-size: 13px;
    color: #606266;
  }

  .mobile-analysis-item__comment {
    line-height: 1.5;
    color: #374151;
    word-break: break-word;
  }

  .analysis-pullback-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .midday-layout {
    display: flex;
    flex-direction: column;
  }

  .midday-card {
    .midday-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: $space-sm;
    }

    .midday-empty-note {
      margin-top: 8px;
      color: #606266;
      line-height: 1.6;
      text-align: center;
      max-width: 420px;
    }
  }

  .midday-mobile-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .midday-mobile-plan {
    line-height: 1.5;
    color: #374151;
    word-break: break-word;
  }

  .mobile-pagination {
    flex-direction: column;
    align-items: center;
    gap: 8px;
    justify-content: center;

    .mobile-pagination__summary {
      font-size: 12px;
      color: #64748b;
      line-height: 1;
    }
  }

  // 统一提示框样式
  .table-header-tip {
    margin-bottom: $space-xs;
    padding: $space-xs $space-xs;
    background-color: #f5f7fa;
    border-radius: 4px;
    font-size: 12px;
    color: #606266;
    line-height: 1.6;

    .tip-item {
      margin-right: $space-sm;

      &:last-child {
        margin-right: 0;
      }
    }
  }

  .risk-regime-banner {
    margin-bottom: 10px;
    padding: 12px;
    border-radius: 12px;
    border: 1px solid #fed7aa;
    background: linear-gradient(180deg, #fffbeb 0%, #fff7ed 100%);

    &__header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 6px;
    }

    &__title {
      font-size: 14px;
      font-weight: 600;
      color: #9a3412;
    }

    &__tags {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    &__summary {
      margin: 0 0 8px;
      color: #7c2d12;
      font-size: 13px;
      line-height: 1.6;
    }

    &__meta {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      color: #9a3412;
      font-size: 12px;
    }
  }

  .history-card {
    height: 100%;

    .history-table {
      flex: 1 1 auto;
      font-size: 12px;

      :deep(.el-table__row) {
        cursor: pointer;

        &:hover {
          background-color: #f0f9ff;
        }
      }

      :deep(.el-table__cell) {
        padding: 5px 0;
      }

      :deep(.cell) {
        padding: 0 10px;
      }
    }

  }

  .candidates-card {
    :deep(.el-card__body) {
      overflow: hidden;
    }

    .candidates-table {
      flex: 1 1 auto;
      min-height: 200px;
      width: 100%;
      font-size: 12px;

      :deep(.cell) {
        white-space: nowrap;
        padding: 0 5px;
      }

      :deep(.el-table__cell) {
        padding: 5px 0;
      }

      :deep(.el-table-fixed-column--right::before),
      :deep(.el-table-fixed-column--right::after) {
        display: none;
      }
    }

    .pagination-wrap {
      display: flex;
      justify-content: flex-end;
      margin-top: $space-xs;
      flex-shrink: 0;
      min-height: 32px;
    }

    .el-divider {
      margin: $space-sm 0;
      flex-shrink: 0;
    }

    .analysis-section {
      flex-shrink: 0;
      overflow: hidden;
      padding: 0 $space-xs;

      .analysis-tip {
        margin-bottom: $space-xs;
        padding: $space-xs $space-xs;
        background-color: #e8f4fd;
        border-radius: 4px;
        font-size: 12px;
        color: #409eff;
        line-height: 1.6;
      }

      h4 {
        margin: 0 0 $space-xs 0;
        font-size: 14px;
        font-weight: 500;
        color: var(--color-text-secondary);
      }
    }
  }

  .history-card {
    .pagination-wrap {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-top: $space-xs;
      flex-shrink: 0;
      min-height: 32px;
      overflow: hidden;
    }

    .pagination-total {
      flex: 0 0 auto;
      font-size: 12px;
      color: #64748b;
      white-space: nowrap;
    }

    :deep(.el-pagination) {
      min-width: 0;
      justify-content: flex-end;
      overflow: hidden;
    }

    :deep(.el-pager) {
      max-width: 212px;
      overflow: hidden;
    }
  }

  // 统一 el-divider 样式
  .el-divider {
    margin: $space-sm 0;
  }

  // 统一 el-tag 样式
  .el-tag {
    border-radius: 4px;
  }

  // 统一按钮样式
  .el-button {
    border-radius: 4px;
  }

  .stock-name-cell {
    display: inline-block;
    max-width: 4em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    vertical-align: bottom;
  }

  .table-header-help {
    cursor: help;
    text-decoration: underline dotted;
    text-underline-offset: 3px;
  }
}

@media (max-width: 767px) {
  .tomorrow-star-page {
    min-height: auto;

    .update-progress-card {
      .progress-content {
        .progress-info {
          flex-wrap: wrap;

          .current-code {
            margin-left: 0;
            width: 100%;
          }
        }
      }
    }

    .table-header-tip {
      .tip-item {
        display: block;
        margin-right: 0;
      }
    }

    .card-header {
      align-items: flex-start;
    }

    .board-filter,
    .source-switch {
      width: 100%;
    }
  }

  .matched-height,
  .history-card,
  .candidates-card {
    height: auto;
    min-height: 0;

    :deep(.el-card__body) {
      overflow: visible;
    }
  }
}

// 等高卡片
.matched-height {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;

  :deep(.el-card__body) {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
}

.history-card {
  :deep(.el-card__body) {
    overflow: hidden;
  }

  .history-table {
    flex: 1;
  }
}

.candidates-card {
  :deep(.el-card__body) {
    overflow: hidden;
  }

  .candidates-table {
    flex: 1;
  }

  .pagination-wrap {
    flex-shrink: 0;
  }

  .el-divider {
    flex-shrink: 0;
  }

  .analysis-section {
    flex-shrink: 0;
  }
}

.midday-plan-action {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;

  span:last-child {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}

.midday-market-overview {
  margin: 10px 0 14px;
  padding: 12px 14px;
  border-radius: 10px;
  background: linear-gradient(135deg, #f4fbf7, #eef8ff);
  border: 1px solid #d8ecdf;
}

.midday-market-overview__summary {
  font-size: 13px;
  line-height: 1.7;
  color: #1f2937;
  font-weight: 600;
}

.midday-market-overview__items {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.midday-market-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.9);
  color: #475569;
  font-size: 12px;
}

.midday-mobile-prices,
.midday-mobile-relative,
.midday-mobile-prev {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: #475569;
}

.midday-mobile-prices {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

// 涨跌颜色
.text-up {
  color: #e74c3c;
}

.text-down {
  color: #2ecc71;
}

// 信号收益率分析弹窗样式
.signal-return-dialog {
  .el-dialog {
    margin-top: 5vh !important;
  }

  .el-dialog__header {
    padding: 10px 15px;
    margin-right: 0;
  }

  .el-dialog__body {
    padding: 5px 15px 10px;
  }

  .el-dialog__footer {
    padding: 5px 15px 10px;
  }

  .signal-return-content {
    min-height: 80px;
  }

  .signal-return-body {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .signal-return-chart-panel {
    padding: 14px;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    background:
      radial-gradient(circle at top right, rgba(191, 219, 254, 0.45), transparent 32%),
      linear-gradient(135deg, #fcfdff, #f7fafc);
  }

  .signal-return-chart-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
  }

  .signal-return-chart-heading {
    min-width: 0;
  }

  .signal-return-chart-title {
    font-size: 16px;
    font-weight: 700;
    color: #111827;
    line-height: 1.4;
  }

  .signal-return-chart-subtitle {
    margin-top: 4px;
    font-size: 12px;
    color: #64748b;
    line-height: 1.5;
  }

  .signal-return-selector {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    justify-content: flex-end;
  }

  .signal-return-selector__button {
    min-width: 102px;
    padding: 7px 10px;
    border: 1px solid #dbeafe;
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.92);
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
    cursor: pointer;
    transition: border-color 0.2s ease, background 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;

    &:hover {
      border-color: #93c5fd;
      transform: translateY(-1px);
    }

    &.is-active {
      border-color: #2563eb;
      background: #eff6ff;
      box-shadow: 0 6px 18px rgba(37, 99, 235, 0.12);
    }

    .selector-code {
      font-size: 12px;
      font-weight: 700;
      color: #1e3a8a;
      line-height: 1.2;
    }

    .selector-name {
      font-size: 11px;
      color: #475569;
      line-height: 1.3;
    }
  }

  .signal-return-summary {
    margin-top: 12px;
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
  }

  .signal-return-summary__item {
    padding: 10px 12px;
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.88);
    border: 1px solid #e5edf6;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .signal-return-summary__item .summary-label {
    font-size: 11px;
    color: #64748b;
    letter-spacing: 0.02em;
  }

  .signal-return-summary__item .summary-value {
    font-size: 14px;
    font-weight: 600;
    color: #111827;
    line-height: 1.4;
  }

  .signal-return-chart {
    margin-top: 12px;
    height: 340px;
    width: 100%;
  }

  .signal-return-chart-empty {
    margin-top: 12px;
    height: 240px;
    border-radius: 10px;
    border: 1px dashed #cbd5e1;
    background: rgba(255, 255, 255, 0.72);
    display: flex;
    align-items: center;
    justify-content: center;
    color: #94a3b8;
    font-size: 13px;
  }

  .signal-return-events {
    margin-top: 12px;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 8px;
  }

  .signal-return-event {
    padding: 10px 12px;
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.92);
    border: 1px solid #e5e7eb;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .signal-return-event__label {
    font-size: 12px;
    font-weight: 700;
    color: #1f2937;
  }

  .signal-return-event__date,
  .signal-return-event__price {
    font-size: 11px;
    color: #64748b;
    line-height: 1.4;
  }

  .signal-return-event__return {
    font-size: 13px;
    font-weight: 700;
    line-height: 1.4;
  }

  .signal-return-table-wrap {
    overflow-x: auto;
  }

  .signal-return-table-tip {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 8px;
    font-size: 12px;
    color: #64748b;
  }

  .signal-return-table {
    min-width: 1180px;

    :deep(.el-table__header th) {
      padding: 5px 0;
      font-size: 12px;
      color: #6b7280;
      background: #fafafa;
    }

    :deep(.el-table__header th .cell) {
      white-space: nowrap !important;
      word-break: keep-all;
      line-height: 1.3;
      padding: 0 6px;
      overflow: visible;
      font-weight: 600;
    }

    :deep(.el-table__header-wrapper tr:first-child th) {
      border-bottom: 0;
      background: #f5f7fa;
    }

    :deep(.el-table__header-wrapper tr:last-child th) {
      background: #fafafa;
    }

    .signal-return-header-help {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: help;
    }

    :deep(.el-table__body td) {
      padding: 6px 0;
      font-size: 12px;
    }

    :deep(.el-table__body td .cell) {
      white-space: nowrap !important;
      word-break: keep-all;
      line-height: 1.3;
      padding: 0 6px;
      overflow: visible;
      text-overflow: clip;
    }

    :deep(.el-table__body tr) {
      cursor: pointer;
    }

    :deep(.el-table__body tr.signal-return-row--active > td) {
      background: #eff6ff !important;
    }

    // 确保收益率数字不换行
    .return-up,
    .return-down {
      white-space: nowrap !important;
      display: inline-block;
    }
  }

  .signal-return-footer {
    display: flex;
    justify-content: flex-end;
  }

  .error-message,
  .empty-message {
    text-align: center;
    padding: 15px;
    color: #909399;
    font-size: 13px;
  }

  @media (max-width: 768px) {
    .signal-return-summary {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .signal-return-chart {
      height: 280px;
    }

    .signal-return-selector__button {
      min-width: 92px;
    }
  }
}

// 中国股市习惯：红涨绿跌
.return-up {
  color: #f56c6c;
  font-weight: 500;
}

.return-down {
  color: #67c23a;
  font-weight: 500;
}

.closing-layout {
  width: 100%;
}

.closing-card {
  min-height: 520px;
}

.closing-summary-grid,
.closing-flow-grid,
.closing-candidate-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 14px 0;
}

.closing-flow-grid,
.closing-candidate-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.closing-summary-card {
  padding: 14px 16px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #64748b;

  strong {
    font-size: 22px;
    color: #111827;
  }
}

.closing-summary-card__label {
  font-size: 12px;
  font-weight: 700;
  color: #334155;
}

.closing-candidate-tabs {
  margin-top: 16px;

  h4 {
    margin: 0 0 8px;
    color: #1f2937;
  }
}

.closing-prediction-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
  color: #64748b;

  h4 {
    margin: 0 0 4px;
  }
}

.closing-prediction-table {
  min-width: 1180px;
}

@media (max-width: 768px) {
  .closing-summary-grid,
  .closing-flow-grid,
  .closing-candidate-grid {
    grid-template-columns: 1fr;
  }
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
}
</style>
