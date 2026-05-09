import axios from 'axios'
import type { AxiosInstance, AxiosError } from 'axios'
import type {
  AdminSummaryResponse,
  AnalysisResultsResponse,
  ApiKeyCreateResponse,
  ApiKeyInfo,
  CandidatesResponse,
  ConfigItem,
  ConfigResponse,
  CurrentHotAnalysisResultsResponse,
  CurrentHotCandidatesResponse,
  CurrentHotDatesResponse,
  CurrentHotIntradayAnalysisActionResponse,
  CurrentHotIntradayAnalysisResponse,
  CurrentHotIntradayAnalysisStatusResponse,
  DataFreshnessResponse,
  DataStatus,
  DiagnosisAnalyzeTaskResponse,
  DiagnosisHistoryResponse,
  DiagnosisHistoryDetailResponse,
  DiagnosisHistoryStatusResponse,
  DiagnosisResultResponse,
  FreshnessResponse,
  IntradayAnalysisActionResponse,
  IntradayAnalysisResponse,
  IntradayAnalysisStatusResponse,
  DailyBatchUpdateResponse,
  IncrementalUpdateResponse,
  IncrementalUpdateStatus,
  KLineData,
  LoginResponse,
  SaveEnvResponse,
  StockInfo,
  StockSearchResponse,
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
  UsageStatsResponse,
  UserListItem,
  UserInfo,
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

export class AppRequestError extends Error {
  status?: number
  code?: string

  constructor(message: string, options?: { status?: number; code?: string }) {
    super(message)
    this.name = 'AppRequestError'
    this.status = options?.status
    this.code = options?.code
  }
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
    const saved = localStorage.getItem('stocktrade_token')
    if (saved && config.headers) {
      config.headers.Authorization = `Bearer ${saved}`
    }
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
      return Promise.reject(new AppRequestError('请求超时。若你刚启动了初始化或分析任务，它可能仍在后台运行，请前往任务中心继续查看。', { code: error.code }))
    }
    const requestUrl = error.config?.url || ''
    const isLoginRequest = requestUrl.includes('/v1/auth/login')

    // 登录接口的 401 应保留后端原始文案，避免误报为“登录已过期”
    if (error.response?.status === 401 && isLoginRequest) {
      const message = error.response.data?.detail || error.response.data?.message || '用户名或密码错误'
      return Promise.reject(new AppRequestError(message, { status: 401 }))
    }

    // 401 未授权：清除 token 并跳转登录页
    if (error.response?.status === 401) {
      console.error('[401 Error]', {
        url: requestUrl,
        method: error.config?.method,
        hasToken: !!localStorage.getItem('stocktrade_token'),
        currentPath: window.location.pathname
      })
      localStorage.removeItem('stocktrade_token')
      // 避免在登录页循环跳转
      if (window.location.pathname !== '/login' && window.location.pathname !== '/register') {
        window.location.href = '/login'
      }
      return Promise.reject(new AppRequestError('登录已过期，请重新登录', { status: 401 }))
    }
    const message = error.response?.data?.detail || error.response?.data?.message || error.message || '请求失败'
    return Promise.reject(new AppRequestError(message, { status: error.response?.status, code: error.code }))
  }
)

export function isRequestCanceled(error: unknown): boolean {
  return axios.isCancel(error) || (typeof error === 'object' && error !== null && 'code' in error && error.code === 'ERR_CANCELED')
}

