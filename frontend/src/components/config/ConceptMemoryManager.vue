<template>
  <div class="concept-memory">
    <el-alert
      title="概念记忆库说明"
      description="这里保存稳定知识、网站补充信息和 AI 归纳结果。检索时会先命中本地记忆，再补官方数据与新闻，最后把上下文交给 LLM 生成建议。"
      type="info"
      show-icon
      :closable="false"
      class="concept-memory__alert"
    />

    <div class="concept-memory__toolbar">
      <el-button :loading="loadingEntries" @click="loadEntries">刷新列表</el-button>
      <el-button type="primary" @click="startCreate">新建条目</el-button>
      <el-button
        type="success"
        :disabled="!selectedEntryId"
        :loading="refreshing"
        @click="refreshSelectedEntry"
      >
        单独更新
      </el-button>
    </div>

    <div class="concept-memory__filters">
      <el-input v-model="filters.keyword" clearable placeholder="关键词 / 标题 / 标签" />
      <el-select v-model="filters.source_type" clearable placeholder="来源类型">
        <el-option label="manual" value="manual" />
        <el-option label="website" value="website" />
        <el-option label="ai" value="ai" />
        <el-option label="static" value="static" />
      </el-select>
      <el-select v-model="filters.status" clearable placeholder="状态">
        <el-option label="draft" value="draft" />
        <el-option label="ready" value="ready" />
        <el-option label="error" value="error" />
      </el-select>
      <el-button :loading="loadingEntries" @click="loadEntries">筛选</el-button>
    </div>

    <div class="concept-memory__stats" v-if="statsCards.length > 0">
      <el-card v-for="card in statsCards" :key="card.label" class="concept-memory__stat-card" shadow="never">
        <div class="concept-memory__stat-label">{{ card.label }}</div>
        <div class="concept-memory__stat-value">{{ card.value }}</div>
      </el-card>
    </div>

    <div class="concept-memory__grid">
      <el-card class="concept-memory__list">
        <template #header>
          <div class="card-header">
            <span>条目列表</span>
            <el-tag size="small" effect="plain">{{ entryCountLabel }}</el-tag>
          </div>
        </template>

        <el-table
          :data="entries"
          stripe
          height="420"
          highlight-current-row
          :row-class-name="resolveRowClassName"
          @current-change="handleSelectEntry"
        >
          <el-table-column prop="keyword" label="主题" min-width="120" />
          <el-table-column prop="title" label="标题" min-width="160" />
          <el-table-column prop="source_type" label="来源" width="90" />
          <el-table-column prop="status" label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="resolveStatusType(row.status)" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="priority" label="优先级" width="88" align="center" />
          <el-table-column prop="is_fixed" label="固定" width="70" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.is_fixed" type="success" size="small">是</el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card class="concept-memory__editor">
        <template #header>
          <div class="card-header">
            <span>{{ form.id ? '编辑条目' : '新建条目' }}</span>
            <el-tag size="small" effect="plain">{{ form.id ? `#${form.id}` : 'draft' }}</el-tag>
          </div>
        </template>

        <el-form label-position="top" class="concept-memory__form">
          <el-form-item label="主题关键字">
            <el-input v-model="form.keyword" placeholder="例如：PCB、光模块、国家规划" />
          </el-form-item>
          <el-form-item label="标题">
            <el-input v-model="form.title" placeholder="例如：PCB 产业链基础知识" />
          </el-form-item>
          <el-form-item label="内容">
            <el-input
              v-model="form.content"
              type="textarea"
              :autosize="{ minRows: 5, maxRows: 12 }"
              placeholder="写入固定知识、事件摘要、策略说明、上下游解释等"
            />
          </el-form-item>
          <div class="concept-memory__form-grid">
            <el-form-item label="分类">
              <el-input v-model="form.category" placeholder="policy / sector / event / company / industry" />
            </el-form-item>
            <el-form-item label="来源类型">
              <el-select v-model="form.source_type">
                <el-option label="manual" value="manual" />
                <el-option label="website" value="website" />
                <el-option label="ai" value="ai" />
                <el-option label="static" value="static" />
              </el-select>
            </el-form-item>
          </div>
          <el-form-item label="来源名称">
            <el-input v-model="form.source_name" placeholder="例如：Tushare 第一财经 / 人工整理" />
          </el-form-item>
          <el-form-item label="来源链接">
            <el-input v-model="form.source_url" placeholder="可选" />
          </el-form-item>
          <div class="concept-memory__form-grid">
            <el-form-item label="状态">
              <el-select v-model="form.status">
                <el-option label="draft" value="draft" />
                <el-option label="ready" value="ready" />
                <el-option label="error" value="error" />
              </el-select>
            </el-form-item>
            <el-form-item label="优先级">
              <el-input-number v-model="form.priority" :min="-100" :max="100" :step="1" />
            </el-form-item>
          </div>
          <div class="concept-memory__form-grid">
            <el-form-item label="固定知识">
              <el-switch v-model="form.is_fixed" />
            </el-form-item>
            <el-form-item label="标签">
              <el-input v-model="form.tags_text" placeholder="逗号、顿号、换行分隔" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
            </el-form-item>
          </div>
          <el-form-item label="关联股票代码">
            <el-input v-model="form.related_stock_codes_text" placeholder="如 000001, 600000" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
          </el-form-item>

          <div class="concept-memory__actions">
            <el-button type="primary" :loading="saving" @click="saveEntry">保存</el-button>
            <el-button @click="resetForm">清空</el-button>
          </div>
        </el-form>
      </el-card>
    </div>

    <el-card v-if="latestRefresh" class="concept-memory__result">
      <template #header>
        <div class="card-header">
          <span>最近更新结果</span>
          <el-tag size="small" :type="resolveStatusType(latestRefresh.run.status)">{{ latestRefresh.run.status }}</el-tag>
        </div>
      </template>
      <div class="result-line"><strong>主题：</strong>{{ latestRefresh.keyword }}</div>
      <div class="result-line"><strong>匹配官方概念：</strong>{{ latestRefresh.matched_official_concepts.map((item) => item.concept_name).join(' / ') || '-' }}</div>
      <div class="result-line"><strong>AI 摘要：</strong>{{ latestRefresh.ai_summary || '-' }}</div>
      <div class="result-line"><strong>AI 关键词：</strong>{{ latestRefresh.ai_keywords.join(' / ') || '-' }}</div>
      <div class="result-line"><strong>相关股票：</strong>{{ latestRefresh.ai_related_stock_codes.join(' / ') || '-' }}</div>
    </el-card>

    <el-card class="concept-memory__query">
      <template #header>
        <div class="card-header">
          <span>上下文检索</span>
          <el-tag size="small" effect="plain">{{ latestCompose?.source || '未检索' }}</el-tag>
        </div>
      </template>

      <div class="concept-memory__query-bar">
        <el-input
          v-model="queryForm.query"
          placeholder="输入问题，例如 PCB、光模块、国家重点规划"
          clearable
          @keyup.enter="composeContext"
        />
        <el-switch v-model="queryForm.use_ai" active-text="调用 LLM" inactive-text="仅上下文" />
        <el-button :loading="composing" type="primary" @click="composeContext">生成上下文</el-button>
        <el-button @click="clearCompose">清空</el-button>
      </div>

      <div class="concept-memory__query-meta">
        <el-tag type="info" effect="plain">命中条目 {{ latestCompose?.matched_entries?.length || 0 }}</el-tag>
        <el-tag type="info" effect="plain">新闻 {{ latestCompose?.matched_news?.length || 0 }}</el-tag>
        <el-tag type="info" effect="plain">官方概念 {{ latestCompose?.matched_official_concepts?.length || 0 }}</el-tag>
      </div>

      <div v-if="latestCompose" class="concept-memory__query-content">
        <div class="query-block">
          <div class="query-block__title">组合上下文</div>
          <pre class="query-block__text">{{ latestCompose.context_text }}</pre>
        </div>
        <div class="query-grid">
          <div class="query-block">
            <div class="query-block__title">本地记忆</div>
            <ul class="query-list">
              <li v-for="item in latestCompose.matched_entries" :key="item.id">
                <strong>{{ item.keyword }}</strong> - {{ item.title }}
              </li>
            </ul>
          </div>
          <div class="query-block">
            <div class="query-block__title">近期新闻</div>
            <ul class="query-list">
              <li v-for="item in latestCompose.matched_news" :key="`${item.datetime || ''}-${item.title || ''}`">
                <strong>{{ item.title || '-' }}</strong>
              </li>
            </ul>
          </div>
        </div>
        <div v-if="latestCompose.ai_result" class="query-block">
          <div class="query-block__title">AI 结果</div>
          <pre class="query-block__text">{{ JSON.stringify(latestCompose.ai_result, null, 2) }}</pre>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiConceptMemory } from '@/api'
