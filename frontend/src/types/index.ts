// 通用类型定义

export interface StockInfo {
  code: string
  name?: string
  market?: string
  industry?: string
  exists?: boolean
}

export interface StockSearchItem {
  code: string
  name?: string
  market?: string
  industry?: string
}

export interface StockSearchResponse {
  items: StockSearchItem[]
  total: number
}

export interface Candidate {
  id: number
  pick_date: string
  code: string
  name?: string
  strategy?: string
  open_price?: number
  close_price?: number
  change_pct?: number
  turnover?: number
  b1_passed?: boolean
  kdj_j?: number
}

export interface AnalysisResult {
  id: number
  pick_date: string
  code: string
  reviewer?: string
  verdict?: 'PASS' | 'WATCH' | 'FAIL'
  total_score?: number
  signal_type?: string
  comment?: string
}

export interface B1Check {
  check_date: string
  close_price?: number
  change_pct?: number
  kdj_j?: number
  kdj_low_rank?: number
  zx_long_pos?: boolean
  weekly_ma_aligned?: boolean
  volume_healthy?: boolean
  in_active_pool?: boolean | null
  b1_passed?: boolean
  prefilter_passed?: boolean | null
  prefilter_blocked_by?: string[] | null
  score?: number
  verdict?: 'PASS' | 'WATCH' | 'FAIL'
  signal_type?: string
  tomorrow_star_pass?: boolean | null
  notes?: string
  comment?: string
  signal_reasoning?: string
  trend_reasoning?: string
  position_reasoning?: string
  volume_reasoning?: string
  abnormal_move_reasoning?: string
  prefilter_reasoning?: string
  fail_reason?: string
  scores?: Record<string, number> | null
  details?: Record<string, any> | null
  detail_ready?: boolean
  detail_version?: string | null
  detail_updated_at?: string | null
}

export interface DiagnosisHistoryDetailPayload {
  score_details?: Record<string, any> | null
  rules?: Record<string, any> | null
  details?: Record<string, any> | null
}

export interface DiagnosisHistoryDetailResponse {
  code: string
  check_date: string
  status: string
  detail_ready: boolean
  detail_version?: string | null
  strategy_version?: string | null
  rule_version?: string | null
  detail_updated_at?: string | null
  payload: DiagnosisHistoryDetailPayload
}

export interface WatchlistItem {
  id: number
  code: string
  name?: string
  add_reason?: string
  entry_price?: number
  position_ratio?: number
  priority: number
  is_active: boolean
  added_at: string
}

export interface WatchlistAnalysis {
  id: number
  watchlist_id: number
  analysis_date: string
  close_price?: number
  verdict?: 'PASS' | 'WATCH' | 'FAIL'
  score?: number
  trend_outlook?: 'bullish' | 'bearish' | 'neutral'
  buy_action?: 'buy' | 'wait' | 'avoid'
  hold_action?: 'hold' | 'hold_cautious' | 'trim' | 'add_on_pullback'
  risk_level?: 'low' | 'medium' | 'high'
  buy_recommendation?: string
  hold_recommendation?: string
  risk_recommendation?: string
  support_level?: number
  resistance_level?: number
  recommendation?: string
}

export interface Task {
  id: number
  task_type: string
  trigger_source: 'manual' | 'auto' | 'system' | string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  task_stage?: string
  progress: number
  params_json?: Record<string, any>
  result_json?: Record<string, any>
  error_message?: string
  summary?: string
  progress_meta_json?: TaskProgressMeta
  started_at?: string
  completed_at?: string
  created_at: string
}

export interface TaskProgressMeta {
  kind?: string
  stage?: string
  stage_label?: string
  stage_index?: number | null
  stage_total?: number | null
  percent?: number | null
  message?: string | null
  eta_seconds?: number | null
  eta_label?: string | null
  current?: number | null
  total?: number | null
  current_code?: string | null
  initial_completed?: number | null
  completed_in_run?: number | null
  failed_count?: number | null
  resume_supported?: boolean
  ready_count?: number | null
  incremental_count?: number | null
  full_count?: number | null
  csv_imported_count?: number | null
  csv_failed_count?: number | null
}

export interface DataStatus {
  raw_data: {
    exists: boolean
    stock_count?: number
    raw_record_count?: number
    latest_date?: number | string
    latest_trade_date?: string | null
    is_latest?: boolean
    is_latest_complete?: boolean
  }
  candidates: { exists: boolean; count: number; latest_date?: string }
  analysis: { exists: boolean; count: number; latest_date?: string }
  kline: { exists: boolean; count: number; latest_date?: string | null }
}

export interface DataFreshnessResponse {
  query_time: string
  latest_calendar_trade_date: string | null
  latest_data_date: string | null
  is_latest_data_ready: boolean
  error?: string
}

