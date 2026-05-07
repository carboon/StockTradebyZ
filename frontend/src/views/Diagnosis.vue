<template>
  <div class="diagnosis-page">
    <el-alert
      v-if="showInitializationAlert"
      class="page-alert"
      type="info"
      :closable="false"
      show-icon
      title="尚未完成首次初始化"
      :description="configStore.initializationMessage"
    />

    <!-- 搜索栏 -->
    <el-card class="search-card">
      <el-form :inline="true" :model="searchForm" class="search-form-row" @submit.prevent="searchAndAnalyze">
        <el-form-item label="代码或名称">
          <el-autocomplete
            v-model="searchForm.code"
            clearable
            class="search-input"
            placeholder="请输入股票代码或名称"
            :fetch-suggestions="fetchStockSuggestions"
            @select="handleStockSuggestionSelect"
            @keyup.enter="searchAndAnalyze"
          >
            <template #default="{ item }">
              <div class="stock-suggestion">
                <span class="suggestion-code">{{ item.code }}</span>
                <span class="suggestion-name">{{ item.name || '-' }}</span>
              </div>
            </template>
          </el-autocomplete>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="searchAndAnalyze">
            诊断
          </el-button>
        </el-form-item>
        <el-form-item v-if="stockCode">
          <el-button @click="addCurrentToWatchlist" :loading="addingToWatchlist" :disabled="isInWatchlist">
            {{ isInWatchlist ? '已纳入重点观察' : '纳入重点观察' }}
          </el-button>
        </el-form-item>
        <el-form-item v-if="analyzing">
          <el-tag type="primary" effect="plain">分析中...</el-tag>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 分析结果 -->
    <template v-if="stockCode">
      <el-row :gutter="20" class="content-row">
        <!-- K线图 -->
        <el-col :span="isMobileViewport ? 24 : 16">
          <el-card class="chart-card">
            <template #header>
              <div class="card-header">
                <div class="chart-header-main">
                  <div class="stock-identity">
                    <div class="stock-line">
                      <span class="stock-code">{{ stockCode }}</span>
                      <span v-if="stockName" class="stock-name">{{ stockName }}</span>
                    </div>
                    <div class="chart-meta">
                      <span class="chart-title">单股诊断 K线图</span>
                      <span class="chart-subtitle">按最近交易日展示趋势区间</span>
                    </div>
                  </div>
                </div>
                <div class="chart-toolbar">
                  <span class="chart-toolbar-label">观察区间</span>
                  <div
                    v-if="!isMobileViewport"
                    class="chart-range-switcher"
                    role="tablist"
                    aria-label="K线区间选择"
                  >
                    <button
                      v-for="days in chartDayOptions"
                      :key="days"
                      type="button"
                      class="chart-range-button"
                      :class="{ 'is-active': chartDays === days }"
                      :aria-pressed="chartDays === days"
                      @click="selectChartDays(days)"
                    >
                      {{ days }}天
                    </button>
                  </div>
                  <div v-else class="chart-range-mobile">
                    <el-select
                      :model-value="chartDays"
                      size="small"
                      class="chart-range-select"
                      aria-label="K线区间选择"
                      @change="selectChartDays"
                    >
                      <el-option
                        v-for="days in chartDayOptions"
                        :key="days"
                        :label="`${days}天`"
                        :value="days"
                      />
                    </el-select>
                    <span v-if="isTomorrowStarMobileSource" class="chart-range-hint">
                      来自明日之星，默认展示30天
                    </span>
                  </div>
                </div>
              </div>
            </template>
            <div ref="chartRef" class="chart-container" />
          </el-card>
        </el-col>

        <!-- 分析面板 -->
        <el-col :span="isMobileViewport ? 24 : 8">
          <el-card class="analysis-card">
            <div v-if="analysisResult" class="analysis-content">
              <div v-if="isMobileViewport" class="analysis-summary-grid">
                <div class="summary-tile">
                  <span class="summary-label">当前评分</span>
                  <el-tag :type="getScoreType(analysisResult.score)" size="large">
                    {{ analysisResult.score != null ? analysisResult.score.toFixed(1) : '-' }}
                  </el-tag>
                </div>
                <div class="summary-tile">
                  <span class="summary-label">B1检查</span>
                  <el-tag :type="analysisResult.b1_passed ? 'success' : 'danger'">
                    {{ analysisResult.b1_passed ? '通过' : '未通过' }}
                  </el-tag>
                </div>
                <div class="summary-tile verdict-tile">
                  <span class="summary-label">
                    趋势判断
                    <el-tooltip raw-content content="PASS: 趋势启动，建议关注<br/>WATCH: 结构偏多，继续观察<br/>FAIL: 条件不足，暂不关注" placement="top">
                      <el-icon class="info-icon"><InfoFilled /></el-icon>
                    </el-tooltip>
                  </span>
                  <span class="value">{{ analysisResult.verdict || '-' }}</span>
                </div>
              </div>

              <template v-else>
                <div class="analysis-item">
                  <span class="label">当前评分</span>
                  <el-tag :type="getScoreType(analysisResult.score)" size="large">
                    {{ analysisResult.score != null ? analysisResult.score.toFixed(1) : '-' }}
                  </el-tag>
                </div>

                <div class="analysis-item">
                  <span class="label">B1检查</span>
                  <el-tag :type="analysisResult.b1_passed ? 'success' : 'danger'">
                    {{ analysisResult.b1_passed ? '通过' : '未通过' }}
                  </el-tag>
                </div>

                <div class="analysis-item">
                  <span class="label">
                    趋势判断
                    <el-tooltip raw-content content="PASS: 趋势启动，建议关注<br/>WATCH: 结构偏多，继续观察<br/>FAIL: 条件不足，暂不关注" placement="top">
                      <el-icon class="info-icon"><InfoFilled /></el-icon>
                    </el-tooltip>
                  </span>
                  <span class="value">{{ analysisResult.verdict || '-' }}</span>
                </div>
              </template>

              <el-divider />

              <div v-if="isMobileViewport" class="mobile-analysis-panels">
                <p class="mobile-analysis-summary">{{ analysisResult.comment || '暂无补充说明' }}</p>
                <el-collapse v-model="mobileAnalysisSections">
                  <el-collapse-item name="b1">
                    <template #title>
                      <span class="collapse-title">B1检查详情</span>
                    </template>
                    <div class="b1-details">
                      <div class="detail-item">
                        <span class="detail-label">
                          KDJ-J
                          <el-tooltip raw-content content="KDJ指标中的J值<br/>反映价格超买超卖状态<br/>J值低于0表示超卖<br/>高于100表示超买<br/>B1策略寻找J值处于低位的股票" placement="top">
                            <el-icon class="info-icon"><InfoFilled /></el-icon>
                          </el-tooltip>
                        </span>
                        <span class="detail-value">{{ analysisResult.kdj_j != null ? analysisResult.kdj_j.toFixed(1) : '-' }}</span>
                      </div>
                      <div class="detail-item">
                        <span class="detail-label">
                          知行线多头
                          <el-tooltip raw-content content="知行线是特殊均线系统<br/>当短期线上穿长期线时<br/>表示趋势转多<br/>股价处于上升通道" placement="top">
                            <el-icon class="info-icon"><InfoFilled /></el-icon>
                          </el-tooltip>
                        </span>
                        <el-tag :type="analysisResult.zx_long_pos ? 'success' : 'info'" size="small">
                          {{ analysisResult.zx_long_pos ? '是' : '否' }}
                        </el-tag>
                      </div>
                      <div class="detail-item">
                        <span class="detail-label">
                          周线多头
                          <el-tooltip raw-content content="周线级别均线呈多头排列<br/>短期均线>中期均线>长期均线<br/>表示中期趋势向上<br/>股票处于稳健上涨阶段" placement="top">
                            <el-icon class="info-icon"><InfoFilled /></el-icon>
                          </el-tooltip>
                        </span>
                        <el-tag :type="analysisResult.weekly_ma_aligned ? 'success' : 'info'" size="small">
                          {{ analysisResult.weekly_ma_aligned ? '是' : '否' }}
                        </el-tag>
                      </div>
                      <div class="detail-item">
                        <span class="detail-label">
                          量能健康
                          <el-tooltip raw-content content="成交量处于合理水平<br/>既不过度萎缩(缺乏人气)<br/>也不过度放大(可能透支)<br/>健康的量能配合价格上涨<br/>是持续上涨的基础" placement="top">
                            <el-icon class="info-icon"><InfoFilled /></el-icon>
                          </el-tooltip>
                        </span>
                        <el-tag :type="analysisResult.volume_healthy ? 'success' : 'info'" size="small">
                          {{ analysisResult.volume_healthy ? '是' : '否' }}
                        </el-tag>
                      </div>
                    </div>
                  </el-collapse-item>

                  <el-collapse-item v-if="analysisResult.scores && Object.keys(analysisResult.scores).length > 0" name="scores">
                    <template #title>
                      <span class="collapse-title">评分明细</span>
                    </template>
                    <div class="score-details">
                      <p class="score-summary">{{ analysisResult.comment || '-' }}</p>
                      <div class="score-grid">
                        <div class="score-item" v-for="item in scoreItems" :key="item.key">
                          <div class="score-header">
                            <span class="score-label">{{ item.label }}</span>
                            <el-tag :type="getScoreType(item.value)" size="small">
                              {{ item.value || 0 }}/5
                            </el-tag>
                          </div>
                          <div class="score-reason">{{ item.reason || '-' }}</div>
                        </div>
                      </div>
                      <div v-if="analysisResult.signal_type" class="signal-type-box">
                        <span class="signal-label">信号类型:</span>
                        <el-tag :type="getSignalTagType(analysisResult.signal_type)" size="small">
                          {{ getSignalLabel(analysisResult.signal_type) }}
                        </el-tag>
                        <span class="signal-reason">{{ analysisResult.signal_reasoning || '' }}</span>
                      </div>
                    </div>
                  </el-collapse-item>
                </el-collapse>
              </div>
              <template v-else>
                <div class="b1-details">
                  <div class="section-header">
                    <h5>B1检查详情</h5>
                  </div>
                  <div class="detail-item">
                    <span class="detail-label">
                      KDJ-J
                      <el-tooltip raw-content content="KDJ指标中的J值<br/>反映价格超买超卖状态<br/>J值低于0表示超卖<br/>高于100表示超买<br/>B1策略寻找J值处于低位的股票" placement="top">
                        <el-icon class="info-icon"><InfoFilled /></el-icon>
                      </el-tooltip>
                    </span>
                    <span class="detail-value">{{ analysisResult.kdj_j != null ? analysisResult.kdj_j.toFixed(1) : '-' }}</span>
                  </div>
                  <div class="detail-item">
                    <span class="detail-label">
                      知行线多头
                      <el-tooltip raw-content content="知行线是特殊均线系统<br/>当短期线上穿长期线时<br/>表示趋势转多<br/>股价处于上升通道" placement="top">
                        <el-icon class="info-icon"><InfoFilled /></el-icon>
                      </el-tooltip>
                    </span>
                    <el-tag :type="analysisResult.zx_long_pos ? 'success' : 'info'" size="small">
                      {{ analysisResult.zx_long_pos ? '是' : '否' }}
                    </el-tag>
                  </div>
                  <div class="detail-item">
                    <span class="detail-label">
                      周线多头
                      <el-tooltip raw-content content="周线级别均线呈多头排列<br/>短期均线>中期均线>长期均线<br/>表示中期趋势向上<br/>股票处于稳健上涨阶段" placement="top">
                        <el-icon class="info-icon"><InfoFilled /></el-icon>
                      </el-tooltip>
                    </span>
                    <el-tag :type="analysisResult.weekly_ma_aligned ? 'success' : 'info'" size="small">
                      {{ analysisResult.weekly_ma_aligned ? '是' : '否' }}
                    </el-tag>
                  </div>
                  <div class="detail-item">
                    <span class="detail-label">
                      量能健康
                      <el-tooltip raw-content content="成交量处于合理水平<br/>既不过度萎缩(缺乏人气)<br/>也不过度放大(可能透支)<br/>健康的量能配合价格上涨<br/>是持续上涨的基础" placement="top">
                        <el-icon class="info-icon"><InfoFilled /></el-icon>
                      </el-tooltip>
                    </span>
                    <el-tag :type="analysisResult.volume_healthy ? 'success' : 'info'" size="small">
                      {{ analysisResult.volume_healthy ? '是' : '否' }}
                    </el-tag>
                  </div>
                </div>

                <template v-if="analysisResult.scores && Object.keys(analysisResult.scores).length > 0">
                  <el-divider />

                  <div class="score-details">
                    <div class="section-header">
                      <h5>评分明细</h5>
                    </div>
                    <p class="score-summary">{{ analysisResult.comment || '-' }}</p>

                    <div class="score-grid">
                      <div class="score-item" v-for="item in scoreItems" :key="item.key">
                        <div class="score-header">
                          <span class="score-label">{{ item.label }}</span>
                          <el-tag :type="getScoreType(item.value)" size="small">
                            {{ item.value || 0 }}/5
                          </el-tag>
                        </div>
                        <el-tooltip :content="item.reason || '-'" placement="top" :disabled="!item.reason">
                          <div class="score-reason">{{ item.reason || '-' }}</div>
                        </el-tooltip>
                      </div>
                    </div>

                    <div v-if="analysisResult.signal_type" class="signal-type-box">
                      <span class="signal-label">信号类型:</span>
                      <el-tag :type="getSignalTagType(analysisResult.signal_type)" size="small">
                        {{ getSignalLabel(analysisResult.signal_type) }}
                      </el-tag>
                      <span class="signal-reason">{{ analysisResult.signal_reasoning || '' }}</span>
                    </div>
                  </div>
                </template>
              </template>
            </div>

            <el-empty v-else description="暂无分析数据" :image-size="80" />
          </el-card>
        </el-col>
      </el-row>

      <!-- 历史记录 -->
      <el-card class="history-card">
        <template #header>
          <div class="history-header">
            <span>每日检查历史 (近180个交易日收盘后回放)</span>
            <div class="history-actions">
              <span v-if="refreshingHistory" class="refreshing-text">
                正在刷新... ({{ historyData.length }}/180)
              </span>
              <el-button
                type="primary"
                size="small"
                :icon="Refresh"
                :loading="refreshingHistory"
                @click="refreshHistory"
              >
                {{ refreshingHistory ? '读取中...' : '读取/刷新历史展示' }}
              </el-button>
            </div>
          </div>
        </template>
        <div v-if="isMobileViewport" class="history-mobile-list">
          <el-empty v-if="historyData.length === 0" description="暂无历史数据" :image-size="72" />
          <div v-else class="history-card-list">
            <article v-for="row in historyData" :key="row.check_date" class="history-summary-card">
              <div class="history-card-head">
                <div class="history-date-block">
                  <span class="history-date">{{ formatDate(row.check_date) }}</span>
                  <span class="history-price">
                    收盘 {{ row.close_price != null ? row.close_price.toFixed(2) : '-' }}
                  </span>
                </div>
                <span :class="['history-change', getChangeClass(row.change_pct)]">
                  {{ formatChange(row.change_pct) }}
                </span>
              </div>
              <div class="history-card-tags">
                <el-tag :type="getGateTagType(row.in_active_pool)" size="small">活跃池 {{ getGateLabel(row.in_active_pool) }}</el-tag>
                <el-tag :type="getGateTagType(row.b1_passed)" size="small">B1 {{ getGateLabel(row.b1_passed) }}</el-tag>
                <el-tag :type="getPrefilterTagType(row.prefilter_passed)" size="small">前置过滤 {{ getGateLabel(row.prefilter_passed) }}</el-tag>
                <el-tag v-if="row.verdict" :type="getVerdictType(row.verdict)" size="small">{{ row.verdict }}</el-tag>
                <el-tag v-if="row.signal_type" :type="getSignalTagType(row.signal_type)" size="small">
                  {{ getSignalLabel(row.signal_type) }}
                </el-tag>
                <el-tag :type="getTomorrowStarTagType(row.tomorrow_star_pass)" size="small">
                  明日之星 {{ getGateLabel(row.tomorrow_star_pass) }}
                </el-tag>
              </div>
              <div class="history-card-footer">
                <div class="history-score-line">
                  <span class="history-score-label">量化评分</span>
                  <el-tag v-if="row.score != null" :type="getScoreType(row.score)" size="small">
                    {{ row.score.toFixed(1) }}
                  </el-tag>
                  <span v-else>-</span>
                </div>
                <el-button size="small" @click="openHistoryDetail(row)">
                  {{ row.detail_ready ? '查看详情' : '生成详情' }}
                </el-button>
              </div>
            </article>
          </div>
        </div>
        <div v-else class="history-table-wrap">
          <el-table
            :data="historyData"
            stripe
            size="small"
            max-height="420"
            table-layout="auto"
            min-width="1060"
          >
          <el-table-column prop="check_date" label="交易日" width="110">
            <template #default="{ row }">
              {{ formatDate(row.check_date) }}
            </template>
          </el-table-column>
          <el-table-column prop="close_price" label="收盘价" width="90" align="right">
            <template #default="{ row }">
              {{ row.close_price != null ? row.close_price.toFixed(2) : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="change_pct" label="涨跌幅" width="80" align="right">
            <template #default="{ row }">
              <span :class="getChangeClass(row.change_pct)">
                {{ formatChange(row.change_pct) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="in_active_pool" width="90" align="center">
            <template #header>
              <span class="table-header-label">
                活跃池
                <el-tooltip content="是否进入当日活跃池；不在活跃池时，后续候选与明日之星口径通常不成立。" placement="top">
                  <el-icon class="table-info-icon"><InfoFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
            <template #default="{ row }">
              <el-tag :type="getGateTagType(row.in_active_pool)" size="small">
                {{ getGateLabel(row.in_active_pool) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="b1_passed" width="60" align="center">
            <template #header>
              <span class="table-header-label">
                B1
                <el-tooltip content="B1 原始策略信号，主要检查 KDJ 低位、结构与量能等基础条件。" placement="top">
                  <el-icon class="table-info-icon"><InfoFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
            <template #default="{ row }">
              <el-tag :type="getGateTagType(row.b1_passed)" size="small">
                {{ getGateLabel(row.b1_passed) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="prefilter_passed" width="100" align="center">
            <template #header>
              <span class="table-header-label">
                前置过滤
                <el-tooltip content="对 ST、新股、解禁、市值层、行业强度、市场环境等做前置过滤；未通过会被拦截。" placement="top">
                  <el-icon class="table-info-icon"><InfoFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
            <template #default="{ row }">
              <el-tooltip
                v-if="row.prefilter_passed === false && row.prefilter_blocked_by?.length"
                :content="formatPrefilterBlockedBy(row.prefilter_blocked_by)"
                placement="top"
              >
                <el-tag :type="getPrefilterTagType(row.prefilter_passed)" size="small">
                  {{ getGateLabel(row.prefilter_passed) }}
                </el-tag>
              </el-tooltip>
              <el-tag v-else :type="getPrefilterTagType(row.prefilter_passed)" size="small">
                {{ getGateLabel(row.prefilter_passed) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="score" width="100" align="center">
            <template #header>
              <span class="table-header-label">
                量化评分
                <el-tooltip content="量化模型的综合评分，当前满分 5 分；仅评分高不等于量化结论 PASS。" placement="top">
                  <el-icon class="table-info-icon"><InfoFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
            <template #default="{ row }">
              <el-tag v-if="row.score != null" :type="getScoreType(row.score)" size="small">
                {{ row.score.toFixed(1) }}
              </el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column prop="verdict" label="量化结论" width="100" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.verdict" :type="getVerdictType(row.verdict)" size="small">
                {{ row.verdict }}
              </el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column prop="signal_type" label="信号类型" width="110" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.signal_type" :type="getSignalTagType(row.signal_type)" size="small">
                {{ getSignalLabel(row.signal_type) }}
              </el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column prop="tomorrow_star_pass" label="明日之星" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="getTomorrowStarTagType(row.tomorrow_star_pass)" size="small">
                {{ getGateLabel(row.tomorrow_star_pass) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="详情" width="120" align="center" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="openHistoryDetail(row)">
                {{ row.detail_ready ? '查看详情' : '生成详情' }}
              </el-button>
            </template>
          </el-table-column>
          </el-table>
        </div>
        <div v-if="historyTotal > historyPageSize" class="history-pagination">
          <el-pagination
            v-model:current-page="historyPage"
            :page-size="historyPageSize"
            layout="prev, pager, next"
            :total="historyTotal"
            :hide-on-single-page="false"
            background
            size="small"
            @current-change="handleHistoryPageChange"
          />
        </div>
      </el-card>

      <el-dialog v-model="historyDetailVisible" title="每日检查详情" :width="isMobileViewport ? '94%' : '760px'" :fullscreen="isMobileViewport">
        <div v-loading="historyDetailLoading">
          <template v-if="historyDetailData">
            <div class="history-detail-section">
              <div class="history-detail-title">规则结果</div>
              <pre class="history-detail-pre">{{ formatDetailJson(historyDetailData.payload.rules) }}</pre>
            </div>
            <div class="history-detail-section">
              <div class="history-detail-title">量化评分</div>
              <pre class="history-detail-pre">{{ formatDetailJson(historyDetailData.payload.score_details) }}</pre>
            </div>
            <div class="history-detail-section">
              <div class="history-detail-title">指标快照</div>
              <pre class="history-detail-pre">{{ formatDetailJson(historyDetailData.payload.details) }}</pre>
            </div>
          </template>
          <el-empty v-else description="暂无详情数据" :image-size="72" />
        </div>
      </el-dialog>
    </template>

    <!-- 初始状态 -->
    <el-empty v-else :description="emptyDescription" :image-size="120">
      <el-button v-if="authStore.isAdmin && !configStore.dataInitialized && configStore.tushareReady" type="primary" @click="goTaskCenter">
        前往任务中心初始化
      </el-button>
      <el-button v-if="authStore.isAdmin && !configStore.tushareReady" @click="goConfig">
        前往配置
      </el-button>
    </el-empty>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, onActivated, onDeactivated, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Search, InfoFilled, Refresh } from '@element-plus/icons-vue'
import { apiAnalysis, apiStock, apiWatchlist, isRequestCanceled } from '@/api'
import { ElMessage } from 'element-plus'
import type { ECharts, EChartsCoreOption } from 'echarts/core'
import type { B1Check, DiagnosisHistoryDetailResponse, KLineData, StockSearchItem, WatchlistItem } from '@/types'
import { useAuthStore } from '@/store/auth'
import { useConfigStore } from '@/store/config'
import { getUserSafeErrorMessage, isInitializationPendingError } from '@/utils/userFacingErrors'
import { useResponsive } from '@/composables/useResponsive'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const configStore = useConfigStore()
const { isMobile } = useResponsive()
const DIAGNOSIS_STATE_KEY = 'stocktrade:diagnosis:state'
const DIAGNOSIS_CHART_CACHE_KEY = 'stocktrade:diagnosis:chart-cache'
const DIAGNOSIS_CHART_CACHE_TTL_MS = 30 * 60 * 1000
const AUTO_HISTORY_REFRESH_INTERVAL_MS = 5 * 60 * 1000
const DIAGNOSIS_INITIAL_CHART_DAYS = 60

const searchForm = ref({ code: '' })
const stockCode = ref('')
const chartDays = ref(120)
const chartRef = ref<HTMLElement>()
const analyzing = ref(false)
const refreshingHistory = ref(false)
const addingToWatchlist = ref(false)
const isInWatchlist = ref(false)

type DiagnosisViewResult = {
  score?: number
  b1_passed?: boolean
  verdict?: string
  signal_type?: string
  signal_reasoning?: string
  comment?: string
  kdj_j?: number
  zx_long_pos?: boolean
  weekly_ma_aligned?: boolean
  volume_healthy?: boolean
  scores?: Record<string, number>
  trend_reasoning?: string
  position_reasoning?: string
  volume_reasoning?: string
  abnormal_move_reasoning?: string
}

type DiagnosisSearchSuggestion = StockSearchItem & {
  value: string
}

const historyData = ref<B1Check[]>([])
const historyTotal = ref(0)
const historyPage = ref(1)
const historyPageSize = 10
const historyDetailVisible = ref(false)
const historyDetailLoading = ref(false)
const historyDetailData = ref<DiagnosisHistoryDetailResponse | null>(null)
const analysisResult = ref<DiagnosisViewResult | null>(null)
const stockName = ref('')
const currentDiagnosisChartData = ref<KLineData | null>(null)
const lastAutoHistoryRefreshAt = ref<Record<string, number>>({})
const mobileAnalysisSections = ref(['b1', 'scores'])

// 评分项配置
const scoreConfig = {
  trend_structure: { label: '趋势结构', weight: 0.2 },
  price_position: { label: '价格位置', weight: 0.2 },
  volume_behavior: { label: '量价行为', weight: 0.3 },
  previous_abnormal_move: { label: '历史异动', weight: 0.3 },
}
const chartDayOptions = [30, 60, 120, 180] as const

// 计算评分项
const scoreItems = computed(() => {
  if (!analysisResult.value?.scores) return []
  const scores = analysisResult.value.scores
  return [
    {
      key: 'trend_structure',
      label: scoreConfig.trend_structure.label,
      value: scores.trend_structure,
      reason: analysisResult.value.trend_reasoning || '',
    },
    {
      key: 'price_position',
      label: scoreConfig.price_position.label,
      value: scores.price_position,
      reason: analysisResult.value.position_reasoning || '',
    },
    {
      key: 'volume_behavior',
      label: scoreConfig.volume_behavior.label,
      value: scores.volume_behavior,
      reason: analysisResult.value.volume_reasoning || '',
    },
    {
      key: 'previous_abnormal_move',
      label: scoreConfig.previous_abnormal_move.label,
      value: scores.previous_abnormal_move,
      reason: analysisResult.value.abnormal_move_reasoning || '',
    },
  ]
})
const showInitializationAlert = computed(() => authStore.isAdmin && configStore.tushareReady && !configStore.dataInitialized)
const emptyDescription = computed(() => {
  if (!configStore.tushareReady) return '请先完成 Tushare 配置后再进行单股诊断'
  if (!configStore.dataInitialized) return '请先完成首次初始化，再进行单股诊断'
  return '请输入股票代码或名称进行诊断'
})
const isMobileViewport = computed(() => isMobile.value)
const isTomorrowStarMobileSource = computed(() => {
  const source = Array.isArray(route.query.source) ? route.query.source[0] : route.query.source
  return isMobile.value && source === 'tomorrow-star'
})

let chartInstance: ECharts | null = null
let chartRuntimePromise: Promise<{ init: (dom: HTMLElement, theme?: string | object, opts?: object) => ECharts }> | null = null
const diagnosisChartCache = new Map<string, KLineData>()
const diagnosisChartCacheDays = new Map<string, number>()
const requestControllers = new Map<string, AbortController>()
let searchSequence = 0

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

function cancelRequest(key: string) {
  const controller = requestControllers.get(key)
  if (controller) {
    controller.abort()
    requestControllers.delete(key)
  }
}

function cancelDiagnosisPageRequests() {
  requestControllers.forEach((controller) => controller.abort())
  requestControllers.clear()
}

function applyMobileRouteChartPreference() {
  if (isTomorrowStarMobileSource.value) {
    chartDays.value = 30
  }
}

onMounted(() => {
  configStore.checkTushareStatus()
  restoreDiagnosisState()
  applyMobileRouteChartPreference()

  // 从路由参数获取股票代码
  const routeCode = normalizeRouteCode(route.query.code)
  if (routeCode) {
    searchForm.value.code = routeCode
    searchAndAnalyze()
  }

  window.addEventListener('resize', handleResize)
})

onActivated(() => {
  configStore.checkTushareStatus()
  applyMobileRouteChartPreference()
  nextTick(() => {
    chartInstance?.resize()
  })

  const routeCode = normalizeRouteCode(route.query.code)
  if (routeCode && routeCode !== stockCode.value) {
    searchForm.value.code = routeCode
    searchAndAnalyze()
    return
  }

  if (stockCode.value) {
    maybeAutoRefreshHistory(true)
  }
})

onDeactivated(() => {
  searchSequence += 1
  stopAnalysisPolling()
  cancelDiagnosisPageRequests()
  refreshingHistory.value = false
  analyzing.value = false
})

onUnmounted(() => {
  searchSequence += 1
  if (chartInstance) {
    chartInstance.dispose()
  }
  window.removeEventListener('resize', handleResize)
  stopAnalysisPolling()
  cancelDiagnosisPageRequests()
})

function handleResize() {
  chartInstance?.resize()
}

async function searchStock(requestId: number) {
  if (!configStore.tushareReady) {
    ElMessage.warning('请先完成 Tushare 配置')
    return
  }

  const keyword = searchForm.value.code.trim()
  if (!keyword) {
    ElMessage.warning('请输入股票代码或名称')
    return
  }

  cancelRequest('stockSearch')
  cancelRequest('stockInfo')
  cancelRequest('watchlistStatus')
  cancelRequest('kline')
  cancelRequest('klineExtended')
  cancelRequest('historyLoad')
  cancelRequest('historyRefresh')
  cancelRequest('historyStatus')
  cancelRequest('analyze')
  cancelRequest('analyzeResult')
  stopAnalysisPolling()

  let matchedStock: DiagnosisSearchSuggestion | null = null
  try {
    matchedStock = await resolveDiagnosisSearchCode(keyword)
  } catch (error: any) {
    if (isRequestCanceled(error)) return
    console.error('resolveDiagnosisSearchCode failed:', error)
    const message = getUserSafeErrorMessage(error, '搜索股票失败')
    ElMessage.error(isInitializationPendingError(error) ? message : `搜索股票失败: ${message}`)
    return
  }

  if (requestId !== searchSequence) return
  if (!matchedStock?.code) {
    ElMessage.warning('未找到匹配的股票代码或名称')
    return
  }

  stockCode.value = matchedStock.code.padStart(6, '0')
  stockName.value = matchedStock.name || ''
  searchForm.value.code = stockCode.value
  analysisResult.value = null
  historyPage.value = 1

  await loadStockInfo()
  if (requestId !== searchSequence) return
  await loadWatchlistStatus()
  if (requestId !== searchSequence) return
  // 加载 K线数据
  await loadKlineData()
  if (requestId !== searchSequence) return

  // 加载历史检查记录
  await loadHistoryData()
  if (requestId !== searchSequence) return
  persistDiagnosisState()
  await maybeAutoRefreshHistory()
}

function toDiagnosisSearchSuggestion(item: StockSearchItem): DiagnosisSearchSuggestion {
  const code = String(item.code || '').padStart(6, '0')
  return {
    ...item,
    code,
    value: code,
  }
}

async function resolveDiagnosisSearchCode(keyword: string): Promise<DiagnosisSearchSuggestion | null> {
  const trimmed = keyword.trim()
  if (!trimmed) return null

  if (/^\d{1,6}$/.test(trimmed)) {
    const code = trimmed.padStart(6, '0')
    return { code, value: code }
  }

  const signal = beginRequest('stockSearch')
  try {
    const data = await apiStock.search(trimmed, 10, { signal })
    const item = data.items?.[0]
    return item ? toDiagnosisSearchSuggestion(item) : null
  } finally {
    finishRequest('stockSearch', signal)
  }
}

async function fetchStockSuggestions(
  queryString: string,
  callback: (items: DiagnosisSearchSuggestion[]) => void,
) {
  const trimmed = queryString.trim()
  if (!trimmed) {
    callback([])
    return
  }

  const signal = beginRequest('stockSearch')
  try {
    const data = await apiStock.search(trimmed, 10, { signal })
    callback((data.items || []).map(toDiagnosisSearchSuggestion))
  } catch (error) {
    if (!isRequestCanceled(error)) {
      console.error('Failed to search stocks:', error)
    }
    callback([])
  } finally {
    finishRequest('stockSearch', signal)
  }
}

function handleStockSuggestionSelect(item: DiagnosisSearchSuggestion) {
  searchForm.value.code = item.code
}

async function searchAndAnalyze() {
  const requestId = ++searchSequence

  // 如果状态还没加载过，先加载一次
  if (!configStore.tushareStatus) {
    await configStore.checkTushareStatus()
  }

  // 现在再检查初始化状态
  if (!configStore.dataInitialized) {
    ElMessage.info('请先完成首次初始化')
    return
  }

  await searchStock(requestId)
  if (requestId !== searchSequence) return

  // 自动开始分析
  if (stockCode.value) {
    await analyzeStock()
  }
}

async function loadStockInfo() {
  if (!stockCode.value) return

  const signal = beginRequest('stockInfo')
  try {
    const data = await apiStock.getInfo(stockCode.value, { signal })
    stockName.value = data.name || ''
    persistDiagnosisState()
  } catch (error) {
    if (isRequestCanceled(error)) return
    stockName.value = ''
  } finally {
    finishRequest('stockInfo', signal)
  }
}

async function loadWatchlistStatus() {
  if (!stockCode.value) return

  const signal = beginRequest('watchlistStatus')
  try {
    const data = await apiWatchlist.getAll({ signal })
    const items = data.items || []
    isInWatchlist.value = items.some((item: WatchlistItem) => item.code === stockCode.value)
  } catch (error) {
    if (isRequestCanceled(error)) return
    isInWatchlist.value = false
  } finally {
    finishRequest('watchlistStatus', signal)
  }
  persistDiagnosisState()
}

async function refreshHistory() {
  historyPage.value = 1
  await triggerHistoryRefresh(false, true)
}

async function triggerHistoryRefresh(silent: boolean = false, force: boolean = false) {
  if (!stockCode.value || refreshingHistory.value) return

  refreshingHistory.value = true
  try {
    const refreshSignal = beginRequest('historyRefresh')
    const result = await apiAnalysis.refreshHistory(
      stockCode.value,
      180,
      historyPage.value,
      historyPageSize,
      force,
      { signal: refreshSignal },
    )
    lastAutoHistoryRefreshAt.value[stockCode.value] = Date.now()
    await loadHistoryData(false)
    persistDiagnosisState()
    if (!silent) {
      ElMessage.success(result.message || '历史数据已刷新')
    }
  } catch (error: any) {
    if (isRequestCanceled(error)) return
    if (!silent) {
      console.error('triggerHistoryRefresh failed:', error)
      const message = getUserSafeErrorMessage(error, '刷新历史数据失败')
      ElMessage.error(isInitializationPendingError(error) ? message : `刷新历史数据失败: ${message}`)
    }
  } finally {
    refreshingHistory.value = false
  }
}

async function maybeAutoRefreshHistory(force: boolean = false) {
  if (!stockCode.value) return

  const lastRefreshAt = lastAutoHistoryRefreshAt.value[stockCode.value] || 0
  const statusSignal = beginRequest('historyStatus')
  let shouldRefresh = false

  try {
    const status = await apiAnalysis.getHistoryStatus(
      stockCode.value,
      180,
      1,
      historyPageSize,
      { signal: statusSignal },
    )
    shouldRefresh = force
      ? !refreshingHistory.value && Date.now() - lastRefreshAt >= AUTO_HISTORY_REFRESH_INTERVAL_MS
      : Boolean(status.needs_refresh) || (Date.now() - lastRefreshAt >= AUTO_HISTORY_REFRESH_INTERVAL_MS)
  } catch (error) {
    if (!isRequestCanceled(error)) {
      shouldRefresh = force
    }
  } finally {
    finishRequest('historyStatus', statusSignal)
  }

  if (shouldRefresh) {
    historyPage.value = 1
    await triggerHistoryRefresh(true)
  }
}

function selectChartDays(days: number) {
  if (chartDays.value === days) return
  chartDays.value = days
  void loadKlineData()
}

watch(
  historyData,
  () => {
    if (!currentDiagnosisChartData.value || !stockCode.value) return
    void renderChart(getDiagnosisDisplayChartData(currentDiagnosisChartData.value, chartDays.value))
  },
  { deep: true },
)

watch(
  () => [route.query.source, isMobile.value],
  () => {
    if (!isTomorrowStarMobileSource.value) return
    if (chartDays.value !== 30) {
      chartDays.value = 30
      persistDiagnosisState()
    }
    if (stockCode.value) {
      void loadKlineData()
    }
  },
)

async function loadKlineData() {
  if (!stockCode.value) return

  const requestedDays = chartDays.value
  const signal = beginRequest('kline')
  try {
    let data = diagnosisChartCache.get(stockCode.value)
    let cachedDays = diagnosisChartCacheDays.get(stockCode.value) || 0

    if (!data || cachedDays < Math.min(requestedDays, DIAGNOSIS_INITIAL_CHART_DAYS)) {
      const persistent = loadDiagnosisChartCache(stockCode.value)
      if (persistent) {
        data = persistent.data
        cachedDays = persistent.days
        diagnosisChartCache.set(stockCode.value, persistent.data)
        diagnosisChartCacheDays.set(stockCode.value, persistent.days)
      }
    }

    const initialDays = requestedDays >= 120 ? DIAGNOSIS_INITIAL_CHART_DAYS : requestedDays
    if (!data || cachedDays < initialDays) {
      data = await apiStock.getKline(stockCode.value, initialDays, false, { signal })
      cachedDays = initialDays
      setDiagnosisChartCache(stockCode.value, data, initialDays)
    }

    const displayData = getDiagnosisDisplayChartData(data, requestedDays)
    currentDiagnosisChartData.value = data
    await nextTick()
    await renderChart(displayData)
    // 确保图表在容器渲染完成后有正确的尺寸
    setTimeout(() => {
      chartInstance?.resize()
    }, 100)
    persistDiagnosisState()
    queueDiagnosisFullChartRefresh(stockCode.value, requestedDays, cachedDays)
  } catch (error: any) {
    if (isRequestCanceled(error)) return
    console.error('Failed to load kline:', error)
    const message = getUserSafeErrorMessage(error, '加载K线数据失败')
    ElMessage.error(isInitializationPendingError(error) ? message : `加载K线数据失败: ${message}`)
  } finally {
    finishRequest('kline', signal)
  }
}

async function renderChart(data: KLineData) {
  if (!chartRef.value) return

  const { init } = await loadDiagnosisChartRuntime()

  if (!chartInstance) {
    chartInstance = init(chartRef.value, undefined, { renderer: 'canvas' })
  }

  const dates = data.daily.map((d) => d.date)
  const values = data.daily.map((d) => [d.open, d.close, d.low, d.high])
  const volumeBars = data.daily.map((d) => {
    const isTrendStart = historyData.value.some((item) => item.check_date === d.date && item.signal_type === 'trend_start')
    return {
      value: d.volume,
      itemStyle: { color: isTrendStart ? '#1d4ed8' : '#778899' },
    }
  })
  const ma5 = data.daily.map((d) => d.ma5)
  const ma10 = data.daily.map((d) => d.ma10)
  const ma20 = data.daily.map((d) => d.ma20)

  // 中国习惯：红涨绿跌
  const option: EChartsCoreOption = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (params: any) => {
        if (!params || params.length === 0) return ''
        const dataIndex = params[0].dataIndex
        const date = dates[dataIndex]
        const rowData = data.daily[dataIndex]

        let result = `<b>${date}</b><br/>`

        if (rowData) {
          const change = ((rowData.close - rowData.open) / rowData.open * 100)
          const changeText = change >= 0 ? '+' : ''
          const changeColor = change >= 0 ? '#ef5350' : '#26a69a'

          result += `开盘: ${rowData.open?.toFixed(2) || '-'}<br/>`
          result += `收盘: ${rowData.close?.toFixed(2) || '-'}<br/>`
          result += `最低: ${rowData.low?.toFixed(2) || '-'}<br/>`
          result += `最高: ${rowData.high?.toFixed(2) || '-'}<br/>`
          result += `涨跌: <span style="color:${changeColor}">${changeText}${change.toFixed(2)}%</span><br/>`

          if (rowData.ma5 != null && !isNaN(rowData.ma5)) {
            result += `MA5: ${rowData.ma5.toFixed(2)}<br/>`
          }
          if (rowData.ma10 != null && !isNaN(rowData.ma10)) {
            result += `MA10: ${rowData.ma10.toFixed(2)}<br/>`
          }
          if (rowData.ma20 != null && !isNaN(rowData.ma20)) {
            result += `MA20: ${rowData.ma20.toFixed(2)}<br/>`
          }

          if (rowData.volume != null && !isNaN(rowData.volume)) {
            result += `成交量: ${(rowData.volume / 10000).toFixed(2)}万`
          }
        }

        return result
      }
    },
    legend: {
      data: ['K线', 'MA5', 'MA10', 'MA20', '趋势启动'],
      top: 10,
    },
    grid: [
      { left: '10%', right: '8%', top: '15%', height: '55%' },
      { left: '10%', right: '8%', top: '75%', height: '15%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        gridIndex: 0,
        axisLabel: { show: false },
      },
      {
        type: 'category',
        data: dates,
        gridIndex: 1,
        axisLabel: { fontSize: 10 },
      },
    ],
    yAxis: [
      {
        scale: true,
        gridIndex: 0,
        splitLine: { show: true, lineStyle: { color: '#f0f0f0' } },
      },
      {
        scale: true,
        gridIndex: 1,
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: values,
        // 中国习惯：红涨绿跌
        itemStyle: {
          color: '#ef5350',        // 阳线（涨）- 红色
          color0: '#26a69a',       // 阴线（跌）- 绿色
          borderColor: '#ef5350',  // 阳线边框 - 红色
          borderColor0: '#26a69a', // 阴线边框 - 绿色
        },
      },
      {
        name: 'MA5',
        type: 'line',
        data: ma5,
        smooth: true,
        lineStyle: { width: 1 },
        symbol: 'none',
      },
      {
        name: 'MA10',
        type: 'line',
        data: ma10,
        smooth: true,
        lineStyle: { width: 1 },
        symbol: 'none',
      },
      {
        name: 'MA20',
        type: 'line',
        data: ma20,
        smooth: true,
        lineStyle: { width: 1 },
        symbol: 'none',
      },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumeBars,
      },
    ],
  }

  await nextTick()
  chartInstance.setOption(option, true)
  chartInstance.resize()
}

function queueDiagnosisFullChartRefresh(code: string, requestedDays: number, currentDays: number) {
  if (requestedDays < 120 || currentDays >= requestedDays) return
  if (stockCode.value !== code) return
  void refreshDiagnosisFullChartInBackground(code, requestedDays)
}

async function refreshDiagnosisFullChartInBackground(code: string, requestedDays: number) {
  const signal = beginRequest('klineExtended')
  try {
    const fullData = await apiStock.getKline(code, requestedDays, false, { signal, timeoutMs: 20000 })
    if (stockCode.value !== code || chartDays.value !== requestedDays) return
    setDiagnosisChartCache(code, fullData, requestedDays)
    currentDiagnosisChartData.value = fullData
    await renderChart(getDiagnosisDisplayChartData(fullData, requestedDays))
    persistDiagnosisState()
  } catch (error) {
    if (isRequestCanceled(error)) return
    console.error('Failed to extend diagnosis kline:', error)
  } finally {
    finishRequest('klineExtended', signal)
  }
}

async function loadDiagnosisChartRuntime() {
  if (!chartRuntimePromise) {
    chartRuntimePromise = (async () => {
      const [{ use, init }, charts, components, renderers] = await Promise.all([
        import('echarts/core'),
        import('echarts/charts'),
        import('echarts/components'),
        import('echarts/renderers'),
      ])

      use([
        charts.BarChart,
        charts.CandlestickChart,
        charts.LineChart,
        components.TooltipComponent,
        components.LegendComponent,
        components.GridComponent,
        renderers.CanvasRenderer,
      ])

      return { init }
    })()
  }

  return chartRuntimePromise
}

async function loadHistoryData(refresh: boolean = false) {
  if (!stockCode.value) return

  const signal = beginRequest('historyLoad')
  try {
    const data = await apiAnalysis.getDiagnosisHistory(
      stockCode.value,
      180,
      historyPage.value,
      historyPageSize,
      refresh,
      { signal },
    )
    historyData.value = data.history || []
    historyTotal.value = data.total || 0
    persistDiagnosisState()
  } catch (error: any) {
    if (isRequestCanceled(error)) return
    console.error('Failed to load history:', error)
  } finally {
    finishRequest('historyLoad', signal)
  }
}

async function handleHistoryPageChange(page: number) {
  historyPage.value = page
  await triggerHistoryRefresh(true)
}

// 分析任务轮询定时器
let analysisPollingTimer: ReturnType<typeof setInterval> | null = null

async function analyzeStock() {
  if (!configStore.dataInitialized) {
    ElMessage.info('请先完成首次初始化')
    return
  }
  if (!stockCode.value) return

  const signal = beginRequest('analyze')
  analyzing.value = true

  try {
    // 1. 提交分析任务
    const taskResponse = await apiAnalysis.analyze(stockCode.value, { signal })

    if (taskResponse.status === 'existing') {
      ElMessage.info(taskResponse.message || '复用现有分析任务')
    } else {
      ElMessage.info('分析任务已创建，正在执行...')
    }

    // 2. 开始轮询任务状态
    startAnalysisPolling()
  } catch (error: any) {
    if (isRequestCanceled(error)) return
    console.error('analyzeStock failed:', error)
    const message = getUserSafeErrorMessage(error, '提交分析任务失败')
    ElMessage.error(isInitializationPendingError(error) ? message : `提交分析任务失败: ${message}`)
    analyzing.value = false
    finishRequest('analyze', signal)
  }
}

function startAnalysisPolling() {
  // 清除之前的轮询
  stopAnalysisPolling()

  // 立即检查一次
  checkAnalysisResult()

  // 每2秒轮询一次
  analysisPollingTimer = setInterval(() => {
    checkAnalysisResult()
  }, 2000)
}

function stopAnalysisPolling() {
  if (analysisPollingTimer) {
    clearInterval(analysisPollingTimer)
    analysisPollingTimer = null
  }
}

async function checkAnalysisResult() {
  if (!stockCode.value) return

  const signal = beginRequest('analyzeResult')
  try {
    const data = await apiAnalysis.getResult(stockCode.value, { signal })

    if (data.status === 'processing') {
      // 任务还在处理中，更新进度信息
      if (data.progress_meta) {
        // 预留任务进度显示能力
      }
    } else if (data.status === 'completed') {
      // 任务完成，更新分析结果
      stopAnalysisPolling()

      stockName.value = data.name || stockName.value
      const analysis = data.analysis || {}
      analysisResult.value = {
        score: data.score,
        b1_passed: data.b1_passed,
        verdict: data.verdict,
        // 从 analysis 对象中获取所有字段
        signal_type: analysis.signal_type,
        signal_reasoning: analysis.signal_reasoning,
        comment: analysis.comment,
        // B1 检查详情
        kdj_j: analysis.kdj_j,
        zx_long_pos: analysis.zx_long_pos,
        weekly_ma_aligned: analysis.weekly_ma_aligned,
        volume_healthy: analysis.volume_healthy,
        // 评分明细
        scores: analysis.scores || {},
        trend_reasoning: analysis.trend_reasoning || '',
        position_reasoning: analysis.position_reasoning || '',
        volume_reasoning: analysis.volume_reasoning || '',
        abnormal_move_reasoning: analysis.abnormal_move_reasoning || '',
      }

      // 刷新历史数据
      await loadHistoryData()
      persistDiagnosisState()

      ElMessage.success('分析完成')
      analyzing.value = false
    } else if (data.status === 'failed') {
      // 任务失败
      stopAnalysisPolling()
      ElMessage.error(isInitializationPendingError({ message: data.error || '' }) ? '系统尚未完成初始化' : (data.error || '分析任务执行失败'))
      analyzing.value = false
    }
  } catch (error: any) {
    if (isRequestCanceled(error)) {
      stopAnalysisPolling()
      return
    }
    // 忽略轮询错误，继续轮询
  } finally {
    finishRequest('analyzeResult', signal)
  }
}

function goTaskCenter() {
  router.push('/update')
}

function goConfig() {
  router.push('/config')
}

async function addCurrentToWatchlist() {
  if (!stockCode.value || isInWatchlist.value) return

  addingToWatchlist.value = true
  try {
    const reasonParts = []
    if (analysisResult.value?.verdict) {
      reasonParts.push(`诊断结论:${analysisResult.value.verdict}`)
    }
    if (analysisResult.value?.score != null) {
      reasonParts.push(`评分:${analysisResult.value.score.toFixed(1)}`)
    }
    await apiWatchlist.add(stockCode.value, reasonParts.join(' | ') || '单股诊断加入重点观察')
    isInWatchlist.value = true
    persistDiagnosisState()
    ElMessage.success(`已将 ${stockCode.value}${stockName.value ? ` ${stockName.value}` : ''} 纳入重点观察`)
  } catch (error: any) {
    console.error('addCurrentToWatchlist failed:', error)
    const message = getUserSafeErrorMessage(error, '纳入重点观察失败')
    ElMessage.error(isInitializationPendingError(error) ? message : `纳入重点观察失败: ${message}`)
  } finally {
    addingToWatchlist.value = false
  }
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  return `${d.getMonth() + 1}/${d.getDate()}`
}

function formatChange(pct?: number): string {
  if (pct === undefined || pct === null) return '-'
  return (pct > 0 ? '+' : '') + pct.toFixed(2) + '%'
}

// 中国习惯：红涨绿跌
function getChangeClass(pct?: number): string {
  if (!pct) return ''
  return pct > 0 ? 'text-up' : 'text-down'
}

function getVerdictType(verdict: string): string {
  const types: Record<string, string> = {
    'PASS': 'success',
    'WATCH': 'warning',
    'FAIL': 'danger',
  }
  return types[verdict] || 'info'
}

function getScoreType(score?: number): string {
  if (!score) return 'info'
  if (score >= 4.5) return 'success'
  if (score >= 4.0) return 'warning'
  return 'danger'
}

function getGateLabel(value?: boolean | null): string {
  if (value === true) return '是'
  if (value === false) return '否'
  return '待定'
}

function getGateTagType(value?: boolean | null): string {
  if (value === true) return 'success'
  if (value === false) return 'info'
  return 'info'
}

function getPrefilterTagType(value?: boolean | null): string {
  if (value === true) return 'success'
  if (value === false) return 'warning'
  return 'info'
}

function getTomorrowStarTagType(value?: boolean | null): string {
  if (value === true) return 'success'
  if (value === false) return 'info'
  return 'info'
}

function formatPrefilterBlockedBy(blockedBy?: string[] | null): string {
  if (!blockedBy?.length) return '-'
  const labels: Record<string, string> = {
    st: 'ST/*ST 风险',
    recent_ipo: '上市天数不足',
    unlock: '近期解禁压力',
    size_bucket: '市值分层不符',
    industry_strength: '行业强度不足',
    market_regime: '市场环境未达标',
  }
  return blockedBy.map((item) => labels[item] || item).join(' / ')
}

function getSignalLabel(signalType: string): string {
  const labels: Record<string, string> = {
    'trend_start': '趋势启动',
    'rebound': '反弹延续',
    'distribution_risk': '风险释放',
    'prefilter_blocked': '前置过滤拦截',
  }
  return labels[signalType] || signalType
}

function getSignalTagType(signalType: string): string {
  const types: Record<string, string> = {
    'trend_start': 'success',
    'rebound': 'warning',
    'distribution_risk': 'danger',
    'prefilter_blocked': 'info',
  }
  return types[signalType] || 'info'
}

function persistDiagnosisState() {
  if (typeof window === 'undefined') return

  const state = {
    searchForm: searchForm.value,
    stockCode: stockCode.value,
    stockName: stockName.value,
    chartDays: chartDays.value,
    historyData: historyData.value,
    analysisResult: analysisResult.value,
    isInWatchlist: isInWatchlist.value,
    lastAutoHistoryRefreshAt: lastAutoHistoryRefreshAt.value,
  }

  sessionStorage.setItem(DIAGNOSIS_STATE_KEY, JSON.stringify(state))
}

function formatDetailJson(value: Record<string, any> | null | undefined): string {
  return JSON.stringify(value ?? {}, null, 2)
}

async function openHistoryDetail(row: B1Check) {
  if (!stockCode.value || !row?.check_date) return
  historyDetailVisible.value = true
  historyDetailLoading.value = true
  historyDetailData.value = null
  try {
    const ensure = await apiAnalysis.ensureHistoryDetail(stockCode.value, row.check_date, false)
    if (ensure.status !== 'ready' && ensure.task_id) {
      await apiAnalysis.getHistoryDetail(stockCode.value, row.check_date)
    }
    historyDetailData.value = await apiAnalysis.getHistoryDetail(stockCode.value, row.check_date)
  } catch (error: any) {
    ElMessage.error('加载历史详情失败: ' + error.message)
  } finally {
    historyDetailLoading.value = false
  }
}

function getDiagnosisDisplayChartData(data: KLineData, requestedDays: number): KLineData {
  if (requestedDays <= 0 || data.daily.length <= requestedDays) {
    return data
  }

  return {
    ...data,
    daily: data.daily.slice(-requestedDays),
  }
}

function loadDiagnosisChartCache(code: string): { code: string; days: number; cachedAt: number; data: KLineData } | null {
  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return null

  const raw = window.localStorage.getItem(DIAGNOSIS_CHART_CACHE_KEY)
  if (!raw) return null

  try {
    const cache = JSON.parse(raw) as Record<string, { code: string; days: number; cachedAt: number; data: KLineData }>
    const entry = cache[code]
    if (!entry) return null
    if (!entry.cachedAt || Date.now() - entry.cachedAt > DIAGNOSIS_CHART_CACHE_TTL_MS) {
      delete cache[code]
      window.localStorage.setItem(DIAGNOSIS_CHART_CACHE_KEY, JSON.stringify(cache))
      return null
    }
    return entry
  } catch {
    window.localStorage.removeItem(DIAGNOSIS_CHART_CACHE_KEY)
    return null
  }
}

function setDiagnosisChartCache(code: string, data: KLineData, days: number) {
  diagnosisChartCache.set(code, data)
  diagnosisChartCacheDays.set(code, days)

  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return

  let cache: Record<string, { code: string; days: number; cachedAt: number; data: KLineData }> = {}
  try {
    cache = JSON.parse(window.localStorage.getItem(DIAGNOSIS_CHART_CACHE_KEY) || '{}')
  } catch {
    cache = {}
  }

  cache[code] = {
    code,
    days,
    cachedAt: Date.now(),
    data,
  }

  const trimmed = Object.values(cache)
    .sort((a, b) => b.cachedAt - a.cachedAt)
    .slice(0, 20)
  window.localStorage.setItem(
    DIAGNOSIS_CHART_CACHE_KEY,
    JSON.stringify(Object.fromEntries(trimmed.map((entry) => [entry.code, entry])))
  )
}

function restoreDiagnosisState() {
  if (typeof window === 'undefined') return

  const raw = sessionStorage.getItem(DIAGNOSIS_STATE_KEY)
  if (!raw) return

  try {
    const state = JSON.parse(raw)
    searchForm.value = state.searchForm || { code: '' }
    stockCode.value = state.stockCode || ''
    stockName.value = state.stockName || ''
    chartDays.value = state.chartDays || 120
    historyData.value = state.historyData || []
    analysisResult.value = state.analysisResult || null
    isInWatchlist.value = Boolean(state.isInWatchlist)
    lastAutoHistoryRefreshAt.value = state.lastAutoHistoryRefreshAt || {}
    applyMobileRouteChartPreference()

    if (stockCode.value) {
      nextTick(() => {
        loadKlineData()
      })
    }
  } catch {
    sessionStorage.removeItem(DIAGNOSIS_STATE_KEY)
  }
}

function normalizeRouteCode(code: unknown): string {
  const raw = Array.isArray(code) ? code[0] : code
  if (typeof raw !== 'string') return ''
  const trimmed = raw.trim()
  if (!trimmed) return ''
  return trimmed.padStart(6, '0')
}
</script>

<style scoped lang="scss">
.diagnosis-page {
  .page-alert {
    margin-bottom: 16px;
  }

  .search-card {
    margin-bottom: 20px;
  }

  .search-form-row {
    align-items: center;
  }

  .search-input {
    width: 240px;
  }

  .stock-suggestion {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;

    .suggestion-code {
      color: #303133;
      font-variant-numeric: tabular-nums;
      font-weight: 600;
    }

    .suggestion-name {
      color: #606266;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .content-row {
    margin-bottom: 20px;
  }

  .chart-card {
    height: 100%;
    display: flex;
    flex-direction: column;

    :deep(.el-card__header) {
      padding: 16px 20px 12px;
    }

    :deep(.el-card__body) {
      flex: 1;
      display: flex;
      flex-direction: column;
    }

    .card-header {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      column-gap: 20px;
      row-gap: 12px;
    }

    .chart-header-main {
      min-width: 0;
    }

    .stock-identity {
      min-width: 0;
      display: grid;
      row-gap: 8px;
    }

    .stock-line {
      display: flex;
      align-items: baseline;
      gap: 12px;
      min-width: 0;
      flex-wrap: wrap;
    }

    .stock-code {
      font-size: 20px;
      font-weight: 700;
      color: #1f2937;
      letter-spacing: 0.03em;
      white-space: nowrap;
      line-height: 1;
    }

    .stock-name {
      min-width: 0;
      font-size: 17px;
      font-weight: 600;
      color: #0f172a;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      line-height: 1.15;
    }

    .chart-meta {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
      flex-wrap: wrap;
    }

    .chart-title {
      display: inline-flex;
      align-items: center;
      padding: 5px 10px;
      border-radius: 999px;
      background: linear-gradient(135deg, #edf5ff 0%, #f5f9ff 100%);
      color: #35516f;
      font-size: 12px;
      font-weight: 600;
      white-space: nowrap;
      box-shadow: inset 0 0 0 1px rgba(138, 164, 194, 0.2);
    }

    .chart-subtitle {
      font-size: 12px;
      line-height: 1.4;
      color: #7b8794;
      white-space: nowrap;
    }

    .chart-toolbar {
      display: grid;
      justify-items: end;
      row-gap: 8px;
    }

    .chart-toolbar-label {
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.08em;
      color: #8090a3;
      white-space: nowrap;
    }

    .chart-range-switcher {
      display: inline-flex;
      align-items: center;
      justify-self: end;
      min-height: 34px;
      padding: 3px;
      border: 1px solid #d8e2ec;
      border-radius: 12px;
      background: linear-gradient(180deg, #f8fbff 0%, #eef4fb 100%);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.92);
    }

    .chart-range-button {
      min-width: 60px;
      height: 28px;
      padding: 0 14px;
      border: none;
      border-radius: 9px;
      background: transparent;
      color: #5b6f86;
      font-size: 12px;
      font-weight: 600;
      line-height: 28px;
      cursor: pointer;
      transition: background-color 0.2s ease, color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;

      &:hover {
        color: #24364a;
        background: rgba(255, 255, 255, 0.55);
      }

      &:focus-visible {
        outline: 2px solid rgba(29, 78, 216, 0.28);
        outline-offset: 1px;
      }

      &.is-active {
        color: #1d4ed8;
        background: #ffffff;
        box-shadow: 0 2px 6px rgba(37, 99, 235, 0.12);
        transform: translateY(-1px);
      }
    }

    .chart-container {
      flex: 1;
      min-height: 400px;
    }
  }

  .analysis-card {
    height: 100%;
    display: flex;
    flex-direction: column;

    :deep(.el-card__body) {
      flex: 1;
      overflow-y: auto;
    }

    .analysis-content {
      .analysis-summary-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
        margin-bottom: 4px;

        .summary-tile {
          display: grid;
          gap: 8px;
          padding: 12px;
          border: 1px solid #e5edf5;
          border-radius: 12px;
          background: #f8fbff;

          &.verdict-tile {
            grid-column: 1 / -1;
          }
        }

        .summary-label {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          color: var(--color-text-secondary);
          font-size: 13px;
        }
      }

      .mobile-analysis-panels {
        display: grid;
        gap: 12px;
      }

      .mobile-analysis-summary {
        margin: 0;
        padding: 10px 12px;
        border-radius: 10px;
        background: #f5f7fa;
        color: #606266;
        font-size: 13px;
        line-height: 1.6;
      }

      .collapse-title {
        font-weight: 600;
        color: #303133;
      }

      :deep(.el-divider) {
        margin: 8px 0;
      }

      .analysis-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 6px 0;
        border-bottom: 1px solid #f0f0f0;

        &:last-of-type {
          border-bottom: none;
        }

        .label {
          display: flex;
          align-items: center;
          gap: 4px;
          color: var(--color-text-secondary);
        }

        .value {
          font-weight: 500;
        }
      }

      .b1-details {
        .section-header {
          margin-bottom: 8px;

		  h5 {
            margin: 0 0 8px 0;
            color: var(--color-text-secondary);
          }

		  :deep(.el-alert) {
		    padding: 8px 12px;

		    .el-alert__title {
		      font-size: 12px;
		      font-weight: 500;
		    }

		    .alert-content {
		      font-size: 11px;
		      color: #606266;
		      margin-top: 4px;
		    }
		  }
		}

        .detail-item {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 6px 0;

          .detail-label {
            display: flex;
            align-items: center;
            gap: 4px;
          }

          .info-icon {
            font-size: 14px;
            color: var(--color-info);
            cursor: help;
          }
        }
      }

      .evaluation-note {
        margin-bottom: 12px;

        :deep(.el-alert__title) {
          font-size: 13px;
          font-weight: 600;
        }

        .note-content {
          font-size: 12px;
          color: #606266;
          line-height: 1.6;
        }
      }

      .score-details {
        .section-header {
          margin-bottom: 8px;

		  h5 {
            margin: 0 0 8px 0;
            color: var(--color-text-secondary);
          }

		  :deep(.el-alert) {
		    padding: 8px 12px;

		    .el-alert__title {
		      font-size: 12px;
		      font-weight: 500;
		    }

		    .alert-content {
		      font-size: 11px;
		      color: #606266;
		      margin-top: 4px;
		    }
		  }
		}

        h5 {
          margin: 0 0 8px 0;
          color: var(--color-text-secondary);
        }

        .score-summary {
          margin: 0 0 10px 0;
          padding: 8px 12px;
          background-color: #f5f7fa;
          border-radius: 4px;
          font-size: 13px;
          color: #606266;
          line-height: 1.5;
        }

        .score-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 10px;
          margin-bottom: 10px;

          .score-item {
            padding: 8px;
            background-color: #fafafa;
            border-radius: 4px;
            border-left: 3px solid #e4e7ed;

            &:nth-child(1) { border-left-color: #409eff; }
            &:nth-child(2) { border-left-color: #67c23a; }
            &:nth-child(3) { border-left-color: #e6a23c; }
            &:nth-child(4) { border-left-color: #f56c6c; }

            .score-header {
              display: flex;
              justify-content: space-between;
              align-items: center;
              margin-bottom: 4px;

              .score-label {
                font-size: 13px;
                font-weight: 500;
                color: #303133;
              }
            }

            .score-reason {
              font-size: 12px;
              color: #909399;
              line-height: 1.4;
              display: -webkit-box;
              -webkit-line-clamp: 2;
              -webkit-box-orient: vertical;
              overflow: hidden;
              cursor: help;
            }
          }
        }

        .signal-type-box {
          padding: 8px 12px;
          background-color: #f0f9ff;
          border-radius: 4px;
          display: flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;

          .signal-label {
            font-size: 13px;
            font-weight: 500;
            color: #303133;
          }

          .signal-reason {
            font-size: 12px;
            color: #606266;
            flex: 1;
          }
        }
      }
    }
  }

  .history-header {
    display: flex;
    justify-content: space-between;
    align-items: center;

    .history-actions {
      display: flex;
      align-items: center;
      gap: 12px;

      .refreshing-text {
        font-size: 13px;
        color: var(--color-warning);
      }
    }
  }

  .history-table-wrap {
    overflow-x: auto;
  }

  .history-pagination {
    display: flex;
    justify-content: center;
    margin-top: 12px;
  }

  .history-mobile-list {
    .history-card-list {
      display: grid;
      gap: 12px;
    }

    .history-summary-card {
      display: grid;
      gap: 12px;
      padding: 14px;
      border: 1px solid #e5edf5;
      border-radius: 14px;
      background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
    }

    .history-card-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
    }

    .history-date-block {
      display: grid;
      gap: 4px;
    }

    .history-date {
      font-size: 15px;
      font-weight: 700;
      color: #1f2937;
    }

    .history-price {
      font-size: 12px;
      color: #6b7280;
    }

    .history-change {
      font-size: 14px;
      font-weight: 600;
      white-space: nowrap;
    }

    .history-card-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .history-card-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }

    .history-score-line {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: #475569;
    }
  }

  .table-header-label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .table-info-icon {
    font-size: 13px;
    color: var(--color-info);
    cursor: help;
  }

  // 中国习惯：红涨绿跌
  .text-up {
    color: #ef5350;  // 红色 - 涨
  }

  .text-down {
    color: #26a69a;  // 绿色 - 跌
  }
}

@media (max-width: 768px) {
  .diagnosis-page {
    min-height: auto;

    .search-form-row {
      :deep(.el-form-item) {
        width: 100%;
        margin-right: 0;
      }
    }

    .search-input {
      width: 100%;
    }

    .content-row {
      margin-bottom: 16px;
    }

    .chart-card {
      margin-bottom: 16px;

      :deep(.el-card__header) {
        padding: 14px 14px 10px;
      }

      .card-header {
        grid-template-columns: 1fr;
        align-items: start;
      }

      .stock-line {
        gap: 8px 10px;
      }

      .stock-name {
        max-width: 100%;
      }

      .chart-meta {
        gap: 8px;
      }

      .chart-subtitle {
        white-space: normal;
      }

      .chart-toolbar {
        justify-items: start;
      }

      .chart-range-mobile {
        display: grid;
        justify-items: start;
        gap: 8px;
      }

      .chart-range-select {
        width: 120px;
      }

      .chart-range-hint {
        font-size: 12px;
        color: #6b7280;
      }

      .chart-container {
        min-height: 300px;
      }
    }

    .analysis-card {
      height: auto;

      :deep(.el-card__body) {
        overflow: visible;
      }

      .analysis-content {
        .analysis-item {
          gap: 12px;
        }

        .score-details {
          .score-grid {
            grid-template-columns: 1fr;
          }

          .score-item {
            padding: 12px;
            border-left-width: 4px;
          }

          .score-header {
            align-items: flex-start;
            gap: 8px;
          }

          .score-reason {
            display: block;
            -webkit-line-clamp: unset;
            -webkit-box-orient: unset;
            overflow: visible;
            white-space: normal;
            word-break: break-word;
            color: #4b5563;
            line-height: 1.6;
            cursor: default;
          }
        }
      }
    }

    .history-card {
      :deep(.el-card__body) {
        overflow: visible;
      }
    }

    .history-header {
      flex-direction: column;
      align-items: stretch;
      gap: 12px;

      .history-actions {
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 8px;
      }
    }
  }
}
</style>
