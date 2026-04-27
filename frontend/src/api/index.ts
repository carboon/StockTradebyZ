import axios from 'axios'
import type { AxiosInstance, AxiosError } from 'axios'
import type {
  AnalysisResultsResponse,
  CandidatesResponse,
  ConfigItem,
  ConfigResponse,
  DataStatus,
  DiagnosisAnalyzeResponse,
  DiagnosisHistoryResponse,
  DiagnosisHistoryStatusResponse,
  FreshnessResponse,
  IncrementalUpdateResponse,
  IncrementalUpdateStatus,
  KLineData,
  SaveEnvResponse,
  StockInfo,
  Task,
  TaskDiagnosticsResponse,
  TaskEnvironmentResponse,
  TaskListResponse,
  TaskLogListResponse,
  TaskOverviewResponse,
  TaskRunningResponse,
  TaskResponse,
  TomorrowStarDatesResponse,
  TushareStatusResponse,
  TushareVerifyResponse,
  WatchlistAnalysisResponse,
  WatchlistAnalyzeResponse,
  WatchlistChartResponse,
  WatchlistItem,
  WatchlistResponse,
} from '@/types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'
type RequestOptions = {
  signal?: AbortSignal
  timeoutMs?: number
}

const TIMEOUTS = {
  short: 10000,
  standard: 20000,
  long: 45000,
}

function withRequestOptions(options: RequestOptions | undefined, timeoutMs: number) {
  return {
    ...options,
    timeout: options?.timeoutMs ?? timeoutMs,
  }
}

// 创建 axios 实例
const api: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: TIMEOUTS.standard,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error: AxiosError<{ message?: string; detail?: string }>) => {
    if (error.code === 'ERR_CANCELED' || axios.isCancel(error)) {
      return Promise.reject(error)
    }
    if (error.code === 'ECONNABORTED') {
      return Promise.reject(new Error('请求超时。若你刚启动了初始化或分析任务，它可能仍在后台运行，请前往任务中心继续查看。'))
    }
    const message = error.response?.data?.detail || error.response?.data?.message || error.message || '请求失败'
    return Promise.reject(new Error(message))
  }
)

export function isRequestCanceled(error: unknown): boolean {
  return axios.isCancel(error) || (typeof error === 'object' && error !== null && 'code' in error && error.code === 'ERR_CANCELED')
}

// API 方法
export const apiConfig = {
  // 获取所有配置
  getAll: () => api.get<never, ConfigResponse>('/v1/config/'),

  // 更新配置
  update: (key: string, value: string) => api.put<{ key: string; value: string }, ConfigItem>('/v1/config/', { key, value }),

  // 验证 Tushare Token
  verifyTushare: (token: string) => api.post<{ token: string }, TushareVerifyResponse>('/v1/config/verify-tushare', { token }),

  // 保存环境变量
  saveEnv: (config: Record<string, string>) => api.post<Record<string, string>, SaveEnvResponse>('/v1/config/save-env', config),

  // 获取 Tushare 状态
  getTushareStatus: () => api.get<never, TushareStatusResponse>('/v1/config/tushare-status'),
}

export const apiStock = {
  // 获取股票信息
  getInfo: (code: string, options?: RequestOptions) => api.get<never, StockInfo>(`/v1/stock/${code}`, withRequestOptions(options, TIMEOUTS.short)),

  // 获取 K线数据
  getKline: (code: string, days: number = 120, includeWeekly: boolean = true, options?: RequestOptions) =>
    api.post<{ code: string; days: number; include_weekly: boolean }, KLineData>(
      '/v1/stock/kline',
      { code, days, include_weekly: includeWeekly },
      withRequestOptions(options, TIMEOUTS.long),
    ),
}

export const apiAnalysis = {
  // 获取明日之星数据新鲜度
  getFreshness: (options?: RequestOptions) => api.get<never, FreshnessResponse>('/v1/analysis/tomorrow-star/freshness', withRequestOptions(options, TIMEOUTS.short)),

  // 获取明日之星历史日期
  getDates: (options?: RequestOptions) => api.get<never, TomorrowStarDatesResponse>('/v1/analysis/tomorrow-star/dates', withRequestOptions(options, TIMEOUTS.short)),

  // 获取候选列表
  getCandidates: (date?: string, options?: RequestOptions) =>
    api.get<never, CandidatesResponse>('/v1/analysis/tomorrow-star/candidates', { ...withRequestOptions(options, TIMEOUTS.standard), params: { date } }),

  // 获取分析结果
  getResults: (date?: string, options?: RequestOptions) =>
    api.get<never, AnalysisResultsResponse>('/v1/analysis/tomorrow-star/results', { ...withRequestOptions(options, TIMEOUTS.standard), params: { date } }),

  // 生成明日之星
  generate: (reviewer: string = 'quant') =>
    api.post<null, { task_id: number }>('/v1/analysis/tomorrow-star/generate', null, { params: { reviewer } }),

  // 获取单股诊断历史
  getDiagnosisHistory: (code: string, days: number = 30, options?: RequestOptions) =>
    api.get<never, DiagnosisHistoryResponse>(`/v1/analysis/diagnosis/${code}/history`, { ...withRequestOptions(options, TIMEOUTS.long), params: { days } }),

  // 获取历史数据生成状态
  getHistoryStatus: (code: string, options?: RequestOptions) =>
    api.get<never, DiagnosisHistoryStatusResponse>(`/v1/analysis/diagnosis/${code}/history-status`, withRequestOptions(options, TIMEOUTS.short)),

  // 重新刷新单股诊断历史数据
  refreshHistory: (code: string, days: number = 30, options?: RequestOptions) =>
    api.post<null, { status: string; message: string; code: string; days: number }>(
      `/v1/analysis/diagnosis/${code}/generate-history`,
      null,
      { ...withRequestOptions(options, TIMEOUTS.long), params: { days, clean: true } },
    ),

  // 启动单股分析
  analyze: (code: string, options?: RequestOptions) =>
    api.post<{ code: string }, DiagnosisAnalyzeResponse>('/v1/analysis/diagnosis/analyze', { code }, withRequestOptions(options, TIMEOUTS.long)),
}