// K线数据
export interface KLineDataPoint {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  ma5?: number
  ma10?: number
  ma20?: number
  ma60?: number
}

export interface KLineData {
  code: string
  name?: string
  daily: KLineDataPoint[]
  weekly?: KLineDataPoint[]
}

export interface ConfigItem {
  key: string
  value: string
  description?: string | null
}

export interface ConfigResponse {
  configs: ConfigItem[]
}

export interface TushareVerifyResponse {
  valid: boolean
  message: string
}

export interface SaveEnvResponse {
  status: string
  message: string
}

export interface TushareStatusResponse {
  configured: boolean
  available?: boolean
  message?: string
  token_prefix?: string
  data_status?: DataStatus
  error?: string
}

export interface TomorrowStarHistoryItem {
  date: string
  count?: number
  pass?: number
  candidate_count?: number
  analysis_count?: number
  trend_start_count?: number
  status?: 'pending' | 'running' | 'success' | 'failed' | 'missing' | string
  source?: string
  error_message?: string | null
  is_latest?: boolean
}

export interface TomorrowStarWindowStatusItem {
  pick_date?: string
  date?: string
  status?: 'pending' | 'running' | 'success' | 'failed' | 'missing' | string
  candidate_count?: number
  analysis_count?: number
  trend_start_count?: number
  reviewer?: string | null
  source?: string | null
  started_at?: string | null
  finished_at?: string | null
  error_message?: string | null
  is_latest?: boolean
}

export interface TomorrowStarWindowStatusResponse {
  window_size?: number
  completed_count?: number
  missing_count?: number
  failed_count?: number
  running_count?: number
  latest_date?: string | null
  current_pick_date?: string | null
  items?: TomorrowStarWindowStatusItem[]
  history?: TomorrowStarWindowStatusItem[]
  runs?: TomorrowStarWindowStatusItem[]
}

export interface TomorrowStarDatesResponse {
  dates: string[]
  history: TomorrowStarHistoryItem[]
  window_status?: TomorrowStarWindowStatusResponse | null
}

export interface FreshnessResponse {
  latest_trade_date?: string | null
  latest_trade_data_ready?: boolean | null
  local_latest_date?: string | null
  latest_candidate_date?: string | null
  latest_result_date?: string | null
  needs_update: boolean
  freshness_version?: string
  running_task_id?: number | null
  running_task_status?: Task['status'] | null
  incremental_update?: IncrementalUpdateStatus
}

export interface CandidatesResponse {
  pick_date?: string | null
  candidates: Candidate[]
  total: number
}

export interface AnalysisResultsResponse {
  pick_date?: string | null
  results: AnalysisResult[]
  total: number
  min_score_threshold: number
}

export interface DiagnosisHistoryResponse {
  code: string
  name?: string
  history: B1Check[]
  total: number
  page?: number
  page_size?: number
  data_ready?: boolean
  message?: string | null
}

export interface DiagnosisHistoryStatusResponse {
  exists: boolean
  generating: boolean
  count: number
  total?: number
  page?: number
  page_size?: number
  needs_refresh?: boolean
  latest_trade_date?: string | null
  latest_history_date?: string | null
  generated_at?: string
}

export interface DiagnosisAnalysisDetails {
  kdj_j?: number
  zx_long_pos?: boolean
  weekly_ma_aligned?: boolean
  volume_healthy?: boolean
  scores?: Record<string, number>
  trend_reasoning?: string
  position_reasoning?: string
  volume_reasoning?: string
  abnormal_move_reasoning?: string
  signal_type?: string
  signal_reasoning?: string
  comment?: string
}

export interface DiagnosisAnalyzeResponse {
  code: string
  name?: string
  current_price?: number
  b1_passed?: boolean
  score?: number
  verdict?: 'PASS' | 'WATCH' | 'FAIL'
  analysis: DiagnosisAnalysisDetails
  kline_data?: {
    dates: string[]
    open: number[]
    high: number[]
    low: number[]
    close: number[]
    volume: number[]
  } | null
}

export interface DiagnosisAnalyzeTaskResponse {
  task_id: number
  code: string
  status: 'pending' | 'existing'
  ws_url: string
  message: string
}

export interface DiagnosisResultResponse {
  code: string
  name?: string
  status: 'processing' | 'completed' | 'failed'
  task_id?: number
  task_status?: Task['status']
  progress?: number
  progress_meta?: TaskProgressMeta
  error?: string
  current_price?: number
  b1_passed?: boolean
  score?: number
  verdict?: 'PASS' | 'WATCH' | 'FAIL'
  analysis?: DiagnosisAnalysisDetails
}

export interface WatchlistResponse {
  items: WatchlistItem[]
  total: number
}

export interface WatchlistAnalysisResponse {
  code: string
  analyses: WatchlistAnalysis[]
  total: number
}

export interface WatchlistAnalyzeResponse {
  status: string
  code: string
  analysis: WatchlistAnalysis
}

