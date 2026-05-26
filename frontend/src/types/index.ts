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

export interface RiskFlagSummary {
  level?: 'low' | 'medium' | 'high' | string | null
  score?: number | null
  heat_score?: number | null
  confirmation_score?: number | null
  narrative_score?: number | null
  recent_limit_up_days?: number | null
  recent_runup_pct?: number | null
  sector_breadth?: number | null
  sector_avg_change_pct?: number | null
  isolated_spike?: boolean | null
  reversal_risk?: boolean | null
  tags?: string[]
  reasons?: string[]
  matched_themes?: string[]
  summary?: string | null
}

export interface RiskRegimeAiResult {
  confirmed_level?: 'low' | 'medium' | 'high' | string | null
  confidence?: number | null
  evidence_strength?: 'weak' | 'medium' | 'strong' | string | null
  stance?: 'confirm' | 'soft_confirm' | 'reject' | string | null
  summary?: string | null
  reasons?: string[]
  risk_signals?: string[]
  news_findings?: string[]
  announcement_findings?: string[]
  warnings?: string[]
}

export interface RiskRegimeAiReview {
  provider?: string | null
  model?: string | null
  enabled?: boolean | null
  context?: Record<string, any> | null
  result?: RiskRegimeAiResult | null
}

export interface RiskRegimeSummary {
  level?: 'low' | 'medium' | 'high' | string | null
  score?: number | null
  heat_score?: number | null
  failure_score?: number | null
  breadth_score?: number | null
  triggered?: boolean | null
  risk_count?: number | null
  total_count?: number | null
  risk_ratio?: number | null
  high_risk_count?: number | null
  reversal_risk_count?: number | null
  isolated_spike_ratio?: number | null
  b1_pass_ratio?: number | null
  trend_start_ratio?: number | null
  failure_ratio?: number | null
  risk_trend?: string | null
  tags?: string[]
  reasons?: string[]
  summary?: string | null
  ai_confirmed_level?: string | null
  ai_confidence?: number | null
  ai_stance?: string | null
  ai_evidence_strength?: string | null
  ai_review?: RiskRegimeAiReview | null
}

