<template>
  <div class="custom-concepts">
    <el-alert
      title="自定义概念说明"
      description="先维护概念名、别名和关联官方板块，再手动触发 AI 汇聚。汇聚结果会落库缓存，后续筛选直接查库，不会重复请求 AI。"
      type="info"
      show-icon
      :closable="false"
      class="custom-concepts__alert"
    />

    <div class="custom-concepts__toolbar">
      <el-button :loading="loadingConcepts" @click="loadConcepts">刷新列表</el-button>
      <el-button type="primary" @click="startCreate">新建概念</el-button>
      <el-button
        type="success"
        :disabled="!selectedConceptId"
        :loading="refreshing"
        @click="refreshSelectedConcept"
      >
        重新汇聚
      </el-button>
      <el-button
        type="danger"
        :disabled="!selectedConceptId"
        :loading="deleting"
        @click="deleteSelectedConcept"
      >
        删除概念
      </el-button>
    </div>

    <div class="custom-concepts__grid">
      <el-card class="custom-concepts__list">
        <template #header>
          <div class="card-header">
            <span>概念列表</span>
            <el-tag size="small" effect="plain">{{ conceptCountLabel }}</el-tag>
          </div>
        </template>

        <el-table
          :data="concepts"
          stripe
          height="420"
          highlight-current-row
          :row-class-name="resolveRowClassName"
          @current-change="handleSelectConcept"
        >
          <el-table-column prop="display_name" label="概念" min-width="140" />
          <el-table-column prop="tag_count" label="标签数" width="88" align="center" />
          <el-table-column label="状态" width="110" align="center">
            <template #default="{ row }">
              <el-tag :type="resolveStatusType(row.status)" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最近运行" min-width="140">
            <template #default="{ row }">
              <span>{{ row.latest_run?.status || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="更新时间" min-width="160">
            <template #default="{ row }">
              <span>{{ formatDateTime(row.last_refreshed_at || row.updated_at) }}</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card class="custom-concepts__editor">
        <template #header>
          <div class="card-header">
            <span>{{ form.id ? '编辑概念' : '新建概念' }}</span>
            <el-tag size="small" effect="plain">{{ form.id ? `#${form.id}` : 'draft' }}</el-tag>
          </div>
        </template>

        <el-form label-position="top" class="custom-concepts__form">
          <el-form-item label="概念名称">
            <el-input v-model="form.name" placeholder="例如：PCB" />
          </el-form-item>
          <el-form-item label="展示名称">
            <el-input v-model="form.display_name" placeholder="默认与概念名称一致" />
          </el-form-item>
          <el-form-item label="概念描述">
            <el-input
              v-model="form.description"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              placeholder="说明这个概念主要覆盖哪些方向"
            />
          </el-form-item>
          <el-form-item label="产业链提示">
            <el-input
              v-model="form.chain_hint"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              placeholder="例如：上游材料，中游模组，下游 AI 算力应用"
            />
          </el-form-item>
          <el-form-item label="别名">
            <el-input
              v-model="form.aliases_text"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              placeholder="支持逗号、顿号、换行分隔，例如：印制电路板, FPC"
            />
          </el-form-item>
          <el-form-item label="关联官方板块">
            <el-input
              v-model="form.related_sectors_text"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              placeholder="用于召回候选池，例如：印制电路板, 消费电子"
            />
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="form.status">
              <el-option label="draft" value="draft" />
              <el-option label="ready" value="ready" />
              <el-option label="error" value="error" />
            </el-select>
          </el-form-item>

          <div class="custom-concepts__actions">
            <el-button :loading="saving" type="primary" @click="saveConcept">保存</el-button>
            <el-button @click="resetForm">清空</el-button>
          </div>
        </el-form>
      </el-card>
    </div>

    <el-card v-if="latestRefresh" class="custom-concepts__result">
      <template #header>
        <div class="card-header">
          <span>最近汇聚结果</span>
          <el-tag size="small" :type="resolveStatusType(latestRefresh.run.status)">{{ latestRefresh.run.status }}</el-tag>
        </div>
      </template>
      <div class="result-line"><strong>概念摘要：</strong>{{ latestRefresh.concept_summary || '-' }}</div>
      <div class="result-line"><strong>产业链定义：</strong>{{ latestRefresh.industry_chain_definition || '-' }}</div>
      <div class="result-line">
        <strong>召回板块：</strong>
        <span v-if="latestRefresh.official_matches.length">{{ latestRefresh.official_matches.map((item) => item.concept_name).join(' / ') }}</span>
        <span v-else>-</span>
      </div>
    </el-card>

    <el-card class="custom-concepts__stocks">
      <template #header>
        <div class="card-header">
          <span>概念股票标签</span>
          <el-tag size="small" effect="plain">{{ stockCountLabel }}</el-tag>
        </div>
      </template>

      <div class="custom-concepts__filters">
        <el-select v-model="stockFilters.chain_position" clearable placeholder="上下游">
          <el-option label="上游" value="upstream" />
          <el-option label="中游" value="midstream" />
          <el-option label="下游" value="downstream" />
          <el-option label="应用" value="application" />
          <el-option label="未知" value="unknown" />
        </el-select>
        <el-input v-model="stockFilters.role_tag" clearable placeholder="角色标签，例如 材料" />
        <el-input-number v-model="stockFilters.min_relevance" :min="0" :max="100" :step="5" />
        <el-button :disabled="!selectedConceptId" :loading="loadingStocks" @click="loadStocks">筛选</el-button>
      </div>

      <el-table :data="stocks" stripe max-height="420" v-loading="loadingStocks">
        <el-table-column prop="stock_code" label="代码" width="100" />
        <el-table-column prop="stock_name" label="名称" width="120" />
        <el-table-column prop="industry" label="行业" min-width="120" />
        <el-table-column prop="chain_position" label="位置" width="110" />
        <el-table-column label="相关度" width="90" align="center">
          <template #default="{ row }">{{ formatScore(row.relevance_score) }}</template>
        </el-table-column>
        <el-table-column label="角色标签" min-width="180">
          <template #default="{ row }">
            <div class="tag-list">
              <el-tag v-for="tag in row.role_tags" :key="tag" size="small" effect="plain">{{ tag }}</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="matched_source_concepts" label="召回来源" min-width="180">
          <template #default="{ row }">{{ row.matched_source_concepts.join(' / ') || '-' }}</template>
        </el-table-column>
        <el-table-column prop="reason" label="原因" min-width="260" show-overflow-tooltip />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiCustomConcepts } from '@/api'
import { formatDateTime } from '@/utils'
import type {
  CustomConceptRefreshResponse,
  CustomConceptStockTagItem,
  CustomConceptSummaryItem,
  CustomConceptUpsertRequest,
} from '@/types'

type FormState = {
  id: number | null
  name: string
  display_name: string
  description: string
  chain_hint: string
  aliases_text: string
  related_sectors_text: string
  status: string
}

const concepts = ref<CustomConceptSummaryItem[]>([])
const stocks = ref<CustomConceptStockTagItem[]>([])
const loadingConcepts = ref(false)
const loadingStocks = ref(false)
const saving = ref(false)
const refreshing = ref(false)
const deleting = ref(false)
const selectedConceptId = ref<number | null>(null)
const latestRefresh = ref<CustomConceptRefreshResponse | null>(null)

const form = reactive<FormState>({
  id: null,
  name: '',
  display_name: '',
  description: '',
  chain_hint: '',
  aliases_text: '',
  related_sectors_text: '',
  status: 'draft',
})

const stockFilters = reactive({
  chain_position: '',
  role_tag: '',
  min_relevance: 60,
})

const conceptCountLabel = computed(() => `${concepts.value.length} 个概念`)
const stockCountLabel = computed(() => `${stocks.value.length} 只股票`)

function splitTextList(value: string): string[] {
  return value
    .split(/[\n,，、;]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function joinTextList(values: string[]): string {
  return values.join('\n')
}

function formatScore(value?: number | null): string {
  if (value === null || value === undefined) return '-'
  return `${Math.round(value)}`
}

function resolveStatusType(status?: string | null): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'ready' || status === 'completed') return 'success'
  if (status === 'error' || status === 'failed') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

function resolveRowClassName({ row }: { row: CustomConceptSummaryItem }) {
  return row.id === selectedConceptId.value ? 'is-selected' : ''
}

function buildPayload(): CustomConceptUpsertRequest {
  return {
    name: form.name.trim(),
    display_name: form.display_name.trim() || form.name.trim(),
    description: form.description.trim() || null,
    chain_hint: form.chain_hint.trim() || null,
    aliases: splitTextList(form.aliases_text),
    related_sectors: splitTextList(form.related_sectors_text),
    status: form.status,
  }
}

function applyConcept(detail: {
  id: number
  name: string
  display_name: string
  description?: string | null
  chain_hint?: string | null
  aliases: string[]
  related_sectors: string[]
  status: string
}) {
  form.id = detail.id
  form.name = detail.name
  form.display_name = detail.display_name
  form.description = detail.description || ''
  form.chain_hint = detail.chain_hint || ''
  form.aliases_text = joinTextList(detail.aliases)
  form.related_sectors_text = joinTextList(detail.related_sectors)
  form.status = detail.status
}

function resetForm() {
  form.id = null
  form.name = ''
  form.display_name = ''
  form.description = ''
  form.chain_hint = ''
  form.aliases_text = ''
  form.related_sectors_text = ''
  form.status = 'draft'
}

function startCreate() {
  selectedConceptId.value = null
  latestRefresh.value = null
  stocks.value = []
  resetForm()
}

async function loadConcepts() {
  loadingConcepts.value = true
  try {
    const response = await apiCustomConcepts.list()
    concepts.value = response.concepts || []
    if (selectedConceptId.value) {
      const current = concepts.value.find((item) => item.id === selectedConceptId.value)
      if (current) {
        await selectConcept(current.id)
      }
    }
  } catch (error) {
    ElMessage.error(String(error instanceof Error ? error.message : error))
  } finally {
    loadingConcepts.value = false
  }
}

async function loadStocks() {
  if (!selectedConceptId.value) {
    stocks.value = []
    return
  }
  loadingStocks.value = true
  try {
    const response = await apiCustomConcepts.getStocks(selectedConceptId.value, {
      chain_position: stockFilters.chain_position || undefined,
      role_tag: stockFilters.role_tag.trim() || undefined,
      min_relevance: stockFilters.min_relevance,
      limit: 500,
    })
    stocks.value = response.stocks || []
  } catch (error) {
    ElMessage.error(String(error instanceof Error ? error.message : error))
  } finally {
    loadingStocks.value = false
  }
}

async function selectConcept(conceptId: number) {
  selectedConceptId.value = conceptId
  try {
    const detail = await apiCustomConcepts.getDetail(conceptId)
    applyConcept(detail)
    await loadStocks()
  } catch (error) {
    ElMessage.error(String(error instanceof Error ? error.message : error))
  }
}

async function handleSelectConcept(row?: CustomConceptSummaryItem | null) {
  if (!row?.id) return
  await selectConcept(row.id)
}

async function saveConcept() {
  const payload = buildPayload()
  if (!payload.name) {
    ElMessage.warning('概念名称不能为空')
    return
  }

  saving.value = true
  try {
    const detail = form.id
      ? await apiCustomConcepts.update(form.id, payload)
      : await apiCustomConcepts.create(payload)
    applyConcept(detail)
    selectedConceptId.value = detail.id
    await loadConcepts()
    await loadStocks()
    ElMessage.success('概念已保存')
  } catch (error) {
    ElMessage.error(String(error instanceof Error ? error.message : error))
  } finally {
    saving.value = false
  }
}

async function refreshSelectedConcept() {
  if (!selectedConceptId.value) {
    ElMessage.warning('请先选择一个概念')
    return
  }
  refreshing.value = true
  try {
    latestRefresh.value = await apiCustomConcepts.refresh(selectedConceptId.value)
    await loadConcepts()
    await loadStocks()
    ElMessage.success(`汇聚完成，保存 ${latestRefresh.value.stocks_saved} 只股票标签`)
  } catch (error) {
    ElMessage.error(String(error instanceof Error ? error.message : error))
  } finally {
    refreshing.value = false
  }
}

async function deleteSelectedConcept() {
  if (!selectedConceptId.value) {
    ElMessage.warning('请先选择一个概念')
    return
  }
  const conceptName = form.display_name || form.name
  try {
    await ElMessageBox.confirm(
      `确定删除「${conceptName}」吗？相关标签和运行记录会一起删除。`,
      '删除自定义概念',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  deleting.value = true
  try {
    await apiCustomConcepts.delete(selectedConceptId.value)
    ElMessage.success('概念已删除')
    startCreate()
    await loadConcepts()
  } catch (error) {
    ElMessage.error(String(error instanceof Error ? error.message : error))
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  void loadConcepts()
})
</script>

<style scoped>
.custom-concepts {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.custom-concepts__toolbar,
.custom-concepts__filters {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

.custom-concepts__grid {
  display: grid;
  grid-template-columns: minmax(320px, 1fr) minmax(340px, 1fr);
  gap: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.custom-concepts__form {
  display: flex;
  flex-direction: column;
}

.custom-concepts__actions {
  display: flex;
  gap: 12px;
}

.result-line {
  line-height: 1.7;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

@media (max-width: 960px) {
  .custom-concepts__grid {
    grid-template-columns: 1fr;
  }
}
</style>