export const apiWatchlist = {
  // 获取观察列表
  getAll: (options?: RequestOptions) => api.get<never, WatchlistResponse>('/v1/watchlist/', withRequestOptions(options, TIMEOUTS.standard)),

  // 添加到观察列表
  add: (code: string, reason?: string, priority: number = 0, entry_price?: number, position_ratio?: number) =>
    api.post<{ code: string; reason?: string; priority: number; entry_price?: number; position_ratio?: number }, WatchlistItem>('/v1/watchlist/', { code, reason, priority, entry_price, position_ratio }),

  // 更新观察项
  update: (id: number, data: Record<string, unknown>) => api.put<Record<string, unknown>, WatchlistItem>(`/v1/watchlist/${id}`, data),

  // 删除观察项
  delete: (id: number) => api.delete<never, { status: string; message: string }>(`/v1/watchlist/${id}`),

  // 获取观察项分析历史
  getAnalysis: (id: number, options?: RequestOptions) => api.get<never, WatchlistAnalysisResponse>(`/v1/watchlist/${id}/analysis`, withRequestOptions(options, TIMEOUTS.standard)),

  // 立即分析观察项
  analyze: (id: number, options?: RequestOptions) => api.post<null, WatchlistAnalyzeResponse>(`/v1/watchlist/${id}/analyze`, null, withRequestOptions(options, TIMEOUTS.long)),

  // 获取观察项图表数据
  getChart: (id: number, options?: RequestOptions) => api.get<never, WatchlistChartResponse>(`/v1/watchlist/${id}/chart`, withRequestOptions(options, TIMEOUTS.long)),
}

export const apiTasks = {
  // 获取任务总览
  getOverview: () => api.get<never, TaskOverviewResponse>('/v1/tasks/overview', { timeout: TIMEOUTS.short }),

  // 获取运行中任务
  getRunning: () => api.get<never, TaskRunningResponse>('/v1/tasks/running', { timeout: TIMEOUTS.short }),

  // 获取环境信息
  getEnvironment: () => api.get<never, TaskEnvironmentResponse>('/v1/tasks/environment', { timeout: TIMEOUTS.short }),

  // 获取本机诊断快照
  getDiagnostics: () => api.get<never, TaskDiagnosticsResponse>('/v1/tasks/diagnostics', { timeout: TIMEOUTS.short }),

  // 获取数据状态
  getStatus: () => api.get<never, DataStatus>('/v1/tasks/status', { timeout: TIMEOUTS.short }),

  // 启动更新
  startUpdate: (reviewer: string = 'quant', skipFetch: boolean = false, startFrom: number = 1) =>
    api.post<{ reviewer: string; skip_fetch: boolean; start_from: number }, TaskResponse>('/v1/tasks/start', { reviewer, skip_fetch: skipFetch, start_from: startFrom }, { timeout: TIMEOUTS.short }),

  // 启动增量更新
  startIncrementalUpdate: (endDate?: string) =>
    api.post<null, IncrementalUpdateResponse>('/v1/tasks/start-incremental', null, { params: { end_date: endDate } }),

  // 获取增量更新状态
  getIncrementalStatus: (options?: RequestOptions) => api.get<never, IncrementalUpdateStatus>('/v1/tasks/incremental-status', withRequestOptions(options, TIMEOUTS.short)),

  // 获取任务列表
  getAll: (status?: string, limit: number = 20) =>
    api.get<never, TaskListResponse>('/v1/tasks/', { params: { status, limit }, timeout: TIMEOUTS.short }),

  // 获取任务详情
  get: (id: number) => api.get<never, Task>(`/v1/tasks/${id}`, { timeout: TIMEOUTS.short }),

  // 获取任务日志
  getLogs: (id: number, limit: number = 300) => api.get<never, TaskLogListResponse>(`/v1/tasks/${id}/logs`, { params: { limit }, timeout: TIMEOUTS.standard }),

  // 取消任务
  cancel: (id: number) => api.post<null, { status: string; message: string }>(`/v1/tasks/${id}/cancel`, null, { timeout: TIMEOUTS.short }),

  // 清空历史任务
  clearTasks: () => api.delete<never, { status: string; message: string }>('/v1/tasks/clear', { timeout: TIMEOUTS.short }),
}

export default api
