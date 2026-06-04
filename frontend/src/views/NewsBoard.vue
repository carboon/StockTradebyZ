<template>
  <div class="news-board-page">
    <section class="news-board-toolbar">
      <div class="toolbar-main">
        <div class="toolbar-title">24H 消息监控</div>
        <div class="toolbar-meta">
          <span v-if="totalCached">缓存 {{ totalCached }} 条</span>
          <span v-if="lastGeneratedAt">更新 {{ formatDateTime(lastGeneratedAt) }}</span>
        </div>
      </div>
      <div class="toolbar-actions">
        <el-input
          v-model="searchKeyword"
          class="keyword-input"
          clearable
          placeholder="搜索标题、摘要..."
          :prefix-icon="Search"
          @clear="onSearchClear"
          @keyup.enter="onSearchEnter"
        />
        <el-button :icon="Refresh" :loading="loading" @click="loadNews">
          刷新
        </el-button>
      </div>
    </section>

    <section class="news-board-layout">
      <main class="news-stream-panel">
        <div class="panel-header">
          <div>
            <h3>统一时间线</h3>
            <p>后台每 5 分钟自动更新，按时间倒序展示。向下滚动加载更多。</p>
          </div>
        </div>

        <div v-if="loading && newsItems.length === 0" class="loading-box">
          <el-skeleton :rows="6" animated />
        </div>
        <el-empty v-else-if="newsItems.length === 0 && !searchActive" description="暂无消息" :image-size="90" />
        <el-empty v-else-if="newsItems.length === 0 && searchActive" description="未找到匹配结果" :image-size="90" />

        <div v-if="searchActive && newsItems.length > 0" class="search-prompt">
          <span class="search-prompt-text">搜索 "{{ searchKeyword }}" 找到 {{ newsItems.length }} 条结果。若想查看详细分析请点击</span>
          <el-button type="primary" size="small" :icon="DataAnalysis" :loading="analyzingBatch" @click="analyzeBatch">
            综合分析
          </el-button>
        </div>

        <div v-if="newsItems.length > 0" ref="scrollContainer" class="news-scroll" @scroll="onScroll">
          <button
            v-for="item in newsItems"
            :key="item.id"
            type="button"
            class="news-item"
            :class="{ active: selectedNews?.id === item.id }"
            @click="selectNews(item)"
          >
            <div class="news-item__top">
              <el-tag :type="categoryTagType(item.category)" size="small">{{ item.category }}</el-tag>
              <el-button
                type="primary"
                size="small"
                :loading="analyzingItemId === item.id"
                @click.stop="analyzeDetailForItem(item)"
              >
                详情分析
              </el-button>
              <span class="news-time">{{ formatRelativeTime(item.eventTime || item.publishedAt) }}</span>
            </div>
            <div class="news-title">{{ item.title }}</div>
            <div v-if="item.summary" class="news-summary">{{ item.summary }}</div>
          </button>
          <div v-if="loadingMore && !searchActive" class="loading-more">
            <el-skeleton :rows="2" animated />
          </div>
          <div v-else-if="!hasMore && !searchActive && newsItems.length > 0" class="end-hint">
            已加载全部消息
          </div>
        </div>
      </main>

      <aside class="analysis-panel">
        <!-- 搜索模式 -->
        <template v-if="searchActive && !selectedNews">
          <div class="panel-header analysis-header">
            <div>
              <h3>AI 事件分析</h3>
              <p>搜索"{{ searchKeyword }}"共 {{ newsItems.length }} 条</p>
            </div>
            <el-button
              type="primary"
              :icon="DataAnalysis"
              :loading="analyzingBatch"
              :disabled="newsItems.length === 0"
              @click="analyzeBatch"
            >
              查询结果分析 {{ newsItems.length }}条
            </el-button>
          </div>

          <div v-if="batchResult" class="detail-result">
            <div class="detail-status">
              <el-tag :type="batchResult.status === 'ready' ? 'success' : 'info'" size="default">
                {{ batchResult.status === 'ready' ? '分析完成' : batchResult.status }}
              </el-tag>
              <span class="detail-confidence">{{ batchResult.total }} 条消息</span>
            </div>

            <div v-if="batchResult.summary" class="detail-section">
              <div class="detail-label">摘要总览</div>
              <div class="detail-text">{{ batchResult.summary }}</div>
            </div>

            <div v-if="batchResult.market_impact" class="detail-section">
              <div class="detail-label">综合判断</div>
              <el-tag :type="impactTag(batchResult.market_impact)" size="default">
                {{ batchResult.market_impact }}
              </el-tag>
            </div>

            <div v-if="batchResult.themes.length" class="detail-section">
              <div class="detail-label">关键主题</div>
              <div class="batch-themes">
                <div v-for="t in batchResult.themes" :key="t.topic" class="batch-theme-item">
                  <div class="batch-theme-header">
                    <span class="batch-theme-topic">{{ t.topic }}</span>
                    <el-tag :type="sentimentTagType(t.sentiment)" size="small">{{ sentimentLabel(t.sentiment) }}</el-tag>
                    <span class="batch-theme-count">{{ t.count }}条</span>
                  </div>
                  <div v-if="t.description" class="batch-theme-desc">{{ t.description }}</div>
                </div>
              </div>
            </div>

            <div v-if="batchResult.key_items.length" class="detail-section">
              <div class="detail-label">高权重消息</div>
              <div class="batch-items">
                <div v-for="(ki, i) in batchResult.key_items" :key="i" class="batch-item-row">
                  <el-tag :type="weightTagType(ki.weight)" size="small">{{ weightLabel(ki.weight) }}</el-tag>
                  <span class="batch-item-title">{{ ki.title }}</span>
                  <span v-if="ki.reason" class="batch-item-reason">— {{ ki.reason }}</span>
                </div>
              </div>
            </div>

            <div v-if="batchResult.watch_points.length" class="detail-section">
              <div class="detail-label">后续观察</div>
              <div class="detail-items">
                <div v-for="(w, i) in batchResult.watch_points" :key="i" class="detail-item">{{ w }}</div>
              </div>
            </div>
          </div>

          <div v-else-if="!analyzingBatch" class="empty-hint">
            点击上方按钮，对搜索结果进行综合分析
          </div>
        </template>

        <!-- 单条消息详情模式 -->
        <template v-else>
          <div class="panel-header analysis-header">
            <div>
              <h3>AI 事件分析</h3>
              <p v-if="searchActive && selectedNews">搜索"{{ searchKeyword }}" — 查看详情</p>
              <p v-else-if="selectedNews">消息详情分析</p>
              <p v-else>请选择左侧消息查看详情</p>
            </div>
            <el-button
              v-if="searchActive && selectedNews"
              text
              size="small"
              @click="backToSearch"
            >
              ← 返回
            </el-button>
          </div>

          <div v-if="selectedNews" class="selected-card">
            <div class="selected-title">{{ selectedNews.title }}</div>
            <div class="selected-meta">
              <span v-if="selectedNews.eventTime">事件 {{ formatDateTime(selectedNews.eventTime) }}</span>
              <span>发布 {{ formatDateTime(selectedNews.publishedAt) }}</span>
              <span v-if="selectedNews.ingestedAt">抓取 {{ formatDateTime(selectedNews.ingestedAt) }}</span>
            </div>
            <p v-if="selectedNews.summary">{{ selectedNews.summary }}</p>
            <div class="selected-actions">
              <el-button
                v-if="selectedNews.sourceUrl || selectedNews.url"
                text
                type="primary"
                size="small"
                @click="openSource(selectedNews)"
              >
                查看原文
              </el-button>
            </div>
          </div>
          <el-empty v-else description="请选择一条消息" :image-size="80" />

          <div v-if="detailResult" class="detail-result">
            <div class="detail-status">
              <el-tag :type="detailStatusTagType(detailResult.status)" size="default">
                {{ detailStatusLabel(detailResult.status) }}
              </el-tag>
              <span v-if="detailResult.confidence !== null && detailResult.confidence !== undefined" class="detail-confidence">
                置信度 {{ (detailResult.confidence * 100).toFixed(0) }}%
              </span>
            </div>

            <template v-if="detailResult.status === 'stopped'">
              <div class="detail-section"><div class="detail-label">停止原因</div><div class="detail-text">{{ detailResult.reason }}</div></div>
              <div v-if="detailResult.watch_points.length" class="detail-section"><div class="detail-label">后续观察</div><div class="detail-items"><div v-for="(wp,i) in detailResult.watch_points" :key="i" class="detail-item">{{ wp }}</div></div></div>
            </template>

            <template v-if="detailResult.status === 'ready'">
              <div class="detail-section"><div class="detail-label">事件概述</div><div class="detail-text">{{ detailResult.event_summary }}</div></div>
              <div v-if="detailResult.core_facts.length" class="detail-section"><div class="detail-label">核心事实</div><div class="detail-items"><div v-for="(f,i) in detailResult.core_facts" :key="i" class="detail-item fact-item">{{ f }}</div></div></div>
              <div v-if="detailResult.impact_path.length" class="detail-section"><div class="detail-label">影响路径</div><div class="detail-items"><div v-for="(p,i) in detailResult.impact_path" :key="i" class="detail-item">{{ p.description || p }}<span v-if="p.confidence" class="detail-sub">(置信度 {{ (p.confidence * 100).toFixed(0) }}%)</span></div></div></div>
              <div v-if="detailResult.direct_sectors.length" class="detail-section"><div class="detail-label">直接关联板块</div><div class="tag-row"><el-tag v-for="s in detailResult.direct_sectors" :key="s" size="small" type="success">{{ s }}</el-tag></div></div>
              <div v-if="detailResult.indirect_sectors.length" class="detail-section"><div class="detail-label">间接关联板块</div><div class="tag-row"><el-tag v-for="s in detailResult.indirect_sectors" :key="s" size="small" type="warning">{{ s }}</el-tag></div></div>
              <div v-if="detailResult.related_stocks.length" class="detail-section"><div class="detail-label">相关标的</div><div class="stock-list"><div v-for="stock in detailResult.related_stocks" :key="stock.code" class="stock-row"><div class="stock-main"><span class="stock-code">{{ stock.code }}</span><span class="stock-name">{{ stock.name }}</span><el-tag :type="mappingStrengthType(stock.mapping_strength)" size="small">{{ mappingStrengthLabel(stock.mapping_strength) }}</el-tag></div><div class="stock-meta"><span>{{ stock.relation }}</span><span v-if="stock.reason">- {{ stock.reason }}</span></div></div></div></div>
              <div v-if="detailResult.risks.length" class="detail-section"><div class="detail-label">风险提示</div><div class="detail-items"><div v-for="(r,i) in detailResult.risks" :key="i" class="detail-item risk-item">{{ r }}</div></div></div>
              <div v-if="detailResult.watch_points.length" class="detail-section"><div class="detail-label">后续观察</div><div class="detail-items"><div v-for="(wp,i) in detailResult.watch_points" :key="i" class="detail-item">{{ wp }}</div></div></div>
            </template>

            <div v-if="detailResult.evidence.length" class="detail-section"><div class="detail-label">证据来源 ({{ detailResult.evidence.length }})</div><div class="evidence-list"><div v-for="ev in detailResult.evidence.slice(0,10)" :key="ev.id" class="evidence-item"><el-tag :type="evidenceLevelType(ev.source_level)" size="small">{{ ev.source_level }}</el-tag><a :href="ev.url" target="_blank" class="evidence-title" :title="ev.title">{{ ev.title }}</a><span class="evidence-source">{{ ev.source }}</span></div></div></div>
          </div>
        </template>
      </aside>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { DataAnalysis, Refresh, Search } from '@element-plus/icons-vue'

