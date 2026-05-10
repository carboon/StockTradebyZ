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
  turnover_rate?: number | null
  volume_ratio?: number | null
  active_pool_rank?: number | null
  b1_passed?: boolean
  kdj_j?: number
  consecutive_days?: number
  verdict?: 'PASS' | 'WATCH' | 'FAIL'
  total_score?: number
  signal_type?: string
  comment?: string
  tomorrow_star_pass?: boolean | null
  prefilter_passed?: boolean | null
  prefilter_summary?: string | null
  prefilter_blocked_by?: string[] | null
}

export interface AnalysisResult {
  id: number
  pick_date: string
  code: string
  name?: string
  reviewer?: string
  verdict?: 'PASS' | 'WATCH' | 'FAIL'
  total_score?: number
  signal_type?: string
  comment?: string
  turnover_rate?: number | null
  volume_ratio?: number | null
  active_pool_rank?: number | null
  tomorrow_star_pass?: boolean | null
  prefilter_passed?: boolean | null
  prefilter_summary?: string | null
  prefilter_blocked_by?: string[] | null
}

export interface CurrentHotCandidate {
  id: number
  pick_date: string
  code: string
  name?: string
  sector_names?: string[]
  board_group?: string | null
  board?: string | null
  board_name?: string | null
  sector_name?: string | null
  open_price?: number
  close_price?: number
  change_pct?: number
  turnover?: number
  turnover_rate?: number | null
  volume_ratio?: number | null
  active_pool_rank?: number | null
  b1_passed?: boolean | null
  kdj_j?: number
  verdict?: 'PASS' | 'WATCH' | 'FAIL'
  total_score?: number | null
  signal_type?: string | null
  comment?: string | null
}

export interface CurrentHotAnalysisResult {
  id: number
  pick_date: string
  code: string
  name?: string
  sector_names?: string[]
  board_group?: string | null
  reviewer?: string
  b1_passed?: boolean | null
  verdict?: 'PASS' | 'WATCH' | 'FAIL'
  total_score?: number
  signal_type?: string
  comment?: string
  turnover_rate?: number | null
  volume_ratio?: number | null
  active_pool_rank?: number | null
  prefilter_passed?: boolean | null
  prefilter_summary?: string | null
  prefilter_blocked_by?: string[] | null
}

export interface ExitPlan {
  action?: 'hold' | 'wash_observe' | 'hold_cautious' | 'take_profit_partial' | 'trim' | 'exit' | string
  action_label?: string
  phase?: string
  entry_price?: number | null
  current_price?: number | null
  pnl?: number | null
  mfe_since_entry?: number | null
  mae_since_entry?: number | null
  drawdown_from_mfe?: number | null
  target_progress?: string | null
  target_prices?: Record<string, Record<string, number | null>>
  risk_lines?: Record<string, number | null>
  morning_state?: string | null
  afternoon_action?: string | null
  key_levels?: Record<string, number | null>
  reason?: string | null
  rules?: string[]
}

export interface WatchlistAnalysisResult {
  trade_date?: string | null
  close_price?: number | null
  verdict?: 'PASS' | 'WATCH' | 'FAIL' | string | null
  score?: number | null
  signal_type?: string | null
  b1_passed?: boolean | null
  kdj_j?: number | null
  zx_long_pos?: boolean | null
  weekly_ma_aligned?: boolean | null
  volume_healthy?: boolean | null
}

export interface WatchlistDerivedData {
  pnl?: number | null
  trend_outlook?: 'bullish' | 'bearish' | 'neutral' | string | null
  buy_action?: 'buy' | 'wait' | 'avoid' | string | null
  hold_action?: 'hold' | 'hold_cautious' | 'trim' | 'add_on_pullback' | string | null
  risk_level?: 'low' | 'medium' | 'high' | string | null
  recommendation?: string | null
  support_level?: number | null
  resistance_level?: number | null
  exit_plan?: ExitPlan | null
}

