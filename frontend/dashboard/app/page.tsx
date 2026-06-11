"use client";

import { useCallback, useEffect, useState } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface PaperStatus {
  running: boolean;
  starting_cash: number;
  cash: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  total_pnl_percent: number;
  open_position_count: number;
  closed_trade_count: number;
  daily_trade_count: number;
  max_trades_per_day: number;
  last_tick_at: string | null;
  last_error: string | null;
  snapshot_storage: string;
  state_restored_from_snapshot: boolean;
  restart_persistent: boolean;
  restore_source?: string;
  restored_closed_trades_count?: number;
  restored_open_positions_count?: number;
  restored_daily_realized_pnl?: number;
  restored_trades_today?: number;
  restore_warning?: string | null;
  restore_warnings?: string[];
  mode: string;
  live_trading_enabled: boolean;
  broker_connected: boolean;
  take_profit_percent: number;
  stop_loss_percent: number;
  max_hold_minutes: number;
  daily_loss_guard?: DailyLossGuard;
}

interface Position {
  position_id: string;
  symbol: string;
  entry_price: number;
  current_price: number;
  shares: number;
  cost_basis: number;
  unrealized_pnl: number;
  unrealized_pnl_percent: number;
  entry_time: string;
  entry_catalyst_type: string;
}

interface Trade {
  position_id: string;
  symbol: string;
  entry_price: number;
  exit_price: number;
  shares: number;
  pnl: number;
  pnl_percent: number;
  exit_reason: string;
  entry_catalyst_type: string;
  hold_minutes: number;
  exit_time: string;
}

interface ScoreComponents {
  market_quality_score: number;
  spread_score: number;
  momentum_score: number;
  volume_score: number;
  catalyst_score: number;
  risk_penalty: number;
}

interface Candidate {
  symbol: string;
  eligible: boolean;
  rejection_reason: string | null;
  action: string | null;
  quality_tradable: boolean;
  spread_percent: number | null;
  change_percent: number | null;
  catalyst_type: string | null;
  catalyst_count: number;
  total_score: number | null;
  score_threshold: number | null;
  score_pass: boolean | null;
  score_components: ScoreComponents | null;
  decision_reason: string | null;
  catalyst_sentiment: string | null;
  catalyst_sentiment_score: number | null;
  catalyst_materiality_score: number | null;
  catalyst_sentiment_reasons: string[] | null;
  bullish_flags: string[] | null;
  bearish_flags: string[] | null;
  strongest_catalyst_title: string | null;
  strongest_catalyst_sentiment: string | null;
  // Phase 2T catalyst type guard fields
  catalyst_type_blocked?: boolean;
  blocked_catalyst_type?: string | null;
  // Phase 2M momentum fields
  entry_mode: string | null;
  momentum_eligible: boolean | null;
  momentum_score: number | null;
  momentum_score_threshold: number | null;
  momentum_rejection_reason: string | null;
  // Phase I4-B: candidate source metadata
  candidate_sources?: string[] | null;
  market_mover_rank?: number | null;
  market_mover_gap_percent?: number | null;
  market_mover_session?: string | null;
  market_mover_mode?: string | null;
  // Phase I4-A: enhanced shadow scoring (diagnostic only, not used for trading)
  enhanced_shadow_score: number | null;
  enhanced_shadow_decision: string | null;
  enhanced_shadow_reason: string | null;
  enhanced_shadow_components: Record<string, number> | null;
  enhanced_shadow_blockers: string[] | null;
  enhanced_shadow_confidence: string | null;
  premarket_rank: number | null;
  premarket_gap_percent: number | null;
  premarket_dollar_volume: number | null;
  premarket_volume: number | null;
  premarket_boost: number | null;
  reddit_rank: number | null;
  reddit_mentions: number | null;
  reddit_spike_ratio: number | null;
  reddit_boost: number | null;
  // Phase I6 intelligence adjustments
  base_score_before_intelligence_adjustments?: number | null;
  intelligence_score_adjustment?: number | null;
  final_score_after_intelligence_adjustments?: number | null;
  earnings_scoring_enabled?: boolean | null;
  earnings_next_date?: string | null;
  earnings_days_until?: number | null;
  earnings_score_adjustment?: number | null;
  earnings_reason?: string | null;
  earnings_blocked?: boolean | null;
  insider_scoring_enabled?: boolean | null;
  insider_recent_buy_count?: number | null;
  insider_recent_buy_value?: number | null;
  insider_score_adjustment?: number | null;
  insider_reason?: string | null;
  insider_latest_transaction_date?: string | null;
  insider_transaction_codes?: string[] | null;
  // Phase M1 market trend overlay
  market_trend_enabled?: boolean | null;
  market_trend_source?: string | null;
  market_trend_direction?: string | null;
  market_trend_strength?: string | null;
  market_trend_adjustment?: number | null;
  market_trend_reason?: string | null;
  market_regime_score_before_trend?: number | null;
  market_regime_score_after_trend?: number | null;
  market_trend_collecting?: boolean | null;
  market_trend_has_5m_window?: boolean | null;
  market_trend_has_10m_window?: boolean | null;
  market_trend_has_15m_window?: boolean | null;
  market_trend_consumers?: Record<string, boolean> | null;
  market_trend_consumed_by_path?: boolean | null;
  market_trend_regime_used?: "raw" | "trend_adjusted" | string | null;
  market_trend_path_name?: string | null;
  market_mover_regime_used?: string | null;
  market_mover_risk_score_used?: number | null;
  market_mover_regime_label_used?: string | null;
  // Phase L1 LLM Shadow Analyst (diagnostic only)
  llm_status?: string | null;
  llm_decision?: "WOULD_ENTER" | "WATCH" | "WOULD_REJECT" | null;
  llm_confidence?: number | null;
  llm_recommended_action?: string | null;
  llm_primary_reason?: string | null;
  llm_summary?: string | null;
  llm_agrees_with_engine?: boolean | null;
  llm_agrees_with_shadow?: boolean | null;
  llm_score_adjustment_suggestion?: number | null;
  llm_directional_bias?: string | null;
  llm_impact_assessment?: string | null;
  llm_latency_ms?: number | null;
  llm_cached?: boolean | null;
  llm_model?: string | null;
  llm_error?: string | null;
}

// ── Analytics types ───────────────────────────────────────────────────────────

interface MarketSession {
  timezone: string;
  regular_open: string;
  regular_close: string;
  is_regular_session_now: boolean;
  note: string;
}

interface SessionInfo {
  running: boolean;
  last_tick_at: string | null;
  daily_trade_count: number;
  max_trades_per_day: number;
  open_position_count: number;
  closed_trade_count: number;
}

interface PnLInfo {
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  total_pnl_percent: number;
  best_trade_pnl: number | null;
  worst_trade_pnl: number | null;
}

interface PerformanceInfo {
  wins: number;
  losses: number;
  breakeven: number;
  win_rate_percent: number | null;
  average_win: number | null;
  average_loss: number | null;
  profit_factor: number | null;
  average_hold_minutes: number | null;
}

interface CandidateFunnelInfo {
  total_candidates: number;
  eligible: number;
  entered: number;
  score_rejected: number;
  hard_rejected: number;
  blocked: number;
  entry_failed: number;
}

interface ScoreDistributionInfo {
  above_threshold: number;
  score_80_plus: number;
  score_70_to_79: number;
  score_50_to_69: number;
  below_50: number;
  average_score: number | null;
}

interface RejectionItem { reason: string; count: number; }
interface CatalystTypeItem { type: string; count: number; }

interface UniverseHealthInfo {
  active_count: number | null;
  max_symbols_per_tick: number | null;
  refresh_reason: string;
  error_count: number;
  top_errors: Array<{ symbol?: string; error: string }>;
}

interface Analytics {
  session: SessionInfo;
  pnl: PnLInfo;
  performance: PerformanceInfo;
  candidate_funnel: CandidateFunnelInfo;
  score_distribution: ScoreDistributionInfo;
  rejections: { top_rejection_reasons: RejectionItem[] };
  catalysts: { by_type: CatalystTypeItem[] };
  universe_health: UniverseHealthInfo;
  market_session: MarketSession;
}

interface UniverseDiscovery {
  enabled: boolean;
  discovered_count: number;
  discovered_symbols: string[];
  refresh_reason: string | null;
  errors: string[];
  warnings: string[];
}

interface UniverseInfo {
  base_symbols: string[];
  dynamic_symbols: string[];
  active_symbols: string[];
  active_count: number;
  max_symbols_per_tick: number;
  last_refreshed_at: string | null;
  refresh_reason: string;
  errors: Array<{ symbol?: string; error: string }>;
  discovery: UniverseDiscovery | null;
}

interface MarketRegimeLeader {
  change_percent: number | null;
  last_trade_price: number | null;
}

interface MarketRegimeData {
  enabled?: boolean;
  symbols_requested?: string[];
  symbols_fetched?: string[];
  symbols_failed?: string[];
  fetch_ratio?: number | null;
  breadth?: {
    total: number;
    positive: number;
    negative: number;
    flat: number;
    positive_percent: number | null;
    avg_change_percent: number | null;
  } | null;
  leaders?: {
    data: {
      SPY: MarketRegimeLeader | null;
      QQQ: MarketRegimeLeader | null;
      IWM: MarketRegimeLeader | null;
    };
    bullish_count: number;
    bearish_count: number;
  } | null;
  risk?: {
    regime: "risk_on" | "neutral" | "risk_off" | "unknown" | string;
    risk_on_score: number | null;
    confidence: "high" | "medium" | "low" | "unknown" | string;
    fetched_count: number;
    warnings?: string[];
  } | null;
  as_of?: string | null;
  disclaimer?: string | null;
  error?: string | null;
}

interface MarketTrendDelta {
  ago_snapshot_as_of?: string | null;
  risk_on_score_ago?: number | null;
  risk_on_score_delta?: number | null;
  qqq_change_ago?: number | null;
  qqq_delta?: number | null;
  spy_change_ago?: number | null;
  spy_delta?: number | null;
  iwm_change_ago?: number | null;
  iwm_delta?: number | null;
}

interface MarketTrendData {
  ok: boolean;
  enabled: boolean;
  source: string;
  futures_available: boolean;
  provider_status: string;
  primary_symbols: string[];
  context_symbols: string[];
  optional_proxy_symbols: string[];
  snapshot_count: number;
  snapshot_interval_seconds: number;
  history_minutes: number;
  windows_minutes: number[];
  latest_snapshot?: Record<string, unknown> | null;
  deltas: Record<string, MarketTrendDelta>;
  market_regime_score_before_trend: number | null;
  market_regime_score_after_trend: number | null;
  raw_regime_label?: string | null;
  adjusted_regime_label?: string | null;
  trend_direction: "improving" | "deteriorating" | "flat" | "unknown" | string;
  trend_strength: "strong" | "moderate" | "weak" | "unknown" | string;
  market_trend_adjustment: number;
  market_trend_reason: string;
  collecting?: boolean;
  has_5m_window?: boolean;
  has_10m_window?: boolean;
  has_15m_window?: boolean;
  trend_consumers?: {
    legacy_momentum?: boolean;
    no_catalyst?: boolean;
    market_mover?: boolean;
    catalyst?: boolean;
    shadow?: boolean;
  };
  warnings?: string[];
  as_of: string | null;
}

interface Dashboard {
  status: PaperStatus;
  positions: Position[];
  trades: Trade[];
  last_candidates: Candidate[];
  universe: UniverseInfo | null;
  analytics: Analytics | null;
  market_regime: MarketRegimeData | null;
  disclaimer: string;
}

// ── Intelligence types ────────────────────────────────────────────────────────

interface RedditRow {
  rank: number;
  ticker: string;
  name: string;
  mentions: number;
  upvotes: number;
  rank_24h_ago: number | null;
  mentions_24h_ago: number | null;
}

interface RedditSpike {
  ticker: string;
  mentions: number;
  prev_mentions: number;
  spike_ratio: number;
}

interface RedditSnapshot {
  ok: boolean;
  source: string;
  fetched_at: number | null;
  age_seconds: number | null;
  ttl_seconds: number | null;
  result_count: number;
  results: RedditRow[];
  spikes: RedditSpike[];
  error: string | null;
}

interface PremarketMover {
  rank: number;
  symbol: string;
  last_price: number;
  previous_close: number | null;
  gap_percent: number;
  raw_change_percent: number | null;
  day_volume: number | null;
  dollar_volume: number | null;
  previous_day_volume: number | null;
  volume_vs_previous_day_ratio: number | null;
  time_adjusted_volume_ratio: number | null;
  session_elapsed_ratio?: number | null;
  avg_daily_volume_30d: number | null;
  volume_vs_30d_avg_ratio: number | null;
  avg_daily_volume_60d: number | null;
  volume_vs_60d_avg_ratio: number | null;
  expected_volume_now: number | null;
  source: string;
}

interface PremarketSnapshot {
  ok: boolean;
  mode: string;
  session: string;
  // Full-universe fields
  universe_count?: number;
  symbols_returned?: number;
  valid_movers_count?: number;
  scan_duration_ms?: number | null;
  top_gainers?: PremarketMover[];
  top_losers?: PremarketMover[];
  top_movers?: PremarketMover[];
  // Active-universe fallback fields (still present on fallback path)
  symbol_count?: number;
  gainers?: PremarketMover[];
  losers?: PremarketMover[];
  // Common
  fetched_at: number | null;
  age_seconds: number | null;
  ttl_seconds: number | null;
  error: string | null;
  warnings?: string[];
}

interface NewsCatalystItem {
  catalyst_id?: string;
  symbol: string;
  source?: string;
  event_type?: string | null;
  classified_event_type?: string | null;
  event_confidence?: number | null;
  title?: string;
  description?: string;
  publisher?: string;
  published_utc?: string | null;
  collected_at?: string | null;
  article_url?: string | null;
  sentiment?: string | null;
  sentiment_score?: number | null;
  materiality_score?: number | null;
  bullish_flags?: string[];
  bearish_flags?: string[];
  sentiment_reasons?: string[];
  tickers?: string[];
  // Phase I5-H2 normalized rule fields
  rule_analysis_available?: boolean;
  rule_event_type?: string | null;
  rule_impact_level?: "high" | "medium" | "low" | "unknown" | string;
  rule_sentiment?: string | null;
  rule_materiality_score?: number | null;
  rule_sentiment_score?: number | null;
  rule_bullish_flags?: string[];
  rule_bearish_flags?: string[];
  rule_reasons?: string[];
  rule_explanation?: string | null;
  used_by_engine?: boolean | "unknown" | string;
  // Phase I5-H2 AI placeholders (inactive in this phase)
  ai_analysis_available?: boolean;
  ai_sentiment?: string | null;
  ai_impact_level?: string | null;
  ai_materiality_score?: number | null;
  ai_confidence?: number | null;
  ai_explanation?: string | null;
  ai_model?: string | null;
}

interface NewsSnapshot {
  ok: boolean;
  enabled: boolean;
  implemented: boolean;
  source: string;
  analysis_mode?: string;
  fetched_at: string | null;
  cache_age_seconds?: number | null;
  ttl_seconds?: number | null;
  stale?: boolean;
  total_count?: number;
  returned_count?: number;
  limit?: number;
  offset?: number;
  filters_applied?: Record<string, unknown>;
  sort_by?: string;
  sort_dir?: string;
  symbols_requested?: string[];
  results: NewsCatalystItem[];
  errors?: { symbol: string; error: string }[];
  warning: string | null;
  note?: string;
}

interface PlaceholderFeed {
  ok: boolean;
  enabled: boolean;
  implemented: boolean;
  source: string | null;
  fetched_at: string | null;
  age_seconds: number | null;
  total_results: number;
  results: unknown[];
  errors?: unknown[];
  warning: string | null;
  note?: string;
}

// ── Journal types ─────────────────────────────────────────────────────────────

interface JournalStatus {
  enabled: boolean;
  database_connected: boolean;
  tables_ready: boolean;
  last_error: string | null;
  last_persist_ok: boolean | null;
  last_retry_at: number | null;
  retention_days: number;
  auto_cleanup_enabled: boolean;
}

interface JournalSummary {
  total_ticks: number;
  total_candidates: number;
  total_entries: number;
  total_exits: number;
  total_closed_trades: number;
  first_tick_at: string | null;
  last_tick_at: string | null;
  error?: string;
}

interface JournalTick {
  tick_id: string;
  started_at: string;
  completed_at: string | null;
  symbols_evaluated: number;
  universe_active_count: number;
  universe_refresh_reason: string | null;
  entries_made: number;
  exits_made: number;
  errors_count: number;
  account_cash: number | null;
  total_pnl: number | null;
  created_at: string;
}

interface JournalPerformance {
  total_trades: number;
  win_rate: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  profit_factor: number | null;
  best_trade: number | null;
  worst_trade: number | null;
  pnl_by_catalyst_type: Array<{ type: string; count: number; total_pnl: number }>;
  pnl_by_score_bucket: Array<{ bucket: string; count: number; total_pnl: number }>;
  error?: string;
}

interface JournalData {
  status: JournalStatus;
  summary: JournalSummary | null;
  recentTicks: JournalTick[];
  performance: JournalPerformance | null;
}

// ── Phase 2L types ───────────────────────────────────────────────────────────

interface ReadinessCheck {
  name: string;
  status: "pass" | "warn" | "fail";
  message: string;
  details: Record<string, unknown>;
}

interface ReadinessSummary {
  pass: number;
  warn: number;
  fail: number;
}

interface ReadinessData {
  overall_status: "ready" | "warning" | "not_ready";
  as_of: string;
  market_session: MarketSession;
  checks: ReadinessCheck[];
  summary: ReadinessSummary;
  recommended_actions: string[];
  disclaimer: string;
}

// ── Phase 2F types ────────────────────────────────────────────────────────────

interface RuntimeConfigStatus {
  overrides_active: boolean;
  override_count: number;
  persistent: boolean;
  warnings: string[];
}

interface DailyLossGuard {
  enabled: boolean;
  triggered: boolean;
  daily_pnl: number;
  daily_pnl_percent: number;
  threshold_percent: number;
  threshold_usd: number | null;
  reason: string | null;
}

interface CatalystTypeGuard {
  enabled: boolean;
  blocked_catalyst_types: string[];
  blocked_candidates_last_tick: number;
  disclaimer?: string;
  error?: string;
}

interface MonitoringStatus {
  backend_ok: boolean;
  paper_running: boolean;
  journal_enabled: boolean;
  journal_database_connected: boolean;
  journal_tables_ready: boolean;
  last_tick_at: string | null;
  last_tick_age_seconds: number | null;
  last_tick_fresh: boolean;
  last_journal_ok: boolean | null;
  last_error: string | null;
  market_session: MarketSession;
  runtime_config?: RuntimeConfigStatus;
  daily_loss_guard?: DailyLossGuard;
  catalyst_type_guard?: CatalystTypeGuard;
  warnings: string[];
}

interface RuntimeConfigField {
  type: string;
  description: string;
  category: string;
  min: number | null;
  max: number | null;
  base_value: number | boolean | null;
  runtime_override: number | boolean | null;
  effective_value: number | boolean | null;
}

interface RuntimeConfigSchema {
  fields: Record<string, RuntimeConfigField>;
  disclaimer: string;
}

interface RuntimeConfigState {
  runtime_overrides: Record<string, number | boolean>;
  base_config: Record<string, number | boolean | null>;
  effective_config: Record<string, number | boolean | null>;
  persistent: boolean;
  warnings: string[];
}

interface TodaySummary {
  trading_date: string;
  total_ticks_today: number;
  total_candidates_today: number;
  total_entries_today: number;
  total_exits_today: number;
  unique_symbols_seen_today: number;
  open_positions_current: number;
  closed_trades_today: number;
  realized_pnl_today: number | null;
  win_rate_today: number | null;
  profit_factor_today: number | null;
  first_tick_at: string | null;
  last_tick_at: string | null;
  last_tick_age_seconds: number | null;
  journal_healthy: boolean;
  notes: string[];
  error?: string;
}

interface TodayCatalyst {
  type: string;
  candidate_count: number;
  entries: number;
  exits: number;
}

interface TodaySymbol {
  symbol: string;
  candidate_count: number;
  entries: number;
  exits: number;
  avg_score: number | null;
  last_seen_at: string | null;
}

interface TodayRejection {
  reason: string;
  count: number;
}

interface TodayReport {
  summary: TodaySummary;
  top_rejections: TodayRejection[];
  catalysts: TodayCatalyst[];
  symbols: TodaySymbol[];
  latest_ticks: Array<{
    started_at: string;
    symbols_evaluated: number;
    entries_made: number;
    exits_made: number;
    errors_count: number;
    account_cash: number | null;
    total_pnl: number | null;
  }>;
  error?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined, decimals = 2): string {
  if (n == null) return "—";
  return n.toFixed(decimals);
}

function fmtUSD(n: number | null | undefined): string {
  if (n == null) return "—";
  const sign = n >= 0 ? "+" : "";
  return `${sign}$${Math.abs(n).toFixed(2)}`;
}

function pnlClass(n: number): string {
  if (n > 0) return "text-green-400";
  if (n < 0) return "text-red-400";
  return "text-gray-300";
}

function utcShort(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toUTCString().replace(" GMT", " UTC");
  } catch {
    return iso;
  }
}

// ── Override display helpers ──────────────────────────────────────────────────

function normalizeConfigValue(v: number | boolean | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return String(v);
}

function isOverrideChanged(
  key: string,
  overrides: Record<string, number | boolean>,
  base: Record<string, number | boolean | null>
): boolean {
  if (!(key in overrides)) return false;
  return String(overrides[key]) !== String(base[key]);
}

type OverrideDisplayState = "changed_override" | "stored_same_as_base" | "base_default";

function getOverrideDisplayState(
  key: string,
  overrides: Record<string, number | boolean>,
  base: Record<string, number | boolean | null>
): OverrideDisplayState {
  if (!(key in overrides)) return "base_default";
  if (String(overrides[key]) !== String(base[key])) return "changed_override";
  return "stored_same_as_base";
}

function getFieldCategory(key: string): string {
  if (key.startsWith("PAPER_NO_CATALYST_")) return "no_catalyst";
  if (key.startsWith("PAPER_MARKET_MOVER_")) return "market_mover";
  if (key.startsWith("PAPER_DAILY_MAX_LOSS_") || key === "PAPER_DAILY_MAX_LOSS_ENABLED") return "daily_loss_guard";
  if (key.startsWith("PAPER_MOMENTUM_")) return "legacy_momentum";
  if (key.startsWith("PAPER_USE_TIME_ADJUSTED_") || key.startsWith("PAPER_TIME_ADJUSTED_")) return "ta_volume";
  return "core_strategy";
}

// ── API calls ─────────────────────────────────────────────────────────────────