interface NewsItem {
  id: string
  title: string
  summary: string
  category: string
  source: string
  eventTime?: string | null
  publishedAt: string
  ingestedAt?: string | null
  impact: 'high' | 'medium' | 'low'
  region?: string
  url?: string | null
  sourceUrl?: string | null
  relatedStocks: RelatedStock[]
}

interface NewsBoardItemsResponse {
  window_hours?: number
  generated_at?: string
  items?: NewsItem[]
  duplicate_count?: number
  has_more?: boolean
  message?: string | null
}

interface RelatedStock {
  code: string
  name: string
  sentiment: string
  reason: string
}

interface DetailRelatedStock {
  code: string
  name: string
  relation: string
  mapping_strength: string
  reason: string
}

interface DetailRealization {
  code: string
  name: string
  change_1d: number | null
  change_3d: number | null
  change_5d: number | null
  change_20d: number | null
  limit_up: boolean
  volume_ratio: number | null
  moved_before_news: boolean
  realization_status: string
  reason: string
}

interface DetailEvidence {
  id: string
  title: string
  url: string
  source: string
  source_level: string
  published_at: string | null
  summary: string
  provider: string
  confidence: number
}

interface DetailRound {
  round_num: number
  queries: string[]
  evidence_count: number
  status: string
}