export interface Candidate {
  id: number
  pick_date: string
  code: string
  name?: string
  industry?: string | null
  sector_names?: string[]
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
  pullback_quality?: string | null
  pullback_negative_flags?: string[] | null
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
  pullback_quality?: string | null
  pullback_negative_flags?: string[] | null
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
  prefilter_passed?: boolean | null
  prefilter_summary?: string | null
  prefilter_blocked_by?: string[] | null
  pullback_quality?: string | null
  pullback_negative_flags?: string[] | null
  risk_flag?: RiskFlagSummary | null
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
  pullback_quality?: string | null
  pullback_negative_flags?: string[] | null
  risk_flag?: RiskFlagSummary | null
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

export interface PreviousIntradayAnalysisSummary {
  pick_date?: string | null
  verdict?: 'PASS' | 'WATCH' | 'FAIL' | string | null
  score?: number | null
  signal_type?: string | null
  comment?: string | null
  b1_passed?: boolean | null
}

export interface IntradayMarketOverviewItem {
  name: string
  ts_code?: string | null
  latest_price?: number | null
  open_price?: number | null
  change_pct?: number | null
  volume_ratio_5d?: number | null
  ma5?: number | null
  above_ma5?: boolean | null
  trend?: string | null
  volume_state?: string | null
  summary?: string | null
}

export interface IntradayMarketOverview {
  summary?: string | null
  market_bias?: string | null
  benchmark_name?: string | null
  benchmark_change_pct?: number | null
  items?: IntradayMarketOverviewItem[]
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
  midday_price?: number | null
  close_price?: number | null
  latest_price?: number | null
  high_price?: number | null
  low_price?: number | null
  volume?: number | null
  amount?: number | null
  change_pct?: number | null
  latest_change_pct?: number | null
  turnover?: number | null
  turnover_rate?: number | null
  volume_ratio?: number | null
  active_pool_rank?: number | null
  b1_passed?: boolean | null
  score?: number | null
  verdict?: 'PASS' | 'WATCH' | 'FAIL'
  signal_type?: string | null
  kdj_j?: number | null
  zx_long_pos?: boolean | null
  weekly_ma_aligned?: boolean | null
  volume_healthy?: boolean | null
  midday_time?: string | null
  analysis_basis?: string | null
  previous_analysis?: PreviousIntradayAnalysisSummary | null
  benchmark_name?: string | null
  benchmark_change_pct?: number | null
  relative_market_status?: string | null
  relative_market_strength_pct?: number | null
  manager_note?: string | null
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
  b1_signal_type?: string | null
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
  daily_row_count?: number
  daily_basic_row_count?: number
  turnover_rate_count?: number
  volume_ratio_count?: number
  metric_fill_ratio?: number
  daily_basic_fill_ratio?: number
  required_fill_ratio?: number
  reason?: string | null
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
  risk_regime?: RiskRegimeSummary | null
}

export interface AnalysisResultsResponse {
  pick_date?: string | null
  results: AnalysisResult[]
  total: number
  min_score_threshold: number
}

export interface TomorrowStarAggregateResponse {
  dates: string[]
  history: TomorrowStarHistoryItem[]
  window_status?: TomorrowStarWindowStatusResponse | null
  candidates: CandidatesResponse | null
  results: AnalysisResultsResponse | null
  freshness: FreshnessResponse | null
  generated_at?: string | null
  cache_hit: boolean
}

export interface CurrentHotAnalysisResultsResponse {
  pick_date?: string | null
  results: CurrentHotAnalysisResult[]
  total: number
  min_score_threshold: number
  risk_regime?: RiskRegimeSummary | null
}

export interface SectorAnalysisRow {
  id: number
  pick_date: string
  sector_key: string
  code: string
  name?: string
  sector_names?: string[]
  concepts?: string[]
  board_group?: string | null
  open_price?: number
  close_price?: number
  change_pct?: number
  turnover?: number
  turnover_rate?: number | null
  volume_ratio?: number | null
  active_pool_rank?: number | null
  b1_passed?: boolean | null
  kdj_j?: number | null
  verdict?: 'PASS' | 'WATCH' | 'FAIL'
  total_score?: number | null
  signal_type?: string | null
  comment?: string | null
  prefilter_passed?: boolean | null
  prefilter_summary?: string | null
  prefilter_blocked_by?: string[] | null
  pullback_quality?: string | null
  pullback_negative_flags?: string[] | null
}

export interface SectorAnalysisRowsResponse {
  sector_key: string
  pick_date?: string | null
  rows: SectorAnalysisRow[]
  total: number
}

export interface CurrentHotSectorLeaderItem {
  code: string
  name?: string | null
  total_score?: number | null
  signal_type?: string | null
  verdict?: 'PASS' | 'WATCH' | 'FAIL' | string | null
  active_pool_rank?: number | null
}

export interface CurrentHotSectorHistoryPoint {
  date: string
  rank: number
  strength_score: number
  tracked_count: number
  b1_count: number
  trend_start_count: number
  pass_count: number
  high_score_count: number
  negative_flag_count: number
  avg_score?: number | null
  avg_change_pct?: number | null
}

export interface CurrentHotSectorSummaryItem {
  sector_key: string
  sector_name: string
  description: string
  policy_focus: string[]
  focus_tracks: string[]
  rank?: number | null
  previous_rank?: number | null
  rank_change?: number | null
  pool_count: number
  tracked_count: number
  pool_hit_ratio: number
  b1_count: number
  trend_start_count: number
  pass_count: number
  high_score_count: number
  negative_flag_count: number
  active_top20_count: number
  active_top50_count: number
  avg_score?: number | null
  avg_change_pct?: number | null
  best_active_pool_rank?: number | null
  strength_score: number
  leaders: CurrentHotSectorLeaderItem[]
}

export interface CurrentHotSectorHistorySeries {
  sector_key: string
  sector_name: string
  points: CurrentHotSectorHistoryPoint[]
}

export interface CurrentHotSectorAnalysisResponse {
  latest_date?: string | null
  previous_date?: string | null
  window_size: number
  dates: string[]
  top_sector_keys: string[]
  sectors: CurrentHotSectorSummaryItem[]
  history: CurrentHotSectorHistorySeries[]
}

/** 当前热盘聚合首屏响应 -- 一次返回全部数据 */
export interface CurrentHotAggregateResponse {
  // 历史摘要
  dates: string[]
  history: {
    pick_date: string
    date: string
    candidate_count: number
    analysis_count: number
    trend_start_count: number
    b1_pass_count: number
    consecutive_candidate_count: number
    pass_count: number
    status: string
    error_message?: string | null
    is_latest: boolean
  }[]
  latest_date?: string | null
  // 候选列表
  candidates: CurrentHotCandidate[]
  candidates_total: number
  // 分析结果
  results: CurrentHotAnalysisResult[]
  results_total: number
  min_score_threshold: number
  // 板块分析
  sectors: CurrentHotSectorSummaryItem[]
  sector_top_keys: string[]
  sector_dates: string[]
  sector_history: CurrentHotSectorHistorySeries[]
  sector_latest_date?: string | null
  sector_previous_date?: string | null
  sector_window_size: number
  // 风险环境
  risk_regime?: RiskRegimeSummary | null
  // 元信息
  pick_date?: string | null
  generated_at?: string | null
  cache_hit: boolean
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
  market_overview?: IntradayMarketOverview | null
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

export interface IntradayAnalysisPrefetchResponse {
  trade_date?: string | null
  source_pick_date?: string | null
  snapshot_time?: string | null
  window_open?: boolean | null
  has_data?: boolean
  status?: string | null
  message?: string | null
  requested_count?: number
  ready_count?: number
  missing_count?: number
  midday_ready_count?: number
  cached_count?: number
  downloaded_count?: number
}

export type CurrentHotIntradayAnalysisStatusResponse = IntradayAnalysisStatusResponse
export type CurrentHotIntradayAnalysisResponse = IntradayAnalysisResponse
export type CurrentHotIntradayAnalysisActionResponse = IntradayAnalysisActionResponse
export type CurrentHotIntradayAnalysisPrefetchResponse = IntradayAnalysisPrefetchResponse

export interface ClosingSectorFlowItem {
  sector_name: string
  net_mf_amount: number
}

export interface ClosingMarketOverview {
  trend: string
  trade_date?: string | null
  previous_trade_date?: string | null
  avg_change_pct?: number | null
  up_count: number
  down_count: number
  flat_count: number
  total_count: number
  summary?: string | null
}

export interface ClosingSectorFlow {
  source?: string | null
  source_trade_date?: string | null
  is_fallback?: boolean
  inflow_top3: ClosingSectorFlowItem[]
  outflow_top3: ClosingSectorFlowItem[]
}

export interface ClosingHotTopicItem {
  keyword: string
  category?: string | null
  heat?: number | null
  reason?: string | null
  related_sectors: string[]
  related_companies: string[]
  evidence: Array<Record<string, any>>
}

export interface ClosingHotTopics {
  source?: string | null
  window_days: number
  start_date?: string | null
  end_date?: string | null
  search_queries: string[]
  keywords: ClosingHotTopicItem[]
  summary?: string | null
  confidence?: number | null
  evidence: Array<Record<string, any>>
}

export interface ClosingCandidateMoveItem {
  code: string
  name?: string | null
  sector_names: string[]
  base_close?: number | null
  latest_close?: number | null
  change_pct: number
  source_pick_date: string
}

export interface ClosingCandidateMoveBucket {
  label: string
  source_pick_date: string
  rising: ClosingCandidateMoveItem[]
  falling: ClosingCandidateMoveItem[]
}

export interface ClosingTomorrowPredictionItem {
  rank?: number | null
  code: string
  name?: string | null
  sector_names: string[]
  b1_score?: number | null
  b1_passed?: boolean | null
  b1_comment?: string | null
  signal_type?: string | null
  verdict?: string | null
  close_price?: number | null
  change_pct?: number | null
  turnover_rate?: number | null
  volume_ratio?: number | null
  sector_net_mf_amount?: number | null
  sector_3d_net_mf_amount?: number | null
  is_industry_leader?: boolean | null
  market_cap?: number | null
  financial_performance?: Record<string, any> | null
  institutional_rating?: Record<string, any> | null
  tomorrow_star_pass?: boolean | null
  is_star_rejected?: boolean | null
  topic_relevance_score?: number | null
  matched_hot_topics: string[]
  local_score?: number | null
  local_reasons: string[]
  ai_score?: number | null
  bullish_news: string[]
  negative_news: string[]
  ai_comment?: string | null
  decision_reason?: string | null
}

export interface ClosingTomorrowPrediction {
  trade_date?: string | null
  status?: string | null
  message?: string | null
  preselected: ClosingTomorrowPredictionItem[]
  selected: ClosingTomorrowPredictionItem[]
  sector_flow_history: Array<Record<string, any>>
  hot_topics?: ClosingHotTopics | null
  ai?: Record<string, any> | null
}

export interface ClosingAnalysisStatusResponse {
  latest_data_date?: string | null
  report_trade_date?: string | null
  has_report: boolean
  can_generate: boolean
  status: string
  message: string
}

export interface ClosingAnalysisReportResponse {
  id?: number | null
  has_report: boolean
  generated: boolean
  status?: string | null
  message?: string | null
  trade_date?: string | null
  source_data_date?: string | null
  generated_at?: string | null
  force_generated: boolean
  market?: ClosingMarketOverview | null
  sector_flow?: ClosingSectorFlow | null
  hot_topics?: ClosingHotTopics | null
  candidate_buckets: ClosingCandidateMoveBucket[]
  tomorrow_prediction?: ClosingTomorrowPrediction | null
}

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
  b1_signal_type?: string | null
  scores?: Record<string, number>
  trend_reasoning?: string
  position_reasoning?: string
  volume_reasoning?: string
  abnormal_move_reasoning?: string
  signal_type?: string
  signal_reasoning?: string
  comment?: string
  risk_flag?: RiskFlagSummary | null
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
  risk_regime?: RiskRegimeSummary | null
}

export interface StockAiAnalysisResponse {
  code: string
  name?: string | null
  provider: string
  model?: string | null
  context: Record<string, any>
  result: Record<string, any>
}

export interface WatchlistResponse {
  items: WatchlistItem[]
  total: number
}

export interface WatchlistLightItem {
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
}

export interface WatchlistLightResponse {
  items: WatchlistLightItem[]
  total: number
  page: number
  page_size: number
}

export interface WatchlistDetailResponse {
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

export interface CsvImportResult {
  total_rows: number
  inserted_count: number
  updated_count: number
  skipped_count: number
  errors: string[]
}

export interface UserListItem {
  id: number
  username: string
  display_name: string | null
  role: 'admin' | 'user'
  is_active: boolean
  daily_quota: number
  created_at: string
  last_login_at: string | null
  is_online: boolean
  recent_visit_count: number
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

// =====================
// 历史信号收益率分析类型
// =====================

export interface SignalReturnTimelinePoint {
  trade_date: string
  close_price?: number | null
  return_pct?: number | null
  benchmark_close?: number | null
  benchmark_return_pct?: number | null
}

export interface SignalReturnEventPoint {
  key: string
  label: string
  trade_date: string
  price?: number | null
  return_pct?: number | null
  benchmark_return_pct?: number | null
}

export interface SignalReturnBenchmark {
  name: string
  ts_code: string
  base_date: string
  base_close?: number | null
}

export interface SignalReturnItem {
  code: string
  name?: string | null
  pick_date: string
  buy_date: string
  buy_price?: number | null
  day5_return?: number | null
  day10_return?: number | null
  day15_return?: number | null
  current_return?: number | null
  max_return?: number | null
  max_return_date?: string | null
  max_loss?: number | null
  max_loss_date?: string | null
  fail_return?: number | null
  fail_date?: string | null
  fail_sell_date?: string | null
  current_price?: number | null
  timeline: SignalReturnTimelinePoint[]
  events: SignalReturnEventPoint[]
}

export interface SignalReturnAnalysisResponse {
  pick_date: string
  signal_type: 'trend_start' | 'tomorrow_star'
  signal_label: string
  source: 'tomorrow_star' | 'current_hot'
  benchmark?: SignalReturnBenchmark | null
  stocks: SignalReturnItem[]
  total: number
  avg_day5_return?: number | null
  avg_day10_return?: number | null
  avg_day15_return?: number | null
  avg_current_return?: number | null
}

// =====================
// 概念板块相关类型
// =====================

export interface ConceptInfo {
  concept_code: string
  concept_name: string
  concept_type?: string | null
  start_date?: string | null
}

export interface ConceptsResponse {
  concepts: ConceptInfo[]
  total: number
}

export interface StockConceptsResponse {
  stocks: Record<string, string[]>  // code -> concepts
  total: number
}

export interface ConceptMembersResponse {
  concept_code: string
  concept_name?: string | null
  members: Array<{
    ts_code: string
    name?: string
    in_date?: string
    out_date?: string
  }>
  total: number
}

export interface CustomConceptRunItem {
  id: number
  status: string
  provider?: string | null
  model?: string | null
  prompt_version: string
  candidate_count: number
  matched_stock_count: number
  started_at?: string | null
  finished_at?: string | null
  error_message?: string | null
}

export interface OfficialConceptMatchItem {
  concept_code: string
  concept_name: string
  score: number
  matched_terms: string[]
}

export interface CustomConceptSummaryItem {
  id: number
  name: string
  display_name: string
  description?: string | null
  chain_hint?: string | null
  status: string
  prompt_version: string
  aliases: string[]
  related_sectors: string[]
  tag_count: number
  last_refreshed_at?: string | null
  updated_at: string
  latest_run?: CustomConceptRunItem | null
}

export interface CustomConceptDetailResponse extends CustomConceptSummaryItem {
  recent_runs: CustomConceptRunItem[]
}

export interface CustomConceptListResponse {
  concepts: CustomConceptSummaryItem[]
  total: number
}

export interface CustomConceptUpsertRequest {
  name: string
  display_name?: string | null
  description?: string | null
  chain_hint?: string | null
  aliases: string[]
  related_sectors: string[]
  status: string
}

export interface CustomConceptStockTagItem {
  stock_code: string
  stock_name?: string | null
  industry?: string | null
  relevance_score?: number | null
  confidence?: number | null
  chain_position: string
  role_tags: string[]
  reason?: string | null
  matched_source_concepts: string[]
  updated_at: string
}

export interface CustomConceptStockTagsResponse {
  concept_id: number
  concept_name: string
  stocks: CustomConceptStockTagItem[]
  total: number
}

export interface StockCustomConceptItem {
  concept_id: number
  concept_name: string
  concept_display_name: string
  relevance_score?: number | null
  confidence?: number | null
  chain_position: string
  role_tags: string[]
  reason?: string | null
  updated_at: string
}

export interface StockCustomConceptsResponse {
  code: string
  concepts: StockCustomConceptItem[]
  total: number
}

export interface CustomConceptRefreshResponse {
  concept_id: number
  concept_name: string
  run: CustomConceptRunItem
  official_matches: OfficialConceptMatchItem[]
  stocks_saved: number
  concept_summary?: string | null
  industry_chain_definition?: string | null
}

export interface CandidateConceptMatchRequestItem {
  code: string
  name?: string | null
  industry?: string | null
  sector_names: string[]
  signal_type?: string | null
  total_score?: number | null
  comment?: string | null
}

export interface CandidateConceptMatchItem {
  code: string
  name?: string | null
  industry?: string | null
  relevance_score?: number | null
  confidence?: number | null
  chain_position: string
  role_tags: string[]
  reason?: string | null
}

export interface CandidateConceptMatchResponse {
  query: string
  concept_id: number
  concept_name: string
  cache_hit: boolean
  source: 'cache' | 'ai' | string
  data_updated_at?: string | null
  refresh_scheduled: boolean
  total_candidates: number
  matched_count: number
  matches: CandidateConceptMatchItem[]
}

export interface ConceptQuerySuggestionItem {
  query: string
  label: string
  source: string
  updated_at?: string | null
}

export interface ConceptQuerySuggestionsResponse {
  items: ConceptQuerySuggestionItem[]
  total: number
}

export interface ConceptMemoryEntryItem {
  id: number
  keyword: string
  title: string
  content: string
  category?: string | null
  source_type: string
  source_name?: string | null
  source_url?: string | null
  status: string
  priority: number
  is_fixed: boolean
  tags: string[]
  related_stock_codes: string[]
  summary?: string | null
  evidence?: Record<string, any> | null
  prompt_version?: string | null
  last_refreshed_at?: string | null
  created_at: string
  updated_at: string
}

export interface ConceptMemoryRunItem {
  id: number
  entry_id?: number | null
  run_type: string
  query_text?: string | null
  status: string
  provider?: string | null
  model?: string | null
  prompt_version?: string | null
  matched_entry_count: number
  matched_news_count: number
  started_at?: string | null
  finished_at?: string | null
  error_message?: string | null
}

export interface ConceptMemoryUpsertRequest {
  keyword: string
  title: string
  content: string
  category?: string | null
  source_type: string
  source_name?: string | null
  source_url?: string | null
  status: string
  priority: number
  is_fixed: boolean
  tags: string[]
  related_stock_codes: string[]
}

export interface ConceptMemoryListResponse {
  entries: ConceptMemoryEntryItem[]
  total: number
  stats: Record<string, any>
}

export interface ConceptMemoryDetailResponse extends ConceptMemoryEntryItem {
  recent_runs: ConceptMemoryRunItem[]
}

export interface ConceptMemoryRefreshResponse {
  entry_id: number
  keyword: string
  run: ConceptMemoryRunItem
  matched_news_count: number
  matched_official_concepts: Record<string, any>[]
  matched_memory_entries: Record<string, any>[]
  ai_summary?: string | null
  ai_keywords: string[]
  ai_related_stock_codes: string[]
}

export interface ConceptMemoryComposeRequest {
  query: string
  use_ai: boolean
  force_refresh: boolean
  max_entries: number
  max_news: number
}

export interface ConceptMemoryComposeResponse {
  query: string
  cache_hit: boolean
  source: 'cache' | 'ai' | 'local' | string
  context_text: string
  matched_entries: ConceptMemoryEntryItem[]
  matched_news: Record<string, any>[]
  matched_official_concepts: Record<string, any>[]
  ai_result?: Record<string, any> | null
  run?: ConceptMemoryRunItem | null
}