import type {
  ConceptMemoryComposeResponse,
  ConceptMemoryDetailResponse,
  ConceptMemoryEntryItem,
  ConceptMemoryListResponse,
  ConceptMemoryRefreshResponse,
  ConceptMemoryUpsertRequest,
} from '@/types'

type FormState = {
  id: number | null
  keyword: string
  title: string
  content: string
  category: string
  source_type: string
  source_name: string
  source_url: string
  status: string
  priority: number
  is_fixed: boolean
  tags_text: string
  related_stock_codes_text: string
}

const entries = ref<ConceptMemoryEntryItem[]>([])
const loadingEntries = ref(false)
const saving = ref(false)
const refreshing = ref(false)
const composing = ref(false)
const selectedEntryId = ref<number | null>(null)
const latestRefresh = ref<ConceptMemoryRefreshResponse | null>(null)
const latestCompose = ref<ConceptMemoryComposeResponse | null>(null)

const filters = reactive({
  keyword: '',
  source_type: '',
  status: '',
})

const form = reactive<FormState>({
  id: null,
  keyword: '',
  title: '',
  content: '',
  category: '',
  source_type: 'manual',
  source_name: '',
  source_url: '',
  status: 'draft',
  priority: 0,
  is_fixed: false,
  tags_text: '',
  related_stock_codes_text: '',
})

