"""
Research paper simulator — fake-money simulation only.

No broker. No live trading. No real orders. No real-money execution.
All positions and P&L are purely virtual for research purposes.
"""

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from catalysts.news_collector import collect_news_for_symbols
from core.config import settings
from data import polygon_client
from paper.runtime_config import effective_value as _cfg, blocked_catalyst_types_list as _blocked_catalyst_types_list
from data.market_quality import evaluate_market_quality
from data.polygon_client import PolygonError
from data.redis_client import make_redis
from paper.account import PaperAccount
from paper.exits import evaluate_virtual_bracket_exit, get_intrabar_data
from paper.journal import persist_tick_result as _persist_journal_tick
from paper.momentum import evaluate_momentum_entry
from paper.no_catalyst_momentum import evaluate_no_catalyst_entry
from paper.risk import daily_loss_guard_triggered as _daily_loss_guard
from paper.scoring import score_candidate
from paper.universe import get_active_paper_universe, get_cached_universe

logger = logging.getLogger(__name__)

_REDIS_KEY = f"{settings.PAPER_STATE_REDIS_NAMESPACE}:state:v2"


def _ny_trading_date() -> str:
    """Return current calendar date in America/New_York as YYYY-MM-DD."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    except Exception:
        from datetime import timedelta
        return datetime.now(timezone(timedelta(hours=-4))).strftime("%Y-%m-%d")


# Module-level state — one instance per process
_account: PaperAccount = PaperAccount(settings.PAPER_STARTING_CASH)
_account.daily_baseline_date = _ny_trading_date()
_account.daily_start_equity = settings.PAPER_STARTING_CASH
_lock: asyncio.Lock = asyncio.Lock()
_simulator_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None
_last_prices: dict[str, float] = {}

_state: dict[str, Any] = {
    "running": False,
    "last_tick_at": None,
    "last_error": None,
    "last_candidates": [],
    "snapshot_storage": "memory",
    "state_restored_from_snapshot": False,
    "restart_persistent": False,
    "last_tick_marketdata": {},  # D2-H1: per-tick cache counters, updated after each tick
    # Phase 2S: restore metadata (populated by restore_paper_session at startup)
    "restore_source": "none",
    "restored_closed_trades_count": 0,
    "restored_open_positions_count": 0,
    "restored_daily_realized_pnl": 0.0,
    "restored_trades_today": 0,
    "restore_warning": None,
    "restore_warnings": [],
}


# ── Public API ────────────────────────────────────────────────────────────────

def get_state() -> dict[str, Any]:
    if _simulator_task is not None and _simulator_task.done():
        _state["running"] = False
    return dict(_state)


def get_open_position_symbols() -> list[str]:
    """Return ticker symbols of all currently open virtual positions.
    Used by the market-data collector universe builder (Phase D4).
    No broker. No real orders. Research/fake-money only.
    """
    return list(_account.positions.keys())


def get_status() -> dict[str, Any]:
    status = _account.to_status(
        _last_prices,
        extra={
            "max_positions": _cfg("PAPER_MAX_OPEN_POSITIONS"),
            "max_trades_per_day": _cfg("PAPER_MAX_TRADES_PER_DAY"),
            "max_position_size_usd": settings.PAPER_MAX_POSITION_SIZE_USD,
            "take_profit_percent": _cfg("PAPER_TAKE_PROFIT_PERCENT"),
            "stop_loss_percent": _cfg("PAPER_STOP_LOSS_PERCENT"),
            "max_hold_minutes": _cfg("PAPER_MAX_HOLD_MINUTES"),
            "poll_interval_seconds": settings.PAPER_POLL_INTERVAL_SECONDS,
        },
    )
    status.update({
        "running": get_state()["running"],
        "last_tick_at": _state["last_tick_at"],
        "last_error": _state["last_error"],
        "snapshot_storage": _state["snapshot_storage"],
        "state_restored_from_snapshot": _state.get("state_restored_from_snapshot", False),
        "restart_persistent": _state.get("restart_persistent", False),
        "restore_source": _state.get("restore_source", "none"),
        "restored_closed_trades_count": _state.get("restored_closed_trades_count", 0),
        "restored_open_positions_count": _state.get("restored_open_positions_count", 0),
        "restored_daily_realized_pnl": _state.get("restored_daily_realized_pnl", 0.0),
        "restored_trades_today": _state.get("restored_trades_today", 0),
        "restore_warning": _state.get("restore_warning"),
        "restore_warnings": _state.get("restore_warnings", []),
        "mode": "research_paper_simulation",
        "live_trading_enabled": False,
        "broker_connected": False,
    })
    # Daily loss guard status (fake-money only, observational)
    try:
        status["daily_loss_guard"] = _daily_loss_guard(_account, _last_prices)
    except Exception:
        status["daily_loss_guard"] = {"triggered": False, "reason": None, "enabled": False}
    # D2-H1: per-tick cache counters (empty until first tick completes)
    status["last_tick_marketdata"] = _state.get("last_tick_marketdata", {})
    return status


def get_positions() -> list[dict]:
    result = []
    for sym, pos in _account.positions.items():
        d = pos.to_dict()
        current = _last_prices.get(sym, pos.entry_price)
        d["current_price"] = current
        d["unrealized_pnl"] = round(pos.unrealized_pnl(current), 4)
        d["unrealized_pnl_percent"] = round(
            (pos.unrealized_pnl(current) / pos.cost_basis * 100) if pos.cost_basis else 0, 4
        )
        result.append(d)
    return result


def get_trades() -> list[dict]:
    return [t.to_dict() for t in _account.trades]


async def reset_simulator() -> None:
    global _account, _last_prices, _restore_attempted
    await stop_simulator()
    _restore_attempted = False
    async with _lock:
        _account.reset()
        _account.daily_baseline_date = _ny_trading_date()
        _account.daily_start_equity = _account.starting_cash
        _last_prices = {}
        _state["last_tick_at"] = None
        _state["last_error"] = None
        _state["last_candidates"] = []
        _state["snapshot_storage"] = "memory"
        _state["state_restored_from_snapshot"] = False
        _state["restart_persistent"] = False
        _state["restore_source"] = "none"
        _state["restored_closed_trades_count"] = 0
        _state["restored_open_positions_count"] = 0
        _state["restored_daily_realized_pnl"] = 0.0
        _state["restored_trades_today"] = 0
        _state["restore_warning"] = None
        _state["restore_warnings"] = []
    await _save_state()


async def start_simulator() -> None:
    global _simulator_task, _stop_event
    if _state["running"]:
        return
    if _simulator_task is not None and _simulator_task.done():
        _simulator_task = None
        _stop_event = None
    _stop_event = asyncio.Event()
    _state["running"] = True
    _state["last_error"] = None
    _simulator_task = asyncio.create_task(_loop())
    logger.info("Paper simulator started.")


async def stop_simulator() -> None:
    global _simulator_task, _stop_event
    if not _state["running"] and (_simulator_task is None or _simulator_task.done()):
        return
    if _stop_event:
        _stop_event.set()
    if _simulator_task and not _simulator_task.done():
        try:
            await asyncio.wait_for(asyncio.shield(_simulator_task), timeout=8.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _simulator_task.cancel()
            try:
                await _simulator_task
            except asyncio.CancelledError:
                pass
    _simulator_task = None
    _stop_event = None
    _state["running"] = False
    logger.info("Paper simulator stopped.")


# ── Simulation loop ───────────────────────────────────────────────────────────

async def _loop() -> None:
    logger.info("Paper simulator loop running.")
    while not _stop_event.is_set():
        try:
            await run_tick()
        except Exception as exc:
            _state["last_error"] = f"{type(exc).__name__}: {exc}"
            logger.error("Paper tick error: %s", exc, exc_info=True)
        try:
            await asyncio.wait_for(
                _stop_event.wait(),
                timeout=float(settings.PAPER_POLL_INTERVAL_SECONDS),
            )
        except asyncio.TimeoutError:
            pass
    _state["running"] = False
    logger.info("Paper simulator loop finished.")


# ── Tick logic ────────────────────────────────────────────────────────────────

async def run_tick() -> dict[str, Any]:
    """
    Run one evaluation tick. Returns a tick summary dict. Never raises.

    No broker. No real orders. Simulation only.
    """
    tick_start = datetime.now(timezone.utc)
    result: dict[str, Any] = {
        "tick_at": tick_start.isoformat(),
        "symbols_evaluated": 0,
        "exits": [],
        "exits_made": 0,
        "entries": [],
        "entries_made": 0,
        "candidates": [],
        "errors": [],
        "universe_active_count": 0,
        "universe_symbols": [],
        "universe_last_refreshed_at": None,
        "universe_refresh_reason": None,
        "discovery_enabled": False,
        "discovery_count": 0,
        "discovery_errors_count": 0,
        "config_overrides_active": False,
        "entry_score_threshold": None,
        "take_profit_percent": None,
        "stop_loss_percent": None,
        "max_hold_minutes": None,
        "momentum_mode_enabled": False,
        "today_momentum_entry_count": 0,
        "no_catalyst_entry_enabled": False,
        "today_no_catalyst_entry_count": 0,
        "daily_loss_guard": {"triggered": False, "reason": None, "enabled": False},
        "intrabar_tp_exits_today": 0,
        "intrabar_sl_exits_today": 0,
        "conservative_both_touched_exits_today": 0,
        "marketdata_cache_hits": 0,
        "marketdata_cache_misses": 0,
        "marketdata_cache_fallbacks": 0,
    }

    # ── 0. Resolve active universe ────────────────────────────────────────────
    try:
        _uni = await get_active_paper_universe()
        symbols = _uni["active_symbols"]
        result["universe_active_count"] = _uni["active_count"]
        result["universe_symbols"] = list(symbols)
        result["universe_last_refreshed_at"] = _uni.get("last_refreshed_at")
        result["universe_refresh_reason"] = _uni.get("refresh_reason")
        _disc = _uni.get("discovery") or {}
        result["discovery_enabled"] = bool(_disc.get("enabled", False))
        result["discovery_count"] = int(_disc.get("discovered_count", 0))
        result["discovery_errors_count"] = len(_disc.get("errors") or [])
    except Exception as exc:
        symbols = settings.paper_base_universe_list()[:int(_cfg("PAPER_MAX_SYMBOLS_PER_TICK"))]
        result["universe_refresh_reason"] = "error_fallback"
        result["errors"].append({"phase": "universe", "error": str(exc)})

    # ── 0b. Snapshot effective runtime config for this tick ───────────────────
    from paper.runtime_config import get_runtime_status as _rc_status
    _rc = _rc_status()
    result["config_overrides_active"] = _rc["overrides_active"]
    result["entry_score_threshold"] = _cfg("PAPER_ENTRY_SCORE_THRESHOLD")
    result["take_profit_percent"] = _cfg("PAPER_TAKE_PROFIT_PERCENT")
    result["stop_loss_percent"] = _cfg("PAPER_STOP_LOSS_PERCENT")
    result["max_hold_minutes"] = _cfg("PAPER_MAX_HOLD_MINUTES")
    result["momentum_mode_enabled"] = bool(_cfg("PAPER_MOMENTUM_MODE_ENABLED"))
    result["no_catalyst_entry_enabled"] = bool(_cfg("PAPER_NO_CATALYST_ENTRY_ENABLED"))

    # ── 1. Fetch market quality for all symbols concurrently ──────────────────
    quality_map: dict[str, dict] = {}
    source_meta_map: dict[str, dict] = {}
    # D2-H1: granular per-tick cache counters
    _cache_stats: dict[str, int] = {
        "hits": 0,          # fresh cache hit, Polygon skipped
        "stale": 0,         # cache had data but it was stale (pre-fallback or no-fallback reject)
        "misses": 0,        # cache miss/error (pre-fallback or no-fallback reject)
        "fallbacks": 0,     # stale/miss → fell through to Polygon successfully
        "polygon_direct": 0,  # cache disabled, called Polygon directly
        "missing": 0,       # _no_fallback: symbol rejected, no quality produced
    }

    async def _fetch_quality(sym: str) -> None:
        _sym_meta: dict[str, Any] = {
            "marketdata_source": "polygon_direct",
            "marketdata_age_seconds": None,
            "marketdata_fetched_at": None,
            "marketdata_stale": False,
            "marketdata_fallback_used": False,
            "marketdata_error": None,
        }
        cache_meta: dict[str, Any] = {}  # populated only when cache path taken

        # Cache layer — only consulted when enabled
        if _cfg("PAPER_USE_MARKETDATA_CACHE"):
            from paper.marketdata_adapter import try_cache_for_quality
            cached_q, cache_meta = await try_cache_for_quality(sym)
            _sym_meta.update(cache_meta)

            if cached_q is not None:
                # Fresh cache hit — skip Polygon entirely
                source_meta_map[sym] = _sym_meta
                quality_map[sym] = cached_q
                _cache_stats["hits"] += 1
                price = cached_q.get("bid") or cached_q.get("last_trade_price")
                if price and price > 0:
                    _last_prices[sym] = price
                return

            orig_src = cache_meta.get("marketdata_source", "")
            if orig_src.endswith("_no_fallback"):
                # Fallback disabled — reject this symbol for this tick
                error_key = orig_src.removesuffix("_no_fallback") + "_marketdata"
                _sym_meta["marketdata_error"] = error_key
                source_meta_map[sym] = _sym_meta
                if "stale" in orig_src:
                    _cache_stats["stale"] += 1
                else:
                    _cache_stats["misses"] += 1
                _cache_stats["missing"] += 1
                result["errors"].append({"symbol": sym, "error": error_key})
                return

            # Stale or missing with fallback enabled → fall through to Polygon
            if "stale" in orig_src:
                _cache_stats["stale"] += 1
            else:
                _cache_stats["misses"] += 1
            _sym_meta["marketdata_source"] = "polygon_fallback"
            _sym_meta["marketdata_stale"] = True
            _sym_meta["marketdata_fallback_used"] = True
            _cache_stats["fallbacks"] += 1
        else:
            _cache_stats["polygon_direct"] += 1

        source_meta_map[sym] = _sym_meta

        # Polygon path — called when cache disabled, stale/miss with fallback, or direct
        try:
            snapshot = await polygon_client.get_ticker_snapshot(sym)
            prev = await polygon_client.get_previous_close(sym)
            q = evaluate_market_quality(snapshot, prev)
            quality_map[sym] = q
            # Fresh Polygon data: clear stale flag unless the cache had a stale hit
            # (stale cache hit signals pipeline lag; missing/error → Polygon is authoritative)
            if _sym_meta.get("marketdata_source") != "polygon_fallback" or cache_meta.get("marketdata_source") not in ("stale", "stale_no_fallback"):
                _sym_meta["marketdata_stale"] = False
            price = q.get("bid") or q.get("last_trade_price")
            if price and price > 0:
                _last_prices[sym] = price
        except PolygonError as exc:
            _sym_meta["marketdata_error"] = str(exc)
            result["errors"].append({"symbol": sym, "error": str(exc)})
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            _sym_meta["marketdata_error"] = err
            result["errors"].append({"symbol": sym, "error": err})

    await asyncio.gather(*[_fetch_quality(sym) for sym in symbols])
    result["symbols_evaluated"] = len(quality_map)

    # D2-H1: named counters (canonical form for monitoring/status/dashboard)
    _md_stats = {
        "cache_hits_last_tick": _cache_stats["hits"],
        "cache_misses_last_tick": _cache_stats["misses"],
        "cache_stale_last_tick": _cache_stats["stale"],
        "polygon_fallbacks_last_tick": _cache_stats["fallbacks"],
        "polygon_direct_last_tick": _cache_stats["polygon_direct"],
        "missing_marketdata_last_tick": _cache_stats["missing"],
    }
    result["marketdata"] = _md_stats
    _state["last_tick_marketdata"] = _md_stats
    # Backward-compat aliases
    result["marketdata_cache_hits"] = _cache_stats["hits"]
    result["marketdata_cache_misses"] = _cache_stats["misses"]
    result["marketdata_cache_fallbacks"] = _cache_stats["fallbacks"]

    # ── 2. Fetch filtered + classified catalysts for tradable symbols ─────────
    tradable = [s for s, q in quality_map.items() if q.get("tradable")]
    catalyst_map: dict[str, list[dict]] = {s: [] for s in symbols}

    if tradable:
        try:
            cat_result = await collect_news_for_symbols(
                tradable,
                limit_per_symbol=5,
                apply_filter=True,
                max_age_hours=24,
                classify_events=True,
                analyze_sentiment=True,
            )
            for c in cat_result.get("filter", {}).get("accepted", []):
                sym = c.get("symbol")
                if sym and sym in catalyst_map:
                    catalyst_map[sym].append(c)
        except Exception as exc:
            result["errors"].append({"phase": "catalysts", "error": str(exc)})

    # ── 2b. Pre-fetch market regime for momentum gating (best-effort) ───────────
    _tick_regime: dict | None = None
    try:
        if _cfg("MARKET_REGIME_ENABLED"):
            from market.regime import get_market_regime
            _regime_data = await get_market_regime()
            _tick_regime = {
                "regime": _regime_data["risk"]["regime"],
                "risk_on_score": _regime_data["risk"]["risk_on_score"],
                "confidence": _regime_data["risk"]["confidence"],
                "as_of": _regime_data["as_of"],
            }
    except Exception:
        pass
    result["market_regime"] = _tick_regime

    # ── 2c. Fetch intrabar data for open positions only (Phase 2Q-Lite) ─────────
    # Fetches recent 1-minute bars to detect TP/SL touches between polling cycles.
    # Only called for currently-open positions (max PAPER_MAX_OPEN_POSITIONS = 5).
    # Results cached for 20 s inside exits.py to avoid duplicate calls per tick.
    intrabar_map: dict[str, dict | None] = {}
    _open_syms_snapshot = list(_account.positions.keys())
    if _open_syms_snapshot:
        _today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        async def _fetch_intrabar(sym: str) -> None:
            try:
                _pos = _account.positions.get(sym)
                _entry_time = _pos.entry_time if _pos else ""
                intrabar_map[sym] = await get_intrabar_data(sym, _entry_time, _today_date)
            except Exception:
                intrabar_map[sym] = None

        await asyncio.gather(*[_fetch_intrabar(s) for s in _open_syms_snapshot])

    # ── 3 & 4. Process exits then entries — single lock, no awaits inside ─────
    async with _lock:
        # Exits first — virtual bracket-order intrabar detection (Phase 2Q-Lite)
        for sym in list(_account.positions.keys()):
            pos = _account.positions.get(sym)
            if pos is None:
                continue
            q = quality_map.get(sym)

            bracket = evaluate_virtual_bracket_exit(
                entry_price=pos.entry_price,
                tp_pct=_cfg("PAPER_TAKE_PROFIT_PERCENT"),
                sl_pct=_cfg("PAPER_STOP_LOSS_PERCENT"),
                quote=q,
                intrabar=intrabar_map.get(sym),
            )

            entry_dt = datetime.fromisoformat(pos.entry_time)
            hold_min = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 60

            exit_reason: str | None = bracket["exit_reason"] if bracket["should_exit"] else None
            exit_price: float = bracket["exit_price"] if bracket["should_exit"] else 0.0

            if not exit_reason and hold_min >= _cfg("PAPER_MAX_HOLD_MINUTES"):
                exit_reason = "max_hold_time"
                # Point-in-time price for time-based exits
                _pt = (q.get("bid") or q.get("last_trade_price")) if q else None
                exit_price = _pt or _last_prices.get(sym, pos.entry_price)

            if exit_reason:
                trade = _account.exit_position(sym, exit_price, exit_reason)
                if trade:
                    # Enrich trade dataclass with intrabar metadata
                    trade.exit_tp_price = round(bracket["tp_price"], 6)
                    trade.exit_sl_price = round(bracket["sl_price"], 6)
                    trade.exit_intrabar_source = bracket["intrabar_source"]
                    trade.exit_intrabar_high = bracket["intrabar_high"]
                    trade.exit_intrabar_low = bracket["intrabar_low"]
                    trade.exit_conservative_both_touched = bracket["conservative_both_touched"]

                    exit_record: dict = {
                        "symbol": sym,
                        "exit_reason": exit_reason,
                        "entry_price": round(pos.entry_price, 4),
                        "exit_price": round(exit_price, 4),
                        "tp_price": round(bracket["tp_price"], 4),
                        "sl_price": round(bracket["sl_price"], 4),
                        "tp_touched": bracket["tp_touched"],
                        "sl_touched": bracket["sl_touched"],
                        "intrabar_high": bracket["intrabar_high"],
                        "intrabar_low": bracket["intrabar_low"],
                        "intrabar_source": bracket["intrabar_source"],
                        "conservative_both_touched": bracket["conservative_both_touched"],
                        "pnl": round(trade.pnl, 4),
                        "pnl_percent": round(trade.pnl_percent, 4),
                        "hold_minutes": trade.hold_minutes,
                        "catalyst_type": trade.entry_catalyst_type,
                        "total_score": trade.entry_score,
                        "entry_mode": trade.entry_mode,
                        "position_id": pos.position_id,
                        "shares": round(pos.shares, 6),
                        "cost_basis": round(pos.cost_basis, 4),
                    }
                    result["exits"].append(exit_record)

                    # Intrabar exit counters
                    if exit_reason == "take_profit_intrabar":
                        result["intrabar_tp_exits_today"] += 1
                    elif exit_reason in (
                        "stop_loss_intrabar",
                        "stop_loss_intrabar_both_touched_conservative",
                    ):
                        result["intrabar_sl_exits_today"] += 1
                        if bracket["conservative_both_touched"]:
                            result["conservative_both_touched_exits_today"] += 1

        # Compute today's momentum entry count from current positions + closed trades
        _today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_momentum_count = sum(
            1 for p in _account.positions.values()
            if p.entry_mode == "momentum" and p.entry_time.startswith(_today_str)
        ) + sum(
            1 for t in _account.trades
            if t.entry_mode == "momentum" and t.entry_time.startswith(_today_str)
        )
        result["today_momentum_entry_count"] = today_momentum_count

        today_no_catalyst_count = sum(
            1 for p in _account.positions.values()
            if p.entry_mode == "momentum_no_catalyst" and p.entry_time.startswith(_today_str)
        ) + sum(
            1 for t in _account.trades
            if t.entry_mode == "momentum_no_catalyst" and t.entry_time.startswith(_today_str)
        )
        result["today_no_catalyst_entry_count"] = today_no_catalyst_count

        # Trading-day baseline rollover — reset if NY calendar date changed
        _today_ny = _ny_trading_date()
        if _account.daily_baseline_date != _today_ny:
            _account.daily_start_equity = _account.get_equity(_last_prices)
            _account.daily_baseline_date = _today_ny
            logger.info(
                "Daily loss guard baseline reset: date=%s equity=%.4f",
                _today_ny, _account.daily_start_equity,
            )

        # Daily loss guard (fake-money only — blocks new entries, never exits)
        _guard = _daily_loss_guard(_account, _last_prices)
        result["daily_loss_guard"] = _guard

        # Phase 2T: blocked catalyst types, computed once per tick
        _blocked_cat_types: set[str] = (
            set(_blocked_catalyst_types_list())
            if _cfg("PAPER_BLOCK_STRONG_NEGATIVE_CATALYST_TYPES")
            else set()
        )

        # Entries
        for sym in symbols:
            q = quality_map.get(sym)
            if not q:
                continue
            cats = catalyst_map.get(sym, [])

            # Score every candidate (transparent, always computed)
            scoring = score_candidate(sym, q, cats)

            # ── Hard safety gates shared by both entry paths ───────────────────
            # These gates hard-reject regardless of mode.
            hard_rejection: str | None = None
            is_no_catalyst_rejection: bool = False
            _sym_meta = source_meta_map.get(sym, {})

            if not q.get("tradable"):
                reasons = q.get("rejection_reasons", [])
                hard_rejection = f"not tradable: {reasons[0] if reasons else 'failed quality gate'}"
            elif (q.get("spread_percent") or 999) > 0.50:
                hard_rejection = f"spread {q.get('spread_percent')}% > 0.50%"
            elif (q.get("change_percent") or 0) <= 0:
                hard_rejection = f"change_percent {q.get('change_percent')} not positive"
            elif q.get("volume_ratio") is not None and q.get("volume_ratio", 1.0) < _cfg("PAPER_MIN_VOLUME_RATIO"):
                hard_rejection = f"volume_ratio {q.get('volume_ratio')} < {_cfg('PAPER_MIN_VOLUME_RATIO')}"
            elif (
                _cfg("PAPER_REJECT_STRONG_BEARISH_CATALYST")
                and scoring.get("catalyst_sentiment") == "bearish"
                and (scoring.get("catalyst_materiality_score") or 0.0)
                >= _cfg("PAPER_BEARISH_CATALYST_REJECT_MATERIALITY")
            ):
                hard_rejection = "strong_bearish_catalyst"
            elif not cats:
                hard_rejection = "no accepted catalysts"
                is_no_catalyst_rejection = True
            elif all(c.get("classified_event_type") == "generic_news" for c in cats):
                hard_rejection = "only generic_news catalysts"
                is_no_catalyst_rejection = True

            # Block new entries when data is stale and fresh cache is required for entries.
            # Stale data overrides is_no_catalyst_rejection so Path C never fires on stale data.
            if (
                _cfg("PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY")
                and _sym_meta.get("marketdata_stale")
            ):
                hard_rejection = "stale_marketdata_entry_blocked"
                is_no_catalyst_rejection = False

            cat_type = cats[0].get("classified_event_type") if cats else None

            # ── Catalyst-type block (Phase 2T — fake-money only, no broker, no real orders) ──
            if hard_rejection is None and cat_type is not None and cat_type in _blocked_cat_types:
                hard_rejection = f"catalyst_type_blocked:{cat_type}"
                is_no_catalyst_rejection = False

            # ── Momentum evaluation (always computed when mode enabled) ────────
            momentum_eval: dict | None = None
            if _cfg("PAPER_MOMENTUM_MODE_ENABLED"):
                try:
                    momentum_eval = evaluate_momentum_entry(sym, q, _tick_regime)
                except Exception:
                    momentum_eval = None

            # ── No-catalyst evaluation (Phase 2R) ─────────────────────────────
            nc_eval: dict | None = None
            if is_no_catalyst_rejection:
                try:
                    nc_eval = evaluate_no_catalyst_entry(sym, q, scoring, _tick_regime)
                except Exception:
                    nc_eval = None

            candidate: dict[str, Any] = {
                "symbol": sym,
                "eligible": False,
                "rejection_reason": hard_rejection,
                "action": None,
                "quality_tradable": q.get("tradable"),
                "spread_percent": q.get("spread_percent"),
                "change_percent": q.get("change_percent"),
                "volume_ratio": q.get("volume_ratio"),
                "catalyst_count": len(cats),
                "catalyst_type": cat_type,
                "catalyst_type_blocked": bool(cat_type and cat_type in _blocked_cat_types),
                "catalyst_type_weight": None,
                # Scoring fields
                "total_score": scoring["total_score"],
                "score_threshold": scoring["score_threshold"],
                "score_pass": scoring["score_pass"],
                "score_components": scoring["components"],
                "positive_reasons": scoring["positive_reasons"],
                "negative_reasons": scoring["negative_reasons"],
                "decision_reason": scoring["decision_reason"],
                # Sentiment fields (Phase 2I)
                "catalyst_sentiment": scoring.get("catalyst_sentiment"),
                "catalyst_sentiment_score": scoring.get("catalyst_sentiment_score"),
                "catalyst_materiality_score": scoring.get("catalyst_materiality_score"),
                "catalyst_sentiment_reasons": scoring.get("catalyst_sentiment_reasons"),
                "bullish_flags": scoring.get("bullish_flags"),
                "bearish_flags": scoring.get("bearish_flags"),
                "strongest_catalyst_title": scoring.get("strongest_catalyst_title"),
                "strongest_catalyst_sentiment": scoring.get("strongest_catalyst_sentiment"),
                # Momentum fields (Phase 2M)
                "entry_mode": None,
                "momentum_eligible": momentum_eval["eligible"] if momentum_eval else False,
                "momentum_score": momentum_eval["momentum_score"] if momentum_eval else None,
                "momentum_score_threshold": momentum_eval["momentum_score_threshold"] if momentum_eval else None,
                "momentum_rejection_reason": momentum_eval["rejection_reason"] if momentum_eval else None,
                "momentum_gate_results": momentum_eval["gate_results"] if momentum_eval else None,
                # No-catalyst momentum fields (Phase 2R)
                "no_catalyst_momentum_eligible": nc_eval["eligible"] if nc_eval else False,
                "no_catalyst_momentum_reasons": nc_eval["positive_reasons"] if nc_eval and nc_eval["eligible"] else None,
                "no_catalyst_momentum_blockers": nc_eval["negative_reasons"] if nc_eval and not nc_eval["eligible"] else None,
                "no_catalyst_config_snapshot": nc_eval["config_snapshot"] if nc_eval else None,
                "catalyst_required": True,
                # Daily loss guard (Phase 2N)
                "daily_loss_guard_triggered": _guard["triggered"],
                # Market-data cache metadata (Phase D2 / D2-H1)
                "marketdata_source": _sym_meta.get("marketdata_source"),
                "marketdata_age_seconds": _sym_meta.get("marketdata_age_seconds"),
                "marketdata_fetched_at": _sym_meta.get("marketdata_fetched_at"),
                "marketdata_stale": _sym_meta.get("marketdata_stale", False),
                "marketdata_fallback_used": _sym_meta.get("marketdata_fallback_used", False),
                "marketdata_error": _sym_meta.get("marketdata_error"),
            }

            # ── Entry decision ────────────────────────────────────────────────
            # Path A: Catalyst entry (existing logic, unchanged)
            if hard_rejection is None and scoring["score_pass"]:
                candidate["eligible"] = True
                candidate["entry_mode"] = "catalyst"
                if _guard["triggered"]:
                    candidate["action"] = "daily_max_loss_guard"
                    candidate["rejection_reason"] = "daily_max_loss_guard"
                    candidate["eligible"] = False
                else:
                    can, block = _account.can_enter(
                        sym,
                        _cfg("PAPER_MAX_OPEN_POSITIONS"),
                        _cfg("PAPER_MAX_TRADES_PER_DAY"),
                    )
                    if can:
                        entry_price = q.get("ask") or q.get("last_trade_price", 0)
                        if entry_price and entry_price > 0:
                            pos_pct = _cfg("PAPER_POSITION_SIZE_PERCENT")
                            budget_pct = _account.cash * (pos_pct / 100.0)
                            position_budget = min(budget_pct, settings.PAPER_MAX_POSITION_SIZE_USD)
                            pos = _account.enter_position(
                                sym, entry_price,
                                position_budget,
                                cat_type or "unknown",
                                entry_score=scoring["total_score"],
                                entry_mode="catalyst",
                            )
                            if pos:
                                candidate["action"] = "entered"
                                result["entries"].append({
                                    "symbol": sym,
                                    "entry_price": round(entry_price, 4),
                                    "shares": round(pos.shares, 6),
                                    "cost_basis": round(pos.cost_basis, 4),
                                    "catalyst_type": cat_type,
                                    "total_score": scoring["total_score"],
                                    "entry_mode": "catalyst",
                                    "position_id": pos.position_id,
                                })
                            else:
                                candidate["action"] = "entry_failed"
                        else:
                            candidate["action"] = "no_valid_price"
                    else:
                        candidate["action"] = f"blocked: {block}"

            # Path C: No-catalyst momentum entry (Phase 2R)
            elif (
                hard_rejection is not None
                and is_no_catalyst_rejection
                and nc_eval is not None
                and nc_eval["eligible"]
            ):
                # No-catalyst daily limit gate
                no_catalyst_max = _cfg("PAPER_NO_CATALYST_MAX_TRADES_PER_DAY")
                if today_no_catalyst_count >= no_catalyst_max:
                    candidate["action"] = f"no_catalyst_blocked: daily limit {no_catalyst_max}"
                    candidate["rejection_reason"] = hard_rejection
                elif _guard["triggered"]:
                    candidate["action"] = "daily_max_loss_guard"
                    candidate["rejection_reason"] = "daily_max_loss_guard"
                else:
                    candidate["eligible"] = True
                    candidate["entry_mode"] = "momentum_no_catalyst"
                    candidate["rejection_reason"] = None
                    candidate["catalyst_required"] = False
                    can, block = _account.can_enter(
                        sym,
                        _cfg("PAPER_MAX_OPEN_POSITIONS"),
                        _cfg("PAPER_MAX_TRADES_PER_DAY"),
                    )
                    if can:
                        entry_price = q.get("ask") or q.get("last_trade_price", 0)
                        if entry_price and entry_price > 0:
                            pos_pct = _cfg("PAPER_POSITION_SIZE_PERCENT")
                            size_multiplier = _cfg("PAPER_NO_CATALYST_POSITION_SIZE_MULTIPLIER")
                            normal_budget = min(
                                _account.cash * (pos_pct / 100.0),
                                settings.PAPER_MAX_POSITION_SIZE_USD,
                            )
                            position_budget = normal_budget * size_multiplier
                            pos = _account.enter_position(
                                sym, entry_price,
                                position_budget,
                                "momentum_no_catalyst",
                                entry_score=scoring["total_score"],
                                entry_mode="momentum_no_catalyst",
                            )
                            if pos:
                                today_no_catalyst_count += 1
                                result["today_no_catalyst_entry_count"] = today_no_catalyst_count
                                candidate["action"] = "entered"
                                result["entries"].append({
                                    "symbol": sym,
                                    "entry_price": round(entry_price, 4),
                                    "shares": round(pos.shares, 6),
                                    "cost_basis": round(pos.cost_basis, 4),
                                    "catalyst_type": "momentum_no_catalyst",
                                    "total_score": scoring["total_score"],
                                    "entry_mode": "momentum_no_catalyst",
                                    "position_id": pos.position_id,
                                })
                            else:
                                candidate["action"] = "entry_failed"
                                candidate["eligible"] = False
                        else:
                            candidate["action"] = "no_valid_price"
                            candidate["eligible"] = False
                    else:
                        candidate["action"] = f"blocked: {block}"
                        candidate["eligible"] = False

            # Path B: Momentum fallback (only when catalyst path not taken)
            elif (
                hard_rejection is not None
                and is_no_catalyst_rejection
                and momentum_eval is not None
                and momentum_eval["eligible"]
            ):
                # Momentum daily limit gate
                momentum_max = _cfg("PAPER_MOMENTUM_MAX_TRADES_PER_DAY")
                if today_momentum_count >= momentum_max:
                    candidate["action"] = f"momentum_blocked: daily limit {momentum_max}"
                    candidate["rejection_reason"] = hard_rejection
                elif _guard["triggered"]:
                    candidate["action"] = "daily_max_loss_guard"
                    candidate["rejection_reason"] = "daily_max_loss_guard"
                else:
                    candidate["eligible"] = True
                    candidate["entry_mode"] = "momentum"
                    candidate["rejection_reason"] = None
                    can, block = _account.can_enter(
                        sym,
                        _cfg("PAPER_MAX_OPEN_POSITIONS"),
                        _cfg("PAPER_MAX_TRADES_PER_DAY"),
                    )
                    if can:
                        entry_price = q.get("ask") or q.get("last_trade_price", 0)
                        if entry_price and entry_price > 0:
                            pos_pct = _cfg("PAPER_POSITION_SIZE_PERCENT")
                            size_multiplier = _cfg("PAPER_MOMENTUM_POSITION_SIZE_MULTIPLIER")
                            normal_budget = min(_account.cash * (pos_pct / 100.0), settings.PAPER_MAX_POSITION_SIZE_USD)
                            position_budget = normal_budget * size_multiplier
                            pos = _account.enter_position(
                                sym, entry_price,
                                position_budget,
                                "momentum",
                                entry_score=momentum_eval["momentum_score"],
                                entry_mode="momentum",
                            )
                            if pos:
                                today_momentum_count += 1
                                result["today_momentum_entry_count"] = today_momentum_count
                                candidate["action"] = "entered"
                                result["entries"].append({
                                    "symbol": sym,
                                    "entry_price": round(entry_price, 4),
                                    "shares": round(pos.shares, 6),
                                    "cost_basis": round(pos.cost_basis, 4),
                                    "catalyst_type": "momentum",
                                    "total_score": momentum_eval["momentum_score"],
                                    "entry_mode": "momentum",
                                    "position_id": pos.position_id,
                                })
                            else:
                                candidate["action"] = "entry_failed"
                                candidate["eligible"] = False
                        else:
                            candidate["action"] = "no_valid_price"
                            candidate["eligible"] = False
                    else:
                        candidate["action"] = f"blocked: {block}"
                        candidate["eligible"] = False

            elif hard_rejection is not None:
                # Hard gate failed and not eligible for momentum
                pass
            else:
                # Catalyst score failed
                candidate["action"] = "score_rejected"
                candidate["rejection_reason"] = scoring["decision_reason"]

            result["candidates"].append(candidate)

    # ── 5. Update in-memory state ─────────────────────────────────────────────
    result["exits_made"] = len(result["exits"])
    result["entries_made"] = len(result["entries"])
    _state["last_tick_at"] = tick_start.isoformat()
    _state["last_error"] = None
    _state["last_candidates"] = result["candidates"]

    # ── 6. Journal write (non-fatal, must not affect simulation) ─────────────
    # Journal is written BEFORE Redis snapshot so that any position stored in
    # Redis always has a corresponding journal entry row (Phase 2U write-order fix).
    result["journal"] = {"ok": False, "skipped": True, "reason": "not attempted"}
    _journal_tick_id: str | None = None
    try:
        result["journal"] = await _persist_journal_tick(
            result, get_status(), get_cached_universe()
        )
        _journal_tick_id = result["journal"].get("tick_id") if isinstance(result["journal"], dict) else None
    except Exception as exc:
        result["journal"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # ── 7. Persist Redis snapshot AFTER journal ───────────────────────────────
    await _save_state(tick_id=_journal_tick_id)

    # ── 8. Market regime already fetched in step 2b (observational only) ────────
    # result["market_regime"] is already set from step 2b.

    return result


# ── Redis persistence (best-effort) ──────────────────────────────────────────

async def _save_state(tick_id: str | None = None) -> None:
    async with _lock:
        snapshot = {
            # ── Phase 2U integrity metadata ──────────────────────────────────
            "schema_version": 2,
            "namespace": settings.PAPER_STATE_REDIS_NAMESPACE,
            "saved_after_journal": True,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "tick_id": tick_id,
            # ── Account state ────────────────────────────────────────────────
            "cash": _account.cash,
            "starting_cash": _account.starting_cash,
            "positions": {s: asdict(p) for s, p in _account.positions.items()},
            "trades": [asdict(t) for t in _account.trades],
            "daily_trade_count": _account._daily_trade_count,
            "daily_date": _account._daily_date,
            "daily_baseline_date": _account.daily_baseline_date,
            "daily_start_equity": _account.daily_start_equity,
            "last_prices": dict(_last_prices),
        }
    try:
        r = make_redis()
        await r.set(_REDIS_KEY, json.dumps(snapshot))
        await r.aclose()
        _state["snapshot_storage"] = "redis_best_effort"
    except Exception:
        _state["snapshot_storage"] = "memory"


# ── Session restore (Phase 2S) ────────────────────────────────────────────────

_restore_attempted: bool = False  # one-shot guard; reset only by reset_simulator()


async def restore_paper_session() -> dict[str, Any]:
    """
    Called once at startup (after init_journal). Attempts to restore today's paper
    session from Redis snapshot, then DB journal fallback.
    Applies restored state to _account and _state in place.
    Non-fatal: errors degrade to a fresh session start.
    No broker. No real orders. Research-only fake-money restore.
    """
    global _restore_attempted
    if _restore_attempted:
        return {"source": "none", "closed_trades_count": 0,
                "open_positions_count": 0, "daily_realized_pnl": 0.0,
                "trades_today": 0, "warning": None, "restore_warnings": []}
    _restore_attempted = True

    from paper.models import ClosedTrade, Position
    from paper.session_restore import restore_session

    ny_today = _ny_trading_date()
    try:
        result = await restore_session(ny_today, settings.PAPER_STARTING_CASH)
    except Exception as exc:
        logger.warning("restore_paper_session: restore_session raised: %s", exc)
        return {
            "source": "none", "closed_trades_count": 0,
            "open_positions_count": 0, "daily_realized_pnl": 0.0,
            "trades_today": 0, "warning": None, "restore_warnings": [],
        }

    source = result.get("source", "none")
    if source == "none":
        return result

    try:
        async with _lock:
            global _last_prices
            if source == "redis":
                snap = result["snapshot"]
                _account.cash = float(snap.get("cash", settings.PAPER_STARTING_CASH))
                _account.starting_cash = float(snap.get("starting_cash", settings.PAPER_STARTING_CASH))
                _account.positions = {
                    s: Position(**p)
                    for s, p in (snap.get("positions") or {}).items()
                }
                _account.trades = [
                    ClosedTrade(**t) for t in (snap.get("trades") or [])
                ]
                _account._daily_trade_count = int(snap.get("daily_trade_count", 0))
                _account._daily_date = snap.get("daily_date", "")
                _account.daily_baseline_date = snap.get("daily_baseline_date", ny_today)
                _account.daily_start_equity = float(
                    snap.get("daily_start_equity", settings.PAPER_STARTING_CASH)
                )
                _last_prices = dict(snap.get("last_prices") or {})

            elif source == "db":
                db_data = result["db_data"]
                _account.cash = float(db_data.get("cash", settings.PAPER_STARTING_CASH))
                _account.trades = db_data.get("trades", [])
                _account.positions = db_data.get("positions", {})
                _account._daily_trade_count = int(db_data.get("daily_trade_count", 0))
                _account._daily_date = ny_today
                _account.daily_baseline_date = ny_today
                _account.daily_start_equity = float(
                    db_data.get("daily_start_equity", settings.PAPER_STARTING_CASH)
                )

            _state["state_restored_from_snapshot"] = True
            _state["restart_persistent"] = True
            _state["restore_source"] = source
            _state["restored_closed_trades_count"] = result.get("closed_trades_count", 0)
            _state["restored_open_positions_count"] = result.get("open_positions_count", 0)
            _state["restored_daily_realized_pnl"] = result.get("daily_realized_pnl", 0.0)
            _state["restored_trades_today"] = result.get("trades_today", 0)
            _state["restore_warning"] = result.get("warning")
            _state["restore_warnings"] = result.get("restore_warnings", [])

    except Exception as exc:
        logger.warning("restore_paper_session: failed to apply state: %s", exc)
        result["apply_error"] = str(exc)

    return result