export interface IntradayAnalysisItem {
  id: number
  trade_date: string
  code: string
  name?: string
  source_pick_date: string
  snapshot_time: string
  open_price?: number | null
  close_price?: number | null
  high_price?: number | null
  low_price?: number | null
  volume?: number | null
  amount?: number | null
  change_pct?: number | null
  turnover?: number | null
  b1_passed?: boolean | null
  score?: number | null
  verdict?: 'PASS' | 'WATCH' | 'FAIL'
  signal_type?: string | null
  kdj_j?: number | null
  zx_long_pos?: boolean | null
  weekly_ma_aligned?: boolean | null
  volume_healthy?: boolean | null
  exit_plan?: ExitPlan | null
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
  active_pool_rank?: number | null
  turnover_rate?: number | null
  volume_ratio?: number | null
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

interface DiagnosisHistoryDetailPayload {
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
  entry_price?: number | null
  entry_date?: string | null
  position_ratio?: number | null
  priority: number
  is_active: boolean
  added_at: string
  analysis?: WatchlistAnalysisResult | null
  derived?: WatchlistDerivedData | null
  exit_plan?: ExitPlan | null
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
  exit_plan?: ExitPlan | null
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
    manifest_latest_trade_date?: string | null
    manifest_status?: string | null
    manifest_record_count?: number
    manifest_stock_count?: number
    manifest_db_record_count?: number
    manifest_db_stock_count?: number
    manifest_loaded_to_db_at?: string | null
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

export interface DailyBatchUpdateResponse {
  success: boolean
  message: string
  trade_date?: string
  task_id?: number
  ws_url?: string
  existing?: boolean
  task?: Task | null
}

export interface Recent120IntegrityResponse {
  success: boolean
  window_size: number
  date_count: number
  date_range?: string[]
  summary?: Record<string, any>
  issues: Array<{ trade_date: string; issues: string[] }>
  dates: Array<Record<string, any>>
  message: string
}

export interface TradeDateRevalidationResponse {
  success: boolean
  trade_date: string
  summary: Record<string, any>
  sample_recomputed_current_hot: Array<Record<string, any>>
  current_hot_mismatches?: Array<Record<string, any>>
  issues: string[]
  message: string
}

// K线数据
interface KLineDataPoint {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  turnover_rate?: number
  turnover_rate_f?: number
  volume_ratio?: number
  free_share?: number
  circ_mv?: number
  buy_sm_amount?: number
  sell_sm_amount?: number
  buy_md_amount?: number
  sell_md_amount?: number
  buy_lg_amount?: number
  sell_lg_amount?: number
  buy_elg_amount?: number
  sell_elg_amount?: number
  net_mf_amount?: number
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
  b1_pass_count?: number
  consecutive_candidate_count?: number
  tomorrow_star_count?: number
  status?: 'pending' | 'running' | 'success' | 'failed' | 'missing' | string
  source?: string
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

interface TomorrowStarWindowStatusItem {
  pick_date?: string
  date?: string
  status?: 'pending' | 'running' | 'success' | 'failed' | 'missing' | string
  candidate_count?: number
  analysis_count?: number
  trend_start_count?: number
  b1_pass_count?: number
  consecutive_candidate_count?: number
  tomorrow_star_count?: number
  reviewer?: string | null
  source?: string | null
  started_at?: string | null
  finished_at?: string | null
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

export interface CurrentHotDatesResponse {
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

export interface CurrentHotCandidatesResponse {
  pick_date?: string | null
  candidates: CurrentHotCandidate[]
  total: number
}

export interface AnalysisResultsResponse {
  pick_date?: string | null
  results: AnalysisResult[]
  total: number
  min_score_threshold: number
}

export interface CurrentHotAnalysisResultsResponse {
  pick_date?: string | null
  results: CurrentHotAnalysisResult[]
  total: number
  min_score_threshold: number
}

export interface IntradayAnalysisStatusResponse {
  trade_date?: string | null
  snapshot_time?: string | null
  source_pick_date?: string | null
  window_open?: boolean | null
  has_data: boolean
  status?: string | null
  message?: string | null
}

export interface IntradayAnalysisResponse {
  trade_date?: string | null
  snapshot_time?: string | null
  source_pick_date?: string | null
  window_open?: boolean | null
  has_data: boolean
  status?: string | null
  items: IntradayAnalysisItem[]
  total: number
  message?: string | null
}

export interface IntradayAnalysisActionResponse {
  trade_date?: string | null
  source_pick_date?: string | null
  snapshot_time?: string | null
  window_open?: boolean | null
  has_data?: boolean
  status?: string | null
  message: string
  generated_count?: number
  skipped_count?: number
}

export type CurrentHotIntradayAnalysisStatusResponse = IntradayAnalysisStatusResponse
export type CurrentHotIntradayAnalysisResponse = IntradayAnalysisResponse
export type CurrentHotIntradayAnalysisActionResponse = IntradayAnalysisActionResponse

export interface DiagnosisHistoryResponse {
  code: string
  name?: string
  history: B1Check[]
  total: number
  page?: number
  page_size?: number
  trend_start_dates?: string[]
  tomorrow_star_dates?: string[]
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

interface DiagnosisAnalysisDetails {
  kdj_j?: number
  zx_long_pos?: boolean
  weekly_ma_aligned?: boolean
  volume_healthy?: boolean
  active_pool_rank?: number | null
  turnover_rate?: number | null
  volume_ratio?: number | null
  in_active_pool?: boolean | null
  scores?: Record<string, number>
  trend_reasoning?: string
  position_reasoning?: string
  volume_reasoning?: string
  abnormal_move_reasoning?: string
  signal_type?: string
  signal_reasoning?: string
  comment?: string
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

interface TaskOverviewCard {
  key: string
  label: string
  value: string
  status: string
  meta?: string | null
}

interface TaskAlertItem {
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

interface TaskEnvironmentSection {
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
  task_id?: number | null
  task_type?: string
  mode?: 'daily_batch' | 'per_stock_fallback' | 'incremental_update' | 'pending' | 'idle' | string
  target_trade_date?: string | null
  stage_label?: string | null
  display_title?: string
  display_detail?: string
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

interface UsageStatsItem {
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

interface AdminSummaryCard {
  key: string
  label: string
  value: string
  status: 'success' | 'warning' | 'danger' | 'info'
  meta?: string | null
  action_label?: string | null
  action_route?: string | null
}

interface AdminSummaryTaskInfo {
  id?: number | null
  task_type?: string | null
  status: string
  stage_label?: string | null
  progress: number
  summary?: string | null
  task_stage?: string | null
  progress_meta_json?: TaskProgressMeta | null
}

interface AdminSummaryDataGap {
  has_gap: boolean
  gap_days?: number | null
  latest_local_date?: string | null
  latest_trade_date?: string | null
}

interface AdminPipelineStageSummary {
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