const queryForm = reactive({
  query: '',
  use_ai: true,
  force_refresh: false,
  max_entries: 8,
  max_news: 10,
})

const entryCountLabel = computed(() => `${entries.value.length} 条`)
const statsCards = computed(() => [
  { label: '总条目', value: latestList.value?.stats?.total ?? entries.value.length },
  { label: '固定知识', value: latestList.value?.stats?.fixed_count ?? 0 },
  { label: '网站来源', value: latestList.value?.stats?.website_count ?? 0 },
  { label: 'AI 来源', value: latestList.value?.stats?.ai_count ?? 0 },
])

const latestList = ref<ConceptMemoryListResponse | null>(null)

function splitTextList(value: string): string[] {
  return value
    .split(/[\n,，、;]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function joinTextList(values: string[]): string {
  return values.join('\n')
}

function resolveStatusType(status?: string | null): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'ready' || status === 'completed') return 'success'
  if (status === 'error' || status === 'failed') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

function resolveRowClassName({ row }: { row: ConceptMemoryEntryItem }) {
  return row.id === selectedEntryId.value ? 'is-selected' : ''
}

function applyEntry(detail: ConceptMemoryDetailResponse) {
  form.id = detail.id
  form.keyword = detail.keyword
  form.title = detail.title
  form.content = detail.content
  form.category = detail.category || ''
  form.source_type = detail.source_type || 'manual'
  form.source_name = detail.source_name || ''
  form.source_url = detail.source_url || ''
  form.status = detail.status || 'draft'
  form.priority = detail.priority || 0
  form.is_fixed = detail.is_fixed
  form.tags_text = joinTextList(detail.tags || [])
  form.related_stock_codes_text = joinTextList(detail.related_stock_codes || [])
}

function resetForm() {
  form.id = null
  form.keyword = ''
  form.title = ''
  form.content = ''
  form.category = ''
  form.source_type = 'manual'
  form.source_name = ''
  form.source_url = ''
  form.status = 'draft'
  form.priority = 0
  form.is_fixed = false
  form.tags_text = ''
  form.related_stock_codes_text = ''
}

function startCreate() {
  selectedEntryId.value = null
  latestRefresh.value = null
  resetForm()
}

function buildPayload(): ConceptMemoryUpsertRequest {
  return {
    keyword: form.keyword.trim(),
    title: form.title.trim(),
    content: form.content.trim(),
    category: form.category.trim() || null,
    source_type: form.source_type || 'manual',
    source_name: form.source_name.trim() || null,
    source_url: form.source_url.trim() || null,
    status: form.status || 'draft',
    priority: Number(form.priority || 0),
    is_fixed: form.is_fixed,
    tags: splitTextList(form.tags_text),
    related_stock_codes: splitTextList(form.related_stock_codes_text),
  }
}

async function loadEntries() {
  loadingEntries.value = true
  try {
    const response = await apiConceptMemory.list({
      keyword: filters.keyword.trim() || undefined,
      source_type: filters.source_type || undefined,
      status: filters.status || undefined,
      limit: 500,
    })
    latestList.value = response
    entries.value = response.entries || []
    if (selectedEntryId.value) {
      const current = entries.value.find((item) => item.id === selectedEntryId.value)
      if (current) {
        await selectEntry(current.id)
      }
    }
  } catch (error) {
    ElMessage.error(String(error instanceof Error ? error.message : error))
  } finally {
    loadingEntries.value = false
  }
}

async function selectEntry(entryId: number) {
  selectedEntryId.value = entryId
  try {
    const detail = await apiConceptMemory.getDetail(entryId)
    applyEntry(detail)
  } catch (error) {
    ElMessage.error(String(error instanceof Error ? error.message : error))
  }
}

async function handleSelectEntry(row?: ConceptMemoryEntryItem | null) {
  if (!row?.id) return
  await selectEntry(row.id)
}

async function saveEntry() {
  const payload = buildPayload()
  if (!payload.keyword) {
    ElMessage.warning('主题关键字不能为空')
    return
  }
  if (!payload.title) {
    ElMessage.warning('标题不能为空')
    return
  }
  if (!payload.content) {
    ElMessage.warning('内容不能为空')
    return
  }

  saving.value = true
  try {
    const detail = form.id
      ? await apiConceptMemory.update(form.id, payload)
      : await apiConceptMemory.create(payload)
    applyEntry(detail)
    selectedEntryId.value = detail.id
    await loadEntries()
    ElMessage.success('概念记忆条目已保存')
  } catch (error) {
    ElMessage.error(String(error instanceof Error ? error.message : error))
  } finally {
    saving.value = false
  }
}

async function refreshSelectedEntry() {
  if (!selectedEntryId.value) {
    ElMessage.warning('请先选择一个条目')
    return
  }
  refreshing.value = true
  try {
    latestRefresh.value = await apiConceptMemory.refresh(selectedEntryId.value)
    await loadEntries()
    ElMessage.success('条目已刷新')
  } catch (error) {
    ElMessage.error(String(error instanceof Error ? error.message : error))
  } finally {
    refreshing.value = false
  }
}

async function composeContext() {
  if (!queryForm.query.trim()) {
    ElMessage.warning('请输入检索问题')
    return
  }
  composing.value = true
  try {
    latestCompose.value = await apiConceptMemory.compose({
      query: queryForm.query.trim(),
      use_ai: queryForm.use_ai,
      force_refresh: queryForm.force_refresh,
      max_entries: queryForm.max_entries,
      max_news: queryForm.max_news,
    })
    ElMessage.success('上下文已生成')
  } catch (error) {
    ElMessage.error(String(error instanceof Error ? error.message : error))
  } finally {
    composing.value = false
  }
}

function clearCompose() {
  queryForm.query = ''
  latestCompose.value = null
}

onMounted(() => {
  void loadEntries()
})
</script>

<style scoped>
.concept-memory {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.concept-memory__toolbar,
.concept-memory__filters,
.concept-memory__query-bar,
.concept-memory__query-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

.concept-memory__stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.concept-memory__stat-card {
  border-radius: 14px;
}

.concept-memory__stat-label {
  color: #64748b;
  font-size: 12px;
}

.concept-memory__stat-value {
  margin-top: 8px;
  font-size: 22px;
  font-weight: 700;
  color: #0f172a;
}

.concept-memory__grid {
  display: grid;
  grid-template-columns: minmax(320px, 1fr) minmax(360px, 1.1fr);
  gap: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.concept-memory__form {
  display: flex;
  flex-direction: column;
}

.concept-memory__form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.concept-memory__actions {
  display: flex;
  gap: 12px;
}

.concept-memory__query-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 12px;
}

.query-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.query-block {
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fbfdff;
}

.query-block__title {
  font-weight: 700;
  margin-bottom: 8px;
  color: #0f172a;
}

.query-block__text {
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: #334155;
}

.query-list {
  margin: 0;
  padding-left: 18px;
}

.result-line {
  line-height: 1.7;
}

@media (max-width: 960px) {
  .concept-memory__grid,
  .concept-memory__stats,
  .query-grid,
  .concept-memory__form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