interface DetailAnalysisResult {
  status: string
  task_id: string
  event_type?: string | null
  confidence?: number | null
  event_summary: string
  core_facts: string[]
  impact_path: { description?: string; confidence?: number }[]
  direct_sectors: string[]
  indirect_sectors: string[]
  related_stocks: DetailRelatedStock[]
  market_realization: DetailRealization[]
  upstream_downstream: string[]
  risks: string[]
  watch_points: string[]
  evidence: DetailEvidence[]
  rounds: DetailRound[]
  reason: string
}

interface NewsBoardStatus {
  redis_available: boolean
  last_update: string | null
  index_count: number
}

interface BatchTheme {
  topic: string
  count: number
  sentiment: string
  description: string
}

interface BatchKeyItem {
  title: string
  event_time: string
  weight: string
  reason: string
}

interface BatchAnalysisResult {
  status: string
  total: number
  summary: string
  themes: BatchTheme[]
  key_items: BatchKeyItem[]
  market_impact: string
  watch_points: string[]
  reason: string
}

const PAGE_SIZE = 50
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'
const loading = ref(false)
const loadingMore = ref(false)
const analyzingBatch = ref(false)
const analyzingItemId = ref<string | null>(null)
const detailCache = new Map<string, DetailAnalysisResult>()
const searchKeyword = ref('')
const newsItems = ref<NewsItem[]>([])
const selectedNews = ref<NewsItem | null>(null)
const detailResult = ref<DetailAnalysisResult | null>(null)
const batchResult = ref<BatchAnalysisResult | null>(null)
const lastGeneratedAt = ref<string | null>(null)
const loadError = ref('')
const hasMore = ref(false)
const searchActive = ref(false)
const totalCached = ref(0)
const scrollContainer = ref<HTMLElement | null>(null)