// 健康检查（无需认证）
export async function checkHealth(): Promise<{ status: string } | null> {
  try {
    // 直接使用 axios 创建一个不携带认证信息的请求
    const response = await axios.get(`${API_BASE_URL}/health`, {
      timeout: 5000,
    })
    return response.data
  } catch {
    return null
  }
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

  // 搜索股票
  search: (q: string, limit: number = 10, options?: RequestOptions) =>
    api.get<never, StockSearchResponse>('/v1/stock/search', {
      ...withRequestOptions(options, TIMEOUTS.short),
      params: { q, limit },
    }),

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

  // 获取当前热盘历史日期
  getCurrentHotDates: (options?: RequestOptions) =>
    api.get<never, CurrentHotDatesResponse>('/v1/analysis/current-hot/dates', withRequestOptions(options, TIMEOUTS.short)),

  // 获取当前热盘候选列表
  getCurrentHotCandidates: (date?: string, options?: RequestOptions) =>
    api.get<never, CurrentHotCandidatesResponse>('/v1/analysis/current-hot/candidates', {
      ...withRequestOptions(options, TIMEOUTS.standard),
      params: { date },
    }),

  // 获取当前热盘分析结果
  getCurrentHotResults: (date?: string, options?: RequestOptions) =>
    api.get<never, CurrentHotAnalysisResultsResponse>('/v1/analysis/current-hot/results', {
      ...withRequestOptions(options, TIMEOUTS.standard),
      params: { date },
    }),

  // 生成当前热盘
  generateCurrentHot: (reviewer: string = 'quant') =>
    api.post<null, { task_id: number }>('/v1/analysis/current-hot/generate', null, { params: { reviewer } }),

  // 获取中盘分析状态
  getMiddayStatus: (options?: RequestOptions) =>
    api.get<never, IntradayAnalysisStatusResponse>('/v1/analysis/intraday/status', withRequestOptions(options, TIMEOUTS.short)),

  // 获取当前交易日中盘分析结果
  getMiddayCurrent: (options?: RequestOptions) =>
    api.get<never, IntradayAnalysisResponse>('/v1/analysis/intraday/data', withRequestOptions(options, TIMEOUTS.standard)),

  // 手动生成中盘分析
  generateMidday: () =>
    api.post<null, IntradayAnalysisActionResponse>('/v1/analysis/intraday/generate', null, { timeout: TIMEOUTS.standard }),

  // 手动刷新中盘分析
  refreshMidday: () =>
    api.post<null, IntradayAnalysisActionResponse>('/v1/analysis/intraday/generate', null, { timeout: TIMEOUTS.standard }),

  // 获取当前热盘中盘分析状态
  getCurrentHotMiddayStatus: (options?: RequestOptions) =>
    api.get<never, CurrentHotIntradayAnalysisStatusResponse>('/v1/analysis/current-hot/intraday/status', withRequestOptions(options, TIMEOUTS.short)),

  // 获取当前热盘中盘分析结果
  getCurrentHotMiddayCurrent: (options?: RequestOptions) =>
    api.get<never, CurrentHotIntradayAnalysisResponse>('/v1/analysis/current-hot/intraday/data', withRequestOptions(options, TIMEOUTS.standard)),

  // 手动生成当前热盘中盘分析
  generateCurrentHotMidday: () =>
    api.post<null, CurrentHotIntradayAnalysisActionResponse>('/v1/analysis/current-hot/intraday/generate', null, { timeout: TIMEOUTS.standard }),

  // 手动刷新当前热盘中盘分析
  refreshCurrentHotMidday: () =>
    api.post<null, CurrentHotIntradayAnalysisActionResponse>('/v1/analysis/current-hot/intraday/generate', null, { timeout: TIMEOUTS.standard }),

  // 获取单股诊断历史
  getDiagnosisHistory: (
    code: string,
    days: number = 180,
    page: number = 1,
    pageSize: number = 10,
    refresh: boolean = false,
    options?: RequestOptions,
  ) =>
    api.get<never, DiagnosisHistoryResponse>(`/v1/analysis/diagnosis/${code}/history`, {
      ...withRequestOptions(options, TIMEOUTS.long),
      params: { days, page, page_size: pageSize, refresh },
    }),

  // 获取历史数据生成状态
  getHistoryStatus: (
    code: string,
    days: number = 180,
    page: number = 1,
    pageSize: number = 10,
    options?: RequestOptions,
  ) =>
    api.get<never, DiagnosisHistoryStatusResponse>(`/v1/analysis/diagnosis/${code}/history-status`, {
      ...withRequestOptions(options, TIMEOUTS.short),
      params: { days, page, page_size: pageSize },
    }),

  // 重新刷新单股诊断历史数据
  refreshHistory: (
    code: string,
    days: number = 180,
    page: number = 1,
    pageSize: number = 10,
    force: boolean = false,
    options?: RequestOptions,
  ) =>
    api.post<null, {
      status: string
      message: string
      code: string
      page: number
      page_size: number
      generated_count: number
      generated_dates: string[]
      latest_trade_date?: string | null
      latest_history_date?: string | null
    }>(
      `/v1/analysis/diagnosis/${code}/generate-history`,
      null,
      { ...withRequestOptions(options, TIMEOUTS.long), params: { days, page, page_size: pageSize, force } },
    ),

  getHistoryDetail: (code: string, checkDate: string, options?: RequestOptions) =>
    api.get<never, DiagnosisHistoryDetailResponse>(
      `/v1/analysis/diagnosis/${code}/history/${checkDate}`,
      withRequestOptions(options, TIMEOUTS.standard),
    ),

  ensureHistoryDetail: (code: string, checkDate: string, force: boolean = false, options?: RequestOptions) =>
    api.post<null, { task_id?: number; status: string; message: string; code: string; check_date: string; ws_url?: string }>(
      `/v1/analysis/diagnosis/${code}/history/${checkDate}/detail`,
      null,
      { ...withRequestOptions(options, TIMEOUTS.standard), params: { force } },
    ),

  // 启动单股分析（后台任务模式）
  analyze: (code: string, options?: RequestOptions) =>
    api.post<{ code: string }, DiagnosisAnalyzeTaskResponse>('/v1/analysis/diagnosis/analyze', { code }, withRequestOptions(options, TIMEOUTS.standard)),

  // 获取单股分析结果
  getResult: (code: string, options?: RequestOptions) =>
    api.get<never, DiagnosisResultResponse>(`/v1/analysis/diagnosis/${code}/result`, withRequestOptions(options, TIMEOUTS.standard)),
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

  // 获取管理员总览摘要（仅管理员）
  getAdminSummary: () => api.get<never, AdminSummaryResponse>('/v1/tasks/admin/summary', { timeout: TIMEOUTS.short }),

  // 获取运行中任务
  getRunning: () => api.get<never, TaskRunningResponse>('/v1/tasks/running', { timeout: TIMEOUTS.short }),

  // 获取环境信息
  getEnvironment: () => api.get<never, TaskEnvironmentResponse>('/v1/tasks/environment', { timeout: TIMEOUTS.short }),

  // 获取本机诊断快照
  getDiagnostics: () => api.get<never, TaskDiagnosticsResponse>('/v1/tasks/diagnostics', { timeout: TIMEOUTS.short }),

  // 获取数据状态
  getStatus: () => api.get<never, DataStatus>('/v1/tasks/status', { timeout: TIMEOUTS.short }),

  // 启动更新
  startUpdate: (reviewer: string = 'quant', skipFetch: boolean = false, startFrom: number = 1, resetDerivedState: boolean = false) =>
    api.post<{ reviewer: string; skip_fetch: boolean; start_from: number; reset_derived_state: boolean }, TaskResponse>(
      '/v1/tasks/start',
      { reviewer, skip_fetch: skipFetch, start_from: startFrom, reset_derived_state: resetDerivedState },
      { timeout: TIMEOUTS.short },
    ),

  // 启动增量更新
  startIncrementalUpdate: (endDate?: string) =>
    api.post<null, IncrementalUpdateResponse>('/v1/tasks/start-incremental', null, { params: { end_date: endDate } }),

  // 启动按交易日批量更新
  startDailyBatchUpdate: (tradeDate?: string) =>
    api.post<null, DailyBatchUpdateResponse>('/v1/tasks/start-daily-batch', null, { params: { trade_date: tradeDate } }),

  // 获取增量更新状态
  // 仅作为兼容兜底状态源；任务展示优先使用 running/tasks 接口
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

  // 查询 Tushare 日线数据最新时效
  getDataFreshness: () => api.get<never, DataFreshnessResponse>('/v1/tasks/data-freshness', { timeout: TIMEOUTS.standard }),
}

