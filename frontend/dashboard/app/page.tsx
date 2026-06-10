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
  // Phase 2M momentum fields
  entry_mode: string | null;
  momentum_eligible: boolean | null;
  momentum_score: number | null;
  momentum_score_threshold: number | null;
  momentum_rejection_reason: string | null;
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
  enabled: boolean;
  symbols_requested: string[];
  symbols_fetched: string[];
  symbols_failed: string[];
  fetch_ratio: number;
  breadth: {
    total: number;
    positive: number;
    negative: number;
    flat: number;
    positive_percent: number | null;
    avg_change_percent: number | null;
  };
  leaders: {
    data: {
      SPY: MarketRegimeLeader | null;
      QQQ: MarketRegimeLeader | null;
      IWM: MarketRegimeLeader | null;
    };
    bullish_count: number;
    bearish_count: number;
  };
  risk: {
    regime: "risk_on" | "neutral" | "risk_off" | "unknown" | string;
    risk_on_score: number | null;
    confidence: "high" | "medium" | "low" | "unknown" | string;
    fetched_count: number;
  };
  as_of: string | null;
  disclaimer: string;
  error?: string;
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

function CandidatesTable({ candidates }: { candidates: Candidate[] }) {
  if (candidates.length === 0)
    return <p className="text-gray-500 text-sm">No tick data yet. Run ⚡ Tick to see candidates.</p>;
  return (
    <div className="overflow-x-auto">
      <p className="text-xs text-gray-600 mb-2">
        Components: Qual=Quality(max 25) · Sprd=Spread(15) · Mom=Momentum(20) · Vol=Volume(15) · Cat=Catalyst(20) · Risk=penalty(−20 max)
      </p>
      <table className="w-full text-sm text-left">
        <thead className="text-gray-400 border-b border-gray-700">
          <tr>
            {["Symbol","✓","Mode","Action","Score","Components","Spread%","Chg%","Cats","Type","Sentiment","Decision / Rejection"].map((h) => (
              <th key={h} className="pb-2 pr-4 font-medium whitespace-nowrap">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {candidates.map((c) => (
            <tr key={c.symbol} className="border-b border-gray-800 hover:bg-gray-800">
              <td className="py-2 pr-4 font-semibold text-yellow-300">{c.symbol}</td>
              <td className="py-2 pr-4">
                {c.eligible
                  ? <span className="text-green-400 font-bold">✓</span>
                  : <span className="text-red-400 font-bold">✗</span>}
              </td>
              <td className="py-2 pr-4 whitespace-nowrap">
                {c.entry_mode === "momentum"
                  ? <span className="text-purple-400 text-xs font-semibold px-1 rounded bg-purple-950 border border-purple-700">mom</span>
                  : c.entry_mode === "catalyst"
                  ? <span className="text-blue-400 text-xs font-semibold px-1 rounded bg-blue-950 border border-blue-700">cat</span>
                  : c.momentum_eligible
                  ? <span className="text-purple-600 text-xs font-mono">m?</span>
                  : <span className="text-gray-600 text-xs">—</span>}
              </td>
              <td className="py-2 pr-4 text-blue-300 whitespace-nowrap">{c.action || "—"}</td>
              <td className={`py-2 pr-4 font-mono font-semibold whitespace-nowrap ${scoreColor(c.total_score, c.score_threshold)}`}>
                {c.total_score != null ? `${c.total_score} / ${c.score_threshold ?? "?"}` : "—"}
              </td>
              <td className="py-2 pr-4 font-mono text-xs text-gray-400 whitespace-nowrap">
                {fmtComponents(c.score_components)}
              </td>
              <td className="py-2 pr-4 font-mono">{fmt(c.spread_percent, 3)}</td>
              <td className={`py-2 pr-4 font-mono ${c.change_percent != null ? pnlClass(c.change_percent) : ""}`}>
                {fmt(c.change_percent)}%
              </td>
              <td className="py-2 pr-4 font-mono">{c.catalyst_count}</td>
              <td className="py-2 pr-4 text-blue-300">{c.catalyst_type || "—"}</td>
              <td className="py-2 pr-4 whitespace-nowrap" title={
                c.catalyst_sentiment_reasons?.join("; ") ?? undefined
              }>
                {sentimentBadge(c.catalyst_sentiment)}
                {c.catalyst_materiality_score != null && (
                  <span className="text-gray-600 text-xs ml-1">{fmt(c.catalyst_materiality_score, 2)}</span>
                )}
              </td>
              <td className="py-2 pr-4 text-gray-400 text-xs max-w-xs truncate">
                {c.decision_reason || c.rejection_reason || "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
  { key: "PAPER_MIN_VOLUME_RATIO",                  label: "Min Volume Ratio",            type: "float", min: 0,    max: 5,   step: 0.05 },
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

// Momentum mode fields (Phase 2M — disabled by default)
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

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-500 italic">
        All editable settings in this panel are applied at runtime to fake-money simulation only.
        No broker, no live trading, no real orders.
        Changes take effect on the next tick and do not retroactively affect existing open positions.
      </p>

      {/* Status row */}
      <div className="flex flex-wrap gap-2 items-center text-xs">
        <span className={`font-semibold px-2 py-0.5 rounded border ${
          overrideCount > 0
            ? "bg-orange-900 text-orange-300 border-orange-700"
            : "bg-gray-800 text-gray-400 border-gray-600"
        }`}>
          {overrideCount > 0 ? `${overrideCount} override(s) active` : "No overrides — using base config"}
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
          return (
            <div key={f.key} className={`bg-gray-900 rounded p-3 border ${
              hasOverride ? "border-orange-700" : "border-gray-700"
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
              <div className="mt-1 flex gap-3 text-xs text-gray-500 font-mono">
                <span>base: {base !== null && base !== undefined ? String(base) : "—"}</span>
                {hasOverride && <span className="text-orange-400">override: {String(override)}</span>}
                <span className={hasOverride ? "text-orange-300 font-semibold" : "text-gray-400"}>
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
          const hasOverride = f.key in config.runtime_overrides;
          const effective = config.effective_config[f.key];
          return (
            <div key={f.key} className={`bg-gray-900 rounded p-3 border ${
              hasOverride ? "border-orange-700" : "border-gray-700"
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
                {hasOverride && <span className="text-orange-400">ovr: {String(effective)}</span>}
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
            const hasOverride = f.key in config.runtime_overrides;
            const effective = config.effective_config[f.key];
            return (
              <div key={f.key} className={`bg-gray-900 rounded p-3 border ${
                hasOverride ? "border-orange-700" : "border-gray-700"
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
                  {hasOverride && <span className="text-orange-400">ovr: {String(effective)}</span>}
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
            return (
              <div key={f.key} className={`bg-gray-900 rounded p-3 border ${
                hasOverride ? "border-orange-700" : "border-gray-700"
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
                <div className="mt-1 flex gap-3 text-xs text-gray-500 font-mono">
                  <span>base: {base !== null && base !== undefined ? String(base) : "—"}</span>
                  {hasOverride && <span className="text-orange-400">override: {String(override)}</span>}
                  <span className={hasOverride ? "text-orange-300 font-semibold" : "text-gray-400"}>
                    eff: {effective !== null && effective !== undefined ? String(effective) : "—"}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Momentum Mode section (Phase 2M — disabled by default) */}
      <div className="border border-purple-800 rounded p-3 bg-gray-950">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-sm font-semibold text-purple-300">Momentum Mode</span>
          <span className={`text-xs px-2 py-0.5 rounded border font-semibold ${
            drafts["PAPER_MOMENTUM_MODE_ENABLED"]
              ? "bg-orange-900 text-orange-300 border-orange-700"
              : "bg-gray-800 text-gray-500 border-gray-600"
          }`}>
            {drafts["PAPER_MOMENTUM_MODE_ENABLED"] ? "ENABLED" : "DISABLED (default)"}
          </span>
        </div>
        <p className="text-xs text-gray-500 italic mb-3">
          Fake-money simulation only. No broker. No live trading. No real orders.
          Momentum mode is a secondary entry path for candidates with no catalyst
          but strong price/volume signals. Disabled by default. Only enable for explicit research testing.
        </p>
        {/* Enable toggle */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
          {[
            { key: "PAPER_MOMENTUM_MODE_ENABLED", label: "Momentum Mode Enabled" },
            { key: "PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON", label: "Require Risk-On Regime" },
          ].map((f) => {
            const base = config.base_config[f.key];
            const hasOverride = f.key in config.runtime_overrides;
            const effective = config.effective_config[f.key];
            return (
              <div key={f.key} className={`bg-gray-900 rounded p-3 border ${
                hasOverride ? "border-orange-700" : "border-gray-700"
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
                  {hasOverride && <span className="text-orange-400">ovr: {String(effective)}</span>}
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
            return (
              <div key={f.key} className={`bg-gray-900 rounded p-3 border ${
                hasOverride ? "border-orange-700" : "border-gray-700"
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
                <div className="mt-1 flex gap-3 text-xs text-gray-500 font-mono">
                  <span>base: {base !== null && base !== undefined ? String(base) : "—"}</span>
                  {hasOverride && <span className="text-orange-400">override: {String(override)}</span>}
                  <span className={hasOverride ? "text-orange-300 font-semibold" : "text-gray-400"}>
                    eff: {effective !== null && effective !== undefined ? String(effective) : "—"}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

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

function MarketRegimePanel({ regime }: { regime: MarketRegimeData | null }) {
  if (!regime || !regime.enabled) {
    return (
      <p className="text-gray-500 text-sm">
        Market regime monitor disabled or data unavailable.
      </p>
    );
  }

  const { breadth, leaders, risk, as_of, symbols_fetched, symbols_failed, error } = regime;

  return (
    <div className="space-y-4">
      {/* Status badges */}
      <div className="flex flex-wrap gap-2 items-center">
        <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${regimeBadgeClass(risk?.regime)}`}>
          Regime: {risk?.regime ? risk.regime.replace("_", " ").toUpperCase() : "UNKNOWN"}
        </span>
        {risk?.risk_on_score != null && (
          <span className={`text-xs font-semibold px-2 py-0.5 rounded border bg-gray-800 border-gray-600 ${regimeColor(risk.regime)}`}>
            Score: {risk.risk_on_score} / 100
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
          {symbols_fetched?.length ?? 0} symbols fetched
          {(symbols_failed?.length ?? 0) > 0 && ` · ${symbols_failed.length} failed`}
        </span>
        {error && (
          <span className="text-xs text-red-400 font-mono bg-red-950 px-2 py-0.5 rounded border border-red-800 truncate max-w-xs">
            ERR: {error}
          </span>
        )}
      </div>

      {/* Breadth stats */}
      {breadth && (
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

      {as_of && (
        <p className="text-xs text-gray-600">
          As of: <span className="font-mono text-gray-500">{utcShort(as_of)}</span>
          {" · "}
          <span className="italic">{regime.disclaimer}</span>
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

function ReadinessPanel({ readiness }: { readiness: ReadinessData | null }) {
  if (!readiness)
    return <p className="text-gray-500 text-sm">Readiness data unavailable.</p>;

  const { overall_status, checks, summary, recommended_actions } = readiness;

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
        {checks.map((c) => (
          <div
            key={c.name}
            className={`rounded border px-3 py-2 text-xs ${
              c.status === "pass"
                ? "bg-gray-900 border-gray-700"
                : c.status === "warn"
                ? "bg-yellow-950 border-yellow-800"
                : "bg-red-950 border-red-800"
            }`}
          >
            <div className="flex items-center gap-1.5 mb-0.5">
              <span className={`font-bold ${checkStatusClass(c.status)}`}>
                {checkStatusIcon(c.status)}
              </span>
              <span className="font-mono text-gray-300 font-semibold">{c.name}</span>
            </div>
            <p className="text-gray-400 leading-snug">{c.message}</p>
          </div>
        ))}
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

  const refresh = useCallback(async () => {
    const [data, jdata, mdata, tdata, rdata] = await Promise.all([
      fetchDashboard(), fetchJournal(), fetchMonitoringStatus(), fetchTodayReport(), fetchReadiness(),
    ]);
    setDashboard(data);
    setJournal(jdata);
    setMonitoring(mdata);
    setTodayReport(tdata);
    setReadiness(rdata);
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
    <main className="min-h-screen bg-gray-950 text-white p-6 max-w-7xl mx-auto">

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

      {/* Market Session Readiness */}
      <section className="mb-6 bg-gray-800 rounded-lg border border-gray-700 p-4">
        <h2 className="text-lg font-semibold mb-3">
          Market Session Readiness
          <span className="ml-2 text-xs font-normal text-gray-400">
            13 checks · fake-money only · no broker · no real orders
          </span>
        </h2>
        <ReadinessPanel readiness={readiness} />
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
            observational only · breadth/risk context · no strategy changes
          </span>
        </h2>
        <MarketRegimePanel regime={dashboard?.market_regime ?? null} />
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
          {s.catalyst_type_guard && !s.catalyst_type_guard.error && (
            <div className={`mt-2 flex flex-wrap gap-3 text-xs font-mono px-1 py-1 rounded border ${
              s.catalyst_type_guard.enabled && s.catalyst_type_guard.blocked_candidates_last_tick > 0
                ? "border-yellow-700 bg-yellow-950 text-yellow-300"
                : "border-gray-700 bg-gray-900 text-gray-400"
            }`}>
              <span>Cat Type Guard: {s.catalyst_type_guard.enabled ? "active" : "disabled"}</span>
              {s.catalyst_type_guard.enabled && (
                <>
                  <span>Blocked types: {s.catalyst_type_guard.blocked_catalyst_types.length > 0 ? s.catalyst_type_guard.blocked_catalyst_types.join(", ") : "none"}</span>
                  <span>Blocked last tick: {s.catalyst_type_guard.blocked_candidates_last_tick}</span>
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

      {/* Strategy Settings */}
      <section className="mb-6 bg-gray-800 rounded-lg border border-gray-700 p-4">
        <h2 className="text-lg font-semibold mb-3">
          Strategy Settings
          <span className="ml-2 text-xs font-normal text-gray-400">
            runtime config · admin-protected · fake-money only
          </span>
        </h2>
        <StrategySettingsPanel token={token} onRefresh={refresh} />
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