async function fetchDashboard(): Promise<Dashboard | null> {
  try {
    const r = await fetch("/api/paper/dashboard");
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

async function fetchJournal(): Promise<JournalData | null> {
  try {
    const [statusR, summaryR, ticksR, perfR] = await Promise.all([
      fetch("/api/journal/status"),
      fetch("/api/journal/summary"),
      fetch("/api/journal/ticks?limit=10"),
      fetch("/api/journal/performance"),
    ]);
    const [status, summary, recentTicks, performance] = await Promise.all([
      statusR.json(),
      summaryR.json(),
      ticksR.json(),
      perfR.json(),
    ]);
    return {
      status,
      summary: summary.error ? null : summary,
      recentTicks: Array.isArray(recentTicks) ? recentTicks : [],
      performance: performance.error ? null : performance,
    };
  } catch {
    return null;
  }
}

async function fetchMonitoringStatus(): Promise<MonitoringStatus | null> {
  try {
    const r = await fetch("/api/monitoring/status");
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

async function fetchReddit(): Promise<RedditSnapshot | null> {
  try {
    const r = await fetch("/api/intelligence/reddit");
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

async function fetchPremarket(): Promise<PremarketSnapshot | null> {
  try {
    const r = await fetch("/api/intelligence/premarket");
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

async function fetchMarketTrend(): Promise<MarketTrendData | null> {
  try {
    const r = await fetch("/api/market/trend");
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

async function fetchNews(): Promise<NewsSnapshot | null> {
  try {
    const r = await fetch("/api/intelligence/news?limit_per_symbol=5&max_age_hours=48");
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

async function fetchEarnings(): Promise<PlaceholderFeed | null> {
  try {
    const r = await fetch("/api/intelligence/earnings");
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

async function fetchInsiders(): Promise<PlaceholderFeed | null> {
  try {
    const r = await fetch("/api/intelligence/insiders");
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

async function fetchTodayReport(): Promise<TodayReport | null> {
  try {
    const r = await fetch("/api/journal/today/report");
    if (!r.ok) return null;
    const data = await r.json();
    return data.error ? null : data;
  } catch {
    return null;
  }
}

async function fetchRuntimeConfig(): Promise<RuntimeConfigState | null> {
  try {
    const r = await fetch("/api/config/runtime");
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

async function fetchRuntimeSchema(): Promise<RuntimeConfigSchema | null> {
  try {
    const r = await fetch("/api/config/runtime/schema");
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

async function fetchReadiness(): Promise<ReadinessData | null> {
  try {
    const r = await fetch("/api/readiness/session");
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

async function adminPost(
  path: string,
  token: string
): Promise<{ ok: boolean; body: unknown }> {
  try {
    const r = await fetch(path, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = await r.json().catch(() => ({}));
    return { ok: r.ok, body };
  } catch (e) {
    return { ok: false, body: String(e) };
  }
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatBox({
  label,
  value,
  cls = "text-white",
}: {
  label: string;
  value: string;
  cls?: string;
}) {
  return (
    <div className="bg-gray-800 rounded p-3 border border-gray-700">
      <div className="text-xs text-gray-400 mb-1">{label}</div>
      <div className={`font-mono font-semibold text-sm ${cls}`}>{value}</div>
    </div>
  );
}

function PositionsTable({ positions }: { positions: Position[] }) {
  if (positions.length === 0)
    return <p className="text-gray-500 text-sm">No open positions.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm text-left">
        <thead className="text-gray-400 border-b border-gray-700">
          <tr>
            {["Symbol","Entry","Current","Shares","Cost","Unreal P&L","Catalyst","Entered"].map((h) => (
              <th key={h} className="pb-2 pr-4 font-medium whitespace-nowrap">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr key={p.position_id} className="border-b border-gray-800 hover:bg-gray-800">
              <td className="py-2 pr-4 font-semibold text-yellow-300">{p.symbol}</td>
              <td className="py-2 pr-4 font-mono">${fmt(p.entry_price, 4)}</td>
              <td className="py-2 pr-4 font-mono">${fmt(p.current_price, 4)}</td>
              <td className="py-2 pr-4 font-mono">{fmt(p.shares, 4)}</td>
              <td className="py-2 pr-4 font-mono">${fmt(p.cost_basis)}</td>
              <td className={`py-2 pr-4 font-mono ${pnlClass(p.unrealized_pnl)}`}>
                {fmtUSD(p.unrealized_pnl)} ({fmt(p.unrealized_pnl_percent)}%)
              </td>
              <td className="py-2 pr-4 text-blue-300">{p.entry_catalyst_type}</td>
              <td className="py-2 pr-4 text-gray-400 text-xs">{utcShort(p.entry_time)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TradesTable({ trades }: { trades: Trade[] }) {
  if (trades.length === 0)
    return <p className="text-gray-500 text-sm">No closed trades yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm text-left">
        <thead className="text-gray-400 border-b border-gray-700">
          <tr>
            {["Symbol","Entry","Exit","P&L","%","Reason","Hold","Catalyst","Closed"].map((h) => (
              <th key={h} className="pb-2 pr-4 font-medium whitespace-nowrap">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[...trades].reverse().map((t) => (
            <tr key={t.position_id + t.exit_time} className="border-b border-gray-800 hover:bg-gray-800">
              <td className="py-2 pr-4 font-semibold text-yellow-300">{t.symbol}</td>
              <td className="py-2 pr-4 font-mono">${fmt(t.entry_price, 4)}</td>
              <td className="py-2 pr-4 font-mono">${fmt(t.exit_price, 4)}</td>
              <td className={`py-2 pr-4 font-mono ${pnlClass(t.pnl)}`}>{fmtUSD(t.pnl)}</td>
              <td className={`py-2 pr-4 font-mono ${pnlClass(t.pnl_percent)}`}>{fmt(t.pnl_percent)}%</td>
              <td className="py-2 pr-4 text-gray-300">{t.exit_reason}</td>
              <td className="py-2 pr-4 font-mono">{t.hold_minutes}m</td>
              <td className="py-2 pr-4 text-blue-300">{t.entry_catalyst_type}</td>
              <td className="py-2 pr-4 text-gray-400 text-xs">{utcShort(t.exit_time)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function sentimentBadge(sentiment: string | null): JSX.Element {
  if (!sentiment) return <span className="text-gray-600">—</span>;
  const map: Record<string, { label: string; cls: string }> = {
    bullish:  { label: "bull", cls: "text-green-400 font-semibold" },
    bearish:  { label: "bear", cls: "text-red-400 font-semibold" },
    mixed:    { label: "mix",  cls: "text-yellow-400 font-semibold" },
    neutral:  { label: "neu",  cls: "text-gray-400" },
    unknown:  { label: "unk",  cls: "text-gray-600" },
  };
  const entry = map[sentiment] ?? { label: sentiment.slice(0, 4), cls: "text-gray-400" };
  return <span className={`font-mono text-xs ${entry.cls}`}>{entry.label}</span>;
}

function scoreColor(score: number | null, threshold: number | null): string {
  if (score == null) return "text-gray-400";
  if (threshold != null && score >= threshold) return "text-green-400";
  if (score >= 50) return "text-yellow-400";
  return "text-red-400";
}

function fmtComponents(c: ScoreComponents | null): string {
  if (!c) return "—";
  return `Qual:${c.market_quality_score} Sprd:${c.spread_score} Mom:${c.momentum_score} Vol:${c.volume_score} Cat:${c.catalyst_score} Risk:${c.risk_penalty}`;
}

function shadowDecisionBadge(decision: string | null | undefined) {
  if (!decision) return <span className="text-gray-600 text-xs">—</span>;
  if (decision === "WOULD_ENTER")
    return <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-emerald-900 text-emerald-300 border border-emerald-700">WOULD_ENTER</span>;
  if (decision === "WATCH")
    return <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-yellow-900 text-yellow-300 border border-yellow-700">WATCH</span>;
  return <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-gray-800 text-gray-500 border border-gray-700">REJECT</span>;
}

function CandidatesTable({ candidates }: { candidates: Candidate[] }) {
  if (candidates.length === 0)
    return <p className="text-gray-500 text-sm">No tick data yet. Run ⚡ Tick to see candidates.</p>;

  const missedOpps = candidates.filter(
    (c) => c.enhanced_shadow_decision === "WOULD_ENTER" && !c.eligible
  );

  return (
    <div className="overflow-x-auto">
      <p className="text-xs text-gray-600 mb-2">
        Components: Qual=Quality(max 25) · Sprd=Spread(15) · Mom=Momentum(20) · Vol=Volume(15) · Cat=Catalyst(20) · Risk=penalty(−20 max)
      </p>

      {missedOpps.length > 0 && (
        <div className="mb-3 rounded border border-emerald-800 bg-emerald-950 px-3 py-2 text-xs text-emerald-300">
          <span className="font-semibold">Shadow only — not used for trading decisions.</span>
          {" "}Enhanced shadow scores {missedOpps.length} missed opportunit{missedOpps.length === 1 ? "y" : "ies"} as{" "}
          <span className="font-bold">WOULD_ENTER</span> (engine rejected):{" "}
          {missedOpps.slice(0, 8).map((c) => (
            <span key={c.symbol} className="mr-1.5 font-mono font-semibold text-yellow-300">
              {c.symbol}({c.enhanced_shadow_score})
            </span>
          ))}
        </div>
      )}

      <table className="w-full text-sm text-left">
        <thead className="text-gray-400 border-b border-gray-700">
          <tr>
            {[
              {h:"Symbol", tip:"Ticker symbol"},
              {h:"✓", tip:"Eligible flag"},
              {h:"Mode", tip:"Entry mode"},
              {h:"Action", tip:"Engine action"},
              {h:"Score", tip:"Total score / threshold"},
              {h:"Components", tip:"Score components"},
              {h:"Earn Adj", tip:"Earnings score adjustment"},
              {h:"Ins Adj", tip:"Insider score adjustment"},
              {h:"Intel Adj", tip:"Intelligence (earnings + insider) adjustment total"},
              {h:"Mkt Trend", tip:"Market trend adjustment direction"},
              {h:"Spread%", tip:"Bid-ask spread percent"},
              {h:"Chg%", tip:"Day change percent"},
              {h:"Cats", tip:"Catalyst count"},
              {h:"Type", tip:"Catalyst type"},
              {h:"Sentiment", tip:"Catalyst sentiment"},
              {h:"Engine Decision", tip:"Real paper engine decision / rejection reason"},
              {h:"Enhanced Score", tip:"Deterministic enhanced shadow score — diagnostic only"},
              {h:"Deterministic Shadow Decision", tip:"Deterministic shadow decision — rule-based, diagnostic only, does not place trades"},
              {h:"Shadow Reason", tip:"Deterministic shadow reasoning"},
              {h:"PRE rank/gap", tip:"Premarket rank and gap percent"},
              {h:"Reddit rank/spike", tip:"Reddit mention rank and spike ratio"},
              {h:"LLM Shadow Decision", tip:"LLM shadow analyst decision — diagnostic only, does not place trades"},
              {h:"LLM Conf.", tip:"LLM confidence (0–1)"},
              {h:"LLM Action", tip:"LLM recommended action"},
              {h:"LLM Reason", tip:"LLM primary reason"},
            ].map(({h, tip}) => (
              <th key={h} title={tip} className={`pb-2 pr-2 font-medium whitespace-nowrap ${
                ["Enhanced Score","Deterministic Shadow Decision","Shadow Reason","PRE rank/gap","Reddit rank/spike"].includes(h)
                  ? "text-emerald-600"
                  : ["Earn Adj","Ins Adj","Intel Adj"].includes(h)
                  ? "text-cyan-500"
                  : h === "Mkt Trend"
                  ? "text-amber-500"
                  : ["LLM Shadow Decision","LLM Conf.","LLM Action","LLM Reason"].includes(h)
                  ? "text-purple-400"
                  : h === "Engine Decision"
                  ? "text-gray-300"
                  : ""
              }`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {candidates.map((c) => (
            <tr key={c.symbol} className={`border-b border-gray-800 hover:bg-gray-800 ${
              c.enhanced_shadow_decision === "WOULD_ENTER" && !c.eligible ? "bg-emerald-950/30" : ""
            }`}>
              <td className="py-2 pr-2 font-semibold text-yellow-300">{c.symbol}</td>
              <td className="py-2 pr-2">
                {c.eligible
                  ? <span className="text-green-400 font-bold">✓</span>
                  : <span className="text-red-400 font-bold">✗</span>}
              </td>
              <td className="py-2 pr-2 whitespace-nowrap">
                {c.entry_mode === "momentum"
                  ? <span className="text-purple-400 text-xs font-semibold px-1 rounded bg-purple-950 border border-purple-700">mom</span>
                  : c.entry_mode === "catalyst"
                  ? <span className="text-blue-400 text-xs font-semibold px-1 rounded bg-blue-950 border border-blue-700">cat</span>
                  : c.momentum_eligible
                  ? <span className="text-purple-600 text-xs font-mono">m?</span>
                  : <span className="text-gray-600 text-xs">—</span>}
              </td>
              <td className="py-2 pr-2 text-blue-300 whitespace-nowrap">{c.action || "—"}</td>
              <td className={`py-2 pr-2 font-mono font-semibold whitespace-nowrap ${scoreColor(c.total_score, c.score_threshold)}`}>
                {c.total_score != null ? `${c.total_score} / ${c.score_threshold ?? "?"}` : "—"}
              </td>
              <td className="py-2 pr-2 font-mono text-xs text-gray-400 whitespace-nowrap">
                {fmtComponents(c.score_components)}
              </td>
              <td className="py-2 pr-2 font-mono text-xs whitespace-nowrap" title={c.earnings_reason ?? "—"}>
                {c.earnings_score_adjustment != null && c.earnings_score_adjustment !== 0
                  ? <span className={c.earnings_score_adjustment < 0 ? "text-orange-400 font-semibold" : "text-green-400 font-semibold"}>
                      {c.earnings_score_adjustment > 0 ? "+" : ""}{c.earnings_score_adjustment}
                    </span>
                  : <span className="text-gray-600">0</span>}
                {c.earnings_blocked && <span className="ml-1 text-red-400">⛔</span>}
                {c.earnings_days_until != null && (
                  <span className="text-gray-600 ml-1">({c.earnings_days_until}d)</span>
                )}
              </td>
              <td className="py-2 pr-2 font-mono text-xs whitespace-nowrap" title={c.insider_reason ?? "—"}>
                {c.insider_score_adjustment != null && c.insider_score_adjustment !== 0
                  ? <span className={c.insider_score_adjustment > 0 ? "text-green-400 font-semibold" : "text-red-400 font-semibold"}>
                      {c.insider_score_adjustment > 0 ? "+" : ""}{c.insider_score_adjustment}
                    </span>
                  : <span className="text-gray-600">0</span>}
                {(c.insider_recent_buy_count ?? 0) > 0 && (
                  <span className="text-gray-600 ml-1">(×{c.insider_recent_buy_count})</span>
                )}
              </td>
              <td className="py-2 pr-2 font-mono text-xs font-semibold whitespace-nowrap"
                  title={`base ${c.base_score_before_intelligence_adjustments ?? "—"} → final ${c.final_score_after_intelligence_adjustments ?? "—"}`}>
                {c.intelligence_score_adjustment != null && c.intelligence_score_adjustment !== 0
                  ? <span className={c.intelligence_score_adjustment > 0 ? "text-cyan-300" : "text-cyan-500"}>
                      {c.intelligence_score_adjustment > 0 ? "+" : ""}{c.intelligence_score_adjustment}
                    </span>
                  : <span className="text-gray-600">0</span>}
              </td>
              <td className="py-2 pr-2 text-xs whitespace-nowrap"
                  title={`${c.market_trend_reason ?? "—"} · regime_used=${c.market_trend_regime_used ?? "—"} · path=${c.market_trend_path_name ?? "—"}`}>
                {c.market_trend_collecting || c.market_trend_direction === "unknown" || c.market_trend_direction == null ? (
                  <span className="text-amber-400">collecting</span>
                ) : (
                  <span className={
                    c.market_trend_direction === "improving" ? "text-green-400" :
                    c.market_trend_direction === "deteriorating" ? "text-red-400" :
                    "text-gray-400"
                  }>
                    {c.market_trend_direction}
                    {c.market_trend_adjustment != null && c.market_trend_adjustment !== 0 && (
                      <span className="ml-1 font-semibold">{c.market_trend_adjustment > 0 ? "+" : ""}{c.market_trend_adjustment}</span>
                    )}
                    {c.market_trend_regime_used && (
                      <span className="ml-1 text-gray-600">[{c.market_trend_regime_used === "trend_adjusted" ? "adj" : "raw"}]</span>
                    )}
                  </span>
                )}
              </td>
              <td className="py-2 pr-2 font-mono">{fmt(c.spread_percent, 3)}</td>
              <td className={`py-2 pr-2 font-mono ${c.change_percent != null ? pnlClass(c.change_percent) : ""}`}>
                {fmt(c.change_percent)}%
              </td>
              <td className="py-2 pr-2 font-mono">{c.catalyst_count}</td>
              <td className="py-2 pr-2 text-blue-300">{c.catalyst_type || "—"}</td>
              <td className="py-2 pr-2 whitespace-nowrap" title={
                c.catalyst_sentiment_reasons?.join("; ") ?? undefined
              }>
                {sentimentBadge(c.catalyst_sentiment)}
                {c.catalyst_materiality_score != null && (
                  <span className="text-gray-600 text-xs ml-1">{fmt(c.catalyst_materiality_score, 2)}</span>
                )}
              </td>
              <td className="py-2 pr-2 text-xs max-w-xs truncate">
                {c.catalyst_type_blocked && (
                  <span className="mr-1 px-1 py-0.5 rounded text-xs font-semibold bg-orange-900 text-orange-300">
                    BLOCKED
                  </span>
                )}
                <span className={c.catalyst_type_blocked ? "text-orange-400" : "text-gray-400"}>
                  {c.rejection_reason || c.decision_reason || "—"}
                </span>
              </td>
              {/* Shadow columns — diagnostic only, not used for trading */}
              <td className="py-2 pr-2 font-mono font-semibold text-emerald-400 whitespace-nowrap">
                {c.enhanced_shadow_score != null ? c.enhanced_shadow_score : "—"}
                {c.enhanced_shadow_confidence && (
                  <span className="ml-1 text-gray-600 text-xs">{c.enhanced_shadow_confidence[0]}</span>
                )}
              </td>
              <td className="py-2 pr-2 whitespace-nowrap">
                {shadowDecisionBadge(c.enhanced_shadow_decision)}
              </td>
              <td className="py-2 pr-2 text-xs text-gray-500 max-w-[180px] truncate" title={c.enhanced_shadow_reason ?? undefined}>
                {c.enhanced_shadow_reason || "—"}
              </td>
              <td className="py-2 pr-2 text-xs whitespace-nowrap">
                {c.premarket_rank != null
                  ? <span className="text-indigo-300">#{c.premarket_rank} {c.premarket_gap_percent != null ? `${c.premarket_gap_percent > 0 ? "+" : ""}${c.premarket_gap_percent.toFixed(1)}%` : ""}</span>
                  : <span className="text-gray-600">—</span>}
              </td>
              <td className="py-2 pr-2 text-xs whitespace-nowrap">
                {c.reddit_rank != null
                  ? <span className="text-pink-300">#{c.reddit_rank}{c.reddit_spike_ratio != null ? ` ×${c.reddit_spike_ratio.toFixed(1)}` : ""}</span>
                  : <span className="text-gray-600">—</span>}
              </td>
              {/* Phase L1: LLM Shadow Analyst columns (diagnostic only) */}
              <td className="py-2 pr-2 text-xs whitespace-nowrap" title={c.llm_summary ?? c.llm_status ?? ""}>
                {c.llm_status === "disabled" ? (
                  <span className="text-gray-600">LLM inactive</span>
                ) : c.llm_status === "missing_api_key" ? (
                  <span className="text-yellow-500">LLM key missing</span>
                ) : c.llm_status === "not_selected" ? (
                  <span className="text-gray-600">not selected</span>
                ) : c.llm_status === "error" ? (
                  <span className="text-red-400">LLM err</span>
                ) : c.llm_decision === "WOULD_ENTER" ? (
                  <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-purple-900 text-purple-200 border border-purple-700">WOULD_ENTER</span>
                ) : c.llm_decision === "WATCH" ? (
                  <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-yellow-900 text-yellow-300 border border-yellow-700">WATCH</span>
                ) : c.llm_decision === "WOULD_REJECT" ? (
                  <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-gray-800 text-gray-500 border border-gray-700">REJECT</span>
                ) : <span className="text-gray-600">—</span>}
              </td>
              <td className="py-2 pr-2 text-xs whitespace-nowrap font-mono">
                {c.llm_confidence != null ? c.llm_confidence.toFixed(2) : <span className="text-gray-600">—</span>}
              </td>
              <td className="py-2 pr-2 text-xs whitespace-nowrap text-purple-300">
                {c.llm_recommended_action ?? <span className="text-gray-600">—</span>}
              </td>
              <td className="py-2 pr-2 text-xs text-gray-400 max-w-[220px] truncate"
                  title={c.llm_primary_reason ?? c.llm_summary ?? ""}>
                {c.llm_primary_reason ?? c.llm_summary ?? <span className="text-gray-600">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-gray-700 mt-2 italic">
        Shadow only — not used for trading decisions. Enhanced score is independent of engine eligible/action/entry_mode.
      </p>
    </div>
  );
}

// ── Analytics panel ───────────────────────────────────────────────────────────

function SessionReadiness({
  analytics,
  status,
}: {
  analytics: Analytics | null;
  status: PaperStatus | undefined;
}) {
  const ms = analytics?.market_session;
  const sess = analytics?.session;
  const uni = analytics?.universe_health;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 items-center">
        <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${
          sess?.running
            ? "bg-green-900 text-green-300 border-green-700"
            : "bg-gray-800 text-gray-400 border-gray-600"
        }`}>
          Simulator: {sess?.running ? "● RUNNING" : "○ STOPPED"}
        </span>
        <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${
          ms?.is_regular_session_now
            ? "bg-blue-900 text-blue-300 border-blue-700"
            : "bg-gray-800 text-gray-500 border-gray-600"
        }`}>
          Market: {ms?.is_regular_session_now ? "● OPEN" : "○ CLOSED"}
        </span>
        <span className="text-xs text-gray-500 border border-gray-700 rounded px-2 py-0.5">
          Mode: fake-money · no broker · no real orders
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatBox label="Last Tick" value={sess?.last_tick_at ? utcShort(sess.last_tick_at) : "—"} />
        <StatBox label="Active Universe" value={uni?.active_count != null ? String(uni.active_count) : "—"} />
        <StatBox
          label="Universe Errors"
          value={String(uni?.error_count ?? 0)}
          cls={(uni?.error_count ?? 0) > 0 ? "text-yellow-400" : "text-green-400"}
        />
        <StatBox label="Market Session" value={`${ms?.regular_open ?? "—"} – ${ms?.regular_close ?? "—"} ET`} />
      </div>
      {ms?.note && <p className="text-xs text-gray-600">{ms.note}</p>}
    </div>
  );
}

function AnalyticsPanel({ analytics }: { analytics: Analytics | null }) {
  if (!analytics) return <p className="text-gray-500 text-sm">No analytics yet. Run ⚡ Tick first.</p>;

  const p = analytics.performance;
  const pnl = analytics.pnl;
  const funnel = analytics.candidate_funnel;
  const dist = analytics.score_distribution;

  return (
    <div className="space-y-6">

      {/* P&L */}
      <div>
        <h3 className="text-sm font-semibold text-gray-300 mb-2">P&L</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <StatBox label="Total P&L" value={fmtUSD(pnl.total_pnl)} cls={pnlClass(pnl.total_pnl)} />
          <StatBox label="Total P&L %" value={`${fmt(pnl.total_pnl_percent)}%`} cls={pnlClass(pnl.total_pnl)} />
          <StatBox label="Realized" value={fmtUSD(pnl.realized_pnl)} cls={pnlClass(pnl.realized_pnl)} />
          <StatBox label="Unrealized" value={fmtUSD(pnl.unrealized_pnl)} cls={pnlClass(pnl.unrealized_pnl)} />
          <StatBox label="Best Trade" value={pnl.best_trade_pnl != null ? fmtUSD(pnl.best_trade_pnl) : "—"} cls={pnl.best_trade_pnl != null ? pnlClass(pnl.best_trade_pnl) : ""} />
          <StatBox label="Worst Trade" value={pnl.worst_trade_pnl != null ? fmtUSD(pnl.worst_trade_pnl) : "—"} cls={pnl.worst_trade_pnl != null ? pnlClass(pnl.worst_trade_pnl) : ""} />
        </div>
      </div>

      {/* Performance */}
      <div>
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Performance</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
          <StatBox label="Wins" value={String(p.wins)} cls="text-green-400" />
          <StatBox label="Losses" value={String(p.losses)} cls="text-red-400" />
          <StatBox label="Breakeven" value={String(p.breakeven)} />
          <StatBox label="Win Rate" value={p.win_rate_percent != null ? `${fmt(p.win_rate_percent)}%` : "—"} cls={p.win_rate_percent != null ? (p.win_rate_percent >= 50 ? "text-green-400" : "text-yellow-400") : ""} />
          <StatBox label="Avg Win" value={p.average_win != null ? fmtUSD(p.average_win) : "—"} cls="text-green-400" />
          <StatBox label="Avg Loss" value={p.average_loss != null ? fmtUSD(p.average_loss) : "—"} cls="text-red-400" />
          <StatBox label="Profit Factor" value={p.profit_factor != null ? fmt(p.profit_factor) : "—"} cls={p.profit_factor != null ? (p.profit_factor >= 1 ? "text-green-400" : "text-red-400") : ""} />
          <StatBox label="Avg Hold" value={p.average_hold_minutes != null ? `${fmt(p.average_hold_minutes)}m` : "—"} />
        </div>
      </div>

      {/* Candidate funnel */}
      <div>
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Candidate Funnel (last tick)</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
          <StatBox label="Total" value={String(funnel.total_candidates)} />
          <StatBox label="Eligible" value={String(funnel.eligible)} cls="text-green-400" />
          <StatBox label="Entered" value={String(funnel.entered)} cls="text-blue-400" />
          <StatBox label="Score Rejected" value={String(funnel.score_rejected)} cls="text-yellow-400" />
          <StatBox label="Hard Rejected" value={String(funnel.hard_rejected)} cls="text-red-400" />
          <StatBox label="Blocked" value={String(funnel.blocked)} cls="text-gray-400" />
          <StatBox label="Entry Failed" value={String(funnel.entry_failed)} cls="text-orange-400" />
        </div>
      </div>

      {/* Score distribution */}
      <div>
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Score Distribution (last tick)</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <StatBox label="Above Threshold" value={String(dist.above_threshold)} cls="text-green-400" />
          <StatBox label="Score 80+" value={String(dist.score_80_plus)} cls="text-green-400" />
          <StatBox label="Score 70–79" value={String(dist.score_70_to_79)} cls="text-yellow-400" />
          <StatBox label="Score 50–69" value={String(dist.score_50_to_69)} cls="text-orange-400" />
          <StatBox label="Below 50" value={String(dist.below_50)} cls="text-red-400" />
          <StatBox label="Avg Score" value={dist.average_score != null ? fmt(dist.average_score) : "—"} />
        </div>
      </div>

      {/* Catalyst breakdown + rejections side by side */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
        <div>
          <h3 className="text-sm font-semibold text-gray-300 mb-2">Catalyst Breakdown</h3>
          {analytics.catalysts.by_type.length === 0
            ? <p className="text-gray-500 text-xs">No catalyst data.</p>
            : (
              <table className="text-xs w-full">
                <thead><tr className="text-gray-500 border-b border-gray-700">
                  <th className="pb-1 text-left font-medium">Type</th>
                  <th className="pb-1 text-right font-medium">Count</th>
                </tr></thead>
                <tbody>
                  {analytics.catalysts.by_type.map((r) => (
                    <tr key={r.type} className="border-b border-gray-800">
                      <td className="py-1 text-blue-300">{r.type}</td>
                      <td className="py-1 text-right font-mono text-white">{r.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        </div>
        <div>
          <h3 className="text-sm font-semibold text-gray-300 mb-2">Top Rejection Reasons</h3>
          {analytics.rejections.top_rejection_reasons.length === 0
            ? <p className="text-gray-500 text-xs">No rejections recorded.</p>
            : (
              <table className="text-xs w-full">
                <thead><tr className="text-gray-500 border-b border-gray-700">
                  <th className="pb-1 text-left font-medium">Reason</th>
                  <th className="pb-1 text-right font-medium">Count</th>
                </tr></thead>
                <tbody>
                  {analytics.rejections.top_rejection_reasons.map((r, i) => (
                    <tr key={i} className="border-b border-gray-800">
                      <td className="py-1 text-gray-300 max-w-xs truncate">{r.reason}</td>
                      <td className="py-1 text-right font-mono text-white">{r.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        </div>
      </div>

      {/* Universe health */}
      <div>
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Universe Health</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-2">
          <StatBox label="Active Count" value={analytics.universe_health.active_count != null ? String(analytics.universe_health.active_count) : "—"} />
          <StatBox label="Max / Tick" value={analytics.universe_health.max_symbols_per_tick != null ? String(analytics.universe_health.max_symbols_per_tick) : "—"} />
          <StatBox label="Refresh Reason" value={analytics.universe_health.refresh_reason || "—"} />
          <StatBox label="Errors" value={String(analytics.universe_health.error_count)} cls={analytics.universe_health.error_count > 0 ? "text-yellow-400" : "text-green-400"} />
        </div>
        {analytics.universe_health.top_errors.length > 0 && (
          <ul className="text-xs font-mono text-red-400 space-y-0.5">
            {analytics.universe_health.top_errors.map((e, i) => (
              <li key={i}>{e.symbol ? `${e.symbol}: ` : ""}{e.error}</li>
            ))}
          </ul>
        )}
      </div>

    </div>
  );
}

function JournalPanel({ journal }: { journal: JournalData | null }) {
  if (!journal) {
    return <p className="text-gray-500 text-sm">Journal data unavailable.</p>;
  }

  const { status, summary, recentTicks, performance } = journal;

  return (
    <div className="space-y-6">

      {/* Status bar */}
      <div className="flex flex-wrap gap-2 items-center">
        <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${
          status.enabled && status.tables_ready
            ? "bg-green-900 text-green-300 border-green-700"
            : "bg-gray-800 text-gray-400 border-gray-600"
        }`}>
          Journal: {status.enabled && status.tables_ready ? "● ENABLED" : "○ DISABLED"}
        </span>
        <span className={`text-xs px-2 py-0.5 rounded border ${
          status.database_connected
            ? "bg-blue-900 text-blue-300 border-blue-700"
            : "bg-gray-800 text-gray-500 border-gray-600"
        }`}>
          DB: {status.database_connected ? "connected" : "not connected"}
        </span>
        {status.last_persist_ok === true && (
          <span className="text-xs px-2 py-0.5 rounded border bg-green-950 text-green-400 border-green-800">last write OK</span>
        )}
        {status.last_persist_ok === false && (
          <span className="text-xs px-2 py-0.5 rounded border bg-red-950 text-red-400 border-red-800">last write FAILED</span>
        )}
        <span className="text-xs text-gray-500 border border-gray-700 rounded px-2 py-0.5">
          retention: {status.retention_days ?? 14}d · auto-cleanup: {status.auto_cleanup_enabled ? "on" : "off"}
        </span>
        {status.last_error && (
          <span className="text-xs text-red-400 font-mono bg-red-950 px-2 py-0.5 rounded border border-red-800 truncate max-w-xs">
            ERR: {status.last_error}
          </span>
        )}
        {!status.enabled && (
          <span className="text-xs text-gray-500">
            In-memory simulation only — journal requires PostgreSQL
          </span>
        )}
      </div>

      {/* Summary stats */}
      {summary && (
        <div>
          <h3 className="text-sm font-semibold text-gray-300 mb-2">Session Summary</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
            <StatBox label="Total Ticks" value={String(summary.total_ticks)} />
            <StatBox label="Candidates" value={String(summary.total_candidates)} />
            <StatBox label="Entries" value={String(summary.total_entries)} cls="text-green-400" />
            <StatBox label="Exits" value={String(summary.total_exits)} />
            <StatBox label="Closed Trades" value={String(summary.total_closed_trades)} />
            <StatBox label="First Tick" value={summary.first_tick_at ? utcShort(summary.first_tick_at) : "—"} />
            <StatBox label="Last Tick" value={summary.last_tick_at ? utcShort(summary.last_tick_at) : "—"} />
          </div>
        </div>
      )}

      {/* Historical performance */}
      {performance && performance.total_trades > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-300 mb-2">
            Historical Performance ({performance.total_trades} closed trades)
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 mb-3">
            <StatBox label="Win Rate" value={performance.win_rate != null ? `${fmt(performance.win_rate)}%` : "—"} cls={performance.win_rate != null ? (performance.win_rate >= 50 ? "text-green-400" : "text-yellow-400") : ""} />
            <StatBox label="Avg Win" value={performance.avg_win != null ? fmtUSD(performance.avg_win) : "—"} cls="text-green-400" />
            <StatBox label="Avg Loss" value={performance.avg_loss != null ? fmtUSD(performance.avg_loss) : "—"} cls="text-red-400" />
            <StatBox label="Profit Factor" value={performance.profit_factor != null ? fmt(performance.profit_factor) : "—"} cls={performance.profit_factor != null ? (performance.profit_factor >= 1 ? "text-green-400" : "text-red-400") : ""} />
            <StatBox label="Best Trade" value={performance.best_trade != null ? fmtUSD(performance.best_trade) : "—"} cls="text-green-400" />
            <StatBox label="Worst Trade" value={performance.worst_trade != null ? fmtUSD(performance.worst_trade) : "—"} cls="text-red-400" />
          </div>
          {performance.pnl_by_catalyst_type.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-gray-500 mb-1">P&L by catalyst type</p>
                <table className="text-xs w-full">
                  <thead><tr className="text-gray-500 border-b border-gray-700">
                    <th className="pb-1 text-left font-medium">Type</th>
                    <th className="pb-1 text-right font-medium">Trades</th>
                    <th className="pb-1 text-right font-medium">P&L</th>
                  </tr></thead>
                  <tbody>
                    {performance.pnl_by_catalyst_type.map((r) => (
                      <tr key={r.type} className="border-b border-gray-800">
                        <td className="py-1 text-blue-300">{r.type}</td>
                        <td className="py-1 text-right font-mono">{r.count}</td>
                        <td className={`py-1 text-right font-mono ${pnlClass(r.total_pnl)}`}>{fmtUSD(r.total_pnl)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {performance.pnl_by_score_bucket.length > 0 && (
                <div>
                  <p className="text-xs text-gray-500 mb-1">P&L by score bucket</p>
                  <table className="text-xs w-full">
                    <thead><tr className="text-gray-500 border-b border-gray-700">
                      <th className="pb-1 text-left font-medium">Bucket</th>
                      <th className="pb-1 text-right font-medium">Trades</th>
                      <th className="pb-1 text-right font-medium">P&L</th>
                    </tr></thead>
                    <tbody>
                      {performance.pnl_by_score_bucket.map((r) => (
                        <tr key={r.bucket} className="border-b border-gray-800">
                          <td className="py-1 text-gray-300">{r.bucket}</td>
                          <td className="py-1 text-right font-mono">{r.count}</td>
                          <td className={`py-1 text-right font-mono ${pnlClass(r.total_pnl)}`}>{fmtUSD(r.total_pnl)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Recent tick history */}
      {recentTicks.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-300 mb-2">
            Recent Ticks ({recentTicks.length} shown)
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead className="text-gray-400 border-b border-gray-700">
                <tr>
                  {["Started","Symbols","Universe","Entries","Exits","Errors","Cash","P&L"].map((h) => (
                    <th key={h} className="pb-2 pr-4 font-medium whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {recentTicks.map((t) => (
                  <tr key={t.tick_id} className="border-b border-gray-800 hover:bg-gray-800">
                    <td className="py-1.5 pr-4 font-mono text-gray-400 whitespace-nowrap">{utcShort(t.started_at)}</td>
                    <td className="py-1.5 pr-4 font-mono">{t.symbols_evaluated}</td>
                    <td className="py-1.5 pr-4 font-mono">{t.universe_active_count}</td>
                    <td className={`py-1.5 pr-4 font-mono ${t.entries_made > 0 ? "text-green-400" : "text-gray-500"}`}>{t.entries_made}</td>
                    <td className="py-1.5 pr-4 font-mono">{t.exits_made}</td>
                    <td className={`py-1.5 pr-4 font-mono ${t.errors_count > 0 ? "text-yellow-400" : "text-gray-500"}`}>{t.errors_count}</td>
                    <td className="py-1.5 pr-4 font-mono">{t.account_cash != null ? `$${fmt(t.account_cash)}` : "—"}</td>
                    <td className={`py-1.5 pr-4 font-mono ${t.total_pnl != null ? pnlClass(t.total_pnl) : ""}`}>{t.total_pnl != null ? fmtUSD(t.total_pnl) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Attribution note */}
      {status.enabled && summary && summary.total_closed_trades === 0 && (
        <p className="text-xs text-blue-500 border border-blue-900 rounded px-3 py-2 bg-blue-950">
          ℹ No closed trades yet. Performance attribution by catalyst type and score bucket will appear once trades close.
        </p>
      )}

      {!summary && !recentTicks.length && status.enabled && (
        <p className="text-gray-500 text-sm">No journal data yet. Run ⚡ Tick to start logging.</p>
      )}

    </div>
  );
}

function UniverseSection({ universe }: { universe: UniverseInfo | null }) {
  if (!universe) {
    return (
      <p className="text-gray-500 text-sm">
        Universe not built yet. Run ⚡ Tick or use 🌐 Universe Refresh to populate.
      </p>
    );
  }
  const first50 = universe.active_symbols.slice(0, 50);
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatBox label="Active Symbols" value={String(universe.active_count)} />
        <StatBox label="Max / Tick" value={String(universe.max_symbols_per_tick)} />
        <StatBox label="Refresh Reason" value={universe.refresh_reason} />
        <StatBox
          label="Errors"
          value={String(universe.errors.length)}
          cls={universe.errors.length > 0 ? "text-yellow-400" : "text-green-400"}
        />
      </div>
      {universe.last_refreshed_at && (
        <p className="text-xs text-gray-500">
          Last refreshed: <span className="font-mono text-gray-400">{utcShort(universe.last_refreshed_at)}</span>
        </p>
      )}
      <div>
        <p className="text-xs text-gray-400 mb-1">
          Active symbols ({first50.length}{universe.active_count > 50 ? ` of ${universe.active_count} shown` : ""}):
        </p>
        <div className="flex flex-wrap gap-1">
          {first50.map((sym) => (
            <span key={sym} className="text-xs font-mono bg-gray-700 text-yellow-300 rounded px-1.5 py-0.5">
              {sym}
            </span>
          ))}
        </div>
      </div>
      {universe.errors.length > 0 && (
        <details className="text-xs text-gray-500">
          <summary className="cursor-pointer text-yellow-600 hover:text-yellow-400">
            {universe.errors.length} fetch error(s) — click to expand
          </summary>
          <ul className="mt-1 space-y-0.5 font-mono text-red-400">
            {universe.errors.slice(0, 10).map((e, i) => (
              <li key={i}>{e.symbol ? `${e.symbol}: ` : ""}{e.error}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

// ── Market Discovery panel ────────────────────────────────────────────────────

function MarketDiscoveryPanel({
  discovery,
  token,
  onRefresh,
}: {
  discovery: UniverseDiscovery | null;
  token: string;
  onRefresh: () => void;
}) {
  const [msg, setMsg] = useState<string | null>(null);

  async function handleRefresh() {
    if (!token) { setMsg("Paste ADMIN_API_TOKEN above first."); return; }
    setMsg("Refreshing discovery…");
    try {
      const r = await fetch("/api/paper/discovery/refresh", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await r.json().catch(() => ({}));
      if (r.ok) {
        setMsg(`Discovery refreshed — ${body.discovered_count ?? 0} symbols found.`);
        onRefresh();
      } else {
        setMsg(`Error: ${r.status}`);
      }
    } catch (e) {
      setMsg(`Network error: ${e}`);
    }
  }

  if (!discovery) {
    return (
      <p className="text-gray-500 text-sm">
        Discovery data unavailable. Run ⚡ Tick or 🌐 Universe Refresh first.
      </p>
    );
  }

  const first50 = (discovery.discovered_symbols ?? []).slice(0, 50);

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500 italic">
        Discovery expands the candidate pool only. It does not bypass quality gates,
        scoring, sentiment checks, or fake-money limits.
      </p>

      <div className="flex flex-wrap gap-2 items-center">
        <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${
          discovery.enabled
            ? "bg-blue-900 text-blue-300 border-blue-700"
            : "bg-gray-800 text-gray-400 border-gray-600"
        }`}>
          Discovery: {discovery.enabled ? "● ENABLED" : "○ DISABLED"}
        </span>
        {discovery.refresh_reason && (
          <span className="text-xs text-gray-500 border border-gray-700 rounded px-2 py-0.5">
            reason: {discovery.refresh_reason}
          </span>
        )}
        <button
          onClick={handleRefresh}
          className="px-3 py-0.5 bg-indigo-700 hover:bg-indigo-600 rounded text-xs font-semibold transition-colors"
        >
          🔍 Refresh Discovery
        </button>
        {msg && <span className="text-xs text-yellow-300 font-mono">{msg}</span>}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <StatBox label="Discovered Symbols" value={String(discovery.discovered_count)} cls="text-blue-300" />
        <StatBox label="Errors" value={String(discovery.errors.length)} cls={discovery.errors.length > 0 ? "text-yellow-400" : "text-green-400"} />
        <StatBox label="Warnings" value={String(discovery.warnings.length)} cls={discovery.warnings.length > 0 ? "text-gray-400" : "text-green-400"} />
      </div>

      {first50.length > 0 && (
        <div>
          <p className="text-xs text-gray-400 mb-1">
            Discovered symbols ({first50.length}{discovery.discovered_count > 50 ? ` of ${discovery.discovered_count} shown` : ""}):
          </p>
          <div className="flex flex-wrap gap-1">
            {first50.map((sym) => (
              <span key={sym} className="text-xs font-mono bg-indigo-900 text-indigo-300 rounded px-1.5 py-0.5">
                {sym}
              </span>
            ))}
          </div>
        </div>
      )}

      {discovery.errors.length > 0 && (
        <details className="text-xs text-gray-500">
          <summary className="cursor-pointer text-yellow-600 hover:text-yellow-400">
            {discovery.errors.length} discovery error(s) — click to expand
          </summary>
          <ul className="mt-1 space-y-0.5 font-mono text-red-400">
            {discovery.errors.map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        </details>
      )}

      {discovery.warnings.length > 0 && (
        <details className="text-xs text-gray-600">
          <summary className="cursor-pointer hover:text-gray-400">
            {discovery.warnings.length} warning(s)
          </summary>
          <ul className="mt-1 space-y-0.5 font-mono">
            {discovery.warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}

// ── Strategy settings panel ───────────────────────────────────────────────────

const STRATEGY_FIELDS: Array<{
  key: string; label: string; type: string; min?: number; max?: number; step?: number;
}> = [
  { key: "PAPER_ENTRY_SCORE_THRESHOLD",             label: "Entry Score Threshold",       type: "int",   min: 0,    max: 100 },
  { key: "PAPER_TAKE_PROFIT_PERCENT",               label: "Take Profit %",               type: "float", min: 0.05, max: 20,  step: 0.05 },
  { key: "PAPER_STOP_LOSS_PERCENT",                 label: "Stop Loss %",                 type: "float", min: 0.05, max: 20,  step: 0.05 },
  { key: "PAPER_MAX_HOLD_MINUTES",                  label: "Max Hold Minutes",            type: "int",   min: 1,    max: 390 },
  { key: "PAPER_MAX_OPEN_POSITIONS",                label: "Max Open Positions",          type: "int",   min: 1,    max: 50 },
  { key: "PAPER_MAX_TRADES_PER_DAY",                label: "Max Trades / Day",            type: "int",   min: 1,    max: 500 },
  { key: "PAPER_POSITION_SIZE_PERCENT",             label: "Position Size %",             type: "float", min: 1,    max: 100, step: 1 },
  { key: "PAPER_MIN_VOLUME_RATIO",                  label: "Min Vol Ratio (Catalyst/Standard)", type: "float", min: 0,    max: 5,   step: 0.05 },
  { key: "PAPER_BEARISH_CATALYST_REJECT_MATERIALITY", label: "Bearish Reject Materiality",type: "float", min: 0,    max: 1,   step: 0.05 },
  { key: "PAPER_MAX_SYMBOLS_PER_TICK",              label: "Max Symbols / Tick",          type: "int",   min: 1,    max: 300 },
];

const STRATEGY_BOOL_FIELDS: Array<{ key: string; label: string }> = [
  { key: "PAPER_REJECT_STRONG_BEARISH_CATALYST", label: "Reject Strong Bearish Catalyst" },
  { key: "PAPER_DYNAMIC_UNIVERSE_ENABLED",       label: "Dynamic Universe" },
  { key: "PAPER_MARKET_DISCOVERY_ENABLED",       label: "Market Discovery" },
  { key: "MARKET_REGIME_ENABLED",                label: "Market Regime Monitor" },
];

// Daily loss guard fields (Phase 2N)
const DAILY_LOSS_NUMERIC_FIELDS: Array<{
  key: string; label: string; type: string; min?: number; max?: number; step?: number;
}> = [
  { key: "PAPER_DAILY_MAX_LOSS_PERCENT", label: "Max Daily Loss %",    type: "float", min: 0.1, max: 20,        step: 0.1 },
  { key: "PAPER_DAILY_MAX_LOSS_USD",     label: "Max Daily Loss USD",  type: "float", min: 0,   max: 1_000_000, step: 1 },
];

// Momentum mode fields (Phase 2M — disabled by default, legacy fallback)
const MOMENTUM_NUMERIC_FIELDS: Array<{
  key: string; label: string; type: string; min?: number; max?: number; step?: number;
}> = [
  { key: "PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD",    label: "Momentum Score Threshold",  type: "int",   min: 0,   max: 100 },
  { key: "PAPER_MOMENTUM_MIN_CHANGE_PERCENT",       label: "Min Change %",              type: "float", min: 0,   max: 20,  step: 0.1 },
  { key: "PAPER_MOMENTUM_MIN_VOLUME_RATIO",         label: "Min Volume Ratio",          type: "float", min: 0,   max: 100, step: 0.1 },
  { key: "PAPER_MOMENTUM_MAX_SPREAD_PERCENT",       label: "Max Spread %",              type: "float", min: 0.01,max: 5,   step: 0.01 },
  { key: "PAPER_MOMENTUM_MIN_MARKET_RISK_SCORE",    label: "Min Regime Risk Score",     type: "int",   min: 0,   max: 100 },
  { key: "PAPER_MOMENTUM_POSITION_SIZE_MULTIPLIER", label: "Position Size Multiplier",  type: "float", min: 0.1, max: 1,   step: 0.05 },
  { key: "PAPER_MOMENTUM_MAX_TRADES_PER_DAY",       label: "Momentum Max Trades/Day",   type: "int",   min: 0,   max: 100 },
];

// Time-Adjusted Volume Gate fields (Phase S1-V1 — read-only display)
const TA_VOLUME_FIELDS: Array<{ key: string; label: string; type: "bool" | "float" }> = [
  { key: "PAPER_USE_TIME_ADJUSTED_VOLUME_RATIO", label: "Use Time-Adjusted Volume Ratio", type: "bool" },
  { key: "PAPER_TIME_ADJUSTED_VOLUME_RATIO_MIN", label: "TA Volume Ratio Min",            type: "float" },
  { key: "PAPER_TIME_ADJUSTED_VOLUME_MIN_FLOOR", label: "Volume Min Floor",               type: "float" },
];

// No-Catalyst Momentum Entry fields (Phase 2N/2O — read-only display, currently active path)
const MARKET_MOVER_FIELDS: Array<{ key: string; label: string; type: "bool" | "int" | "float" | "str" }> = [
  { key: "PAPER_MARKET_MOVER_ENTRY_ENABLED",                        label: "Entry Enabled",                         type: "bool" },
  { key: "PAPER_MARKET_MOVER_ALLOWED_SESSIONS",                     label: "Allowed Sessions",                      type: "str" },
  { key: "PAPER_MARKET_MOVER_TOP_RANK_MAX",                         label: "Top Rank Max",                          type: "int" },
  { key: "PAPER_MARKET_MOVER_MIN_CHANGE_PERCENT",                   label: "Min Change %",                          type: "float" },
  { key: "PAPER_MARKET_MOVER_MAX_CHANGE_PERCENT",                   label: "Max Change %",                          type: "float" },
  { key: "PAPER_MARKET_MOVER_MIN_TIME_ADJ_VOLUME_RATIO",            label: "Min TA Vol Ratio (Regular)",            type: "float" },
  { key: "PAPER_MARKET_MOVER_MIN_PREMARKET_VOLUME_VS_PREV_DAY_RATIO", label: "Min Premarket Vol vs Prev Day",       type: "float" },
  { key: "PAPER_MARKET_MOVER_MIN_DOLLAR_VOLUME",                    label: "Min Dollar Volume (Premarket Fallback)", type: "int" },
  { key: "PAPER_MARKET_MOVER_MAX_SPREAD_PERCENT",                   label: "Max Spread %",                          type: "float" },
  { key: "PAPER_MARKET_MOVER_MIN_SCORE",                            label: "Min Score",                             type: "int" },
  { key: "PAPER_MARKET_MOVER_POSITION_SIZE_MULTIPLIER",             label: "Position Size Multiplier",              type: "float" },
  { key: "PAPER_MARKET_MOVER_MAX_TRADES_PER_DAY",                   label: "Max Trades/Day",                        type: "int" },
  { key: "PAPER_MARKET_MOVER_BLOCK_IF_ANY_BEARISH",                 label: "Block If Any Bearish",                  type: "bool" },
  { key: "PAPER_MARKET_MOVER_ALLOW_RISK_OFF",                       label: "Allow Risk-Off Regime",                 type: "bool" },
];

const NO_CATALYST_FIELDS: Array<{ key: string; label: string; type: "bool" | "int" | "float" }> = [
  { key: "PAPER_NO_CATALYST_ENTRY_ENABLED",            label: "Entry Enabled",            type: "bool" },
  { key: "PAPER_NO_CATALYST_REQUIRE_RISK_ON",          label: "Require Risk-On Regime",   type: "bool" },
  { key: "PAPER_NO_CATALYST_BLOCK_IF_ANY_BEARISH",     label: "Block If Any Bearish",     type: "bool" },
  { key: "PAPER_NO_CATALYST_MIN_SCORE",                label: "Min Score",                type: "int" },
  { key: "PAPER_NO_CATALYST_MIN_MOMENTUM_SCORE",       label: "Min Momentum Score",       type: "int" },
  { key: "PAPER_NO_CATALYST_MIN_RISK_SCORE",           label: "Min Risk Score",           type: "int" },
  { key: "PAPER_NO_CATALYST_MIN_CHANGE_PERCENT",       label: "Min Change %",             type: "float" },
  { key: "PAPER_NO_CATALYST_MIN_VOLUME_RATIO",         label: "Min Vol Ratio (No-Catalyst)", type: "float" },
  { key: "PAPER_NO_CATALYST_MAX_SPREAD_PERCENT",       label: "Max Spread %",             type: "float" },
  { key: "PAPER_NO_CATALYST_POSITION_SIZE_MULTIPLIER", label: "Position Size Multiplier", type: "float" },
  { key: "PAPER_NO_CATALYST_MAX_TRADES_PER_DAY",       label: "Max Trades/Day",           type: "int" },
];

function StrategySettingsPanel({
  token,
  onRefresh,
}: {
  token: string;
  onRefresh: () => void;
}) {
  const [config, setConfig] = useState<RuntimeConfigState | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string | boolean>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);

  const loadConfig = useCallback(async () => {
    const c = await fetchRuntimeConfig();
    setConfig(c);
    if (c) {
      const init: Record<string, string | boolean> = {};
      for (const f of STRATEGY_FIELDS) {
        const v = c.effective_config[f.key];
        init[f.key] = v !== null && v !== undefined ? String(v) : "";
      }
      for (const f of STRATEGY_BOOL_FIELDS) {
        const v = c.effective_config[f.key];
        init[f.key] = typeof v === "boolean" ? v : false;
      }
      // Daily loss guard fields
      for (const f of DAILY_LOSS_NUMERIC_FIELDS) {
        const v = c.effective_config[f.key];
        init[f.key] = v !== null && v !== undefined ? String(v) : "";
      }
      const dlv = c.effective_config["PAPER_DAILY_MAX_LOSS_ENABLED"];
      init["PAPER_DAILY_MAX_LOSS_ENABLED"] = typeof dlv === "boolean" ? dlv : true;
      // Momentum fields
      for (const f of MOMENTUM_NUMERIC_FIELDS) {
        const v = c.effective_config[f.key];
        init[f.key] = v !== null && v !== undefined ? String(v) : "";
      }
      const mv = c.effective_config["PAPER_MOMENTUM_MODE_ENABLED"];
      init["PAPER_MOMENTUM_MODE_ENABLED"] = typeof mv === "boolean" ? mv : false;
      const mrv = c.effective_config["PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON"];
      init["PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON"] = typeof mrv === "boolean" ? mrv : true;
      setDrafts(init);
    }
  }, []);

  useEffect(() => { loadConfig(); }, [loadConfig]);

  async function handleSave() {
    if (!token) { setMsg("Paste ADMIN_API_TOKEN above first."); return; }
    setSaving(true);
    setMsg(null);

    const updates: Record<string, number | boolean> = {};
    for (const f of STRATEGY_FIELDS) {
      const raw = drafts[f.key] as string;
      if (raw === undefined || raw === "") continue;
      const parsed = f.type === "int" ? parseInt(raw, 10) : parseFloat(raw);
      if (!isNaN(parsed)) updates[f.key] = parsed;
    }
    for (const f of STRATEGY_BOOL_FIELDS) {
      if (f.key in drafts) updates[f.key] = drafts[f.key] as boolean;
    }
    // Daily loss guard fields
    for (const f of DAILY_LOSS_NUMERIC_FIELDS) {
      const raw = drafts[f.key] as string;
      if (raw === undefined || raw === "") continue;
      const parsed = f.type === "int" ? parseInt(raw, 10) : parseFloat(raw);
      if (!isNaN(parsed)) updates[f.key] = parsed;
    }
    if ("PAPER_DAILY_MAX_LOSS_ENABLED" in drafts)
      updates["PAPER_DAILY_MAX_LOSS_ENABLED"] = drafts["PAPER_DAILY_MAX_LOSS_ENABLED"] as boolean;
    // Momentum fields
    for (const f of MOMENTUM_NUMERIC_FIELDS) {
      const raw = drafts[f.key] as string;
      if (raw === undefined || raw === "") continue;
      const parsed = f.type === "int" ? parseInt(raw, 10) : parseFloat(raw);
      if (!isNaN(parsed)) updates[f.key] = parsed;
    }
    if ("PAPER_MOMENTUM_MODE_ENABLED" in drafts)
      updates["PAPER_MOMENTUM_MODE_ENABLED"] = drafts["PAPER_MOMENTUM_MODE_ENABLED"] as boolean;
    if ("PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON" in drafts)
      updates["PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON"] = drafts["PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON"] as boolean;

    try {
      const r = await fetch("/api/config/runtime", {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ updates, updated_by: "dashboard" }),
      });
      const body = await r.json().catch(() => ({}));
      if (r.ok) {
        setMsg("Settings saved.");
        onRefresh();
        await loadConfig();
      } else {
        const errs = body?.detail?.validation_errors;
        setMsg(errs ? `Validation errors: ${errs.join("; ")}` : `Error ${r.status}: ${JSON.stringify(body?.detail)}`);
      }
    } catch (e) {
      setMsg(`Network error: ${e}`);
    } finally {
      setSaving(false);
    }
  }

  async function handleReset() {
    if (!token) { setMsg("Paste ADMIN_API_TOKEN above first."); return; }
    setResetting(true);
    setMsg(null);
    try {
      const r = await fetch("/api/config/runtime/reset", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ updated_by: "dashboard" }),
      });
      const body = await r.json().catch(() => ({}));
      if (r.ok) {
        setMsg("Overrides cleared — base settings restored.");
        onRefresh();
        await loadConfig();
      } else {
        setMsg(`Error ${r.status}`);
      }
    } catch (e) {
      setMsg(`Network error: ${e}`);
    } finally {
      setResetting(false);
    }
  }

  if (!config) {
    return <p className="text-gray-500 text-sm">Loading strategy settings…</p>;
  }

  const overrideCount = Object.keys(config.runtime_overrides).length;
  const changedOverrideCount = Object.keys(config.runtime_overrides).filter(
    k => String(config.runtime_overrides[k]) !== String(config.base_config[k])
  ).length;
  const sameOverrideCount = overrideCount - changedOverrideCount;

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-500 italic">
        All editable settings in this panel are applied at runtime to fake-money simulation only.
        No broker, no live trading, no real orders.
        Changes take effect on the next tick and do not retroactively affect existing open positions.
      </p>
      {sameOverrideCount > 0 && (
        <p className="text-xs text-gray-500 italic">
          Note: {sameOverrideCount} stored override{sameOverrideCount > 1 ? "s" : ""} equal to base value — these do not change behavior.
        </p>
      )}

      {/* Status row */}
      <div className="flex flex-wrap gap-2 items-center text-xs">
        <span className={`font-semibold px-2 py-0.5 rounded border ${
          changedOverrideCount > 0
            ? "bg-orange-900 text-orange-300 border-orange-700"
            : "bg-gray-800 text-gray-400 border-gray-600"
        }`}>
          {changedOverrideCount > 0
            ? `${changedOverrideCount} changed override(s)${sameOverrideCount > 0 ? ` · ${sameOverrideCount} = base` : ""}`
            : overrideCount > 0
            ? `${overrideCount} stored override(s) = base (no behavior change)`
            : "No overrides — using base config"}
        </span>
        <span className={`px-2 py-0.5 rounded border ${
          config.persistent
            ? "bg-blue-900 text-blue-300 border-blue-700"
            : "bg-gray-800 text-gray-400 border-gray-600"
        }`}>
          {config.persistent ? "Persisted to DB" : "Memory-only"}
        </span>
        {config.warnings.map((w, i) => (
          <span key={i} className="text-yellow-500 font-mono">{w}</span>
        ))}
      </div>

      {/* Numeric fields */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {STRATEGY_FIELDS.map((f) => {
          const base = config.base_config[f.key];
          const override = config.runtime_overrides[f.key];
          const effective = config.effective_config[f.key];
          const hasOverride = f.key in config.runtime_overrides;
          const isChanged = hasOverride && String(override) !== String(base);
          const isSameAsBase = hasOverride && !isChanged;
          return (
            <div key={f.key} className={`bg-gray-900 rounded p-3 border ${
              isChanged ? "border-orange-700" : "border-gray-700"
            }`}>
              <label className="block text-xs text-gray-400 mb-1">{f.label}</label>
              <input
                type="number"
                min={f.min}
                max={f.max}
                step={f.step ?? (f.type === "int" ? 1 : 0.01)}
                value={drafts[f.key] as string ?? ""}
                onChange={(e) => setDrafts((d) => ({ ...d, [f.key]: e.target.value }))}
                className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm font-mono text-white focus:outline-none focus:border-blue-500"
              />
              <div className="mt-1 flex gap-3 text-xs text-gray-500 font-mono flex-wrap">
                <span>base: {base !== null && base !== undefined ? String(base) : "—"}</span>
                {isChanged && <span className="text-orange-400">override: {String(override)}</span>}
                {isSameAsBase && <span className="text-gray-600">stored same as base</span>}
                <span className={isChanged ? "text-orange-300 font-semibold" : "text-gray-400"}>
                  eff: {effective !== null && effective !== undefined ? String(effective) : "—"}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Boolean toggles */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {STRATEGY_BOOL_FIELDS.map((f) => {
          const base = config.base_config[f.key];
          const override = config.runtime_overrides[f.key];
          const hasOverride = f.key in config.runtime_overrides;
          const effective = config.effective_config[f.key];
          const isChanged = hasOverride && String(override) !== String(base);
          const isSameAsBase = hasOverride && !isChanged;
          return (
            <div key={f.key} className={`bg-gray-900 rounded p-3 border ${
              isChanged ? "border-orange-700" : "border-gray-700"
            }`}>
              <label className="block text-xs text-gray-400 mb-2">{f.label}</label>
              <button
                onClick={() => setDrafts((d) => ({ ...d, [f.key]: !(d[f.key] as boolean) }))}
                className={`w-full text-sm font-semibold py-1 rounded border transition-colors ${
                  drafts[f.key]
                    ? "bg-green-800 border-green-600 text-green-300"
                    : "bg-gray-700 border-gray-600 text-gray-400"
                }`}
              >
                {drafts[f.key] ? "ON" : "OFF"}
              </button>
              <div className="mt-1 flex gap-2 text-xs text-gray-500 font-mono flex-wrap">
                <span>base: {String(base)}</span>
                {isChanged && <span className="text-orange-400">ovr: {String(effective)}</span>}
                {isSameAsBase && <span className="text-gray-600">stored same as base</span>}
              </div>
            </div>
          );
        })}
      </div>

      {/* Daily Loss Guard section (Phase 2N) */}
      <div className="border border-red-900 rounded p-3 bg-gray-950">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-sm font-semibold text-red-300">Daily Loss Guard</span>
          <span className={`text-xs px-2 py-0.5 rounded border font-semibold ${
            drafts["PAPER_DAILY_MAX_LOSS_ENABLED"]
              ? "bg-green-900 text-green-300 border-green-700"
              : "bg-gray-800 text-gray-500 border-gray-600"
          }`}>
            {drafts["PAPER_DAILY_MAX_LOSS_ENABLED"] ? "ENABLED" : "DISABLED"}
          </span>
        </div>
        <p className="text-xs text-gray-500 italic mb-3">
          Fake-money simulation only. Blocks new entries when daily P&L falls below the threshold.
          Exits (stop-loss, take-profit, max-hold) are never blocked.
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
          {[{ key: "PAPER_DAILY_MAX_LOSS_ENABLED", label: "Guard Enabled" }].map((f) => {
            const base = config.base_config[f.key];
            const override = config.runtime_overrides[f.key];
            const hasOverride = f.key in config.runtime_overrides;
            const effective = config.effective_config[f.key];
            const isChanged = hasOverride && String(override) !== String(base);
            const isSameAsBase = hasOverride && !isChanged;
            return (
              <div key={f.key} className={`bg-gray-900 rounded p-3 border ${
                isChanged ? "border-orange-700" : "border-gray-700"
              }`}>
                <label className="block text-xs text-gray-400 mb-2">{f.label}</label>
                <button
                  onClick={() => setDrafts((d) => ({ ...d, [f.key]: !(d[f.key] as boolean) }))}
                  className={`w-full text-sm font-semibold py-1 rounded border transition-colors ${
                    drafts[f.key]
                      ? "bg-green-800 border-green-600 text-green-300"
                      : "bg-gray-700 border-gray-600 text-gray-400"
                  }`}
                >
                  {drafts[f.key] ? "ON" : "OFF"}
                </button>
                <div className="mt-1 flex gap-2 text-xs text-gray-500 font-mono flex-wrap">
                  <span>base: {String(base)}</span>
                  {isChanged && <span className="text-orange-400">ovr: {String(effective)}</span>}
                  {isSameAsBase && <span className="text-gray-600">stored same as base</span>}
                </div>
              </div>
            );
          })}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {DAILY_LOSS_NUMERIC_FIELDS.map((f) => {
            const base = config.base_config[f.key];
            const override = config.runtime_overrides[f.key];
            const effective = config.effective_config[f.key];
            const hasOverride = f.key in config.runtime_overrides;
            const isChanged = hasOverride && String(override) !== String(base);
            const isSameAsBase = hasOverride && !isChanged;
            return (
              <div key={f.key} className={`bg-gray-900 rounded p-3 border ${
                isChanged ? "border-orange-700" : "border-gray-700"
              }`}>
                <label className="block text-xs text-gray-400 mb-1">{f.label}</label>
                <input
                  type="number"
                  min={f.min}
                  max={f.max}
                  step={f.step ?? 0.1}
                  value={drafts[f.key] as string ?? ""}
                  onChange={(e) => setDrafts((d) => ({ ...d, [f.key]: e.target.value }))}
                  className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm font-mono text-white focus:outline-none focus:border-red-500"
                />
                <div className="mt-1 flex gap-3 text-xs text-gray-500 font-mono flex-wrap">
                  <span>base: {base !== null && base !== undefined ? String(base) : "—"}</span>
                  {isChanged && <span className="text-orange-400">override: {String(override)}</span>}
                  {isSameAsBase && <span className="text-gray-600">stored same as base</span>}
                  <span className={isChanged ? "text-orange-300 font-semibold" : "text-gray-400"}>
                    eff: {effective !== null && effective !== undefined ? String(effective) : "—"}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Legacy Momentum Fallback section (Phase 2M — disabled by default, separate from No-Catalyst Entry) */}
      <div className="border border-purple-800 rounded p-3 bg-gray-950">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-sm font-semibold text-purple-300">Legacy Momentum Fallback</span>
          <span className={`text-xs px-2 py-0.5 rounded border font-semibold ${
            drafts["PAPER_MOMENTUM_MODE_ENABLED"]
              ? "bg-orange-900 text-orange-300 border-orange-700"
              : "bg-gray-800 text-gray-500 border-gray-600"
          }`}>
            {drafts["PAPER_MOMENTUM_MODE_ENABLED"] ? "ENABLED (legacy)" : "DISABLED (legacy/default)"}
          </span>
        </div>
        <p className="text-xs text-gray-500 italic mb-3">
          Legacy secondary momentum fallback path. Separate from the newer No-Catalyst Momentum Entry
          settings below. Fake-money simulation only. No broker. No real orders.
        </p>
        {/* Enable toggle */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
          {[
            { key: "PAPER_MOMENTUM_MODE_ENABLED", label: "Momentum Mode Enabled" },
            { key: "PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON", label: "Require Risk-On Regime" },
          ].map((f) => {
            const base = config.base_config[f.key];
            const override = config.runtime_overrides[f.key];
            const hasOverride = f.key in config.runtime_overrides;
            const effective = config.effective_config[f.key];
            const isChanged = hasOverride && String(override) !== String(base);
            const isSameAsBase = hasOverride && !isChanged;
            return (
              <div key={f.key} className={`bg-gray-900 rounded p-3 border ${
                isChanged ? "border-orange-700" : "border-gray-700"
              }`}>
                <label className="block text-xs text-gray-400 mb-2">{f.label}</label>
                <button
                  onClick={() => setDrafts((d) => ({ ...d, [f.key]: !(d[f.key] as boolean) }))}
                  className={`w-full text-sm font-semibold py-1 rounded border transition-colors ${
                    drafts[f.key]
                      ? "bg-purple-800 border-purple-600 text-purple-300"
                      : "bg-gray-700 border-gray-600 text-gray-400"
                  }`}
                >
                  {drafts[f.key] ? "ON" : "OFF"}
                </button>
                <div className="mt-1 flex gap-2 text-xs text-gray-500 font-mono flex-wrap">
                  <span>base: {String(base)}</span>
                  {isChanged && <span className="text-orange-400">ovr: {String(effective)}</span>}
                  {isSameAsBase && <span className="text-gray-600">stored same as base</span>}
                </div>
              </div>
            );
          })}
        </div>
        {/* Numeric fields */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {MOMENTUM_NUMERIC_FIELDS.map((f) => {
            const base = config.base_config[f.key];
            const override = config.runtime_overrides[f.key];
            const effective = config.effective_config[f.key];
            const hasOverride = f.key in config.runtime_overrides;
            const isChanged = hasOverride && String(override) !== String(base);
            const isSameAsBase = hasOverride && !isChanged;
            return (
              <div key={f.key} className={`bg-gray-900 rounded p-3 border ${
                isChanged ? "border-orange-700" : "border-gray-700"
              }`}>
                <label className="block text-xs text-gray-400 mb-1">{f.label}</label>
                <input
                  type="number"
                  min={f.min}
                  max={f.max}
                  step={f.step ?? (f.type === "int" ? 1 : 0.01)}
                  value={drafts[f.key] as string ?? ""}
                  onChange={(e) => setDrafts((d) => ({ ...d, [f.key]: e.target.value }))}
                  className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm font-mono text-white focus:outline-none focus:border-purple-500"
                />
                <div className="mt-1 flex gap-3 text-xs text-gray-500 font-mono flex-wrap">
                  <span>base: {base !== null && base !== undefined ? String(base) : "—"}</span>
                  {isChanged && <span className="text-orange-400">override: {String(override)}</span>}
                  {isSameAsBase && <span className="text-gray-600">stored same as base</span>}
                  <span className={isChanged ? "text-orange-300 font-semibold" : "text-gray-400"}>
                    eff: {effective !== null && effective !== undefined ? String(effective) : "—"}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* No-Catalyst Momentum Entry panel — read-only display of currently active path */}
      {config && (() => {
        const ncChangedCount = Object.keys(config.runtime_overrides).filter(k =>
          k.startsWith("PAPER_NO_CATALYST_") && String(config.runtime_overrides[k]) !== String(config.base_config[k])
        ).length;
        const ncSameAsBaseCount = Object.keys(config.runtime_overrides).filter(k =>
          k.startsWith("PAPER_NO_CATALYST_") && String(config.runtime_overrides[k]) === String(config.base_config[k])
        ).length;
        const ncEnabled = config.effective_config["PAPER_NO_CATALYST_ENTRY_ENABLED"];
        return (
          <div className="border border-blue-800 rounded p-3 bg-gray-950">
            <div className="flex items-center gap-2 mb-2 flex-wrap">
              <span className="text-sm font-semibold text-blue-300">No-Catalyst Momentum Entry</span>
              <span className={`text-xs px-2 py-0.5 rounded border font-semibold ${
                ncEnabled
                  ? "bg-green-900 text-green-300 border-green-700"
                  : "bg-gray-800 text-gray-500 border-gray-600"
              }`}>
                {ncEnabled ? "ENABLED" : "DISABLED"}
              </span>
              {ncChangedCount > 0 && (
                <span className="text-xs px-2 py-0.5 rounded border bg-orange-900 text-orange-300 border-orange-700">
                  {ncChangedCount} changed override{ncChangedCount > 1 ? "s" : ""}
                </span>
              )}
              {ncSameAsBaseCount > 0 && (
                <span className="text-xs px-2 py-0.5 rounded border bg-gray-800 text-gray-500 border-gray-700">
                  {ncSameAsBaseCount} stored same as base
                </span>
              )}
            </div>
            <p className="text-xs text-gray-500 italic mb-3">
              This is the currently active no-catalyst entry path when PAPER_NO_CATALYST_ENTRY_ENABLED is true.
              It is separate from Legacy Momentum Fallback. Fake-money simulation only. No broker. No real orders.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {NO_CATALYST_FIELDS.map((f) => {
                const base = config.base_config[f.key];
                const override = config.runtime_overrides[f.key];
                const effective = config.effective_config[f.key];
                const hasOverride = f.key in config.runtime_overrides;
                const isChanged = hasOverride && String(override) !== String(base);
                const isSameAsBase = hasOverride && !isChanged;
                return (
                  <div key={f.key} className={`bg-gray-900 rounded p-3 border ${
                    isChanged ? "border-orange-700" : "border-gray-700"
                  }`}>
                    <div className="text-xs text-gray-400 mb-1">{f.label}</div>
                    <div className={`text-sm font-mono font-semibold ${
                      f.type === "bool"
                        ? (effective ? "text-green-400" : "text-gray-500")
                        : isChanged ? "text-orange-300" : "text-white"
                    }`}>
                      {effective !== null && effective !== undefined ? String(effective) : "—"}
                    </div>
                    <div className="mt-1 flex gap-2 text-xs text-gray-500 font-mono flex-wrap">
                      <span>base: {base !== null && base !== undefined ? String(base) : "—"}</span>
                      {isChanged && <span className="text-orange-400">override: {String(override)}</span>}
                      {isSameAsBase && <span className="text-gray-600">stored same as base</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })()}

      {/* Time-Adjusted Volume Gate section (Phase S1-V1) */}
      {config && (() => {
        const taEnabled = config.effective_config["PAPER_USE_TIME_ADJUSTED_VOLUME_RATIO"];
        return (
          <div className="border border-indigo-800 rounded p-3 bg-gray-950">
            <div className="flex items-center gap-2 mb-2 flex-wrap">
              <span className="text-sm font-semibold text-indigo-300">Time-Adjusted Volume Gate</span>
              <span className={`text-xs px-2 py-0.5 rounded border font-semibold ${
                taEnabled
                  ? "bg-indigo-900 text-indigo-300 border-indigo-700"
                  : "bg-gray-800 text-gray-500 border-gray-600"
              }`}>
                {taEnabled ? "time_adjusted" : "raw_full_day"}
              </span>
              <span className="text-xs text-gray-500">volume_gate_mode</span>
            </div>
            <p className="text-xs text-gray-500 italic mb-2">
              When enabled and in regular session (9:30–16:00 ET), the volume gate uses time-adjusted
              relative volume instead of raw full-day volume ratio. Fake-money simulation only. No broker. No real orders.
            </p>
            <p className="text-xs text-gray-600 mb-3">
              <span className="font-semibold text-gray-500">Separate gates for separate entry paths:</span>{" "}
              Catalyst/Standard path uses <span className="font-mono text-gray-400">PAPER_MIN_VOLUME_RATIO</span> (raw, default 0.8) ·
              No-Catalyst path uses <span className="font-mono text-gray-400">PAPER_NO_CATALYST_MIN_VOLUME_RATIO</span> (raw, default 1.5) ·
              Time-Adjusted gate uses <span className="font-mono text-gray-400">PAPER_TIME_ADJUSTED_VOLUME_RATIO_MIN</span> (adjusted, default 0.8, regular session only).
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {TA_VOLUME_FIELDS.map((f) => {
                const base = config.base_config[f.key];
                const override = config.runtime_overrides[f.key];
                const effective = config.effective_config[f.key];
                const hasOverride = f.key in config.runtime_overrides;
                const isChanged = hasOverride && String(override) !== String(base);
                const isSameAsBase = hasOverride && !isChanged;
                return (
                  <div key={f.key} className={`bg-gray-900 rounded p-3 border ${
                    isChanged ? "border-orange-700" : "border-gray-700"
                  }`}>
                    <div className="text-xs text-gray-400 mb-1">{f.label}</div>
                    <div className={`text-sm font-mono font-semibold ${
                      f.type === "bool"
                        ? (effective ? "text-indigo-400" : "text-gray-500")
                        : isChanged ? "text-orange-300" : "text-white"
                    }`}>
                      {effective !== null && effective !== undefined ? String(effective) : "—"}
                    </div>
                    <div className="mt-1 flex gap-2 text-xs text-gray-500 font-mono flex-wrap">
                      <span>base: {base !== null && base !== undefined ? String(base) : "—"}</span>
                      {isChanged && <span className="text-orange-400">override: {String(override)}</span>}
                      {isSameAsBase && <span className="text-gray-600">stored same as base</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })()}

      {/* Full-Market Mover Entry panel (Phase N1) */}
      {config && (() => {
        const mmChangedCount = Object.keys(config.runtime_overrides).filter(k =>
          k.startsWith("PAPER_MARKET_MOVER_") && String(config.runtime_overrides[k]) !== String(config.base_config[k])
        ).length;
        const mmSameAsBaseCount = Object.keys(config.runtime_overrides).filter(k =>
          k.startsWith("PAPER_MARKET_MOVER_") && String(config.runtime_overrides[k]) === String(config.base_config[k])
        ).length;
        const mmEnabled = config.effective_config["PAPER_MARKET_MOVER_ENTRY_ENABLED"];
        return (
          <div className="border border-purple-800 rounded p-3 bg-gray-950">
            <div className="flex items-center gap-2 mb-2 flex-wrap">
              <span className="text-sm font-semibold text-purple-300">Full-Market Mover Entry</span>
              <span className={`text-xs px-2 py-0.5 rounded border font-semibold ${
                mmEnabled
                  ? "bg-green-900 text-green-300 border-green-700"
                  : "bg-gray-800 text-gray-500 border-gray-600"
              }`}>
                {mmEnabled ? "ENABLED" : "DISABLED"}
              </span>
              {mmChangedCount > 0 && (
                <span className="text-xs px-2 py-0.5 rounded border bg-orange-900 text-orange-300 border-orange-700">
                  {mmChangedCount} changed override{mmChangedCount > 1 ? "s" : ""}
                </span>
              )}
              {mmSameAsBaseCount > 0 && (
                <span className="text-xs px-2 py-0.5 rounded border bg-gray-800 text-gray-500 border-gray-700">
                  {mmSameAsBaseCount} stored same as base
                </span>
              )}
              <span className="text-xs px-2 py-0.5 rounded border bg-yellow-900 text-yellow-300 border-yellow-700 font-semibold">
                HIGH-RISK NO-CATALYST PATH
              </span>
            </div>
            <p className="text-xs text-yellow-600 italic mb-2 font-semibold">
              High-risk no-catalyst full-market mover path — fake-money only. No live trading. No real-money execution.
            </p>
            <p className="text-xs text-gray-500 italic mb-2">
              Separate from: catalyst path · legacy momentum fallback · no-catalyst momentum entry.
              Fires only for symbols from the full-market movers scanner (source=full_market_movers)
              during premarket or regular session. Afterhours, closed, non_regular, and overnight are always blocked.
            </p>
            <p className="text-xs text-gray-600 mb-3">
              <span className="font-semibold text-gray-500">Volume gates by session:</span>{" "}
              Regular → time-adjusted ratio ≥ <span className="font-mono text-gray-400">PAPER_MARKET_MOVER_MIN_TIME_ADJ_VOLUME_RATIO</span> ·
              Premarket → <span className="font-mono text-gray-400">PAPER_MARKET_MOVER_MIN_PREMARKET_VOLUME_VS_PREV_DAY_RATIO</span>{" "}
              OR <span className="font-mono text-gray-400">PAPER_MARKET_MOVER_MIN_DOLLAR_VOLUME</span> (fallback).
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {MARKET_MOVER_FIELDS.map((f) => {
                const base = config.base_config[f.key];
                const override = config.runtime_overrides[f.key];
                const effective = config.effective_config[f.key];
                const hasOverride = f.key in config.runtime_overrides;
                const isChanged = hasOverride && String(override) !== String(base);
                const isSameAsBase = hasOverride && !isChanged;
                return (
                  <div key={f.key} className={`bg-gray-900 rounded p-3 border ${
                    isChanged ? "border-orange-700" : "border-gray-700"
                  }`}>
                    <div className="text-xs text-gray-400 mb-1">{f.label}</div>
                    <div className={`text-sm font-mono font-semibold ${
                      f.type === "bool"
                        ? (effective ? "text-indigo-400" : "text-gray-500")
                        : isChanged ? "text-orange-300" : "text-white"
                    }`}>
                      {effective !== null && effective !== undefined ? String(effective) : "—"}
                    </div>
                    <div className="mt-1 flex gap-2 text-xs text-gray-500 font-mono flex-wrap">
                      <span>base: {base !== null && base !== undefined ? String(base) : "—"}</span>
                      {isChanged && <span className="text-orange-400">override: {String(override)}</span>}
                      {isSameAsBase && <span className="text-gray-600">stored same as base</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })()}

      {/* Action buttons */}
      <div className="flex flex-wrap gap-3 items-center mt-2">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 text-white text-sm font-semibold rounded border border-blue-500"
        >
          {saving ? "Saving…" : "Save Settings"}
        </button>
        <button
          onClick={handleReset}
          disabled={resetting || overrideCount === 0}
          className="px-4 py-1.5 bg-gray-700 hover:bg-gray-600 disabled:opacity-40 text-white text-sm font-semibold rounded border border-gray-500"
        >
          {resetting ? "Resetting…" : "Reset to Base"}
        </button>
        {msg && (
          <span className={`text-sm font-mono ${
            msg.startsWith("Error") || msg.startsWith("Validation") || msg.startsWith("Network")
              ? "text-red-400" : "text-green-400"
          }`}>{msg}</span>
        )}
      </div>
    </div>
  );
}

// ── Market regime panel ───────────────────────────────────────────────────────

function regimeColor(regime: string | null | undefined): string {
  if (regime === "risk_on") return "text-green-400";
  if (regime === "risk_off") return "text-red-400";
  if (regime === "neutral") return "text-yellow-400";
  return "text-gray-400";
}

function regimeBadgeClass(regime: string | null | undefined): string {
  if (regime === "risk_on") return "bg-green-900 text-green-300 border-green-700";
  if (regime === "risk_off") return "bg-red-900 text-red-300 border-red-700";
  if (regime === "neutral") return "bg-yellow-900 text-yellow-300 border-yellow-700";
  return "bg-gray-800 text-gray-400 border-gray-600";
}

function MarketTrendPanel({ trend }: { trend: MarketTrendData | null }) {
  if (!trend) {
    return <p className="text-gray-500 text-sm">Market trend data unavailable.</p>;
  }
  const dirColor =
    trend.trend_direction === "improving" ? "bg-green-900 text-green-300 border-green-700" :
    trend.trend_direction === "deteriorating" ? "bg-red-900 text-red-300 border-red-700" :
    trend.trend_direction === "flat" ? "bg-gray-800 text-gray-300 border-gray-600" :
    "bg-gray-900 text-gray-500 border-gray-700";
  const strengthColor =
    trend.trend_strength === "strong" ? "text-orange-300" :
    trend.trend_strength === "moderate" ? "text-yellow-300" :
    trend.trend_strength === "weak" ? "text-gray-300" : "text-gray-500";
  const adj = trend.market_trend_adjustment;
  const adjStr = adj === 0 ? "0" : `${adj > 0 ? "+" : ""}${adj}`;
  const adjColor = adj > 0 ? "text-green-400" : adj < 0 ? "text-red-400" : "text-gray-400";
  const before = trend.market_regime_score_before_trend;
  const after = trend.market_regime_score_after_trend;

  return (
    <div className="space-y-4">
      <div className="rounded border border-blue-900 bg-blue-950 px-3 py-2 text-xs text-blue-300">
        <span className="font-semibold">Source: ETF proxy.</span>{" "}
        True Nasdaq/SPX futures are not configured/available in this phase — using QQQ / SPY / IWM.
        Trend alone does not create entries and does not affect exits. Used as risk-on adjustment for
        no-catalyst momentum and market-mover gates.
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${dirColor}`}>
          Direction: {trend.trend_direction.toUpperCase()}
        </span>
        <span className={`text-xs font-semibold px-2 py-0.5 rounded border bg-gray-800 border-gray-600 ${strengthColor}`}>
          Strength: {trend.trend_strength}
        </span>
        <span className={`text-xs font-semibold px-2 py-0.5 rounded border bg-gray-800 border-gray-600 ${adjColor}`}>
          Adjustment: {adjStr}
        </span>
        <span className="text-xs text-gray-400 border border-gray-700 rounded px-2 py-0.5">
          Snapshots: {trend.snapshot_count} (interval {trend.snapshot_interval_seconds}s, history {trend.history_minutes}m)
        </span>
        <span className="text-xs text-gray-500 border border-gray-700 rounded px-2 py-0.5">
          Provider: {trend.provider_status} · futures_available: {String(trend.futures_available)}
        </span>
        <span className="text-xs border border-gray-700 rounded px-2 py-0.5">
          Windows: 5m {trend.has_5m_window ? "✓" : "—"} · 10m {trend.has_10m_window ? "✓" : "—"} · 15m {trend.has_15m_window ? "✓" : "—"}
        </span>
        {trend.collecting && (
          <span className="text-xs font-semibold px-2 py-0.5 rounded border bg-amber-950 text-amber-300 border-amber-700">
            COLLECTING
          </span>
        )}
      </div>

      {/* Consumer config (Phase M1-H1) */}
      {trend.trend_consumers && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="font-semibold text-gray-300">Consumers:</span>
          {Object.entries(trend.trend_consumers).map(([path, on]) => (
            <span
              key={path}
              className={`px-2 py-0.5 rounded border font-mono ${
                on
                  ? "bg-cyan-950 text-cyan-300 border-cyan-800"
                  : "bg-gray-800 text-gray-500 border-gray-700"
              }`}
            >
              {path}: {on ? "trend_adjusted" : "raw"}
            </span>
          ))}
        </div>
      )}

      {/* Raw vs adjusted regime label */}
      {(trend.raw_regime_label || trend.adjusted_regime_label) && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-gray-400">
          <span>Raw regime: <span className="font-mono text-gray-300">{trend.raw_regime_label ?? "—"}</span></span>
          <span>·</span>
          <span>Adjusted regime: <span className="font-mono text-gray-300">{trend.adjusted_regime_label ?? "—"}</span></span>
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatBox label="Score (raw)" value={before != null ? String(before) : "—"} />
        <StatBox label="Score (trend-adjusted)" value={after != null ? String(after) : "—"} cls={
          after != null && before != null && after > before ? "text-green-400" :
          after != null && before != null && after < before ? "text-red-400" : ""
        } />
        <StatBox label="Primary symbols" value={(trend.primary_symbols || []).join(", ") || "—"} />
        <StatBox label="Optional proxies" value={(trend.optional_proxy_symbols || []).join(", ") || "—"} />
      </div>

      {(trend.snapshot_count ?? 0) >= 1 ? (
        <div>
          <h3 className="text-sm font-semibold text-gray-300 mb-2">Rolling deltas</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-400 border-b border-gray-700">
                  <th className="pb-2 pr-2 text-left whitespace-nowrap">Window</th>
                  <th className="pb-2 pr-2 text-right whitespace-nowrap">Risk Δ</th>
                  <th className="pb-2 pr-2 text-right whitespace-nowrap">QQQ Δ%</th>
                  <th className="pb-2 pr-2 text-right whitespace-nowrap">SPY Δ%</th>
                  <th className="pb-2 pr-2 text-right whitespace-nowrap">IWM Δ%</th>
                  <th className="pb-2 pr-2 text-left whitespace-nowrap">Snapshot as_of</th>
                </tr>
              </thead>
              <tbody>
                {(trend.windows_minutes || [5, 10, 15]).map((w) => {
                  const d = trend.deltas?.[`${w}m`];
                  const fmtDelta = (v: number | null | undefined) => {
                    if (v == null) return "—";
                    const cls = v > 0 ? "text-green-400" : v < 0 ? "text-red-400" : "text-gray-400";
                    return <span className={cls}>{v > 0 ? "+" : ""}{v}</span>;
                  };
                  return (
                    <tr key={w} className="border-b border-gray-800">
                      <td className="py-1.5 pr-2 font-mono text-xs">{w}m</td>
                      <td className="py-1.5 pr-2 font-mono text-xs text-right">{fmtDelta(d?.risk_on_score_delta as number | null | undefined)}</td>
                      <td className="py-1.5 pr-2 font-mono text-xs text-right">{fmtDelta(d?.qqq_delta as number | null | undefined)}</td>
                      <td className="py-1.5 pr-2 font-mono text-xs text-right">{fmtDelta(d?.spy_delta as number | null | undefined)}</td>
                      <td className="py-1.5 pr-2 font-mono text-xs text-right">{fmtDelta(d?.iwm_delta as number | null | undefined)}</td>
                      <td className="py-1.5 pr-2 font-mono text-xs text-gray-500">{d?.ago_snapshot_as_of ? String(d.ago_snapshot_as_of).slice(0, 19) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      <p className="text-xs text-gray-500 italic">
        Reason: {trend.market_trend_reason}
      </p>
      {(trend.warnings ?? []).map((w, i) => (
        <p key={i} className="text-xs text-yellow-500">⚠ {w}</p>
      ))}
      {trend.as_of && (
        <p className="text-xs text-gray-600">As of: <span className="font-mono">{utcShort(trend.as_of)}</span></p>
      )}
    </div>
  );
}

function MarketRegimePanel({ regime }: { regime: MarketRegimeData | null }) {
  // Show panel if data is present (enabled flag OR risk object exists)
  const hasData = regime && (regime.enabled === true || regime.risk != null);
  if (!hasData) {
    const reason = !regime
      ? "No data returned from dashboard."
      : regime.error
      ? `Error: ${regime.error}`
      : "Market regime monitor disabled by configuration (MARKET_REGIME_ENABLED=False).";
    return <p className="text-gray-500 text-sm">{reason}</p>;
  }

  const { breadth, leaders, risk, as_of, symbols_fetched, symbols_failed, fetch_ratio, error } = regime;
  const warnings = risk?.warnings ?? [];

  return (
    <div className="space-y-4">
      {/* Status badges */}
      <div className="flex flex-wrap gap-2 items-center">
        <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${regimeBadgeClass(risk?.regime)}`}>
          Regime: {risk?.regime ? risk.regime.replace(/_/g, " ").toUpperCase() : "UNKNOWN"}
        </span>
        {risk?.risk_on_score != null && (
          <span className={`text-xs font-semibold px-2 py-0.5 rounded border bg-gray-800 border-gray-600 ${regimeColor(risk.regime)}`}>
            Risk-on score: {risk.risk_on_score} / 100
          </span>
        )}
        <span className={`text-xs px-2 py-0.5 rounded border ${
          risk?.confidence === "high" ? "bg-green-950 text-green-400 border-green-800" :
          risk?.confidence === "medium" ? "bg-yellow-950 text-yellow-400 border-yellow-800" :
          "bg-gray-800 text-gray-500 border-gray-600"
        }`}>
          Confidence: {risk?.confidence ?? "—"}
        </span>
        <span className="text-xs text-gray-500 border border-gray-700 rounded px-2 py-0.5">
          {symbols_fetched?.length ?? 0} fetched
          {(symbols_failed?.length ?? 0) > 0 && (
            <span className="text-red-400"> · {symbols_failed!.length} failed</span>
          )}
          {fetch_ratio != null && (
            <span className="text-gray-600"> · {Math.round(fetch_ratio * 100)}% ratio</span>
          )}
        </span>
        {error && (
          <span className="text-xs text-red-400 font-mono bg-red-950 px-2 py-0.5 rounded border border-red-800 truncate max-w-xs">
            ERR: {error}
          </span>
        )}
      </div>

      {/* Warnings from scoring */}
      {warnings.length > 0 && (
        <div className="space-y-1">
          {warnings.map((w, i) => (
            <p key={i} className="text-xs text-yellow-500">{w}</p>
          ))}
        </div>
      )}

      {/* Breadth stats */}
      {breadth && breadth.total > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-300 mb-2">Market Breadth</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
            <StatBox label="Total Symbols" value={String(breadth.total)} />
            <StatBox label="Positive" value={String(breadth.positive)} cls="text-green-400" />
            <StatBox label="Negative" value={String(breadth.negative)} cls="text-red-400" />
            <StatBox label="Flat" value={String(breadth.flat)} cls="text-gray-400" />
            <StatBox
              label="Positive %"
              value={breadth.positive_percent != null ? `${breadth.positive_percent}%` : "—"}
              cls={
                breadth.positive_percent != null
                  ? breadth.positive_percent >= 60 ? "text-green-400"
                  : breadth.positive_percent >= 40 ? "text-yellow-400"
                  : "text-red-400"
                  : ""
              }
            />
            <StatBox
              label="Avg Change"
              value={breadth.avg_change_percent != null ? `${fmt(breadth.avg_change_percent)}%` : "—"}
              cls={breadth.avg_change_percent != null ? pnlClass(breadth.avg_change_percent) : ""}
            />
          </div>
        </div>
      )}

      {/* Leaders */}
      {leaders && (
        <div>
          <h3 className="text-sm font-semibold text-gray-300 mb-2">Key Leaders</h3>
          <div className="grid grid-cols-3 sm:grid-cols-5 gap-3">
            {(["SPY", "QQQ", "IWM"] as const).map((sym) => {
              const d = leaders.data?.[sym];
              return (
                <div key={sym} className="bg-gray-800 rounded p-3 border border-gray-700">
                  <div className="text-xs text-gray-400 mb-1">{sym}</div>
                  {d ? (
                    <>
                      <div className={`font-mono font-semibold text-sm ${d.change_percent != null ? pnlClass(d.change_percent) : "text-gray-400"}`}>
                        {d.change_percent != null ? `${d.change_percent > 0 ? "+" : ""}${fmt(d.change_percent)}%` : "—"}
                      </div>
                      {d.last_trade_price != null && (
                        <div className="text-xs text-gray-500 font-mono mt-0.5">${fmt(d.last_trade_price, 2)}</div>
                      )}
                    </>
                  ) : (
                    <div className="font-mono text-sm text-gray-600">—</div>
                  )}
                </div>
              );
            })}
            <StatBox label="Bullish Leaders" value={String(leaders.bullish_count)} cls="text-green-400" />
            <StatBox label="Bearish Leaders" value={String(leaders.bearish_count)} cls="text-red-400" />
          </div>
        </div>
      )}

      {/* Usage note */}
      <div className="rounded border border-gray-700 bg-gray-900 px-3 py-2 text-xs text-gray-400">
        <span className="font-semibold text-gray-300">Used by selected entry gates: </span>
        no-catalyst momentum risk-on requirement · market-mover risk-off allow/block · shadow/diagnostic scoring context.
        <span className="text-gray-600"> Not a broker or live-trading control.</span>
      </div>

      {as_of && (
        <p className="text-xs text-gray-600">
          As of: <span className="font-mono text-gray-500">{utcShort(as_of)}</span>
          {regime.disclaimer && (
            <>{" · "}<span className="italic">{regime.disclaimer}</span></>
          )}
        </p>
      )}
    </div>
  );
}

// ── Readiness panel ───────────────────────────────────────────────────────────

function readinessBadge(status: ReadinessData["overall_status"] | null): JSX.Element {
  if (status === "ready")
    return <span className="text-xs font-semibold px-2 py-0.5 rounded border bg-green-900 text-green-300 border-green-700">● READY</span>;
  if (status === "warning")
    return <span className="text-xs font-semibold px-2 py-0.5 rounded border bg-yellow-900 text-yellow-300 border-yellow-700">⚠ WARNING</span>;
  if (status === "not_ready")
    return <span className="text-xs font-semibold px-2 py-0.5 rounded border bg-red-900 text-red-300 border-red-700">✗ NOT READY</span>;
  return <span className="text-xs px-2 py-0.5 rounded border bg-gray-800 text-gray-500 border-gray-600">—</span>;
}

function checkStatusIcon(status: ReadinessCheck["status"]): string {
  if (status === "pass") return "✓";
  if (status === "warn") return "⚠";
  return "✗";
}

function checkStatusClass(status: ReadinessCheck["status"]): string {
  if (status === "pass") return "text-green-400";
  if (status === "warn") return "text-yellow-400";
  return "text-red-400";
}

function ReadinessPanel({ readiness, config }: { readiness: ReadinessData | null; config?: RuntimeConfigState | null }) {
  const [rcOpen, setRcOpen] = useState(false);
  const [rcPinned, setRcPinned] = useState(false);

  if (!readiness)
    return <p className="text-gray-500 text-sm">Readiness data unavailable.</p>;

  const { overall_status, checks, summary, recommended_actions } = readiness;

  const rcChangedKeys = config
    ? Object.keys(config.runtime_overrides).filter(k => isOverrideChanged(k, config.runtime_overrides, config.base_config))
    : [];
  const rcSameKeys = config
    ? Object.keys(config.runtime_overrides).filter(k => !isOverrideChanged(k, config.runtime_overrides, config.base_config))
    : [];

  function rcCardMsg(c: ReadinessCheck): string {
    if (c.name !== "runtime_config") return c.message;
    if (!config) return "Runtime config: loading…";
    const parts: string[] = [];
    if (rcChangedKeys.length > 0) parts.push(`${rcChangedKeys.length} changed`);
    if (rcSameKeys.length > 0) parts.push(`${rcSameKeys.length} stored same as base`);
    return `Runtime config: ${parts.length > 0 ? parts.join(", ") : "no overrides"}`;
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-500 italic">
        Readiness is operational guidance for fake-money simulation monitoring only.
        It does not enable broker trading or real orders.
      </p>

      {/* Overall status row */}
      <div className="flex flex-wrap gap-3 items-center">
        {readinessBadge(overall_status)}
        <span className="text-xs text-gray-400 font-mono">
          {summary.pass}✓ {summary.warn}⚠ {summary.fail}✗
        </span>
        <span className="text-xs text-gray-600 border border-gray-700 rounded px-2 py-0.5">
          as of {readiness.as_of ? new Date(readiness.as_of).toUTCString().replace(" GMT", " UTC") : "—"}
        </span>
      </div>

      {/* Check list */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
        {checks.map((c) => {
          const isRcCheck = c.name === "runtime_config";
          const showPopover = isRcCheck && (rcOpen || rcPinned);
          return (
            <div
              key={c.name}
              className={`rounded border px-3 py-2 text-xs relative overflow-visible ${isRcCheck ? "cursor-pointer select-none" : ""} ${
                c.status === "pass"
                  ? "bg-gray-900 border-gray-700"
                  : c.status === "warn"
                  ? "bg-yellow-950 border-yellow-800"
                  : "bg-red-950 border-red-800"
              }`}
              onMouseEnter={isRcCheck ? () => setRcOpen(true) : undefined}
              onMouseLeave={isRcCheck ? () => { if (!rcPinned) setRcOpen(false); } : undefined}
              onClick={isRcCheck ? () => { const next = !rcPinned; setRcPinned(next); setRcOpen(next); } : undefined}
            >
              <div className="flex items-center gap-1.5 mb-0.5">
                <span className={`font-bold ${checkStatusClass(c.status)}`}>
                  {checkStatusIcon(c.status)}
                </span>
                <span className="font-mono text-gray-300 font-semibold">{c.name}</span>
                {isRcCheck && (
                  <span className={`ml-auto text-xs leading-none ${rcPinned ? "text-blue-400" : "text-gray-500"}`}>
                    {rcPinned ? "📌" : "ⓘ"}
                  </span>
                )}
              </div>
              <p className="text-gray-400 leading-snug">{rcCardMsg(c)}</p>

              {/* Runtime config popover — React-state controlled, z-[9999] to avoid clipping */}
              {showPopover && (
                <div
                  className="absolute z-[9999] left-0 top-full mt-1 w-96 bg-gray-900 border border-gray-500 rounded-lg shadow-2xl p-3 text-xs"
                  onClick={(e) => e.stopPropagation()}
                  onMouseEnter={() => setRcOpen(true)}
                  onMouseLeave={() => { if (!rcPinned) setRcOpen(false); }}
                >
                  <div className="flex items-center justify-between mb-2 pb-1 border-b border-gray-700">
                    <span className="font-semibold text-gray-200">Runtime Overrides</span>
                    <button
                      className="text-gray-500 hover:text-gray-200 text-xs px-1 rounded"
                      onClick={(e) => { e.stopPropagation(); setRcPinned(false); setRcOpen(false); }}
                    >
                      ✕ close
                    </button>
                  </div>
                  <div className="max-h-64 overflow-y-auto space-y-2">
                    {!config && (
                      <p className="text-gray-500 italic py-1">Loading runtime config…</p>
                    )}
                    {config && rcChangedKeys.length === 0 && rcSameKeys.length === 0 && (
                      <p className="text-gray-500 italic py-1">No runtime overrides.</p>
                    )}
                    {config && rcChangedKeys.length > 0 && (
                      <div>
                        <p className="font-semibold text-orange-400 mb-1 uppercase tracking-wide">
                          Changed overrides ({rcChangedKeys.length})
                        </p>
                        <div className="space-y-1">
                          {rcChangedKeys.map(k => (
                            <div key={k} className="bg-gray-800 rounded px-2 py-1.5 border border-orange-900">
                              <div className="font-mono text-orange-300 break-all mb-0.5">{k}</div>
                              <div className="flex flex-wrap gap-x-3 text-gray-400 font-mono">
                                <span>base: {normalizeConfigValue(config.base_config[k])}</span>
                                <span className="text-orange-400">ovr: {normalizeConfigValue(config.runtime_overrides[k])}</span>
                                <span className="text-orange-300 font-semibold">eff: {normalizeConfigValue(config.effective_config[k])}</span>
                                <span className="text-gray-600">[{getFieldCategory(k)}]</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {config && rcSameKeys.length > 0 && (
                      <div>
                        <p className="font-semibold text-gray-500 mb-1 uppercase tracking-wide">
                          Stored same as base ({rcSameKeys.length}) — no behavior change
                        </p>
                        <div className="space-y-1">
                          {rcSameKeys.map(k => (
                            <div key={k} className="bg-gray-800 rounded px-2 py-1.5 border border-gray-700">
                              <div className="font-mono text-gray-500 break-all mb-0.5">{k}</div>
                              <div className="flex flex-wrap gap-x-3 text-gray-600 font-mono">
                                <span>value: {normalizeConfigValue(config.base_config[k])}</span>
                                <span>[{getFieldCategory(k)}]</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Recommended actions */}
      {recommended_actions.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-semibold text-gray-400">Recommended actions:</p>
          {recommended_actions.map((a, i) => (
            <div key={i} className="text-xs text-yellow-300 bg-yellow-950 border border-yellow-800 rounded px-3 py-1.5">
              ▶ {a}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Monitoring panel ──────────────────────────────────────────────────────────

function MonitoringPanel({ monitoring }: { monitoring: MonitoringStatus | null }) {
  if (!monitoring) return <p className="text-gray-500 text-sm">Monitoring data unavailable.</p>;

  const {
    backend_ok, paper_running, journal_enabled, journal_database_connected,
    journal_tables_ready, last_tick_at, last_tick_age_seconds, last_tick_fresh,
    last_journal_ok, last_error, market_session, warnings,
  } = monitoring;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 items-center">
        <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${
          backend_ok ? "bg-green-900 text-green-300 border-green-700" : "bg-red-900 text-red-300 border-red-700"
        }`}>
          Backend: {backend_ok ? "● OK" : "✗ DOWN"}
        </span>
        <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${
          paper_running ? "bg-green-900 text-green-300 border-green-700" : "bg-gray-800 text-gray-400 border-gray-600"
        }`}>
          Simulator: {paper_running ? "● RUNNING" : "○ STOPPED"}
        </span>
        <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${
          market_session.is_regular_session_now
            ? "bg-blue-900 text-blue-300 border-blue-700"
            : "bg-gray-800 text-gray-500 border-gray-600"
        }`}>
          Market: {market_session.is_regular_session_now ? "● OPEN" : "○ CLOSED"}
        </span>
        <span className={`text-xs px-2 py-0.5 rounded border ${
          journal_enabled && journal_tables_ready
            ? "bg-green-900 text-green-300 border-green-700"
            : "bg-gray-800 text-gray-400 border-gray-600"
        }`}>
          Journal: {journal_enabled && journal_tables_ready ? "● enabled" : "○ disabled"}
        </span>
        <span className={`text-xs px-2 py-0.5 rounded border ${
          journal_database_connected
            ? "bg-blue-900 text-blue-300 border-blue-700"
            : "bg-gray-800 text-gray-500 border-gray-600"
        }`}>
          DB: {journal_database_connected ? "connected" : "not connected"}
        </span>
        {last_journal_ok === true && (
          <span className="text-xs px-2 py-0.5 rounded border bg-green-950 text-green-400 border-green-800">last write OK</span>
        )}
        {last_journal_ok === false && (
          <span className="text-xs px-2 py-0.5 rounded border bg-red-950 text-red-400 border-red-800">last write FAILED</span>
        )}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatBox label="Last Tick" value={last_tick_at ? utcShort(last_tick_at) : "—"} />
        <StatBox
          label="Tick Age"
          value={last_tick_age_seconds != null ? `${last_tick_age_seconds}s` : "—"}
          cls={last_tick_fresh ? "text-green-400" : "text-red-400"}
        />
        <StatBox
          label="Tick Fresh"
          value={last_tick_fresh ? "● fresh" : "✗ stale"}
          cls={last_tick_fresh ? "text-green-400" : "text-red-400"}
        />
        <StatBox label="Session Hours" value={`${market_session.regular_open} – ${market_session.regular_close} ET`} />
      </div>

      {last_error && (
        <div className="text-xs font-mono text-red-400 bg-red-950 border border-red-800 rounded px-3 py-2 truncate">
          ERR: {last_error}
        </div>
      )}

      {warnings.length > 0 && (
        <div className="space-y-1">
          {warnings.map((w, i) => (
            <div key={i} className="text-xs text-yellow-300 bg-yellow-950 border border-yellow-800 rounded px-3 py-1.5">
              ⚠ {w}
            </div>
          ))}
        </div>
      )}

      {market_session.note && <p className="text-xs text-gray-600">{market_session.note}</p>}
    </div>
  );
}

// ── Today / Session report panel ──────────────────────────────────────────────

function TodayReportPanel({ report }: { report: TodayReport | null }) {
  if (!report) {
    return (
      <p className="text-gray-500 text-sm">
        Today&apos;s report unavailable — journal may be disabled or no data yet.
      </p>
    );
  }

  const { summary, top_rejections, catalysts, symbols, latest_ticks } = report;

  return (
    <div className="space-y-6">

      {/* Summary */}
      <div>
        <div className="flex items-center gap-3 mb-2">
          <h3 className="text-sm font-semibold text-gray-300">Today — {summary.trading_date}</h3>
          <span className={`text-xs px-2 py-0.5 rounded border ${
            summary.journal_healthy
              ? "bg-green-900 text-green-300 border-green-700"
              : "bg-yellow-900 text-yellow-300 border-yellow-700"
          }`}>
            {summary.journal_healthy ? "● healthy" : "⚠ degraded"}
          </span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
          <StatBox label="Ticks Today" value={String(summary.total_ticks_today)} />
          <StatBox label="Candidates" value={String(summary.total_candidates_today)} />
          <StatBox label="Entries" value={String(summary.total_entries_today)} cls="text-green-400" />
          <StatBox label="Exits" value={String(summary.total_exits_today)} />
          <StatBox label="Uniq Symbols" value={String(summary.unique_symbols_seen_today)} />
          <StatBox label="Open Pos." value={String(summary.open_positions_current)} />
          <StatBox label="Closed Trades" value={String(summary.closed_trades_today)} />
          <StatBox
            label="Realized P&L"
            value={summary.realized_pnl_today != null ? fmtUSD(summary.realized_pnl_today) : "—"}
            cls={summary.realized_pnl_today != null ? pnlClass(summary.realized_pnl_today) : ""}
          />
        </div>
        {(summary.win_rate_today != null || summary.profit_factor_today != null) && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3">
            <StatBox
              label="Win Rate Today"
              value={summary.win_rate_today != null ? `${fmt(summary.win_rate_today)}%` : "—"}
              cls={summary.win_rate_today != null ? (summary.win_rate_today >= 50 ? "text-green-400" : "text-yellow-400") : ""}
            />
            <StatBox
              label="Profit Factor Today"
              value={summary.profit_factor_today != null ? fmt(summary.profit_factor_today) : "—"}
              cls={summary.profit_factor_today != null ? (summary.profit_factor_today >= 1 ? "text-green-400" : "text-red-400") : ""}
            />
            <StatBox label="First Tick" value={summary.first_tick_at ? utcShort(summary.first_tick_at) : "—"} />
            <StatBox label="Last Tick" value={summary.last_tick_at ? utcShort(summary.last_tick_at) : "—"} />
          </div>
        )}
        {summary.notes.length > 0 && (
          <div className="mt-2 space-y-1">
            {summary.notes.map((n, i) => (
              <p key={i} className="text-xs text-blue-400">ℹ {n}</p>
            ))}
          </div>
        )}
      </div>

      {/* Rejections + Catalysts */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
        <div>
          <h3 className="text-sm font-semibold text-gray-300 mb-2">Top Rejection Reasons Today</h3>
          {top_rejections.length === 0
            ? <p className="text-gray-500 text-xs">No rejection data today.</p>
            : (
              <table className="text-xs w-full">
                <thead><tr className="text-gray-500 border-b border-gray-700">
                  <th className="pb-1 text-left font-medium">Reason</th>
                  <th className="pb-1 text-right font-medium">Count</th>
                </tr></thead>
                <tbody>
                  {top_rejections.map((r, i) => (
                    <tr key={i} className="border-b border-gray-800">
                      <td className="py-1 text-gray-300 max-w-xs truncate">{r.reason}</td>
                      <td className="py-1 text-right font-mono text-white">{r.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        </div>
        <div>
          <h3 className="text-sm font-semibold text-gray-300 mb-2">Catalyst Breakdown Today</h3>
          {catalysts.length === 0
            ? <p className="text-gray-500 text-xs">No catalyst data today.</p>
            : (
              <table className="text-xs w-full">
                <thead><tr className="text-gray-500 border-b border-gray-700">
                  <th className="pb-1 text-left font-medium">Type</th>
                  <th className="pb-1 text-right font-medium">Candidates</th>
                  <th className="pb-1 text-right font-medium">Entries</th>
                  <th className="pb-1 text-right font-medium">Exits</th>
                </tr></thead>
                <tbody>
                  {catalysts.map((c) => (
                    <tr key={c.type} className="border-b border-gray-800">
                      <td className="py-1 text-blue-300">{c.type}</td>
                      <td className="py-1 text-right font-mono">{c.candidate_count}</td>
                      <td className="py-1 text-right font-mono text-green-400">{c.entries}</td>
                      <td className="py-1 text-right font-mono">{c.exits}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        </div>
      </div>

      {/* Symbol table */}
      {symbols.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-300 mb-2">
            Symbols Seen Today ({symbols.length})
            <a
              href="/api/journal/today/report.csv"
              className="ml-2 text-xs text-blue-400 hover:text-blue-300"
              download
            >
              ↓ CSV
            </a>
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead className="text-gray-400 border-b border-gray-700">
                <tr>
                  {["Symbol","Candidates","Entries","Exits","Avg Score","Last Seen"].map((h) => (
                    <th key={h} className="pb-2 pr-4 font-medium whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {symbols.map((sym) => (
                  <tr key={sym.symbol} className="border-b border-gray-800 hover:bg-gray-800">
                    <td className="py-1.5 pr-4 font-semibold text-yellow-300">{sym.symbol}</td>
                    <td className="py-1.5 pr-4 font-mono">{sym.candidate_count}</td>
                    <td className={`py-1.5 pr-4 font-mono ${sym.entries > 0 ? "text-green-400" : "text-gray-500"}`}>{sym.entries}</td>
                    <td className="py-1.5 pr-4 font-mono">{sym.exits}</td>
                    <td className="py-1.5 pr-4 font-mono">{sym.avg_score != null ? fmt(sym.avg_score, 1) : "—"}</td>
                    <td className="py-1.5 pr-4 text-gray-400 text-xs">{utcShort(sym.last_seen_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Latest ticks */}
      {latest_ticks.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-300 mb-2">
            Latest Ticks Today ({latest_ticks.length} shown)
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead className="text-gray-400 border-b border-gray-700">
                <tr>
                  {["Time","Symbols","Entries","Exits","Errors","Cash","P&L"].map((h) => (
                    <th key={h} className="pb-2 pr-4 font-medium whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {latest_ticks.map((t, i) => (
                  <tr key={i} className="border-b border-gray-800 hover:bg-gray-800">
                    <td className="py-1.5 pr-4 font-mono text-gray-400 whitespace-nowrap">{utcShort(t.started_at)}</td>
                    <td className="py-1.5 pr-4 font-mono">{t.symbols_evaluated}</td>
                    <td className={`py-1.5 pr-4 font-mono ${t.entries_made > 0 ? "text-green-400" : "text-gray-500"}`}>{t.entries_made}</td>
                    <td className="py-1.5 pr-4 font-mono">{t.exits_made}</td>
                    <td className={`py-1.5 pr-4 font-mono ${t.errors_count > 0 ? "text-yellow-400" : "text-gray-500"}`}>{t.errors_count}</td>
                    <td className="py-1.5 pr-4 font-mono">{t.account_cash != null ? `$${fmt(t.account_cash)}` : "—"}</td>
                    <td className={`py-1.5 pr-4 font-mono ${t.total_pnl != null ? pnlClass(t.total_pnl) : ""}`}>{t.total_pnl != null ? fmtUSD(t.total_pnl) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

    </div>
  );
}

// ── Intelligence section ──────────────────────────────────────────────────────

const INTEL_TABS = [
  { key: "reddit",    label: "🚀 Reddit"          },
  { key: "premarket", label: "🌐 Full-Market Movers" },
  { key: "earnings",  label: "📅 Earnings"         },
  { key: "insiders",  label: "👔 Insiders"         },
  { key: "news",      label: "📰 News"             },
  { key: "heatmap",   label: "🗺 Heatmap"          },
  { key: "llm",       label: "🤖 LLM Shadow"       },
] as const;

type IntelTab = typeof INTEL_TABS[number]["key"];

function IntelligenceSection({
  reddit,
  premarket,
  token,
  onRefresh,
}: {
  reddit: RedditSnapshot | null;
  premarket: PremarketSnapshot | null;
  token: string;
  onRefresh: () => void;
}) {
  const [activeTab, setActiveTab] = useState<IntelTab>("reddit");
  const [refreshMsg, setRefreshMsg] = useState("");

  async function handleRedditRefresh() {
    if (!token) { setRefreshMsg("Enter ADMIN_API_TOKEN first."); return; }
    setRefreshMsg("Refreshing…");
    try {
      const r = await fetch("/api/intelligence/reddit/refresh", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await r.json();
      if (r.ok) {
        setRefreshMsg(`Refreshed — ${body.result_count ?? 0} tickers`);
        onRefresh();
      } else {
        setRefreshMsg(`Failed: ${body.detail ?? JSON.stringify(body)}`);
      }
    } catch (e) {
      setRefreshMsg(`Error: ${String(e)}`);
    }
  }

  function ComingSoon({ name }: { name: string }) {
    return (
      <div className="text-center py-12 text-gray-500">
        <div className="text-4xl mb-3">🚧</div>
        <p className="text-lg font-semibold text-gray-400">{name}</p>
        <p className="text-sm mt-2">Planned for a future phase.</p>
        <p className="text-xs mt-1 text-gray-600">Read-only · no trading integration</p>
      </div>
    );
  }

  function PremarketTab() {
    if (!premarket) {
      return (
        <div className="text-center py-8 text-gray-500 text-sm animate-pulse">
          Loading full-market movers data…
        </div>
      );
    }

    const SESSION_TITLES: Record<string, string> = {
      premarket:  "Premarket Movers",
      regular:    "Regular Session Movers",
      afterhours: "After-Hours Movers",
      closed:     "Last Cached Movers / Market Closed",
    };
    const SESSION_COLORS: Record<string, string> = {
      premarket:  "text-yellow-400",
      regular:    "text-green-400",
      afterhours: "text-blue-400",
      closed:     "text-gray-500",
    };
    const sessionTitle = SESSION_TITLES[premarket.session] ?? "Full-Market Movers";
    const sessionColor = SESSION_COLORS[premarket.session] ?? "text-gray-400";
    const age = premarket.age_seconds;
    const ageLabel = age == null ? "—" : age < 60 ? `${age}s` : `${Math.floor(age / 60)}m ${age % 60}s`;

    const isFullUniverse = premarket.mode === "full_universe";
    const gainers = (premarket.top_gainers ?? premarket.gainers ?? []).slice(0, 30);
    const losers  = (premarket.top_losers  ?? premarket.losers  ?? []).slice(0, 30);
    const universeCount = premarket.universe_count ?? premarket.symbol_count ?? 0;

    function MoverRow({ m }: { m: PremarketMover }) {
      const gap = m.gap_percent;
      const isPos = gap >= 0;
      const gapStr = `${isPos ? "+" : ""}${gap.toFixed(2)}%`;
      const vol = m.day_volume != null ? m.day_volume.toLocaleString() : "—";
      const dvol = m.dollar_volume != null
        ? `$${(m.dollar_volume / 1_000_000).toFixed(1)}M`
        : null;
      const volVsPrev = m.volume_vs_previous_day_ratio != null
        ? `${m.volume_vs_previous_day_ratio.toFixed(2)}x`
        : "—";
      const taVol = m.time_adjusted_volume_ratio != null
        ? `${m.time_adjusted_volume_ratio.toFixed(2)}x`
        : "—";
      const avgVolMult = m.volume_vs_30d_avg_ratio != null
        ? `${m.volume_vs_30d_avg_ratio.toFixed(2)}x`
        : "—";
      return (
        <div className="flex items-center justify-between px-3 py-2 rounded bg-gray-900 border border-gray-800 text-sm">
          <span className="font-bold text-white w-16">{m.symbol}</span>
          <span className="text-gray-300 w-20 text-right">${m.last_price.toFixed(2)}</span>
          <span className={`font-semibold w-20 text-right ${isPos ? "text-green-400" : "text-red-400"}`}>
            {gapStr}
          </span>
          <span className="text-gray-400 w-20 text-right text-xs">
            prev ${m.previous_close != null ? m.previous_close.toFixed(2) : "—"}
          </span>
          <span className="text-gray-500 w-24 text-right text-xs">
            {dvol ?? vol}
          </span>
          <span className="text-gray-500 w-20 text-right text-xs" title="Vol vs Previous Day">
            {volVsPrev}
          </span>
          <span className="text-indigo-400 w-16 text-right text-xs" title="Time-Adjusted Vol Ratio">
            {taVol}
          </span>
          <span className="text-gray-600 w-16 text-right text-xs" title="Avg Vol Multiple (30d — null until available)">
            {avgVolMult}
          </span>
        </div>
      );
    }

    return (
      <div>
        {/* Title + disclaimer */}
        <div className="mb-3">
          <h3 className={`text-base font-bold ${sessionColor}`}>{sessionTitle}</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Read-only full-market visibility. Not used in trading decisions unless explicitly injected into the fake-money paper candidate universe. No broker. No real orders.
          </p>
        </div>
        {/* Header row */}
        <div className="flex flex-wrap items-center gap-3 mb-4 text-xs text-gray-500">
          {isFullUniverse ? (
            <span className="rounded px-1.5 py-0.5 bg-indigo-900 text-indigo-300 font-mono text-xs">
              FULL UNIVERSE
            </span>
          ) : (
            <span className="rounded px-1.5 py-0.5 bg-gray-800 text-gray-400 font-mono text-xs">
              ACTIVE UNIVERSE
            </span>
          )}
          <span>{universeCount.toLocaleString()} symbols scanned</span>
          {premarket.valid_movers_count != null && (
            <span>{premarket.valid_movers_count.toLocaleString()} valid movers</span>
          )}
          <span>age: {ageLabel}</span>
          {premarket.ttl_seconds != null && <span>ttl: {premarket.ttl_seconds}s</span>}
          {premarket.scan_duration_ms != null && (
            <span>scan: {premarket.scan_duration_ms}ms</span>
          )}
          {premarket.fetched_at && (
            <span>fetched: {new Date(premarket.fetched_at * 1000).toLocaleTimeString()}</span>
          )}
        </div>

        {premarket.error && (
          <div className="rounded border border-yellow-700 bg-yellow-950 text-yellow-300 px-3 py-2 text-sm mb-4">
            <span className="font-semibold">⚠ Refresh failed;</span> showing cached data. {premarket.error}
          </div>
        )}

        {(premarket.warnings ?? []).filter(w => w).length > 0 && (
          <div className="rounded border border-gray-700 bg-gray-900 text-gray-400 px-3 py-2 text-xs mb-4">
            {(premarket.warnings ?? []).map((w, i) => <div key={i}>{w}</div>)}
          </div>
        )}

        {gainers.length === 0 && losers.length === 0 ? (
          <div className="text-center py-8 text-gray-500 text-sm">
            No movers available — scanner may not have run yet.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Gainers */}
            <div>
              <h4 className="text-xs font-semibold text-green-500 uppercase tracking-wide mb-2">
                Top 30 Gainers ({gainers.length})
              </h4>
              <div className="flex items-center justify-between px-3 py-1 text-xs text-gray-600 mb-1">
                <span className="w-16">Symbol</span>
                <span className="w-20 text-right">Last</span>
                <span className="w-20 text-right">Gap%</span>
                <span className="w-20 text-right">Prev Close</span>
                <span className="w-24 text-right">{isFullUniverse ? "$ Vol" : "Vol"}</span>
                <span className="w-20 text-right">Vol vs Prev Day</span>
                <span className="w-16 text-right">Time-Adj Vol</span>
                <span className="w-16 text-right">Avg Vol Multiple</span>
              </div>
              <div className="space-y-1">
                {gainers.map((m) => <MoverRow key={m.symbol} m={m} />)}
              </div>
            </div>
            {/* Losers */}
            <div>
              <h4 className="text-xs font-semibold text-red-500 uppercase tracking-wide mb-2">
                Top 30 Losers ({losers.length})
              </h4>
              <div className="flex items-center justify-between px-3 py-1 text-xs text-gray-600 mb-1">
                <span className="w-16">Symbol</span>
                <span className="w-20 text-right">Last</span>
                <span className="w-20 text-right">Gap%</span>
                <span className="w-20 text-right">Prev Close</span>
                <span className="w-24 text-right">{isFullUniverse ? "$ Vol" : "Vol"}</span>
                <span className="w-20 text-right">Vol vs Prev Day</span>
                <span className="w-16 text-right">Time-Adj Vol</span>
                <span className="w-16 text-right">Avg Vol Multiple</span>
              </div>
              <div className="space-y-1">
                {losers.map((m) => <MoverRow key={m.symbol} m={m} />)}
              </div>
            </div>
          </div>
        )}

        <p className="text-xs text-gray-600 mt-4">
          {isFullUniverse
            ? `Full Universe · Polygon bulk snapshot · ~${universeCount.toLocaleString()} CS tickers · price ≥ $3 · sorted by |gap%| · read-only · no broker · no real orders`
            : "Active Universe fallback · marketdata collector cache · price ≥ $3 · sorted by |gap%| · read-only · no broker · no real orders"
          }
        </p>
      </div>
    );
  }

  function RedditTab() {
    if (!reddit) {
      return (
        <div className="text-center py-8 text-gray-500 text-sm animate-pulse">
          Loading Reddit data…
        </div>
      );
    }
    // Full error panel only when there are no cached results to show
    if (reddit.error && reddit.results.length === 0) {
      return (
        <div className="rounded border border-red-800 bg-red-950 text-red-300 px-4 py-3 text-sm">
          <span className="font-semibold">ApeWisdom unavailable:</span> {reddit.error}
          <div className="text-xs mt-1 text-red-500">No cached data available.</div>
        </div>
      );
    }

    const age = reddit.age_seconds;
    const ageLabel = age == null ? "—"
      : age < 60 ? `${age}s ago`
      : age < 3600 ? `${Math.round(age / 60)}m ago`
      : `${Math.round(age / 3600)}h ago`;

    const fetchedAt = reddit.fetched_at
      ? new Date(reddit.fetched_at * 1000).toUTCString().replace(" GMT", " UTC")
      : "never";

    return (
      <div>
        {/* Inline warning banner: error but cached results still available */}
        {reddit.error && reddit.results.length > 0 && (
          <div className="mb-3 rounded border border-yellow-700 bg-yellow-950 px-3 py-2 text-xs text-yellow-300">
            <span className="font-semibold">⚠ ApeWisdom refresh failed;</span> showing cached Reddit data.
          </div>
        )}
        {/* Header row */}
        <div className="flex flex-wrap items-center gap-3 mb-4 text-xs text-gray-400">
          <span className="bg-gray-700 px-2 py-0.5 rounded font-mono">
            source: {reddit.source}
          </span>
          <span>Fetched: {fetchedAt}</span>
          <span>Age: {ageLabel}</span>
          {reddit.ttl_seconds != null && (
            <span>TTL: {reddit.ttl_seconds}s</span>
          )}
          <span>{reddit.result_count} tickers</span>
          <button
            onClick={handleRedditRefresh}
            className="ml-auto px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs font-semibold transition-colors"
          >
            ↺ Refresh
          </button>
        </div>
        {refreshMsg && (
          <p className="text-xs text-yellow-300 font-mono mb-3">{refreshMsg}</p>
        )}

        {/* Spike alerts */}
        {reddit.spikes && reddit.spikes.length > 0 && (
          <div className="mb-4 rounded border border-orange-700 bg-orange-950 px-3 py-2">
            <p className="text-orange-300 font-semibold text-xs mb-1">
              🚨 {reddit.spikes.length} mention spike{reddit.spikes.length > 1 ? "s" : ""} detected (≥3× previous)
            </p>
            <div className="flex flex-wrap gap-2">
              {reddit.spikes.map((sp) => (
                <span key={sp.ticker} className="bg-orange-900 text-orange-200 text-xs px-2 py-0.5 rounded font-mono">
                  {sp.ticker} ×{sp.spike_ratio} ({sp.prev_mentions}→{sp.mentions})
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Empty state */}
        {reddit.results.length === 0 && (
          <p className="text-gray-500 text-sm py-4 text-center">
            No Reddit data available. Click Refresh to fetch.
          </p>
        )}

        {/* Results table */}
        {reddit.results.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-400 border-b border-gray-700">
                  <th className="pb-2 text-left w-10">#</th>
                  <th className="pb-2 text-left w-20">Ticker</th>
                  <th className="pb-2 text-left max-w-[140px]">Name</th>
                  <th className="pb-2 text-right">Mentions</th>
                  <th className="pb-2 text-right">Upvotes</th>
                  <th className="pb-2 text-right">Rank Δ24h</th>
                  <th className="pb-2 text-right">Mentions Δ24h</th>
                  <th className="pb-2 text-center w-16">Spike</th>
                </tr>
              </thead>
              <tbody>
                {reddit.results.map((row) => {
                  const isSpike = reddit.spikes.some((s) => s.ticker === row.ticker);
                  const spikeObj = reddit.spikes.find((s) => s.ticker === row.ticker);
                  const rankDelta = row.rank_24h_ago != null
                    ? row.rank_24h_ago - row.rank
                    : null;
                  const mentionDelta = row.mentions_24h_ago != null
                    ? row.mentions - row.mentions_24h_ago
                    : null;
                  return (
                    <tr
                      key={row.ticker}
                      className={`border-b border-gray-800 ${isSpike ? "bg-orange-950/40" : "hover:bg-gray-800/40"}`}
                    >
                      <td className="py-1.5 pr-2 text-gray-500 font-mono text-xs">{row.rank}</td>
                      <td className="py-1.5 pr-3 font-mono font-semibold text-white">
                        {row.ticker}
                      </td>
                      <td className="py-1.5 pr-3 text-gray-400 text-xs truncate max-w-[140px]">
                        {row.name || "—"}
                      </td>
                      <td className="py-1.5 text-right font-mono">{row.mentions.toLocaleString()}</td>
                      <td className="py-1.5 text-right font-mono text-gray-400">{row.upvotes.toLocaleString()}</td>
                      <td className={`py-1.5 text-right font-mono text-xs ${
                        rankDelta == null ? "text-gray-600"
                        : rankDelta > 0 ? "text-green-400"
                        : rankDelta < 0 ? "text-red-400"
                        : "text-gray-400"
                      }`}>
                        {rankDelta == null ? "—"
                          : rankDelta > 0 ? `▲${rankDelta}`
                          : rankDelta < 0 ? `▼${Math.abs(rankDelta)}`
                          : "—"}
                      </td>
                      <td className={`py-1.5 text-right font-mono text-xs ${
                        mentionDelta == null ? "text-gray-600"
                        : mentionDelta > 0 ? "text-green-400"
                        : mentionDelta < 0 ? "text-red-400"
                        : "text-gray-400"
                      }`}>
                        {mentionDelta == null ? "—"
                          : mentionDelta > 0 ? `+${mentionDelta.toLocaleString()}`
                          : mentionDelta < 0 ? mentionDelta.toLocaleString()
                          : "0"}
                      </td>
                      <td className="py-1.5 text-center">
                        {isSpike && spikeObj && (
                          <span className="bg-orange-700 text-orange-200 text-xs px-1.5 py-0.5 rounded font-semibold">
                            ×{spikeObj.spike_ratio}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  }

  return (
    <div>
      {/* Disclaimer */}
      <div className="mb-4 text-xs text-gray-500 border border-gray-700 rounded px-3 py-2 bg-gray-900">
        Read-only intelligence layer · Not integrated into trading decisions ·
        No broker · No live trading · No real orders
      </div>

      {/* Tab bar */}
      <div className="flex flex-wrap gap-1 mb-5 border-b border-gray-700 pb-2">
        {INTEL_TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`px-3 py-1.5 rounded-t text-sm font-medium transition-colors ${
              activeTab === t.key
                ? "bg-gray-700 text-white border border-b-transparent border-gray-600"
                : "text-gray-400 hover:text-gray-200 hover:bg-gray-800"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "reddit"    && <RedditTab />}
      {activeTab === "premarket" && <PremarketTab />}
      {activeTab === "news"      && <NewsTab token={token} />}
      {activeTab === "earnings"  && <EarningsTab token={token} />}
      {activeTab === "insiders"  && <InsidersTab token={token} />}
      {activeTab === "heatmap"   && <ComingSoon name="Sector Heatmap" />}
      {activeTab === "llm"       && <LLMPlaceholderTab />}
    </div>
  );
}

// ── News / Earnings / Insiders / LLM tabs (Phase I5) ──────────────────────────

function NewsTab({ token }: { token: string }) {
  const [data, setData] = useState<NewsSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState("");
  const [ticker, setTicker] = useState("");
  const [eventType, setEventType] = useState("");
  const [sentiment, setSentiment] = useState("");
  const [impact, setImpact] = useState("");
  const [sortBy, setSortBy] = useState("published_at");
  const [sortDir, setSortDir] = useState("desc");
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);
  const [refreshMsg, setRefreshMsg] = useState("");

  const fetchNewsLocal = useCallback(async () => {
    const params = new URLSearchParams();
    if (q.trim()) params.set("q", q.trim());
    if (ticker.trim()) params.set("ticker", ticker.trim());
    if (eventType) params.set("event_type", eventType);
    if (sentiment) params.set("sentiment", sentiment);
    if (impact) params.set("rule_impact_level", impact);
    params.set("sort_by", sortBy);
    params.set("sort_dir", sortDir);
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    setLoading(true);
    try {
      const r = await fetch(`/api/intelligence/news?${params.toString()}`);
      if (r.ok) setData(await r.json());
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [q, ticker, eventType, sentiment, impact, sortBy, sortDir, limit, offset]);

  // Reset pagination when filters change (offset is reset before refetch).
  useEffect(() => {
    setOffset(0);
  }, [q, ticker, eventType, sentiment, impact, sortBy, sortDir, limit]);

  // Debounce filter changes so typing doesn't fire on every keystroke.
  useEffect(() => {
    const id = setTimeout(() => { fetchNewsLocal(); }, 300);
    return () => clearTimeout(id);
  }, [fetchNewsLocal]);

  // Periodic poll for cache_age display (cache-first backend; no Polygon pressure).
  useEffect(() => {
    const id = setInterval(() => { fetchNewsLocal(); }, 30_000);
    return () => clearInterval(id);
  }, [fetchNewsLocal]);

  async function handleManualRefresh() {
    if (!token) {
      setRefreshMsg("Enter ADMIN_API_TOKEN in the Controls section to refresh the news cache.");
      return;
    }
    setRefreshMsg("Refreshing news cache…");
    try {
      const r = await fetch("/api/intelligence/news/refresh", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await r.json();
      if (r.ok && body.ok) {
        setRefreshMsg(`Cache refreshed — ${body.total_count ?? 0} items in ${body.fetch_duration_ms ?? "?"}ms`);
        await fetchNewsLocal();
      } else {
        setRefreshMsg(`Refresh failed: ${body.error ?? body.detail ?? JSON.stringify(body)}`);
      }
    } catch (e) {
      setRefreshMsg(`Error: ${String(e)}`);
    }
  }

  if (!data && loading) {
    return <div className="text-center py-8 text-gray-500 text-sm animate-pulse">Loading news/catalyst feed…</div>;
  }
  if (!data) {
    return <div className="text-center py-8 text-gray-500 text-sm">No news data.</div>;
  }
  const items = data.results ?? [];
  const fetchedAt = data.fetched_at ? new Date(data.fetched_at).toUTCString().replace(" GMT", " UTC") : "—";
  const cacheAge = data.cache_age_seconds;
  const cacheAgeLabel = cacheAge == null ? "—"
    : cacheAge < 60 ? `${cacheAge}s ago`
    : cacheAge < 3600 ? `${Math.round(cacheAge / 60)}m ago`
    : `${Math.round(cacheAge / 3600)}h ago`;

  return (
    <div>
      <div className="mb-3 rounded border border-blue-800 bg-blue-950 px-3 py-2 text-xs text-blue-300">
        <span className="font-semibold">Rule-based analysis.</span> News/catalyst scoring is deterministic
        (event-type classification + keyword/structured sentiment + materiality). No AI/LLM analysis yet.
        Backend is cache-first (TTL {data.ttl_seconds ?? 300}s) — GET does not call Polygon on each refresh.
      </div>

      {/* Filter / search / sort controls */}
      <div className="mb-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-2">
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search ticker, company, keyword, source, catalyst…"
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        />
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          placeholder="Ticker (exact, e.g. NVDA)"
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-blue-500"
        />
        <select
          value={eventType}
          onChange={(e) => setEventType(e.target.value)}
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="">Event type: any</option>
          <option value="generic_news">generic_news</option>
          <option value="earnings">earnings</option>
          <option value="fda_regulatory">fda_regulatory</option>
          <option value="product_launch">product_launch</option>
          <option value="offering">offering</option>
          <option value="legal_regulatory">legal_regulatory</option>
          <option value="macro">macro</option>
          <option value="sector_news">sector_news</option>
        </select>
        <select
          value={sentiment}
          onChange={(e) => setSentiment(e.target.value)}
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="">Sentiment: any</option>
          <option value="bullish">bullish</option>
          <option value="bearish">bearish</option>
          <option value="mixed">mixed</option>
          <option value="neutral">neutral</option>
          <option value="unknown">unknown</option>
        </select>
        <select
          value={impact}
          onChange={(e) => setImpact(e.target.value)}
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="">Impact: any</option>
          <option value="high">high</option>
          <option value="medium">medium</option>
          <option value="low">low</option>
          <option value="unknown">unknown</option>
        </select>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="published_at">Sort: Date</option>
          <option value="ticker">Sort: Ticker</option>
          <option value="event_type">Sort: Event Type</option>
          <option value="materiality_score">Sort: Materiality</option>
          <option value="sentiment_score">Sort: Sentiment Score</option>
          <option value="fetched_at">Sort: Fetched</option>
        </select>
        <select
          value={sortDir}
          onChange={(e) => setSortDir(e.target.value)}
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="desc">Newest / High → Low</option>
          <option value="asc">Oldest / Low → High</option>
        </select>
        <select
          value={limit}
          onChange={(e) => setLimit(parseInt(e.target.value, 10))}
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value={50}>Limit: 50</option>
          <option value={100}>Limit: 100</option>
          <option value={250}>Limit: 250</option>
          <option value={500}>Limit: 500</option>
        </select>
        <div className="flex gap-2">
          <button
            onClick={() => { setQ(""); setTicker(""); setEventType(""); setSentiment(""); setImpact(""); setSortBy("published_at"); setSortDir("desc"); setLimit(100); setOffset(0); }}
            className="flex-1 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-sm font-semibold transition-colors"
          >
            Clear
          </button>
          <button
            onClick={handleManualRefresh}
            disabled={!token}
            title={token ? "Force fresh Polygon fetch (admin)" : "Enter ADMIN_API_TOKEN in Controls to enable"}
            className={`flex-1 px-3 py-1.5 rounded text-sm font-semibold transition-colors ${
              token ? "bg-blue-700 hover:bg-blue-600" : "bg-gray-800 text-gray-500 cursor-not-allowed"
            }`}
          >
            ↺ Refresh
          </button>
        </div>
      </div>

      {refreshMsg && (
        <p className="text-xs text-yellow-300 font-mono mb-3">{refreshMsg}</p>
      )}

      <div className="flex flex-wrap items-center gap-3 mb-4 text-xs text-gray-400">
        <span className="bg-gray-700 px-2 py-0.5 rounded font-mono">source: cache-first</span>
        <span>Cache: {fetchedAt}</span>
        <span>Age: {cacheAgeLabel}</span>
        {data.ttl_seconds != null && <span>TTL: {data.ttl_seconds}s</span>}
        <span>Showing <span className="text-gray-200 font-semibold">{data.returned_count ?? items.length}</span> of <span className="text-gray-200 font-semibold">{data.total_count ?? "?"}</span> matched</span>
        {data.symbols_requested && (
          <span>{data.symbols_requested.length} symbols cached</span>
        )}
        {data.stale && (
          <span className="text-yellow-400">⚠ stale</span>
        )}
      </div>

      {data.warning && (
        <div className="mb-3 rounded border border-yellow-700 bg-yellow-950 px-3 py-2 text-xs text-yellow-300">
          ⚠ {data.warning}
        </div>
      )}

      {items.length === 0 ? (
        <p className="text-gray-500 text-sm py-4 text-center">No news items match the current filters.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-400 border-b border-gray-700">
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Time</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Ticker(s)</th>
                <th className="pb-2 pr-2 text-left">Title</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Source</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Rule Event Type</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Rule Impact</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Rule Sentiment</th>
                <th className="pb-2 pr-2 text-right whitespace-nowrap">Materiality</th>
                <th className="pb-2 pr-2 text-right whitespace-nowrap">Sent. Score</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Bullish Flags</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Bearish Flags</th>
                <th className="pb-2 pr-2 text-left">Rule Explanation</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">AI Analysis</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">URL</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, i) => {
                const pub = item.published_utc ? new Date(item.published_utc).toUTCString().replace(" GMT", " UTC").slice(0, -4) : "—";
                const bull = item.rule_bullish_flags ?? item.bullish_flags ?? [];
                const bear = item.rule_bearish_flags ?? item.bearish_flags ?? [];
                const sentVal = (item.rule_sentiment ?? item.sentiment ?? "unknown").toLowerCase();
                const sentBadge =
                  sentVal === "bullish" ? "bg-green-900 text-green-300 border-green-700" :
                  sentVal === "bearish" ? "bg-red-900 text-red-300 border-red-700" :
                  sentVal === "mixed"   ? "bg-yellow-900 text-yellow-300 border-yellow-700" :
                  sentVal === "neutral" ? "bg-gray-800 text-gray-300 border-gray-600" :
                                          "bg-gray-900 text-gray-500 border-gray-700";
                const impactVal = (item.rule_impact_level ?? "unknown").toLowerCase();
                const impactBadge =
                  impactVal === "high"   ? "bg-orange-900 text-orange-300 border-orange-700" :
                  impactVal === "medium" ? "bg-yellow-900 text-yellow-300 border-yellow-700" :
                  impactVal === "low"    ? "bg-gray-800 text-gray-400 border-gray-600" :
                                           "bg-gray-900 text-gray-500 border-gray-700";
                const evType = item.rule_event_type || item.classified_event_type || item.event_type || "—";
                const tickers = (item.tickers && item.tickers.length > 0)
                  ? item.tickers.slice(0, 4).join(", ") + (item.tickers.length > 4 ? ` +${item.tickers.length - 4}` : "")
                  : item.symbol;
                const reasons = item.rule_reasons ?? item.sentiment_reasons ?? [];
                const explanation = item.rule_explanation ?? (reasons.length > 0 ? reasons.join("; ") : "");
                const sentScore = item.rule_sentiment_score ?? item.sentiment_score;
                const materiality = item.rule_materiality_score ?? item.materiality_score;

                return (
                  <tr key={item.catalyst_id ?? `${item.symbol}-${i}`} className="border-b border-gray-800 hover:bg-gray-800/40 align-top">
                    <td className="py-1.5 pr-2 text-xs text-gray-500 font-mono whitespace-nowrap">{pub}</td>
                    <td className="py-1.5 pr-2 font-mono font-semibold text-yellow-300 whitespace-nowrap" title={(item.tickers ?? [item.symbol]).join(", ")}>
                      <span className="text-yellow-200">{item.symbol}</span>
                      {item.tickers && item.tickers.length > 1 && (
                        <span className="text-gray-500 text-xs ml-1">({tickers})</span>
                      )}
                    </td>
                    <td className="py-1.5 pr-2 text-gray-200 max-w-[360px] truncate" title={item.title}>{item.title || "—"}</td>
                    <td className="py-1.5 pr-2 text-xs text-gray-500 whitespace-nowrap max-w-[120px] truncate" title={item.publisher || item.source || ""}>
                      {item.publisher || item.source || "—"}
                    </td>
                    <td className="py-1.5 pr-2 text-xs text-blue-300 whitespace-nowrap">{evType}</td>
                    <td className="py-1.5 pr-2 whitespace-nowrap">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${impactBadge}`}>
                        {impactVal.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-1.5 pr-2 whitespace-nowrap">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${sentBadge}`}>
                        {sentVal}
                      </span>
                    </td>
                    <td className="py-1.5 pr-2 text-xs font-mono text-right whitespace-nowrap text-gray-300">
                      {materiality != null ? Number(materiality).toFixed(2) : "—"}
                    </td>
                    <td className="py-1.5 pr-2 text-xs font-mono text-right whitespace-nowrap text-gray-300">
                      {sentScore != null ? Number(sentScore).toFixed(2) : "—"}
                    </td>
                    <td className="py-1.5 pr-2 text-xs whitespace-nowrap" title={bull.join(", ")}>
                      {bull.length > 0 ? (
                        <span className="text-green-400 font-semibold">+{bull.length}</span>
                      ) : <span className="text-gray-600">—</span>}
                    </td>
                    <td className="py-1.5 pr-2 text-xs whitespace-nowrap" title={bear.join(", ")}>
                      {bear.length > 0 ? (
                        <span className="text-red-400 font-semibold">−{bear.length}</span>
                      ) : <span className="text-gray-600">—</span>}
                    </td>
                    <td className="py-1.5 pr-2 text-xs text-gray-400 max-w-[220px] truncate" title={explanation || "—"}>
                      {explanation || <span className="text-gray-600">—</span>}
                    </td>
                    <td className="py-1.5 pr-2 text-xs whitespace-nowrap" title="AI analysis not active yet — no OpenAI/Anthropic/Ollama calls in this phase.">
                      <span className="text-xs font-semibold px-2 py-0.5 rounded border bg-purple-950 text-purple-400 border-purple-800">
                        inactive
                      </span>
                    </td>
                    <td className="py-1.5 pr-2 text-xs whitespace-nowrap">
                      {item.article_url ? (
                        <a href={item.article_url} target="_blank" rel="noreferrer" className="text-blue-400 hover:text-blue-300 underline">open</a>
                      ) : <span className="text-gray-600">—</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {data.total_count != null && data.total_count > limit && (
        <div className="flex items-center justify-between gap-3 mt-3 text-xs text-gray-400">
          <span>
            Rows {offset + 1}–{Math.min(offset + (data.returned_count ?? 0), data.total_count)} of {data.total_count}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setOffset(Math.max(0, offset - limit))}
              disabled={offset <= 0}
              className={`px-3 py-1 rounded font-semibold transition-colors ${
                offset <= 0 ? "bg-gray-800 text-gray-600 cursor-not-allowed" : "bg-gray-700 hover:bg-gray-600 text-gray-200"
              }`}
            >
              ← Previous
            </button>
            <button
              onClick={() => setOffset(offset + limit)}
              disabled={data.total_count != null && offset + (data.returned_count ?? 0) >= data.total_count}
              className={`px-3 py-1 rounded font-semibold transition-colors ${
                data.total_count != null && offset + (data.returned_count ?? 0) >= data.total_count
                  ? "bg-gray-800 text-gray-600 cursor-not-allowed"
                  : "bg-gray-700 hover:bg-gray-600 text-gray-200"
              }`}
            >
              Next →
            </button>
          </div>
        </div>
      )}

      {/* AI placeholder note */}
      <div className="mt-3 rounded border border-purple-900 bg-purple-950/30 px-3 py-2 text-xs text-purple-300">
        <span className="font-semibold">AI Analysis column:</span>{" "}
        AI analysis not active yet — no OpenAI/Anthropic/Ollama calls in this phase. The AI column is reserved
        for a future side-by-side comparison against the current rule-based output.
      </div>

      <p className="text-xs text-gray-600 mt-4">
        {data.note ?? "Display feed only — no live orders, no AI/LLM."}
      </p>
    </div>
  );
}

function NotImplementedFeed({ name, data }: { name: string; data: PlaceholderFeed | null }) {
  const warning = data?.warning ?? `${name} is not yet implemented in microtrading.`;
  return (
    <div className="text-center py-10 text-gray-400 border border-dashed border-gray-700 rounded bg-gray-900">
      <div className="text-4xl mb-3">🚧</div>
      <p className="text-lg font-semibold text-gray-300">{name}</p>
      <p className="text-sm mt-2 text-gray-400 max-w-xl mx-auto">{warning}</p>
      <p className="text-xs mt-3 text-gray-600">
        Status: <span className="font-mono">implemented={String(data?.implemented ?? false)}</span>
        {" · "}<span className="font-mono">enabled={String(data?.enabled ?? false)}</span>
      </p>
      <p className="text-xs mt-1 text-gray-600">Display feed only · no trading integration · no fake data shown</p>
    </div>
  );
}

// ── Earnings tab (Phase I6) ──────────────────────────────────────────────────

interface EarningsRow {
  ticker: string;
  report_date: string | null;
  report_time: string | null;
  eps_estimate: number | null;
  revenue_estimate: number | null;
  eps_actual?: number | null;
  revenue_actual?: number | null;
  surprise?: number | null;
  confirmed: boolean | string | null;
  days_until: number | null;
  source: string | null;
  fetched_at: string | null;
}

interface EarningsSnapshot {
  ok: boolean;
  enabled: boolean;
  available?: boolean;
  implemented: boolean;
  provider_status?: "not_configured" | "configured_but_unwired" | "active" | string;
  source: string | null;
  fetched_at: string | null;
  cache_age_seconds: number | null;
  ttl_seconds: number | null;
  stale: boolean;
  total_count: number;
  returned_count: number;
  limit: number;
  offset: number;
  filters_applied?: Record<string, unknown>;
  sort_by?: string;
  sort_dir?: string;
  results: EarningsRow[];
  errors?: unknown[];
  warning: string | null;
  note?: string;
}

function EarningsTab({ token }: { token: string }) {
  const [data, setData] = useState<EarningsSnapshot | null>(null);
  const [ticker, setTicker] = useState("");
  const [daysAhead, setDaysAhead] = useState(30);
  const [sortBy, setSortBy] = useState("report_date");
  const [sortDir, setSortDir] = useState("asc");
  const [limit, setLimit] = useState(100);
  const [refreshMsg, setRefreshMsg] = useState("");

  const fetchEarningsLocal = useCallback(async () => {
    const params = new URLSearchParams();
    if (ticker.trim()) params.set("ticker", ticker.trim());
    params.set("days_ahead", String(daysAhead));
    params.set("sort_by", sortBy);
    params.set("sort_dir", sortDir);
    params.set("limit", String(limit));
    try {
      const r = await fetch(`/api/intelligence/earnings?${params.toString()}`);
      if (r.ok) setData(await r.json());
    } catch { /* ignore */ }
  }, [ticker, daysAhead, sortBy, sortDir, limit]);

  useEffect(() => {
    const id = setTimeout(() => { fetchEarningsLocal(); }, 300);
    return () => clearTimeout(id);
  }, [fetchEarningsLocal]);

  async function handleRefresh() {
    if (!token) { setRefreshMsg("Enter ADMIN_API_TOKEN to refresh."); return; }
    setRefreshMsg("Refreshing earnings cache…");
    try {
      const r = await fetch("/api/intelligence/earnings/refresh", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await r.json();
      if (r.ok && body.ok) {
        setRefreshMsg(`Refreshed — ${body.total_count ?? 0} items. ${body.warning ?? ""}`);
        await fetchEarningsLocal();
      } else {
        setRefreshMsg(`Failed: ${body.error ?? body.detail ?? JSON.stringify(body)}`);
      }
    } catch (e) {
      setRefreshMsg(`Error: ${String(e)}`);
    }
  }

  const items = data?.results ?? [];
  const cacheAge = data?.cache_age_seconds;
  const cacheAgeLabel = cacheAge == null ? "—"
    : cacheAge < 60 ? `${cacheAge}s ago`
    : cacheAge < 3600 ? `${Math.round(cacheAge / 60)}m ago`
    : `${Math.round(cacheAge / 3600)}h ago`;

  return (
    <div>
      <div className="mb-3 rounded border border-blue-800 bg-blue-950 px-3 py-2 text-xs text-blue-300">
        <span className="font-semibold">Earnings calendar is used as a risk/proximity input.</span>{" "}
        Upcoming earnings are not automatically bullish — they apply a deterministic penalty when too close
        (1d −10, 2d −5, 3d −3; configurable). Earnings alone cannot create an entry.
      </div>

      {(data?.enabled === false || data?.available === false) && (
        <div className="mb-3 rounded border border-yellow-700 bg-yellow-950 px-3 py-2 text-xs text-yellow-300">
          ⚠{" "}
          {data?.provider_status === "configured_but_unwired"
            ? `Provider ${data?.source ?? "?"} is configured but no fetcher is implemented yet. No fake data shown.`
            : data?.provider_status === "not_configured"
            ? "Earnings provider is not configured. No fake data shown."
            : data?.warning ?? "Earnings provider unavailable."}
          {data?.provider_status && (
            <span className="ml-2 text-yellow-500 font-mono">
              [provider_status: {data.provider_status}]
            </span>
          )}
        </div>
      )}

      <div className="mb-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-2">
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          placeholder="Ticker (e.g. NVDA)"
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-blue-500"
        />
        <select
          value={daysAhead}
          onChange={(e) => setDaysAhead(parseInt(e.target.value, 10))}
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value={7}>Next 7 days</option>
          <option value={14}>Next 14 days</option>
          <option value={30}>Next 30 days</option>
          <option value={60}>Next 60 days</option>
          <option value={90}>Next 90 days</option>
        </select>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="report_date">Sort: Date</option>
          <option value="ticker">Sort: Ticker</option>
          <option value="days_until">Sort: Days Until</option>
          <option value="confirmed">Sort: Confirmed</option>
        </select>
        <select
          value={sortDir}
          onChange={(e) => setSortDir(e.target.value)}
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="asc">Soonest first</option>
          <option value="desc">Latest first</option>
        </select>
        <select
          value={limit}
          onChange={(e) => setLimit(parseInt(e.target.value, 10))}
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value={50}>Limit: 50</option>
          <option value={100}>Limit: 100</option>
          <option value={250}>Limit: 250</option>
          <option value={500}>Limit: 500</option>
        </select>
        <button
          onClick={handleRefresh}
          disabled={!token}
          title={token ? "Force fresh fetch (admin)" : "Enter ADMIN_API_TOKEN in Controls to enable"}
          className={`px-3 py-1.5 rounded text-sm font-semibold transition-colors ${
            token ? "bg-blue-700 hover:bg-blue-600" : "bg-gray-800 text-gray-500 cursor-not-allowed"
          }`}
        >
          ↺ Refresh
        </button>
      </div>

      {refreshMsg && <p className="text-xs text-yellow-300 font-mono mb-3">{refreshMsg}</p>}

      <div className="flex flex-wrap items-center gap-3 mb-3 text-xs text-gray-400">
        <span className="bg-gray-700 px-2 py-0.5 rounded font-mono">source: {data?.source ?? "—"}</span>
        <span>Cache age: {cacheAgeLabel}</span>
        {data?.ttl_seconds != null && <span>TTL: {data.ttl_seconds}s</span>}
        <span>Showing <span className="text-gray-200 font-semibold">{data?.returned_count ?? 0}</span> of <span className="text-gray-200 font-semibold">{data?.total_count ?? 0}</span></span>
        {data?.stale && <span className="text-yellow-400">⚠ stale</span>}
      </div>

      {items.length === 0 ? (
        <p className="text-gray-500 text-sm py-4 text-center">No earnings rows. {data?.warning ?? ""}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-400 border-b border-gray-700">
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Date</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Time</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Ticker</th>
                <th className="pb-2 pr-2 text-right whitespace-nowrap">Days Until</th>
                <th className="pb-2 pr-2 text-right whitespace-nowrap">EPS Estimate</th>
                <th className="pb-2 pr-2 text-right whitespace-nowrap">Revenue Estimate</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Confirmed</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Source</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Last Refreshed</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r, i) => (
                <tr key={`${r.ticker}-${r.report_date}-${i}`} className="border-b border-gray-800 hover:bg-gray-800/40">
                  <td className="py-1.5 pr-2 font-mono text-xs text-gray-300 whitespace-nowrap">{r.report_date ?? "—"}</td>
                  <td className="py-1.5 pr-2 text-xs text-gray-400 whitespace-nowrap">{r.report_time ?? "—"}</td>
                  <td className="py-1.5 pr-2 font-mono font-semibold text-yellow-300 whitespace-nowrap">{r.ticker}</td>
                  <td className="py-1.5 pr-2 font-mono text-xs text-right whitespace-nowrap">{r.days_until ?? "—"}</td>
                  <td className="py-1.5 pr-2 font-mono text-xs text-right whitespace-nowrap text-gray-300">{r.eps_estimate ?? "—"}</td>
                  <td className="py-1.5 pr-2 font-mono text-xs text-right whitespace-nowrap text-gray-300">{r.revenue_estimate ?? "—"}</td>
                  <td className="py-1.5 pr-2 text-xs text-gray-400 whitespace-nowrap">{String(r.confirmed ?? "unknown")}</td>
                  <td className="py-1.5 pr-2 text-xs text-gray-500 whitespace-nowrap">{r.source ?? "—"}</td>
                  <td className="py-1.5 pr-2 text-xs text-gray-600 whitespace-nowrap font-mono">{r.fetched_at?.slice(0, 19) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Insiders tab (Phase I6) ──────────────────────────────────────────────────

interface InsiderRow {
  ticker: string;
  transaction_date: string | null;
  insider_name: string | null;
  insider_title?: string | null;
  transaction_code: string | null;
  transaction_type: string;
  buy_sell_label: string;
  shares: number | null;
  price: number | null;
  value: number | null;
  is_discretionary_buy: boolean | "unknown" | null;
  is_recent: boolean | null;
  source: string | null;
  fetched_at: string | null;
  warning?: string | null;
}

interface InsiderSnapshot {
  ok: boolean;
  enabled: boolean;
  available?: boolean;
  implemented: boolean;
  provider_status?: "not_configured" | "configured_but_unwired" | "active" | string;
  source: string | null;
  fetched_at: string | null;
  cache_age_seconds: number | null;
  ttl_seconds: number | null;
  stale: boolean;
  total_count: number;
  returned_count: number;
  limit: number;
  offset: number;
  filters_applied?: Record<string, unknown>;
  sort_by?: string;
  sort_dir?: string;
  results: InsiderRow[];
  errors?: unknown[];
  warning: string | null;
  note?: string;
}

function InsidersTab({ token }: { token: string }) {
  const [data, setData] = useState<InsiderSnapshot | null>(null);
  const [ticker, setTicker] = useState("");
  const [txnType, setTxnType] = useState("");
  const [minValue, setMinValue] = useState<number | "">("");
  const [daysBack, setDaysBack] = useState(30);
  const [sortBy, setSortBy] = useState("transaction_date");
  const [sortDir, setSortDir] = useState("desc");
  const [limit, setLimit] = useState(100);
  const [refreshMsg, setRefreshMsg] = useState("");

  const fetchInsidersLocal = useCallback(async () => {
    const params = new URLSearchParams();
    if (ticker.trim()) params.set("ticker", ticker.trim());
    if (txnType) params.set("transaction_type", txnType);
    if (minValue !== "" && !Number.isNaN(Number(minValue))) params.set("min_value", String(minValue));
    params.set("days_back", String(daysBack));
    params.set("sort_by", sortBy);
    params.set("sort_dir", sortDir);
    params.set("limit", String(limit));
    try {
      const r = await fetch(`/api/intelligence/insiders?${params.toString()}`);
      if (r.ok) setData(await r.json());
    } catch { /* ignore */ }
  }, [ticker, txnType, minValue, daysBack, sortBy, sortDir, limit]);

  useEffect(() => {
    const id = setTimeout(() => { fetchInsidersLocal(); }, 300);
    return () => clearTimeout(id);
  }, [fetchInsidersLocal]);

  async function handleRefresh() {
    if (!token) { setRefreshMsg("Enter ADMIN_API_TOKEN to refresh."); return; }
    setRefreshMsg("Refreshing insider cache…");
    try {
      const r = await fetch("/api/intelligence/insiders/refresh", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await r.json();
      if (r.ok && body.ok) {
        setRefreshMsg(`Refreshed — ${body.total_count ?? 0} items. ${body.warning ?? ""}`);
        await fetchInsidersLocal();
      } else {
        setRefreshMsg(`Failed: ${body.error ?? body.detail ?? JSON.stringify(body)}`);
      }
    } catch (e) {
      setRefreshMsg(`Error: ${String(e)}`);
    }
  }

  const items = data?.results ?? [];
  const cacheAge = data?.cache_age_seconds;
  const cacheAgeLabel = cacheAge == null ? "—"
    : cacheAge < 60 ? `${cacheAge}s ago`
    : cacheAge < 3600 ? `${Math.round(cacheAge / 60)}m ago`
    : `${Math.round(cacheAge / 3600)}h ago`;

  return (
    <div>
      <div className="mb-3 rounded border border-blue-800 bg-blue-950 px-3 py-2 text-xs text-blue-300">
        <span className="font-semibold">Only recent open-market purchases are treated as bullish.</span>{" "}
        Sales, awards, tax withholding, and option exercises are surfaced informationally but do not
        auto-create bearish penalties.
      </div>

      {(data?.enabled === false || data?.available === false) && (
        <div className="mb-3 rounded border border-yellow-700 bg-yellow-950 px-3 py-2 text-xs text-yellow-300">
          ⚠{" "}
          {data?.provider_status === "configured_but_unwired"
            ? `Provider ${data?.source ?? "?"} is configured but no fetcher is implemented yet. No fake data shown.`
            : data?.provider_status === "not_configured"
            ? "Insider provider is not configured. No fake data shown."
            : data?.warning ?? "Insider provider unavailable."}
          {data?.provider_status && (
            <span className="ml-2 text-yellow-500 font-mono">
              [provider_status: {data.provider_status}]
            </span>
          )}
        </div>
      )}

      <div className="mb-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-2">
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          placeholder="Ticker (e.g. NVDA)"
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-blue-500"
        />
        <select
          value={txnType}
          onChange={(e) => setTxnType(e.target.value)}
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="">Type: any</option>
          <option value="open_market_purchase">open_market_purchase</option>
          <option value="sale">sale</option>
          <option value="option_exercise">option_exercise</option>
          <option value="stock_award">stock_award</option>
          <option value="tax_withholding">tax_withholding</option>
          <option value="gift">gift</option>
          <option value="other">other</option>
        </select>
        <input
          type="number"
          value={minValue}
          onChange={(e) => setMinValue(e.target.value === "" ? "" : Number(e.target.value))}
          placeholder="Min value (USD)"
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-blue-500"
        />
        <select
          value={daysBack}
          onChange={(e) => setDaysBack(parseInt(e.target.value, 10))}
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value={7}>Last 7 days</option>
          <option value={14}>Last 14 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="transaction_date">Sort: Date</option>
          <option value="value">Sort: Value</option>
          <option value="ticker">Sort: Ticker</option>
          <option value="transaction_type">Sort: Type</option>
        </select>
        <select
          value={sortDir}
          onChange={(e) => setSortDir(e.target.value)}
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="desc">Newest / High → Low</option>
          <option value="asc">Oldest / Low → High</option>
        </select>
        <select
          value={limit}
          onChange={(e) => setLimit(parseInt(e.target.value, 10))}
          className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value={50}>Limit: 50</option>
          <option value={100}>Limit: 100</option>
          <option value={250}>Limit: 250</option>
          <option value={500}>Limit: 500</option>
        </select>
        <button
          onClick={handleRefresh}
          disabled={!token}
          title={token ? "Force fresh fetch (admin)" : "Enter ADMIN_API_TOKEN in Controls to enable"}
          className={`px-3 py-1.5 rounded text-sm font-semibold transition-colors ${
            token ? "bg-blue-700 hover:bg-blue-600" : "bg-gray-800 text-gray-500 cursor-not-allowed"
          }`}
        >
          ↺ Refresh
        </button>
      </div>

      {refreshMsg && <p className="text-xs text-yellow-300 font-mono mb-3">{refreshMsg}</p>}

      <div className="flex flex-wrap items-center gap-3 mb-3 text-xs text-gray-400">
        <span className="bg-gray-700 px-2 py-0.5 rounded font-mono">source: {data?.source ?? "—"}</span>
        <span>Cache age: {cacheAgeLabel}</span>
        {data?.ttl_seconds != null && <span>TTL: {data.ttl_seconds}s</span>}
        <span>Showing <span className="text-gray-200 font-semibold">{data?.returned_count ?? 0}</span> of <span className="text-gray-200 font-semibold">{data?.total_count ?? 0}</span></span>
        {data?.stale && <span className="text-yellow-400">⚠ stale</span>}
      </div>

      {items.length === 0 ? (
        <p className="text-gray-500 text-sm py-4 text-center">No insider transactions. {data?.warning ?? ""}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-400 border-b border-gray-700">
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Date</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Ticker</th>
                <th className="pb-2 pr-2 text-left">Insider</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Code</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Type</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Label</th>
                <th className="pb-2 pr-2 text-right whitespace-nowrap">Shares</th>
                <th className="pb-2 pr-2 text-right whitespace-nowrap">Price</th>
                <th className="pb-2 pr-2 text-right whitespace-nowrap">Value</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Discretionary?</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Source</th>
                <th className="pb-2 pr-2 text-left whitespace-nowrap">Last Refreshed</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r, i) => {
                const labelColor =
                  r.buy_sell_label === "bullish_buy" ? "text-green-400" :
                  r.buy_sell_label === "informational_buy" ? "text-emerald-500" :
                  r.buy_sell_label === "sale" ? "text-red-400" :
                  r.buy_sell_label === "neutral_compensation" ? "text-gray-400" : "text-gray-500";
                return (
                  <tr key={`${r.ticker}-${r.transaction_date}-${i}`} className="border-b border-gray-800 hover:bg-gray-800/40">
                    <td className="py-1.5 pr-2 font-mono text-xs text-gray-300 whitespace-nowrap">{r.transaction_date ?? "—"}</td>
                    <td className="py-1.5 pr-2 font-mono font-semibold text-yellow-300 whitespace-nowrap">{r.ticker}</td>
                    <td className="py-1.5 pr-2 text-xs text-gray-300 max-w-[160px] truncate" title={`${r.insider_name ?? ""} ${r.insider_title ? "(" + r.insider_title + ")" : ""}`}>
                      {r.insider_name ?? "—"}
                    </td>
                    <td className="py-1.5 pr-2 font-mono text-xs text-blue-300 whitespace-nowrap">{r.transaction_code ?? "—"}</td>
                    <td className="py-1.5 pr-2 text-xs text-gray-400 whitespace-nowrap">{r.transaction_type}</td>
                    <td className={`py-1.5 pr-2 text-xs font-semibold whitespace-nowrap ${labelColor}`}>{r.buy_sell_label}</td>
                    <td className="py-1.5 pr-2 font-mono text-xs text-right whitespace-nowrap">{r.shares?.toLocaleString() ?? "—"}</td>
                    <td className="py-1.5 pr-2 font-mono text-xs text-right whitespace-nowrap">{r.price != null ? `$${Number(r.price).toFixed(2)}` : "—"}</td>
                    <td className="py-1.5 pr-2 font-mono text-xs text-right whitespace-nowrap">{r.value != null ? `$${Number(r.value).toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—"}</td>
                    <td className="py-1.5 pr-2 text-xs text-gray-400 whitespace-nowrap">{String(r.is_discretionary_buy ?? "unknown")}</td>
                    <td className="py-1.5 pr-2 text-xs text-gray-500 whitespace-nowrap">{r.source ?? "—"}</td>
                    <td className="py-1.5 pr-2 text-xs text-gray-600 whitespace-nowrap font-mono">{r.fetched_at?.slice(0, 19) ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

interface LLMStatus {
  enabled: boolean;
  provider: string;
  model: string;
  api_key_env: string;
  api_key_present: boolean;
  max_candidates_per_tick: number;
  calls_total: number;
  calls_last_tick: number;
  calls_success: number;
  calls_error: number;
  cache_hits: number;
  cache_misses: number;
  average_latency_ms: number | null;
  last_call_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  last_model_used: string | null;
  prompt_version: string;
  disclaimer: string;
}

function LLMPlaceholderTab() {
  const [data, setData] = useState<LLMStatus | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch("/api/intelligence/llm/status");
      if (r.ok) setData(await r.json());
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetchStatus();
    const id = setInterval(fetchStatus, 30_000);
    return () => clearInterval(id);
  }, [fetchStatus]);

  if (!data && loading) {
    return <div className="text-center py-8 text-gray-500 text-sm animate-pulse">Loading LLM status…</div>;
  }

  const statusLabel = !data ? "unknown"
    : !data.enabled ? "DISABLED"
    : !data.api_key_present ? "KEY MISSING"
    : data.last_error ? "ENABLED · last call errored"
    : "ENABLED";
  const statusColor = !data ? "text-gray-500"
    : !data.enabled ? "bg-gray-800 text-gray-400 border-gray-600"
    : !data.api_key_present ? "bg-yellow-900 text-yellow-300 border-yellow-700"
    : data.last_error ? "bg-orange-900 text-orange-300 border-orange-700"
    : "bg-green-900 text-green-300 border-green-700";

  return (
    <div className="space-y-4">
      <div className="rounded border border-purple-900 bg-purple-950/30 px-3 py-2 text-xs text-purple-300">
        <span className="font-semibold">LLM Shadow Analyst.</span>{" "}
        Diagnostic only — does not affect entries, exits, or position sizing. The model reviews structured data
        and returns WOULD_ENTER / WATCH / WOULD_REJECT plus reasoning. Cache-first; max-per-tick capped.
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${statusColor}`}>
          Status: {statusLabel}
        </span>
        <span className="text-xs text-gray-400 border border-gray-700 rounded px-2 py-0.5">
          Provider: <span className="font-mono">{data?.provider ?? "—"}</span>
        </span>
        <span className="text-xs text-gray-400 border border-gray-700 rounded px-2 py-0.5">
          Model: <span className="font-mono">{data?.model ?? "—"}</span>
        </span>
        <span className={`text-xs px-2 py-0.5 rounded border font-mono ${
          data?.api_key_present
            ? "bg-green-950 text-green-400 border-green-800"
            : "bg-gray-800 text-gray-500 border-gray-600"
        }`}>
          Key ({data?.api_key_env ?? "?"}): {data?.api_key_present ? "present" : "missing"}
        </span>
        <span className="text-xs text-gray-500 border border-gray-700 rounded px-2 py-0.5">
          Max/tick: {data?.max_candidates_per_tick ?? "—"}
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatBox label="Calls (total)" value={String(data?.calls_total ?? 0)} />
        <StatBox label="Calls (last tick)" value={String(data?.calls_last_tick ?? 0)} />
        <StatBox label="Cache hits" value={String(data?.cache_hits ?? 0)} cls="text-green-400" />
        <StatBox label="Cache misses" value={String(data?.cache_misses ?? 0)} cls="text-gray-400" />
        <StatBox label="Success" value={String(data?.calls_success ?? 0)} cls="text-green-400" />
        <StatBox label="Errors" value={String(data?.calls_error ?? 0)} cls={(data?.calls_error ?? 0) > 0 ? "text-red-400" : "text-gray-400"} />
        <StatBox label="Avg latency" value={data?.average_latency_ms != null ? `${data.average_latency_ms} ms` : "—"} />
        <StatBox label="Prompt version" value={data?.prompt_version ?? "—"} />
      </div>

      {data?.last_error && (
        <div className="rounded border border-orange-700 bg-orange-950 px-3 py-2 text-xs text-orange-300 font-mono">
          last_error: {data.last_error}
        </div>
      )}

      <div className="text-xs text-gray-500">
        <p>Last call: {data?.last_call_at ?? "—"}</p>
        <p>Last success: {data?.last_success_at ?? "—"}</p>
        <p className="italic mt-1">{data?.disclaimer ?? "LLM shadow only; does not affect trading decisions."}</p>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Home() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [journal, setJournal] = useState<JournalData | null>(null);
  const [monitoring, setMonitoring] = useState<MonitoringStatus | null>(null);
  const [todayReport, setTodayReport] = useState<TodayReport | null>(null);
  const [readiness, setReadiness] = useState<ReadinessData | null>(null);
  const [loading, setLoading] = useState(true);
  const [token, setToken] = useState("");
  const [actionMsg, setActionMsg] = useState("");
  const [lastRefresh, setLastRefresh] = useState("");
  const [reddit, setReddit] = useState<RedditSnapshot | null>(null);
  const [premarket, setPremarket] = useState<PremarketSnapshot | null>(null);
  const [marketTrend, setMarketTrend] = useState<MarketTrendData | null>(null);
  const [runtimeConfig, setRuntimeConfig] = useState<RuntimeConfigState | null>(null);
  const [topTab, setTopTab] = useState<"main" | "intelligence" | "strategy">("main");

  // Note: NewsTab / EarningsTab / InsidersTab manage their own cache-first
  // fetches with filters. They are not part of the global 30s loop so the
  // Intelligence feeds incur no recurring external API pressure when the tab
  // is not open.

  const refresh = useCallback(async () => {
    const [data, jdata, mdata, tdata, rdata, rddata, pmdata, rcfgdata, mtdata] = await Promise.all([
      fetchDashboard(), fetchJournal(), fetchMonitoringStatus(), fetchTodayReport(), fetchReadiness(),
      fetchReddit(), fetchPremarket(), fetchRuntimeConfig(), fetchMarketTrend(),
    ]);
    setDashboard(data);
    setJournal(jdata);
    setMonitoring(mdata);
    setTodayReport(tdata);
    setReadiness(rdata);
    setReddit(rddata);
    setPremarket(pmdata);
    setRuntimeConfig(rcfgdata);
    setMarketTrend(mtdata);
    setLoading(false);
    setLastRefresh(new Date().toUTCString());
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  async function handleAction(path: string, label: string) {
    if (!token) { setActionMsg("Enter ADMIN_API_TOKEN first."); return; }
    setActionMsg(`Running ${label}…`);
    const { ok, body } = await adminPost(path, token);
    if (ok) {
      setActionMsg(`${label} OK`);
      await refresh();
    } else {
      const detail = (body as { detail?: string })?.detail || JSON.stringify(body);
      setActionMsg(`${label} failed: ${detail}`);
    }
  }

  const s = dashboard?.status;

  return (
    <main className="min-h-screen bg-gray-950 text-white p-6 max-w-[1800px] mx-auto">

      {/* Disclaimer */}
      <div className="mb-5 rounded-lg border border-yellow-600 bg-yellow-950 px-5 py-3 text-yellow-300 text-sm font-semibold">
        ⚠ Research-only fake-money simulation. No broker. No live trading. No real orders.
        All P&amp;L is virtual and for research purposes only. Not financial advice.
      </div>

      <h1 className="text-3xl font-bold mb-1">Microtrading Research Dashboard</h1>
      <p className="text-gray-400 text-sm mb-1">
        Fake-money simulator · No broker · No live trading · No real orders · Phase 2M
      </p>
      <p className="text-gray-500 text-xs mb-6">
        Auto-refreshes every 30s · Last: <span className="font-mono text-gray-400">{lastRefresh || "—"}</span>
      </p>

      {loading && <p className="text-gray-400 animate-pulse">Loading…</p>}

      {/* Top-level tab navigation (Phase I5) */}
      <nav className="mb-5 flex flex-wrap gap-1 border-b border-gray-700 pb-1">
        {([
          { key: "main",          label: "📊 Main Dashboard" },
          { key: "intelligence",  label: "🧠 Intelligence" },
          { key: "strategy",      label: "⚙ Strategy Settings" },
        ] as const).map((t) => (
          <button
            key={t.key}
            onClick={() => setTopTab(t.key)}
            className={`px-4 py-2 rounded-t text-sm font-semibold transition-colors ${
              topTab === t.key
                ? "bg-gray-800 text-white border border-b-transparent border-gray-600"
                : "text-gray-400 hover:text-gray-200 hover:bg-gray-800/60"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {topTab === "main" && (<>
      {/* Market Session Readiness */}
      <section className="mb-6 bg-gray-800 rounded-lg border border-gray-700 p-4">
        <h2 className="text-lg font-semibold mb-3">
          Market Session Readiness
          <span className="ml-2 text-xs font-normal text-gray-400">
            13 checks · fake-money only · no broker · no real orders
          </span>
        </h2>
        <ReadinessPanel readiness={readiness} config={runtimeConfig} />
      </section>

      {/* Monitoring Status */}
      <section className="mb-6 bg-gray-800 rounded-lg border border-gray-700 p-4">
        <h2 className="text-lg font-semibold mb-3">
          Monitoring Status
          <span className="ml-2 text-xs font-normal text-gray-400">
            backend · simulator · journal · market session
          </span>
        </h2>
        <MonitoringPanel monitoring={monitoring} />
      </section>

      {/* Market Regime */}
      <section className="mb-6 bg-gray-800 rounded-lg border border-gray-700 p-4">
        <h2 className="text-lg font-semibold mb-3">
          Market Regime
          <span className="ml-2 text-xs font-normal text-gray-400">
            breadth/risk context · used by selected fake-money entry gates
          </span>
        </h2>
        <MarketRegimePanel regime={dashboard?.market_regime ?? null} />
      </section>

      {/* Market Trend (Phase M1) */}
      <section className="mb-6 bg-gray-800 rounded-lg border border-gray-700 p-4">
        <h2 className="text-lg font-semibold mb-3">
          Market Trend
          <span className="ml-2 text-xs font-normal text-gray-400">
            ETF proxy momentum · 5/10/15-minute rolling deltas · futures not configured
          </span>
        </h2>
        <MarketTrendPanel trend={marketTrend} />
      </section>

      {/* Session Readiness */}
      <section className="mb-6 bg-gray-800 rounded-lg border border-gray-700 p-4">
        <h2 className="text-lg font-semibold mb-3">Session Readiness</h2>
        <SessionReadiness analytics={dashboard?.analytics ?? null} status={dashboard?.status} />
      </section>

      {/* Account stats */}
      {s && (
        <section className="mb-6">
          <div className="flex flex-wrap items-center gap-3 mb-3">
            <h2 className="text-xl font-semibold">Account</h2>
            <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${
              s.running
                ? "bg-green-900 text-green-300 border-green-700"
                : "bg-gray-800 text-gray-400 border-gray-600"
            }`}>
              {s.running ? "● RUNNING" : "○ STOPPED"}
            </span>
            {s.last_error && (
              <span className="text-xs text-red-400 font-mono bg-red-950 px-2 py-0.5 rounded border border-red-800 truncate max-w-xs">
                ERR: {s.last_error}
              </span>
            )}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 mb-3">
            <StatBox label="Starting Cash" value={`$${fmt(s.starting_cash)}`} />
            <StatBox label="Cash" value={`$${fmt(s.cash)}`} />
            <StatBox label="Equity" value={`$${fmt(s.equity)}`} />
            <StatBox label="Realized P&L" value={fmtUSD(s.realized_pnl)} cls={pnlClass(s.realized_pnl)} />
            <StatBox label="Unrealized P&L" value={fmtUSD(s.unrealized_pnl)} cls={pnlClass(s.unrealized_pnl)} />
            <StatBox label="Total P&L" value={`${fmtUSD(s.total_pnl)} (${fmt(s.total_pnl_percent)}%)`} cls={pnlClass(s.total_pnl)} />
            <StatBox label="Trades Today" value={`${s.daily_trade_count} / ${s.max_trades_per_day}`} />
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
            <StatBox label="Open Positions" value={String(s.open_position_count)} />
            <StatBox label="Closed Trades" value={String(s.closed_trade_count)} />
            <StatBox label="Take Profit" value={`+${s.take_profit_percent}%`} />
            <StatBox label="Stop Loss" value={`-${s.stop_loss_percent}%`} />
            <StatBox label="Max Hold" value={`${s.max_hold_minutes}m`} />
            <StatBox label="Snapshot Storage" value={s.snapshot_storage ?? "memory"} />
            {(() => {
              const restartPersistentKnown = typeof s.restart_persistent === "boolean";
              const restartPersistentLabel = restartPersistentKnown ? String(s.restart_persistent) : "unknown";
              const restartPersistentClass = restartPersistentKnown
                ? (s.restart_persistent ? "text-green-400" : "text-red-400")
                : "text-slate-400";
              return <StatBox label="Restart Persistent" value={restartPersistentLabel} cls={restartPersistentClass} />;
            })()}
          </div>
          {s.daily_loss_guard && (
            <div className={`mt-2 flex flex-wrap gap-3 text-xs font-mono px-1 py-1 rounded border ${
              s.daily_loss_guard.triggered
                ? "border-red-700 bg-red-950 text-red-300"
                : "border-gray-700 bg-gray-900 text-gray-400"
            }`}>
              <span>Loss Guard: {s.daily_loss_guard.enabled ? (s.daily_loss_guard.triggered ? "TRIGGERED" : "active") : "disabled"}</span>
              <span>Daily P&L: <span className={pnlClass(s.daily_loss_guard.daily_pnl)}>{fmtUSD(s.daily_loss_guard.daily_pnl)} ({fmt(s.daily_loss_guard.daily_pnl_percent)}%)</span></span>
              <span>Threshold: -{s.daily_loss_guard.threshold_percent}%{s.daily_loss_guard.threshold_usd ? ` / $${s.daily_loss_guard.threshold_usd}` : ""}</span>
              {s.daily_loss_guard.triggered && s.daily_loss_guard.reason && (
                <span className="text-red-400 font-semibold">Reason: {s.daily_loss_guard.reason}</span>
              )}
            </div>
          )}
          {monitoring?.catalyst_type_guard && !monitoring.catalyst_type_guard.error && (
            <div className={`mt-2 flex flex-wrap gap-3 text-xs font-mono px-1 py-1 rounded border ${
              monitoring.catalyst_type_guard.enabled && monitoring.catalyst_type_guard.blocked_candidates_last_tick > 0
                ? "border-yellow-700 bg-yellow-950 text-yellow-300"
                : "border-gray-700 bg-gray-900 text-gray-400"
            }`}>
              <span>Cat Type Guard: {monitoring.catalyst_type_guard.enabled ? "active" : "disabled"}</span>
              {monitoring.catalyst_type_guard.enabled && (
                <>
                  <span>Blocked types: {monitoring.catalyst_type_guard.blocked_catalyst_types.length > 0 ? monitoring.catalyst_type_guard.blocked_catalyst_types.join(", ") : "none"}</span>
                  <span>Blocked last tick: {monitoring.catalyst_type_guard.blocked_candidates_last_tick}</span>
                </>
              )}
            </div>
          )}
          {s.last_tick_at && (
            <p className="text-xs text-gray-500 mt-2">Last tick: {utcShort(s.last_tick_at)}</p>
          )}
        </section>
      )}

      {/* Controls */}
      <section className="mb-6 bg-gray-800 rounded-lg border border-gray-700 p-4">
        <h2 className="text-lg font-semibold mb-3">Controls</h2>
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-400">ADMIN_API_TOKEN</label>
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="paste token here"
              className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm font-mono w-56 focus:outline-none focus:border-blue-500"
            />
          </div>
          {[
            { label: "▶ Start",          path: "/api/paper/start"           },
            { label: "■ Stop",           path: "/api/paper/stop"            },
            { label: "↺ Reset",          path: "/api/paper/reset"           },
            { label: "⚡ Tick",          path: "/api/paper/tick"            },
            { label: "🌐 Universe",      path: "/api/paper/universe/refresh"},
          ].map(({ label, path }) => (
            <button
              key={path}
              onClick={() => handleAction(path, label)}
              className="px-4 py-1.5 bg-blue-700 hover:bg-blue-600 active:bg-blue-800 rounded text-sm font-semibold transition-colors"
            >
              {label}
            </button>
          ))}
        </div>
        {actionMsg && (
          <p className="mt-2 text-sm text-yellow-300 font-mono">{actionMsg}</p>
        )}
      </section>

      {/* Open positions */}
      <section className="mb-6">
        <h2 className="text-xl font-semibold mb-3">
          Open Positions ({dashboard?.positions.length ?? 0})
        </h2>
        <PositionsTable positions={dashboard?.positions ?? []} />
      </section>

      {/* Closed trades */}
      <section className="mb-6">
        <h2 className="text-xl font-semibold mb-3">
          Closed Trades ({dashboard?.trades.length ?? 0})
        </h2>
        <TradesTable trades={dashboard?.trades ?? []} />
      </section>

      {/* Last tick candidates */}
      <section className="mb-6">
        <h2 className="text-xl font-semibold mb-3">Last Tick — Candidate Decisions</h2>
        <CandidatesTable candidates={dashboard?.last_candidates ?? []} />
      </section>

      {/* Paper Universe */}
      <section className="mb-6 bg-gray-800 rounded-lg border border-gray-700 p-4">
        <h2 className="text-lg font-semibold mb-3">
          Paper Universe
          <span className="ml-2 text-xs font-normal text-gray-400">
            dynamic · ranked by movement · fake-money only
          </span>
        </h2>
        <UniverseSection universe={dashboard?.universe ?? null} />
      </section>

      {/* Market Discovery */}
      <section className="mb-6 bg-gray-800 rounded-lg border border-gray-700 p-4">
        <h2 className="text-lg font-semibold mb-3">
          Market Discovery
          <span className="ml-2 text-xs font-normal text-gray-400">
            movers expansion · candidate pool only · no gate bypass
          </span>
        </h2>
        <MarketDiscoveryPanel
          discovery={dashboard?.universe?.discovery ?? null}
          token={token}
          onRefresh={refresh}
        />
      </section>

      {/* Analytics */}
      <section className="mb-6 bg-gray-800 rounded-lg border border-gray-700 p-4">
        <h2 className="text-lg font-semibold mb-3">
          Analytics
          <span className="ml-2 text-xs font-normal text-gray-400">
            fake-money · no broker · research-only
          </span>
        </h2>
        <AnalyticsPanel analytics={dashboard?.analytics ?? null} />
      </section>

      {/* Today / Session Report */}
      <section className="mb-6 bg-gray-800 rounded-lg border border-gray-700 p-4">
        <h2 className="text-lg font-semibold mb-3">
          Today / Session Report
          <span className="ml-2 text-xs font-normal text-gray-400">
            daily journal · fake-money · no broker
          </span>
        </h2>
        <TodayReportPanel report={todayReport} />
      </section>

      {/* Journal / History */}
      <section className="mb-6 bg-gray-800 rounded-lg border border-gray-700 p-4">
        <h2 className="text-lg font-semibold mb-3">
          Journal / History
          <span className="ml-2 text-xs font-normal text-gray-400">
            persistent PostgreSQL log · fake-money · no broker
          </span>
        </h2>
        <JournalPanel journal={journal} />
      </section>
      </>)}

      {topTab === "strategy" && (
        <section className="mb-6 bg-gray-800 rounded-lg border border-gray-700 p-4">
          <h2 className="text-lg font-semibold mb-3">
            Strategy Settings
            <span className="ml-2 text-xs font-normal text-gray-400">
              runtime config · admin-protected · fake-money only
            </span>
          </h2>
          <StrategySettingsPanel token={token} onRefresh={refresh} />
        </section>
      )}

      {topTab === "intelligence" && (
        <section className="mb-6 bg-gray-800 rounded-lg border border-gray-700 p-4">
          <h2 className="text-lg font-semibold mb-1">
            Intelligence
            <span className="ml-2 text-xs font-normal text-gray-400">
              read-only · no trading integration · rule-based · no AI/LLM · Phase I5
            </span>
          </h2>
          <IntelligenceSection
            reddit={reddit}
            premarket={premarket}
            token={token}
            onRefresh={refresh}
          />
        </section>
      )}

      <footer className="text-center text-xs text-gray-600 mt-8 border-t border-gray-800 pt-4 space-y-1">
        <p>{dashboard?.disclaimer}</p>
        <p>
          mode: {s?.mode ?? "—"} · live_trading: {String(s?.live_trading_enabled ?? false)} ·{" "}
          broker: {String(s?.broker_connected ?? false)} · restart_persistent:{" "}
          {s != null ? String(s.restart_persistent) : "unknown"}
        </p>
        <p className="text-gray-700">
          restore_source: {s?.restore_source ?? "none"} · restored_closed_trades:{" "}
          {s?.restored_closed_trades_count ?? "—"} · restored_open_positions:{" "}
          {s?.restored_open_positions_count ?? "—"} · restored_pnl:{" "}
          {typeof s?.restored_daily_realized_pnl === "number"
            ? `$${s.restored_daily_realized_pnl.toFixed(2)}`
            : "—"}{" "}
          · restored_trades_today: {s?.restored_trades_today ?? "—"}
        </p>
        {s?.restore_warning && (
          <p className="text-yellow-500">
            restore_warning: {s.restore_warning}
          </p>
        )}
        {s?.restore_warnings && s.restore_warnings.length > 0 && (
          <p className="text-yellow-600">
            restore_warnings: {s.restore_warnings.join(" | ")}
          </p>
        )}
      </footer>
    </main>
  );
}