export const apiAuth = {
  // 获取注册验证问题
  getRegisterValidationPrompt: () =>
    api.get<never, { question: string }>('/v1/auth/register-validation'),

  // 用户注册
  register: (username: string, password: string, admin_wechat: string, display_name?: string) =>
    api.post<{ username: string; password: string; admin_wechat: string; display_name?: string }, LoginResponse>(
      '/v1/auth/register',
      { username, password, admin_wechat, display_name },
    ),

  // 用户登录
  login: (username: string, password: string) =>
    api.post<{ username: string; password: string }, LoginResponse>(
      '/v1/auth/login',
      { username, password },
    ),

  // 获取当前用户信息
  getMe: () => api.get<never, UserInfo>('/v1/auth/me'),

  // 修改密码
  changePassword: (old_password: string, new_password: string) =>
    api.put<{ old_password: string; new_password: string }, { message: string }>(
      '/v1/auth/password',
      { old_password, new_password },
    ),

  // 创建 API Key
  createApiKey: (name?: string) =>
    api.post<{ name?: string }, ApiKeyCreateResponse>('/v1/auth/keys', { name }),

  // 列出 API Key
  listApiKeys: () => api.get<never, ApiKeyInfo[]>('/v1/auth/keys'),

  // 吊销 API Key
  revokeApiKey: (id: number) =>
    api.delete<never, { message: string }>(`/v1/auth/keys/${id}`),

  // 获取用量统计
  getUsage: () => api.get<never, UsageStatsResponse>('/v1/auth/usage'),

  // 管理员：获取用户列表
  adminGetUsers: () => api.get<never, UserListItem[]>('/v1/auth/admin/users'),

  // 管理员：更新用户
  adminUpdateUser: (userId: number, data: { is_active?: boolean; daily_quota?: number; role?: string }) =>
    api.put<typeof data, { message: string }>(`/v1/auth/admin/users/${userId}`, data),

  // 管理员：禁用用户
  adminDisableUser: (userId: number) =>
    api.delete<never, { message: string }>(`/v1/auth/admin/users/${userId}`),

  // 管理员：获取用户用量
  adminGetUsage: (userId: number) =>
    api.get<never, UsageStatsResponse>(`/v1/auth/admin/usage/${userId}`),
}

export default api