onMounted(async () => {
  await loadStatus()
  loadNews()
})

let _searchTimer: ReturnType<typeof setTimeout> | null = null
watch(searchKeyword, (val) => {
  if (_searchTimer) clearTimeout(_searchTimer)
  if (!val.trim()) return
  _searchTimer = setTimeout(() => doSearch(val.trim()), 350)
})

function onSearchEnter() {
  if (_searchTimer) clearTimeout(_searchTimer)
  const val = searchKeyword.value.trim()
  if (val) {
    doSearch(val)
  }
}

function onSearchClear() {
  if (_searchTimer) clearTimeout(_searchTimer)
  searchActive.value = false
  loadNews()
}

async function doSearch(keyword: string) {
  searchActive.value = true
  loading.value = true
  loadError.value = ''
  hasMore.value = false
  try {
    const data = await requestJson<NewsBoardItemsResponse>(`news-board/items?window_hours=24&limit=100&keyword=${encodeURIComponent(keyword)}`)
    newsItems.value = data.items || []
    selectedNews.value = newsItems.value[0] || null
    detailResult.value = null
    if (data.message) loadError.value = data.message
  } catch (error) {
    newsItems.value = []
    selectedNews.value = null
    loadError.value = error instanceof Error ? error.message : '搜索请求失败'
  } finally {
    loading.value = false
  }
}

async function loadStatus() {
  try {
    const data = await requestJson<NewsBoardStatus>('news-board/status')
    totalCached.value = data.index_count || 0
  } catch {
    // ignore
  }
}

