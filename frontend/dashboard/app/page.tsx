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
  mode: string;
  live_trading_enabled: boolean;
  broker_connected: boolean;
  take_profit_percent: number;
  stop_loss_percent: number;
  max_hold_minutes: number;
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

interface UniverseInfo {
  base_symbols: string[];
  dynamic_symbols: string[];
  active_symbols: string[];
  active_count: number;
  max_symbols_per_tick: number;
  last_refreshed_at: string | null;
  refresh_reason: string;
  errors: Array<{ symbol?: string; error: string }>;
}

interface Dashboard {
  status: PaperStatus;
  positions: Position[];
  trades: Trade[];
  last_candidates: Candidate[];
  universe: UniverseInfo | null;
  analytics: Analytics | null;
  disclaimer: string;
}

// ── Journal types ─────────────────────────────────────────────────────────────

interface JournalStatus {
  enabled: boolean;
  database_connected: boolean;
  tables_ready: boolean;
  last_error: string | null;
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
            {["Symbol","✓","Action","Score","Components","Spread%","Chg%","Cats","Type","Decision / Rejection"].map((h) => (
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

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Home() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [journal, setJournal] = useState<JournalData | null>(null);
  const [loading, setLoading] = useState(true);
  const [token, setToken] = useState("");
  const [actionMsg, setActionMsg] = useState("");
  const [lastRefresh, setLastRefresh] = useState("");

  const refresh = useCallback(async () => {
    const [data, jdata] = await Promise.all([fetchDashboard(), fetchJournal()]);
    setDashboard(data);
    setJournal(jdata);
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
        Fake-money simulator · No broker · No live trading · No real orders · Phase 2E
      </p>
      <p className="text-gray-500 text-xs mb-6">
        Auto-refreshes every 30s · Last: <span className="font-mono text-gray-400">{lastRefresh || "—"}</span>
      </p>

      {loading && <p className="text-gray-400 animate-pulse">Loading…</p>}

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
            <StatBox label="Restart Persistent" value="false" cls="text-red-400" />
          </div>
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
          broker: {String(s?.broker_connected ?? false)} · restart_persistent: false
        </p>
        <p className="text-gray-700">
          Redis is used only for best-effort latest-state snapshot. Simulator state is not restored after container restart.
        </p>
      </footer>
    </main>
  );
}
