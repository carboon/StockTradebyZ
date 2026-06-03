<template>
  <div class="news-board-page">
    <section class="news-board-toolbar">
      <div class="toolbar-main">
        <div class="toolbar-title">24H 消息监控</div>
        <div class="toolbar-meta">
          <span>{{ visibleNews.length }} 条有效消息</span>
          <span>{{ uniqueSourceCount }} 个来源</span>
          <span>去重 {{ duplicateCount }} 条</span>
          <span v-if="lastGeneratedAt">更新 {{ formatDateTime(lastGeneratedAt) }}</span>
        </div>
      </div>
      <div class="toolbar-actions">
        <el-input
          v-model="keyword"
          class="keyword-input"
          clearable
          placeholder="搜索政策、人物、公司、股票"
          :prefix-icon="Search"
        />
        <el-button :icon="Refresh" :loading="loading" @click="loadNews">
          刷新
        </el-button>
      </div>
    </section>

    <el-alert
      v-if="loadError"
      type="warning"
      show-icon
      :closable="false"
      class="page-alert"
      title="真实消息源暂不可用"
      :description="loadError"
    />

    <section class="source-strip">
      <div
        v-for="source in sourceStatus"
        :key="source.source_key"
        class="source-item"
      >
        <span class="source-dot" :class="source.available ? 'is-ready' : 'is-pending'" />
        <span>{{ source.name }}</span>
        <small>{{ source.item_count }} 条 · {{ source.description || source.source_key }}</small>
      </div>
    </section>

    <section class="news-board-layout">
      <aside class="category-panel">
        <button
          v-for="category in categories"
          :key="category.key"
          type="button"
          class="category-button"
          :class="{ active: activeCategory === category.key }"
          @click="activeCategory = category.key"
        >
          <span class="category-label">{{ category.label }}</span>
          <span class="category-count">{{ getCategoryCount(category.key) }}</span>
        </button>
      </aside>

      <main class="news-stream-panel">
        <div class="panel-header">
          <div>
            <h3>{{ activeCategoryLabel }}</h3>
            <p>仅展示最近 24 小时内消息，按 Tushare news 来源分组。</p>
          </div>
        </div>

        <div v-if="loading && visibleNews.length === 0" class="loading-box">
          <el-skeleton :rows="6" animated />
        </div>
        <el-empty v-else-if="filteredNews.length === 0" description="暂无匹配消息" :image-size="90" />
        <div v-else class="news-scroll">
          <button
            v-for="item in filteredNews"
            :key="item.id"
            type="button"
            class="news-item"
            :class="{ active: selectedNews?.id === item.id }"
            @click="selectNews(item)"
          >
            <div class="news-item__top">
              <el-tag :type="categoryTagType(item.category)" size="small">{{ categoryLabel(item.category) }}</el-tag>
              <el-tag :type="impactTagType(item.impact)" size="small" effect="plain">{{ impactLabel(item.impact) }}</el-tag>
              <span class="news-time">{{ formatRelativeTime(item.eventTime || item.publishedAt) }}</span>
            </div>
            <div class="news-title">{{ item.title }}</div>
            <div v-if="item.summary" class="news-summary">{{ item.summary }}</div>
            <div class="news-footer">
              <span>{{ item.source }}</span>
              <span>{{ sourceLevelLabel(item.sourceLevel) }}</span>
              <span v-if="item.eventTime">事件 {{ formatDateTime(item.eventTime) }}</span>
              <span v-if="item.ingestedAt">延迟 {{ formatLatency(item.eventTime || item.publishedAt, item.ingestedAt) }}</span>
              <span v-if="item.region">{{ item.region }}</span>
              <span v-if="item.relatedStocks.length">{{ item.relatedStocks.length }} 只关联股票</span>
            </div>
          </button>
        </div>
      </main>

      <aside class="analysis-panel">
        <div class="panel-header analysis-header">
          <div>
            <h3>AI 分析端口</h3>
            <p>基于消息文本、来源和市场标签生成股票线索。</p>
          </div>
          <el-button
            type="primary"
            :icon="DataAnalysis"
            :loading="analyzing"
            :disabled="!selectedNews"
            @click="analyzeSelectedNews"
          >
            分析
          </el-button>
        </div>

        <div v-if="selectedNews" class="selected-card">
          <div class="selected-title">{{ selectedNews.title }}</div>
          <div class="selected-meta">
            <span>{{ selectedNews.source }}</span>
            <span>{{ sourceLevelLabel(selectedNews.sourceLevel) }}</span>
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

        <div v-if="analysisResult" class="analysis-result">
          <div class="analysis-summary">{{ analysisResult.summary }}</div>
          <div class="stock-list">
            <div
              v-for="stock in analysisResult.stocks"
              :key="stock.code"
              class="stock-row"
            >
              <div class="stock-main">
                <span class="stock-code">{{ stock.code }}</span>
                <span class="stock-name">{{ stock.name }}</span>
              </div>
              <div class="stock-meta">
                <el-tag :type="stock.sentiment === 'positive' ? 'success' : stock.sentiment === 'negative' ? 'danger' : 'warning'" size="small">
                  {{ sentimentLabel(stock.sentiment) }}
                </el-tag>
                <span>{{ stock.reason }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="watch-keywords">
          <div class="watch-keywords__title">重点追踪对象</div>
          <div class="keyword-tags">
            <el-tag v-for="tag in watchKeywords" :key="tag" size="small" effect="plain">{{ tag }}</el-tag>
          </div>
        </div>
      </aside>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { DataAnalysis, Refresh, Search } from '@element-plus/icons-vue'

type NewsCategory = 'xq' | 'jinshi' | 'sina' | 'jinrongjie' | 'yicai' | '10jqka' | 'cls' | 'eastmoney' | 'wallstreetcn'
type NewsImpact = 'high' | 'medium' | 'low'
type Sentiment = 'positive' | 'neutral' | 'negative'

interface NewsItem {
  id: string
  title: string
  summary: string
  category: NewsCategory
  source: string
  eventTime?: string | null
  publishedAt: string
  ingestedAt?: string | null
  impact: Exclude<NewsImpact, 'all'>
  region?: string
  url?: string | null
  sourceUrl?: string | null
  sourceLevel?: string | null
  sourceType?: string | null
  relatedStocks: RelatedStock[]
}

interface NewsSourceStatus {
  name: string
  source_key: string
  available: boolean
  item_count: number
  description?: string | null
}

interface NewsBoardItemsResponse {
  window_hours?: number
  generated_at?: string
  items?: NewsItem[]
  sources?: NewsSourceStatus[]
  duplicate_count?: number
  message?: string | null
}

interface RelatedStock {
  code: string
  name: string
  sentiment: Sentiment
  reason: string
}

interface NewsAnalysisResult {
  summary: string
  stocks: RelatedStock[]
}

const categories: Array<{ key: NewsCategory, label: string }> = [
  { key: 'xq', label: '雪球' },
  { key: 'jinshi', label: '金十' },
  { key: 'sina', label: '新浪财经' },
  { key: 'jinrongjie', label: '金融界' },
  { key: 'yicai', label: '第一财经' },
  { key: '10jqka', label: '同花顺' },
  { key: 'cls', label: '财联社' },
  { key: 'eastmoney', label: '东方财富' },
  { key: 'wallstreetcn', label: '华尔街见闻' },
]

const watchKeywords = ['雪球', '金十', '新浪财经', '金融界', '第一财经', '同花顺', '财联社', '东方财富', '华尔街见闻']
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'
const loading = ref(false)
const analyzing = ref(false)
const keyword = ref('')
const activeCategory = ref<NewsCategory>('xq')
const newsItems = ref<NewsItem[]>([])
const sourceStatus = ref<NewsSourceStatus[]>([])
const selectedNews = ref<NewsItem | null>(null)
const analysisResult = ref<NewsAnalysisResult | null>(null)
const lastGeneratedAt = ref<string | null>(null)
const loadError = ref('')

const duplicateCount = ref(0)
const uniqueSourceCount = computed(() => new Set(visibleNews.value.map((item) => item.source)).size)
const activeCategoryLabel = computed(() => categories.find((item) => item.key === activeCategory.value)?.label || '雪球')

const visibleNews = computed(() => {
  const since = Date.now() - 24 * 60 * 60 * 1000
  const seen = new Set<string>()
  return newsItems.value
    .filter((item) => new Date(item.eventTime || item.publishedAt).getTime() >= since)
    .filter((item) => {
      const key = `${normalizeText(item.title)}:${item.source}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    .sort((a, b) => new Date(b.eventTime || b.publishedAt).getTime() - new Date(a.eventTime || a.publishedAt).getTime())
})

const filteredNews = computed(() => {
  const query = normalizeText(keyword.value)
  return visibleNews.value.filter((item) => {
    const categoryMatched = item.category === activeCategory.value
    const haystack = `${item.title}${item.summary}${item.source}${item.region || ''}${item.sourceLevel || ''}`
    const queryMatched = !query || normalizeText(haystack).includes(query)
    return categoryMatched && queryMatched
  })
})

onMounted(() => {
  loadNews()
})

async function loadNews() {
  loading.value = true
  loadError.value = ''
  try {
    newsItems.value = await fetchNewsItems()
    selectedNews.value = filteredNews.value[0] || null
    analysisResult.value = selectedNews.value ? buildHeuristicAnalysis(selectedNews.value) : null
  } catch (error) {
    newsItems.value = []
    selectedNews.value = null
    analysisResult.value = null
    loadError.value = error instanceof Error ? error.message : '消息接口请求失败'
  } finally {
    loading.value = false
  }
}

function selectNews(item: NewsItem) {
  selectedNews.value = item
  analysisResult.value = buildHeuristicAnalysis(item)
}

async function analyzeSelectedNews() {
  if (!selectedNews.value) return
  analyzing.value = true
  try {
    analysisResult.value = await fetchNewsAnalysis(selectedNews.value)
  } finally {
    analyzing.value = false
  }
}

async function fetchNewsItems(): Promise<NewsItem[]> {
  const data = await requestJson<NewsBoardItemsResponse>('news-board/items?window_hours=24')
  sourceStatus.value = data.sources || []
  lastGeneratedAt.value = data.generated_at || null
  duplicateCount.value = data.duplicate_count || 0
  if (data.message) {
    loadError.value = data.message
  }
  return Array.isArray(data.items) ? data.items : []
}

async function fetchNewsAnalysis(item: NewsItem): Promise<NewsAnalysisResult> {
  try {
    return await requestJson<NewsAnalysisResult>('news-board/analyze', {
      method: 'POST',
      body: JSON.stringify({ news_id: item.id, title: item.title, summary: item.summary, category: item.category }),
    })
  } catch {
    return buildHeuristicAnalysis(item)
  }
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

function buildHeuristicAnalysis(item: NewsItem): NewsAnalysisResult {
  const stocks = item.relatedStocks.length > 0 ? item.relatedStocks : inferStocks(item)
  const attentionText = item.impact === 'high' ? '关注度较高，可能带动 A 股相关板块扩散。' : '关注度中低，先观察同源和跨源扩散。'
  return {
    summary: `${categoryLabel(item.category)}消息触发 ${stocks.length} 条 A 股股票线索。${attentionText}请结合板块成交额、涨停扩散和原始来源二次确认。`,
    stocks,
  }
}

function inferStocks(item: NewsItem): RelatedStock[] {
  const text = `${item.title}${item.summary}`.toLowerCase()
  if (text.includes('ai') || text.includes('算力') || text.includes('英伟达')) {
    return [{ code: '300308.SZ', name: '中际旭创', sentiment: 'positive', reason: 'A股 AI 光模块与高速互联链条' }]
  }
  return [{ code: '000300.SH', name: '沪深300', sentiment: 'neutral', reason: '未识别明确 A 股产业链，先作为市场风险偏好观察' }]
}

function getCategoryCount(category: NewsCategory) {
  return visibleNews.value.filter((item) => item.category === category).length
}

function normalizeText(text: string) {
  return text.trim().toLowerCase().replace(/\s+/g, '')
}

function categoryLabel(category: NewsItem['category']) {
  return categories.find((item) => item.key === category)?.label || category
}

function categoryTagType(category: NewsItem['category']) {
  const map: Record<NewsItem['category'], 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
    xq: 'primary',
    jinshi: 'warning',
    sina: 'danger',
    jinrongjie: 'success',
    yicai: 'primary',
    '10jqka': 'info',
    cls: 'warning',
    eastmoney: 'success',
    wallstreetcn: 'info',
  }
  return map[category]
}

function impactLabel(impact: NewsItem['impact']) {
  const map = { high: '高影响', medium: '中影响', low: '低影响' }
  return map[impact]
}

function impactTagType(impact: NewsItem['impact']) {
  if (impact === 'high') return 'danger'
  if (impact === 'medium') return 'warning'
  return 'info'
}

function sentimentLabel(sentiment: Sentiment) {
  if (sentiment === 'positive') return '利好'
  if (sentiment === 'negative') return '利空'
  return '中性'
}

function sourceLevelLabel(level?: string | null) {
  const map: Record<string, string> = {
    regulatory: '监管源',
    official: '官方源',
    company_ir: '公司源',
    data_vendor: '数据源',
    media: '媒体源',
    model_search: '模型检索',
  }
  return map[level || ''] || '媒体源'
}

function formatLatency(startValue?: string | null, endValue?: string | null) {
  if (!startValue || !endValue) return '-'
  const start = new Date(startValue).getTime()
  const end = new Date(endValue).getTime()
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return '-'
  const minutes = Math.round((end - start) / 60000)
  if (minutes < 60) return `${minutes}分钟`
  return `${Math.floor(minutes / 60)}小时${minutes % 60}分钟`
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
.source-strip,
.category-panel,
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

.source-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  padding: 12px;
}

.source-item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  color: #334155;
}

.source-item small {
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 999px;
  background: #f59e0b;
}

.source-dot.is-ready {
  background: #16a34a;
}

.news-board-layout {
  display: grid;
  grid-template-columns: 180px minmax(380px, 1fr) 360px;
  gap: 16px;
  align-items: start;
}

.category-panel {
  display: flex;
  flex-direction: column;
  padding: 8px;
  position: sticky;
  top: 12px;
}

.category-button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  min-height: 40px;
  padding: 8px 10px;
  border: 0;
  border-radius: 6px;
  color: #334155;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.category-button.active {
  background: #e0f2fe;
  color: #0369a1;
  font-weight: 700;
}

.category-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.category-count {
  min-width: 24px;
  padding: 1px 6px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 12px;
  text-align: center;
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

.filter-stack {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.source-level-select,
.topic-select {
  width: 132px;
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
.watch-keywords {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px;
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

.analysis-result {
  margin-top: 12px;
  background: #f8fafc;
}

.analysis-summary {
  color: #334155;
  line-height: 1.6;
}

.stock-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}

.stock-row {
  padding: 10px;
  border-radius: 6px;
  background: #fff;
}

.stock-main {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.stock-code {
  font-weight: 800;
  color: #0f172a;
}

.stock-name {
  color: #475569;
}

.stock-meta {
  margin-top: 8px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.watch-keywords {
  margin-top: 12px;
}

.watch-keywords__title {
  margin-bottom: 10px;
  color: #334155;
  font-weight: 700;
}

.keyword-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.loading-box {
  padding: 16px 0;
}

@media (max-width: 1180px) {
  .news-board-layout {
    grid-template-columns: 160px minmax(0, 1fr);
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
  .toolbar-actions,
  .panel-header,
  .filter-stack {
    flex-direction: column;
    align-items: stretch;
  }

  .source-level-select,
  .topic-select {
    width: 100%;
  }

  .keyword-input {
    width: 100%;
  }

  .source-strip,
  .news-board-layout {
    grid-template-columns: 1fr;
  }

  .category-panel {
    position: static;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .news-scroll {
    min-height: 0;
  }
}
</style>