async function loadNews() {
  if (searchKeyword.value.trim()) {
    doSearch(searchKeyword.value.trim())
    return
  }
  searchActive.value = false
  loading.value = true
  loadError.value = ''
  try {
    newsItems.value = await fetchPage()
    selectedNews.value = newsItems.value[0] || null
    detailResult.value = null
  } catch (error) {
    newsItems.value = []
    selectedNews.value = null
    loadError.value = error instanceof Error ? error.message : '消息接口请求失败'
  } finally {
    loading.value = false
  }
  await loadStatus()
}

async function loadMore() {
  if (loadingMore.value || !hasMore.value || searchActive.value) return
  const oldest = _oldestTs()
  if (oldest === null) return
  loadingMore.value = true
  try {
    const items = await fetchPage(oldest)
    if (items.length > 0) {
      newsItems.value = [...newsItems.value, ...items]
      totalCached.value = Math.max(totalCached.value, newsItems.value.length)
    }
  } catch {
    // silently ignore
  } finally {
    loadingMore.value = false
  }
}

function _oldestTs(): number | null {
  if (newsItems.value.length === 0) return null
  let oldest = Infinity
  for (const item of newsItems.value) {
    const ts = new Date(item.eventTime || item.publishedAt).getTime()
    if (ts < oldest) oldest = ts
  }
  return oldest === Infinity ? null : oldest
}

async function fetchPage(before?: number): Promise<NewsItem[]> {
  let url = `news-board/items?window_hours=24&limit=${PAGE_SIZE}`
  if (before) {
    url += `&before=${new Date(before / 1000 * 1000).toISOString()}`
  }
  const data = await requestJson<NewsBoardItemsResponse>(url)
  lastGeneratedAt.value = data.generated_at || null
  hasMore.value = data.has_more || false
  if (data.message && newsItems.value.length === 0) {
    loadError.value = data.message
  }
  return Array.isArray(data.items) ? data.items : []
}

let _scrollTimer: ReturnType<typeof setTimeout> | null = null
function onScroll() {
  if (_scrollTimer) return
  _scrollTimer = setTimeout(() => {
    _scrollTimer = null
    const el = scrollContainer.value
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120
    if (nearBottom) {
      loadMore()
    }
  }, 100)
}

function selectNews(item: NewsItem) {
  selectedNews.value = item
  detailResult.value = null
}

function backToSearch() {
  selectedNews.value = null
  detailResult.value = null
}

async function analyzeBatch() {
  analyzingBatch.value = true
  batchResult.value = null
  try {
    const items = newsItems.value.map(it => ({
      title: it.title,
      summary: it.summary,
      category: it.category,
      source: it.source,
      eventTime: it.eventTime || it.publishedAt,
      publishedAt: it.publishedAt,
      impact: it.impact,
      region: it.region,
      relatedStocks: it.relatedStocks,
    }))
    batchResult.value = await requestJson<BatchAnalysisResult>('news-board/analyze-batch', {
      method: 'POST',
      body: JSON.stringify({ items, keyword: searchKeyword.value }),
    })
  } catch (error) {
    batchResult.value = {
      status: 'failed',
      total: 0, summary: '', themes: [], key_items: [],
      market_impact: '', watch_points: [],
      reason: error instanceof Error ? error.message : '请求失败',
    }
  } finally {
    analyzingBatch.value = false
  }
}

async function analyzeDetailForItem(item: NewsItem) {
  selectedNews.value = item
  if (detailCache.has(item.id)) {
    detailResult.value = detailCache.get(item.id)!
    return
  }
  analyzingItemId.value = item.id
  detailResult.value = null
  try {
    detailResult.value = await requestJson<DetailAnalysisResult>('news-board/analyze-detail', {
      method: 'POST',
      body: JSON.stringify({
        news_id: item.id,
        title: item.title,
        summary: item.summary,
        category: item.category,
        source: item.source,
        published_at: item.eventTime || item.publishedAt,
        event_time: item.eventTime || null,
        url: item.sourceUrl || item.url || null,
      }),
    })
    detailCache.set(item.id, detailResult.value!)
  } catch (error) {
    detailResult.value = {
      status: 'failed', task_id: '', event_summary: '',
      core_facts: [], impact_path: [], direct_sectors: [], indirect_sectors: [],
      related_stocks: [], market_realization: [], upstream_downstream: [],
      risks: [], watch_points: [], evidence: [], rounds: [],
      reason: error instanceof Error ? error.message : '请求失败',
    }
  } finally {
    analyzingItemId.value = null
  }
}