export interface WatchlistChartResponse {
  code: string
  kline: KLineData
  latest_analysis: WatchlistAnalysis | null
}

export interface TaskResponse {
  task: Task
  ws_url: string
}

export interface TaskListResponse {
  tasks: Task[]
  total: number
}

export interface TaskLogItem {
  id: number
  task_id: number
  log_time: string
  level: string
  stage?: string | null
  message: string
}

export interface TaskLogListResponse {
  task_id: number
  logs: TaskLogItem[]
  total: number
}

export interface TaskOverviewCard {
  key: string
  label: string
  value: string
  status: string
  meta?: string | null
}

export interface TaskAlertItem {
  level: string
  title: string
  message: string
}

export interface TaskOverviewResponse {
  cards: TaskOverviewCard[]
  alerts: TaskAlertItem[]
}

export interface TaskRunningResponse {
  tasks: Task[]
  total: number
}

export interface TaskEnvironmentSection {
  key: string
  label: string
  items: Record<string, any>
}

export interface TaskEnvironmentResponse {
  sections: TaskEnvironmentSection[]
}

export interface TaskDiagnosticCheck {
  key: string
  label: string
  status: string
  summary: string
  action?: string | null
}

export interface TaskDiagnosticsResponse {
  generated_at: string
  checks: TaskDiagnosticCheck[]
  running_tasks: Task[]
  latest_failed_task?: Task | null
  latest_completed_task?: Task | null
  environment: TaskEnvironmentSection[]
  data_status: DataStatus
}

export interface IncrementalUpdateStatus {
  status?: 'idle' | 'running' | 'completed' | 'failed' | string
  running: boolean
  progress: number
  current: number
  total: number
  current_code?: string
  updated_count: number
  skipped_count: number
  failed_count: number
  started_at?: string
  completed_at?: string
  eta_seconds?: number | null
  elapsed_seconds?: number
  resume_supported?: boolean
  initial_completed?: number
  completed_in_run?: number
  checkpoint_path?: string | null
  last_error?: string | null
  message: string
}

export interface IncrementalUpdateResponse {
  success: boolean
  message: string
  running: boolean
  state?: IncrementalUpdateStatus
}

// =====================
// 认证相关类型
// =====================

export interface UserInfo {
  id: number
  username: string
  display_name: string | null
  role: 'admin' | 'user'
  is_active: boolean
  daily_quota: number
  created_at: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user: UserInfo
}

export interface ApiKeyInfo {
  id: number
  key_prefix: string
  name: string | null
  is_active: boolean
  last_used_at: string | null
  created_at: string
}

export interface ApiKeyCreateResponse {
  id: number
  key: string
  key_prefix: string
  name: string | null
}

export interface UsageStatsItem {
  date: string
  total_calls: number
  endpoints: Record<string, number>
}

export interface UsageStatsResponse {
  stats: UsageStatsItem[]
  total_calls: number
}

export interface UserListItem {
  id: number
  username: string
  display_name: string | null
  role: 'admin' | 'user'
  is_active: boolean
  daily_quota: number
  created_at: string
}

// =====================
// 管理员总览摘要类型
// =====================

export interface AdminSummaryCard {
  key: string
  label: string
  value: string
  status: 'success' | 'warning' | 'danger' | 'info'
  meta?: string | null
  action_label?: string | null
  action_route?: string | null
}

export interface AdminSummaryTaskInfo {
  id?: number | null
  task_type?: string | null
  status: string
  stage_label?: string | null
  progress: number
  summary?: string | null
  task_stage?: string | null
  progress_meta_json?: TaskProgressMeta | null
}

export interface AdminSummaryDataGap {
  has_gap: boolean
  gap_days?: number | null
  latest_local_date?: string | null
  latest_trade_date?: string | null
}

export interface AdminPipelineStageSummary {
  key: string
  label: string
  status: 'success' | 'warning' | 'danger' | 'info'
  ready: boolean
  value: string
  meta?: string | null
  detail?: string | null
}

export interface AdminSummaryResponse {
  today_status: AdminSummaryCard[]
  pipeline_status: AdminPipelineStageSummary[]
  data_production: Record<string, string | number | boolean | null>
  data_gap: AdminSummaryDataGap
  current_task: AdminSummaryTaskInfo | null
  latest_task: {
    id?: number | null
    status?: string | null
    summary?: string | null
    completed_at?: string | null
  } | null
  gap_days: number
  task_status: 'idle' | 'running' | 'failed' | 'completed'
  latest_task_summary?: string | null
  latest_trade_date?: string | null
  latest_db_date?: string | null
  latest_candidate_date?: string | null
  latest_analysis_date?: string | null
  system_ready: boolean
  pending_actions: Array<{
    type: string
    title: string
    message: string
    action: string
    route: string
  }>
}