function detailStatusTagType(status: string) {
  const map: Record<string, 'success' | 'warning' | 'danger' | 'info' | ''> = {
    ready: 'success',
    need_more_data: 'warning',
    stopped: 'info',
    failed: 'danger',
    running: '',
  }
  return map[status] || 'info'
}

function detailStatusLabel(status: string) {
  const map: Record<string, string> = {
    ready: '分析完成',
    need_more_data: '证据不足',
    stopped: '已停止',
    failed: '分析失败',
    running: '分析中...',
  }
  return map[status] || status
}

function mappingStrengthType(strength: string) {
  const map: Record<string, 'success' | 'warning' | 'info' | 'danger' | ''> = {
    strong: 'success',
    medium: 'warning',
    weak: 'info',
  }
  return map[strength] || 'info'
}

function mappingStrengthLabel(strength: string) {
  const map: Record<string, string> = {
    strong: '强关联',
    medium: '中关联',
    weak: '弱关联',
  }
  return map[strength] || strength
}

function evidenceLevelType(level: string) {
  const map: Record<string, 'success' | 'warning' | 'info' | 'danger' | ''> = {
    A: 'success',
    B: '',
    C: 'warning',
    D: 'danger',
  }
  return map[level] || 'info'
}

async function requestJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('stocktrade_token')
  const response = await fetch(buildApiUrl(path), {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  })
  if (!response.ok) {
    throw new Error(`news-board request failed: ${response.status}`)
  }
  return response.json() as Promise<T>
}

function buildApiUrl(path: string) {
  const normalizedBase = API_BASE_URL.replace(/\/+$/, '')
  const normalizedPath = path.replace(/^\/+/, '')
  if (normalizedBase.endsWith('/v1')) {
    return `${normalizedBase}/${normalizedPath}`
  }
  return `${normalizedBase}/v1/${normalizedPath}`
}

function categoryTagType(category: string) {
  const map: Record<string, 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
    policy: 'primary',
    weather: 'warning',
    people: 'danger',
    us_market: 'info',
    price: 'success',
  }
  return map[category] || 'info'
}


function sentimentLabel(s: string) {
  const m: Record<string,string> = { positive:'偏利好', negative:'偏利空', neutral:'中性', mixed:'分化' }
  return m[s] || s
}

function sentimentTagType(s: string) {
  const m: Record<string,string> = { positive:'success', negative:'danger', neutral:'info', mixed:'warning' }
  return m[s] || 'info'
}

function impactTag(s: string) {
  const m: Record<string,string> = { '偏利好':'success', '偏利空':'danger', '中性':'info', '分化':'warning' }
  return m[s] || 'info'
}

function weightTagType(w: string) {
  const m: Record<string,string> = { high:'danger', medium:'warning', low:'info' }
  return m[w] || 'info'
}

function weightLabel(w: string) {
  const m: Record<string,string> = { high:'高', medium:'中', low:'低' }
  return m[w] || w
}

function openSource(item: NewsItem) {
  const url = item.sourceUrl || item.url
  if (!url) return
  window.open(url, '_blank', 'noopener,noreferrer')
}

function formatRelativeTime(value: string) {
  const minutes = Math.max(1, Math.round((Date.now() - new Date(value).getTime()) / 60000))
  if (minutes < 60) return `${minutes}分钟前`
  return `${Math.floor(minutes / 60)}小时前`
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
</script>

<style scoped lang="scss">
.news-board-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.news-board-toolbar,
.news-stream-panel,
.analysis-panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.news-board-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px;
}

.toolbar-main {
  min-width: 220px;
}

.toolbar-title {
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
}

.toolbar-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 6px;
  color: #64748b;
  font-size: 12px;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.keyword-input {
  width: min(360px, 42vw);
}

.news-board-layout {
  display: grid;
  grid-template-columns: minmax(380px, 1fr) 360px;
  gap: 16px;
  align-items: start;
}

.news-stream-panel,
.analysis-panel {
  min-width: 0;
  padding: 14px;
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: #0f172a;
}

.panel-header p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.search-prompt {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  margin-bottom: 12px;
}

.search-prompt-text {
  color: #2563eb;
  font-size: 13px;
}

.news-scroll {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: calc(100vh - 300px);
  min-height: 480px;
  overflow: auto;
  padding-right: 4px;
}

.news-item {
  width: 100%;
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  text-align: left;
}

.news-item.active {
  border-color: #38bdf8;
  box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.14);
}

.news-item__top,
.news-footer,
.selected-meta,
.stock-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.news-time,
.news-footer,
.selected-meta {
  color: #64748b;
  font-size: 12px;
}

.news-title {
  margin-top: 9px;
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.4;
}

.news-summary {
  margin-top: 6px;
  color: #475569;
  line-height: 1.6;
}

.news-footer {
  margin-top: 10px;
}

.analysis-header {
  align-items: center;
}

.selected-card,
.analysis-result,
.empty-hint {
  text-align: center;
  color: #94a3b8;
  padding: 40px 0;
  font-size: 13px;
}

.batch-themes {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.batch-theme-item {
  padding: 8px 10px;
  background: #fff;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
}

.batch-theme-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.batch-theme-topic {
  font-weight: 700;
  color: #0f172a;
}

.batch-theme-count {
  color: #94a3b8;
  font-size: 12px;
  margin-left: auto;
}

.batch-theme-desc {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.batch-items {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.batch-item-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 8px;
  background: #fff;
  border-radius: 4px;
  font-size: 13px;
}

.batch-item-title {
  color: #0f172a;
  flex: 1;
  min-width: 0;
}

.batch-item-reason {
  color: #94a3b8;
  font-size: 12px;
  white-space: nowrap;
}

.selected-title {
  font-weight: 700;
  color: #0f172a;
  line-height: 1.5;
}

.selected-card p {
  margin: 10px 0 0;
  color: #475569;
  line-height: 1.6;
}

.selected-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

.analysis-buttons {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.detail-result {
  margin-top: 12px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px;
  max-height: calc(100vh - 280px);
  overflow-y: auto;
}

.detail-status {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.detail-confidence {
  color: #64748b;
  font-size: 12px;
}

.detail-section {
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid #e5e7eb;
}

.detail-section:last-child {
  border-bottom: none;
  margin-bottom: 0;
  padding-bottom: 0;
}

.detail-label {
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 6px;
  font-size: 13px;
}

.detail-text {
  color: #475569;
  line-height: 1.6;
  font-size: 13px;
}

.detail-items {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.detail-item {
  color: #475569;
  line-height: 1.5;
  font-size: 13px;
  padding: 4px 8px;
  background: #fff;
  border-radius: 4px;
}

.fact-item {
  border-left: 3px solid #38bdf8;
}

.risk-item {
  border-left: 3px solid #f87171;
}

.detail-sub {
  color: #94a3b8;
  font-size: 11px;
  margin-left: 4px;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.realization-row {
  padding: 8px 10px;
}

.realization-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 6px;
}

.realization-item {
  font-size: 12px;
  color: #64748b;
}

.realization-item .up {
  color: #dc2626;
}

.realization-item .down {
  color: #16a34a;
}

.evidence-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.evidence-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 4px 6px;
  background: #fff;
  border-radius: 4px;
}

.evidence-title {
  color: #2563eb;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.evidence-source {
  color: #94a3b8;
  white-space: nowrap;
  flex-shrink: 0;
}

.rounds-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.round-item {
  font-size: 12px;
  color: #64748b;
  padding: 3px 8px;
  background: #fff;
  border-radius: 4px;
}

.keyword-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.loading-box {
  padding: 16px 0;
}

.loading-more {
  padding: 8px 0;
}

.end-hint {
  text-align: center;
  color: #94a3b8;
  font-size: 12px;
  padding: 12px 0;
}

@media (max-width: 1180px) {
  .news-board-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .analysis-panel {
    grid-column: 1 / -1;
  }

  .news-scroll {
    max-height: none;
  }
}

@media (max-width: 760px) {
  .news-board-toolbar,
  .toolbar-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .keyword-input {
    width: 100%;
  }

  .news-scroll {
    min-height: 0;
  }
}
</style>
