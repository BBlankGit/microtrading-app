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
from paper.time_adjusted_volume import session_elapsed_ratio as _tv_session_ratio, time_adjusted_volume_ratio as _tv_ratio
from paper.universe import get_active_paper_universe, get_cached_universe

logger = logging.getLogger(__name__)

_REDIS_KEY = f"{settings.PAPER_STATE_REDIS_NAMESPACE}:state:v2"
_DESIRED_RUNNING_KEY = f"{settings.PAPER_STATE_REDIS_NAMESPACE}:desired_running"

# Phase N1-H1: hard-wired safe sessions for market_mover_no_catalyst.
# These are the only sessions where the volume gate is fully defined.
# Runtime config PAPER_MARKET_MOVER_ALLOWED_SESSIONS is intersected with this
# set so that a misconfigured operator cannot bypass the session guard.
_MM_SAFE_SESSIONS: frozenset[str] = frozenset({"premarket", "regular"})


# ── Phase M1-H4: pure helper for trend telemetry per actual selected branch ──
# Called only AFTER the entry-decision branch chain assigns _final_selected_path.
# Never infers from broad predicates or candidate source metadata.
_VALID_TREND_PATHS: frozenset[str] = frozenset({
    "catalyst",
    "market_mover_no_catalyst",
    "no_catalyst",
    "legacy_momentum",
    "rejected_before_path",
})


def _trend_usage_for_path(
    path_name: str,
    tick_regime: dict | None,
    tick_regime_adjusted: dict | None,
    *,
    apply_legacy: bool,
    apply_no_cat: bool,
    apply_mm: bool,
    apply_catalyst: bool,
) -> dict:
    """
    Compute trend telemetry strictly from the final entry branch selected.

    Args:
      path_name: one of catalyst | market_mover_no_catalyst | no_catalyst |
                 legacy_momentum | rejected_before_path
      tick_regime: raw regime dict (or None)
      tick_regime_adjusted: trend-adjusted regime dict (or None when trend
                            isn't computed)
      apply_*: per-consumer config flags

    Returns dict with: path_name, consumed, regime_used, regime_label_used.
    """
    if path_name not in _VALID_TREND_PATHS:
        path_name = "rejected_before_path"
    apply_for: dict[str, bool] = {
        "catalyst":                 apply_catalyst,
        "market_mover_no_catalyst": apply_mm,
        "no_catalyst":              apply_no_cat,
        "legacy_momentum":          apply_legacy,
        "rejected_before_path":     False,
    }
    apply_flag = apply_for[path_name]
    consumed = bool(apply_flag and tick_regime_adjusted is not None)
    regime_used = "trend_adjusted" if consumed else "raw"
    regime_label_used = (
        (tick_regime_adjusted or {}).get("regime")
        if consumed
        else (tick_regime or {}).get("regime")
    )
    return {
        "path_name": path_name,
        "consumed": consumed,
        "regime_used": regime_used,
        "regime_label_used": regime_label_used,
    }


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
    "last_shadow_stats": {},    # I4-A: shadow aggregate stats, updated after each tick
    "last_tick_symbols_evaluated": 0,  # I4-B: symbols evaluated last tick
    "last_tick_market_movers": {},     # I4-B: market movers injection stats
    # Phase 2S: restore metadata (populated by restore_paper_session at startup)
    "restore_source": "none",
    "restored_closed_trades_count": 0,
    "restored_open_positions_count": 0,
    "restored_daily_realized_pnl": 0.0,
    "restored_trades_today": 0,
    "restore_warning": None,
    "restore_warnings": [],
    # S1-V1: auto-resume metadata (populated by auto_resume_if_desired at startup)
    "desired_running": False,
    "auto_resumed": False,
    "auto_resumed_at": None,
    "auto_resume_attempted": False,
    "auto_resume_source": None,
    "auto_resume_warning": None,
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
            "poll_interval_seconds": _cfg("PAPER_POLL_INTERVAL_SECONDS"),
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
        # S1-V1: auto-resume fields
        "desired_running": _state.get("desired_running", False),
        "auto_resumed": _state.get("auto_resumed", False),
        "auto_resumed_at": _state.get("auto_resumed_at"),
        "auto_resume_attempted": _state.get("auto_resume_attempted", False),
        "auto_resume_source": _state.get("auto_resume_source"),
        "auto_resume_warning": _state.get("auto_resume_warning"),
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
    _ltmd = _state.get("last_tick_marketdata", {})
    status["last_tick_marketdata"] = _ltmd
    # I4-A: shadow aggregate stats (empty until first tick completes)
    status["last_shadow_stats"] = _state.get("last_shadow_stats", {})

    # I4-B: flat telemetry fields for dashboard/monitoring consumers
    _last_at = _state.get("last_tick_at")
    status["last_tick"] = _last_at
    status["tick_age_seconds"] = None
    if _last_at:
        try:
            from datetime import datetime, timezone as _tz
            _lt = datetime.fromisoformat(_last_at)
            if _lt.tzinfo is None:
                _lt = _lt.replace(tzinfo=_tz.utc)
            status["tick_age_seconds"] = round(
                (datetime.now(_tz.utc) - _lt).total_seconds(), 1
            )
        except Exception:
            pass
    status["symbols_evaluated_last_tick"] = _state.get("last_tick_symbols_evaluated", 0)
    status["cache_hits_last_tick"]         = _ltmd.get("cache_hits_last_tick")
    status["cache_misses_last_tick"]       = _ltmd.get("cache_misses_last_tick")
    status["polygon_fallbacks_last_tick"]  = _ltmd.get("polygon_fallbacks_last_tick")
    status["missing_marketdata_last_tick"] = _ltmd.get("missing_marketdata_last_tick")
    # I4-B: market movers injection stats
    status["last_tick_market_movers"] = _state.get("last_tick_market_movers", {})
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
        try:
            from paper import shadow_wallets as _sw
            _sw.reset()
        except Exception:
            pass
        _last_prices = {}
        _state["last_tick_at"] = None
        _state["last_tick_symbols_evaluated"] = 0
        _state["last_tick_market_movers"] = {}
        _state["last_tick_marketdata"] = {}
        _state["last_shadow_stats"] = {}
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
        _state["desired_running"] = False
        _state["auto_resumed"] = False
        _state["auto_resumed_at"] = None
        _state["auto_resume_attempted"] = False
        _state["auto_resume_source"] = None
        _state["auto_resume_warning"] = None
    await _save_state()


# ── Auto-resume helpers (Phase S1-V1) ─────────────────────────────────────────

async def _persist_desired_running(val: bool) -> None:
    """Persist desired_running flag to Redis (best-effort, non-fatal)."""
    _state["desired_running"] = val
    try:
        r = make_redis()
        await r.set(_DESIRED_RUNNING_KEY, "1" if val else "0")
        await r.aclose()
    except Exception:
        pass


async def load_desired_running() -> bool | None:
    """Load desired_running from Redis. Returns None on error or missing key."""
    try:
        r = make_redis()
        raw = await r.get(_DESIRED_RUNNING_KEY)
        await r.aclose()
        if raw is None:
            return None
        return raw.decode() == "1" if isinstance(raw, bytes) else str(raw) == "1"
    except Exception:
        return None


async def auto_resume_if_desired() -> dict:
    """
    Called once at startup (after restore_paper_session).
    Reads the persisted desired_running flag and auto-starts the simulator if True.
    Non-fatal: errors are recorded in _state but do not prevent startup.
    No broker. No real orders. Fake-money only.
    """
    result: dict = {"auto_resumed": False, "auto_resume_attempted": False, "source": None, "warning": None}
    if settings.LIVE_TRADING_ENABLED:
        warn = "auto_resume blocked: LIVE_TRADING_ENABLED is True — fake-money simulator will not auto-start"
        _state["auto_resume_warning"] = warn
        result["warning"] = warn
        logger.warning(warn)
        return result
    try:
        desired = await load_desired_running()
        if desired is None:
            result["source"] = "no_persisted_state"
            _state["auto_resume_source"] = "no_persisted_state"
            return result
        _state["desired_running"] = desired
        if desired:
            _state["auto_resume_attempted"] = True
            result["auto_resume_attempted"] = True
            await start_simulator()
            _state["auto_resumed"] = True
            _state["auto_resumed_at"] = datetime.now(timezone.utc).isoformat()
            _state["auto_resume_source"] = "redis"
            result.update({"auto_resumed": True, "source": "redis"})
            logger.info("Paper simulator auto-resumed from desired_running flag.")
        else:
            _state["auto_resume_source"] = "redis_not_desired"
            result["source"] = "redis_not_desired"
    except Exception as exc:
        warn = f"auto_resume_if_desired error: {type(exc).__name__}: {exc}"
        _state["auto_resume_warning"] = warn
        result["warning"] = warn
        logger.warning(warn)
    return result


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
    await _persist_desired_running(True)
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
    await _persist_desired_running(False)
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
                timeout=float(_cfg("PAPER_POLL_INTERVAL_SECONDS")),
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
        "market_mover_no_catalyst_enabled": False,
        "today_market_mover_no_catalyst_entry_count": 0,
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

    # ── 0c. Full-market movers candidate injection (Phase I4-B) ──────────────
    # Reads only from the already-fetched full-universe snapshot cache.
    # No new Polygon calls. No broker. Fake-money only.
    # Injected symbols are merged into the candidate set and still go through
    # all existing quality/score/catalyst gates unchanged.
    _mover_meta_map: dict[str, dict] = {}  # symbol → mover metadata for candidate tagging
    _movers_added: list[str] = []
    _movers_skipped_gap: int = 0
    _movers_skipped_mode: int = 0
    _movers_injected_total: int = 0
    if _cfg("PAPER_MARKET_MOVERS_CANDIDATES_ENABLED"):
        try:
            from intelligence import full_premarket as _fp_inj
            _fm_snap = _fp_inj.get_snapshot() or {}
            _fm_mode = _fm_snap.get("mode", "unknown")
            _require_full = _cfg("PAPER_MARKET_MOVERS_CANDIDATES_REQUIRE_FULL_UNIVERSE")
            _top_n = int(_cfg("PAPER_MARKET_MOVERS_CANDIDATES_TOP_N"))
            _min_gap = float(_cfg("PAPER_MARKET_MOVERS_CANDIDATES_MIN_GAP_PERCENT"))
            _max_gap = float(_cfg("PAPER_MARKET_MOVERS_CANDIDATES_MAX_GAP_PERCENT"))
            _min_price = float(settings.PREMARKET_SCANNER_MIN_PRICE)

            if _fm_snap.get("ok") and (not _require_full or _fm_mode == "full_universe"):
                # Collect ranked movers: top_gainers first, then top_movers for diversity
                _seen_inj: set[str] = set()
                _mover_candidates: list[dict] = []
                for _lst_key in ("top_gainers", "top_movers", "top_losers"):
                    for _m in (_fm_snap.get(_lst_key) or []):
                        _msym = (_m.get("symbol") or "").upper()
                        if _msym and _msym not in _seen_inj:
                            _seen_inj.add(_msym)
                            _mover_candidates.append(_m)

                _rank_counter = 0
                for _m in _mover_candidates:
                    if len(_movers_added) >= _top_n:
                        break
                    _msym = (_m.get("symbol") or "").upper()
                    if not _msym:
                        continue
                    _gap = _m.get("gap_percent")
                    _price = _m.get("last_price") or _m.get("price") or 0.0
                    try:
                        _gap_f = float(_gap) if _gap is not None else None
                    except (TypeError, ValueError):
                        _gap_f = None
                    if _gap_f is None:
                        _movers_skipped_gap += 1
                        continue
                    _abs_gap = abs(_gap_f)
                    if _abs_gap < _min_gap or _abs_gap > _max_gap:
                        _movers_skipped_gap += 1
                        continue
                    try:
                        _price_f = float(_price)
                    except (TypeError, ValueError):
                        _price_f = 0.0
                    if _price_f < _min_price:
                        continue
                    _rank_counter += 1
                    _mover_meta_map[_msym] = {
                        "market_mover_rank":       _m.get("rank") or _rank_counter,
                        "market_mover_gap_percent": _gap_f,
                        "market_mover_session":    _fm_snap.get("session"),
                        "market_mover_mode":       _fm_mode,
                    }
                    if _msym not in symbols:
                        symbols = list(symbols) + [_msym]
                        _movers_added.append(_msym)
                _movers_injected_total = len(_mover_meta_map)
            else:
                _movers_skipped_mode = 1
        except Exception as _inj_exc:
            result["errors"].append({"phase": "market_movers_injection", "error": str(_inj_exc)})

    _mm_stats = {
        "enabled": bool(_cfg("PAPER_MARKET_MOVERS_CANDIDATES_ENABLED")),
        "injected_count": _movers_injected_total,
        "added_to_universe": len(_movers_added),
        "skipped_gap_filter": _movers_skipped_gap,
        "skipped_mode_filter": _movers_skipped_mode,
        "injected_symbols": _movers_added[:20],
    }
    result["market_movers_injection"] = _mm_stats
    _state["last_tick_market_movers"] = _mm_stats

    # I4-B-H1: track which symbols are injection-only (added by movers, not in base universe).
    # These symbols must never trigger a Polygon call — cache hits only.
    _injection_only_symbols: set[str] = set(_movers_added)

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

    # S1-V1: session context computed once per tick for time-adjusted volume gate
    try:
        from intelligence.full_premarket import get_current_session as _gcs
        _tick_session_type: str = _gcs()
    except Exception:
        _tick_session_type = "unknown"
    _tick_session_elapsed_ratio: float = _tv_session_ratio()

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

            # I4-B-H1: injection-only symbols must never fall back to Polygon.
            if sym in _injection_only_symbols:
                if "stale" in orig_src:
                    _cache_stats["stale"] += 1
                    _err_key = "stale_marketdata_for_injected_mover"
                else:
                    _cache_stats["misses"] += 1
                    _err_key = "missing_marketdata_for_injected_mover"
                _sym_meta["marketdata_error"] = _err_key
                _sym_meta["marketdata_source"] = "injection_only_no_polygon"
                _sym_meta["marketdata_fallback_used"] = False
                source_meta_map[sym] = _sym_meta
                _cache_stats["missing"] += 1
                result["errors"].append({"symbol": sym, "error": _err_key})
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
            # I4-B-H1: injection-only without cache → reject, no Polygon call.
            if sym in _injection_only_symbols:
                _sym_meta["marketdata_error"] = "missing_marketdata_for_injected_mover"
                _sym_meta["marketdata_source"] = "injection_only_no_polygon"
                source_meta_map[sym] = _sym_meta
                _cache_stats["missing"] += 1
                result["errors"].append({"symbol": sym, "error": "missing_marketdata_for_injected_mover"})
                return
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

    # ── Phase M1 / M1-H1: market trend overlay (ETF proxies, 5/10/15m) ────────
    # M1-H1: DO NOT mutate the shared _tick_regime in place. Build a separate
    # _tick_regime_adjusted with the trend-adjusted score + regime label so
    # consumers can be opted in / out individually via config.
    _tick_trend: dict | None = None
    _tick_regime_adjusted: dict | None = None
    try:
        if _cfg("MARKET_TREND_ENABLED"):
            from market.trend import build_trend_overlay
            _tick_trend = build_trend_overlay()
    except Exception:
        pass

    if _tick_regime is not None and _tick_trend is not None:
        adj_score = _tick_trend.get("market_regime_score_after_trend")
        adj_label = _tick_trend.get("adjusted_regime_label")
        # Copy raw regime + overlay adjusted fields. Never overwrite raw.
        _tick_regime_adjusted = dict(_tick_regime)
        if adj_score is not None:
            _tick_regime_adjusted["risk_on_score_before_trend"] = _tick_regime.get("risk_on_score")
            _tick_regime_adjusted["risk_on_score"] = adj_score
        if adj_label and adj_label != "unknown":
            _tick_regime_adjusted["regime_before_trend"] = _tick_regime.get("regime")
            _tick_regime_adjusted["regime"] = adj_label
        _tick_regime_adjusted["trend"] = _tick_trend

    # Phase M1-H1 / M1-H2 consumer flags (read once per tick).
    _trend_apply_legacy = bool(_cfg("MARKET_TREND_APPLY_TO_LEGACY_MOMENTUM"))
    _trend_apply_no_cat = bool(_cfg("MARKET_TREND_APPLY_TO_NO_CATALYST"))
    _trend_apply_mm     = bool(_cfg("MARKET_TREND_APPLY_TO_MARKET_MOVER"))
    _trend_apply_shadow = bool(_cfg("MARKET_TREND_APPLY_TO_SHADOW"))
    _trend_apply_catalyst = bool(_cfg("MARKET_TREND_APPLY_TO_CATALYST"))

    def _regime_for(consumer_flag: bool) -> dict | None:
        """Return adjusted regime when consumer opts in; else raw. Never mutates."""
        if consumer_flag and _tick_regime_adjusted is not None:
            return _tick_regime_adjusted
        return _tick_regime

    result["market_regime"] = _tick_regime
    result["market_regime_adjusted"] = _tick_regime_adjusted
    result["market_trend"] = _tick_trend

    # ── 2c. Phase I6: snapshot earnings + insider caches once per tick ──────────
    # Cache-first reads only; no external API calls inside the tick loop.
    _earnings_by_symbol: dict[str, dict] = {}
    _insider_txns_by_symbol: dict[str, list[dict]] = {}
    try:
        from intelligence import earnings as _earnings_intel
        if _earnings_intel.get_snapshot() is None:
            try:
                await _earnings_intel.fetch_and_refresh()
            except Exception:
                pass
        _earnings_by_symbol = _earnings_intel.get_results_by_symbol()
    except Exception:
        _earnings_by_symbol = {}
    try:
        from intelligence import insiders as _insiders_intel
        if _insiders_intel.get_snapshot() is None:
            try:
                await _insiders_intel.fetch_and_refresh()
            except Exception:
                pass
        _insider_txns_by_symbol = _insiders_intel.get_results_grouped_by_symbol()
    except Exception:
        _insider_txns_by_symbol = {}

    # ── 2d. Shadow scoring: snapshot premarket + reddit caches once per tick ──
    # Read-only from already-fetched in-memory caches. No new Polygon/ApeWisdom calls.
    # Phase I4-A: shadow/diagnostic only. Does not affect entries, exits, or decisions.
    _shadow_premarket_snap: dict | None = None
    _shadow_reddit_snap: dict | None = None
    _shadow_pm_lookup: dict = {}
    _shadow_rd_lookup: dict = {}
    try:
        from intelligence import full_premarket as _fp
        from intelligence.shadow_scoring import _build_premarket_lookup, _build_reddit_lookup
        _shadow_premarket_snap = _fp.get_snapshot() or None
        _shadow_pm_lookup = _build_premarket_lookup(_shadow_premarket_snap)
    except Exception:
        pass
    try:
        from intelligence import reddit as _reddit_intel
        from intelligence.shadow_scoring import _build_reddit_lookup as _brl
        _shadow_reddit_snap = _reddit_intel.get_snapshot()
        _shadow_rd_lookup = _brl(_shadow_reddit_snap)
    except Exception:
        pass

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

        # ── Phase G1B-H2 Part F: late EOD flatten ──────────────────────────
        # Catches positions that survived a prior NY session (e.g. the
        # simulator was stopped over the weekend, or the close window was
        # missed entirely). Runs on EVERY tick while overnight holding is
        # disabled — independent of `flatten_due()` which only fires at or
        # after 16:00 ET on the current session.
        result.setdefault("eod_flatten_warnings", [])
        try:
            from paper import eod as _eod_late
            for sym in list(_account.positions.keys()):
                pos = _account.positions.get(sym)
                if pos is None or not _eod_late.position_is_stale_overnight(pos.entry_time):
                    continue
                q = quality_map.get(sym) or {}
                exit_price = (
                    q.get("bid")
                    or q.get("last_trade_price")
                    or _last_prices.get(sym)
                )
                if not exit_price:
                    result["eod_flatten_warnings"].append({
                        "wallet_id": "engine",
                        "symbol": sym,
                        "entry_time": pos.entry_time,
                        "reason": "missing_exit_price_late_flatten",
                    })
                    continue
                trade = _account.exit_position(sym, float(exit_price), _eod_late.LATE_FLATTEN_REASON)
                if trade is None:
                    continue
                result["exits"].append({
                    "symbol": sym,
                    "exit_reason": _eod_late.LATE_FLATTEN_REASON,
                    "entry_price": round(pos.entry_price, 4),
                    "exit_price": round(float(exit_price), 4),
                    "pnl": round(trade.pnl, 4),
                    "pnl_percent": round(trade.pnl_percent, 4),
                    "hold_minutes": trade.hold_minutes,
                    "catalyst_type": trade.entry_catalyst_type,
                    "total_score": trade.entry_score,
                    "entry_mode": trade.entry_mode,
                    "position_id": pos.position_id,
                    "shares": round(pos.shares, 6),
                    "cost_basis": round(pos.cost_basis, 4),
                    "wallet_id": "engine",
                    "strategy_id": "engine",
                })
        except Exception as exc:
            logger.warning("Late EOD flatten failed defensively: %s", exc)

        # ── Phase G1B-H1 Part E: end-of-day flatten ─────────────────────────
        # Close every remaining open engine position once we're inside the
        # flatten window (defaults: at/after 16:00 ET). Reuses the standard
        # exit_position mechanics — no TP/SL changes outside this window.
        # Shadow wallets are flattened by their own helper below.
        try:
            from paper import eod as _eod
            if _eod.flatten_due():
                for sym in list(_account.positions.keys()):
                    pos = _account.positions.get(sym)
                    if pos is None:
                        continue
                    q = quality_map.get(sym) or {}
                    exit_price = (
                        q.get("bid")
                        or q.get("last_trade_price")
                        or _last_prices.get(sym)
                    )
                    if not exit_price:
                        result["eod_flatten_warnings"].append({
                            "wallet_id": "engine",
                            "symbol": sym,
                            "reason": "missing_exit_price",
                        })
                        continue
                    trade = _account.exit_position(sym, float(exit_price), "eod_flatten")
                    if trade is None:
                        continue
                    result["exits"].append({
                        "symbol": sym,
                        "exit_reason": "eod_flatten",
                        "entry_price": round(pos.entry_price, 4),
                        "exit_price": round(float(exit_price), 4),
                        "pnl": round(trade.pnl, 4),
                        "pnl_percent": round(trade.pnl_percent, 4),
                        "hold_minutes": trade.hold_minutes,
                        "catalyst_type": trade.entry_catalyst_type,
                        "total_score": trade.entry_score,
                        "entry_mode": trade.entry_mode,
                        "position_id": pos.position_id,
                        "shares": round(pos.shares, 6),
                        "cost_basis": round(pos.cost_basis, 4),
                        "wallet_id": "engine",
                        "strategy_id": "engine",
                    })
        except Exception as exc:
            logger.warning("EOD flatten failed defensively: %s", exc)

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

        today_market_mover_count = sum(
            1 for p in _account.positions.values()
            if p.entry_mode == "market_mover_no_catalyst" and p.entry_time.startswith(_today_str)
        ) + sum(
            1 for t in _account.trades
            if t.entry_mode == "market_mover_no_catalyst" and t.entry_time.startswith(_today_str)
        )
        result["today_market_mover_no_catalyst_entry_count"] = today_market_mover_count
        result["market_mover_no_catalyst_enabled"] = bool(_cfg("PAPER_MARKET_MOVER_ENTRY_ENABLED"))

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

            # ── Determine candidate sources (Phase I4-B) — must precede hard gates ──
            _mm_meta = _mover_meta_map.get(sym)
            _cand_sources: list[str] = []
            if _mm_meta:
                _cand_sources.append("full_market_movers")
            if not _cand_sources:
                _cand_sources.append("dynamic")

            # S1-V1: per-symbol time-adjusted volume computation
            _ta_ratio: float | None = None
            _expected_volume_now: int | None = None
            # True when TA vol is configured for this session but inputs are missing/invalid
            _ta_vol_missing: bool = False
            if bool(_cfg("PAPER_USE_TIME_ADJUSTED_VOLUME_RATIO")) and _tick_session_type == "regular":
                _min_floor = float(_cfg("PAPER_TIME_ADJUSTED_VOLUME_MIN_FLOOR"))
                _ta_ratio = _tv_ratio(
                    q.get("day_volume"),
                    q.get("previous_day_volume"),
                    _tick_session_elapsed_ratio,
                    _min_floor,
                )
                if _ta_ratio is not None and q.get("previous_day_volume"):
                    _eff = max(_tick_session_elapsed_ratio, _min_floor)
                    _expected_volume_now = int(q["previous_day_volume"] * _eff)
                else:
                    _ta_vol_missing = True

            # S1-V1: when time-adjusted volume is active and computable, replace
            # volume_ratio in quality view so all downstream evaluators use it.
            _use_ta_vol = bool(_cfg("PAPER_USE_TIME_ADJUSTED_VOLUME_RATIO")) and _tick_session_type == "regular" and _ta_ratio is not None
            _q_for_paths = dict(q, volume_ratio=_ta_ratio) if _use_ta_vol else q

            # Phase I6: per-symbol earnings + insider info from pre-fetched caches.
            try:
                from intelligence.earnings import score_earnings_proximity as _score_earnings
                _earn_info = _score_earnings(sym, _earnings_by_symbol)
            except Exception:
                _earn_info = None
            try:
                from intelligence.insiders import score_insiders as _score_insiders
                _ins_info = _score_insiders(sym, _insider_txns_by_symbol)
            except Exception:
                _ins_info = None

            # Score using adjusted quality view so scoring volume component also uses TA ratio.
            scoring = score_candidate(
                sym,
                _q_for_paths,
                cats,
                earnings_info=_earn_info,
                insider_info=_ins_info,
            )

            # ── Hard safety gates shared by all entry paths ────────────────────
            # These gates hard-reject regardless of mode.
            hard_rejection: str | None = None
            is_no_catalyst_rejection: bool = False
            _sym_meta = source_meta_map.get(sym, {})

            # N1: market mover candidates in premarket use their own volume gate — skip
            # the raw volume_ratio gate so the no-catalyst check can proceed to Path D.
            _is_mm_premarket = (
                bool(_cfg("PAPER_MARKET_MOVER_ENTRY_ENABLED"))
                and _mm_meta is not None
                and _tick_session_type not in ("regular",)
            )

            if not q.get("tradable"):
                reasons = q.get("rejection_reasons", [])
                hard_rejection = f"not tradable: {reasons[0] if reasons else 'failed quality gate'}"
            elif (q.get("spread_percent") or 999) > 0.50:
                hard_rejection = f"spread {q.get('spread_percent')}% > 0.50%"
            elif (q.get("change_percent") or 0) <= 0:
                hard_rejection = f"change_percent {q.get('change_percent')} not positive"
            elif _ta_vol_missing:
                hard_rejection = "missing_time_adjusted_volume"
            elif _use_ta_vol and _ta_ratio < float(_cfg("PAPER_TIME_ADJUSTED_VOLUME_RATIO_MIN")):
                hard_rejection = f"ta_volume_ratio {_ta_ratio} < {_cfg('PAPER_TIME_ADJUSTED_VOLUME_RATIO_MIN')}"
            elif (
                not _use_ta_vol
                and not _is_mm_premarket
                and q.get("volume_ratio") is not None
                and q.get("volume_ratio", 1.0) < _cfg("PAPER_MIN_VOLUME_RATIO")
            ):
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
            # Stale data overrides is_no_catalyst_rejection so Path C/D never fire on stale data.
            if (
                _cfg("PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY")
                and _sym_meta.get("marketdata_stale")
            ):
                hard_rejection = "stale_marketdata_entry_blocked"
                is_no_catalyst_rejection = False

            cat_type = cats[0].get("classified_event_type") if cats else None

            # ── Catalyst-type block (Phase 2T — fake-money only, no broker, no real orders) ──
            # Scan all accepted catalysts; block on the first match in order.
            _blocked_cat_type: str | None = None
            if hard_rejection is None and _blocked_cat_types:
                for _c in cats:
                    _ct = _c.get("classified_event_type")
                    if _ct and _ct in _blocked_cat_types:
                        _blocked_cat_type = _ct
                        break
                if _blocked_cat_type is not None:
                    hard_rejection = f"catalyst_type_blocked:{_blocked_cat_type}"
                    is_no_catalyst_rejection = False

            # ── Momentum evaluation (always computed when mode enabled) ────────
            # Phase M1-H1: legacy momentum reads the RAW regime by default.
            # Operators can opt in to the trend-adjusted regime via
            # MARKET_TREND_APPLY_TO_LEGACY_MOMENTUM=true.
            momentum_eval: dict | None = None
            _legacy_regime_used = _regime_for(_trend_apply_legacy)
            if _cfg("PAPER_MOMENTUM_MODE_ENABLED"):
                try:
                    momentum_eval = evaluate_momentum_entry(sym, _q_for_paths, _legacy_regime_used)
                except Exception:
                    momentum_eval = None

            # ── No-catalyst evaluation (Phase 2R) ─────────────────────────────
            # Phase M1-H1: no-catalyst uses TREND-ADJUSTED regime by default
            # so deteriorating proxy momentum makes the risk_on gate harder.
            nc_eval: dict | None = None
            _nc_regime_used = _regime_for(_trend_apply_no_cat)
            if is_no_catalyst_rejection:
                try:
                    nc_eval = evaluate_no_catalyst_entry(sym, _q_for_paths, scoring, _nc_regime_used)
                except Exception:
                    nc_eval = None

            # ── Market mover no-catalyst evaluation (Phase N1) ─────────────────
            # Fires for full_market_movers candidates in allowed sessions only.
            # Separate from nc_eval — different thresholds and volume check.
            # No Polygon calls. Fake-money only. No broker. No real orders.
            _mm_eval: dict | None = None
            _mm_entry_checked = False
            _mm_entry_eligible = False
            _mm_entry_reason: str | None = None
            _mm_entry_blockers: list[str] = []
            _mm_entry_session: str | None = None
            _mm_entry_vol_gate_type: str | None = None
            _mm_entry_vol_ratio_used: float | None = None
            _mm_entry_size_mult: float | None = None
            _mm_unsafe_sessions_warning: str | None = None
            _mm_risk_off_allowed: bool | None = None
            _mm_regime_used_kind: str | None = None
            _mm_regime_label_used: str | None = None
            _mm_risk_score_used: int | float | None = None

            if (
                bool(_cfg("PAPER_MARKET_MOVER_ENTRY_ENABLED"))
                and _mm_meta is not None
                and (hard_rejection is None or is_no_catalyst_rejection)
            ):
                _mm_entry_checked = True
                _mm_entry_session = _tick_session_type

                # N1-H1: normalize configured sessions and intersect with safe set.
                # Unsafe values (afterhours, closed, non_regular, overnight, unknown)
                # are silently stripped and exposed as a warning — never allowed.
                _mm_raw_sessions = frozenset(
                    s.strip().lower()
                    for s in str(_cfg("PAPER_MARKET_MOVER_ALLOWED_SESSIONS")).split(",")
                    if s.strip()
                )
                _mm_configured_safe = _mm_raw_sessions & _MM_SAFE_SESSIONS
                _mm_configured_unsafe = _mm_raw_sessions - _MM_SAFE_SESSIONS
                if _mm_configured_unsafe:
                    _mm_unsafe_sessions_warning = (
                        f"Unsafe market mover sessions ignored: "
                        f"{', '.join(sorted(_mm_configured_unsafe))}"
                    )

                # Hard block: session is not in the safe set at all.
                if _tick_session_type not in _MM_SAFE_SESSIONS:
                    _mm_entry_reason = "market_mover_session_not_allowed"
                    _mm_entry_blockers = ["session_hard_blocked"]
                # Config block: session is safe but operator disabled it via config.
                elif _tick_session_type not in _mm_configured_safe:
                    _mm_entry_reason = "market_mover_session_not_allowed"
                    _mm_entry_blockers = ["session_not_allowed_by_config"]
                else:
                    _mm_blockers: list[str] = []

                    # Risk-off gate (Phase N1-H1 + M1-H1): block when regime is
                    # risk_off and PAPER_MARKET_MOVER_ALLOW_RISK_OFF=false.
                    # M1-H1: use trend-adjusted regime when
                    # MARKET_TREND_APPLY_TO_MARKET_MOVER=true.
                    _mm_risk_off_allowed = bool(_cfg("PAPER_MARKET_MOVER_ALLOW_RISK_OFF"))
                    _mm_regime_obj = _regime_for(_trend_apply_mm)
                    _mm_regime_used_kind = (
                        "trend_adjusted"
                        if _trend_apply_mm and _tick_regime_adjusted is not None
                        else "raw"
                    )
                    _mm_regime_label_used = (
                        (_mm_regime_obj or {}).get("regime") if _mm_regime_obj else None
                    )
                    _mm_risk_score_used = (
                        (_mm_regime_obj or {}).get("risk_on_score") if _mm_regime_obj else None
                    )
                    if (
                        not _mm_risk_off_allowed
                        and _mm_regime_obj is not None
                        and _mm_regime_obj.get("regime") == "risk_off"
                    ):
                        _mm_blockers.append(
                            "market_mover_risk_off_blocked_by_trend_adjusted_regime"
                            if _mm_regime_used_kind == "trend_adjusted"
                            else "risk_off_blocked"
                        )

                    # Rank check
                    _mm_rank = _mm_meta.get("market_mover_rank")
                    _mm_rank_max = int(_cfg("PAPER_MARKET_MOVER_TOP_RANK_MAX"))
                    if _mm_rank is None or _mm_rank > _mm_rank_max:
                        _mm_blockers.append(f"rank_{_mm_rank}_above_{_mm_rank_max}")

                    # Change percent window
                    _mm_chg = q.get("change_percent") or 0
                    _mm_chg_min = float(_cfg("PAPER_MARKET_MOVER_MIN_CHANGE_PERCENT"))
                    _mm_chg_max = float(_cfg("PAPER_MARKET_MOVER_MAX_CHANGE_PERCENT"))
                    if _mm_chg < _mm_chg_min:
                        _mm_blockers.append(f"change_{round(_mm_chg, 2)}_below_{_mm_chg_min}")
                    elif _mm_chg > _mm_chg_max:
                        _mm_blockers.append(f"change_{round(_mm_chg, 2)}_above_{_mm_chg_max}")

                    # Spread
                    _mm_spread = q.get("spread_percent") or 999
                    _mm_spread_max = float(_cfg("PAPER_MARKET_MOVER_MAX_SPREAD_PERCENT"))
                    if _mm_spread > _mm_spread_max:
                        _mm_blockers.append(f"spread_{round(_mm_spread, 4)}_above_{_mm_spread_max}")

                    # Score
                    _mm_score_val = scoring.get("total_score") or 0
                    _mm_score_min = int(_cfg("PAPER_MARKET_MOVER_MIN_SCORE"))
                    if _mm_score_val < _mm_score_min:
                        _mm_blockers.append(f"score_{_mm_score_val}_below_{_mm_score_min}")

                    # Catalyst type block (fda_regulatory, etc.)
                    if _blocked_cat_type is not None:
                        _mm_blockers.append(f"catalyst_type_blocked:{_blocked_cat_type}")

                    # Bearish block
                    if bool(_cfg("PAPER_MARKET_MOVER_BLOCK_IF_ANY_BEARISH")):
                        _mm_bearish_mat = scoring.get("catalyst_materiality_score") or 0
                        if (scoring.get("catalyst_sentiment") == "bearish"
                                and _mm_bearish_mat >= float(_cfg("PAPER_BEARISH_CATALYST_REJECT_MATERIALITY"))):
                            _mm_blockers.append("strong_bearish_blocked")

                    # Session-specific volume gate — only reachable for safe sessions.
                    # regular → time-adjusted volume ratio required.
                    # premarket → volume_vs_prev or dollar_volume required.
                    # Any other value cannot reach here (hard-blocked above).
                    _mm_day_vol = q.get("day_volume") or 0
                    _mm_prev_vol = q.get("previous_day_volume") or 0
                    _mm_price = q.get("last_trade_price") or q.get("ask") or 0
                    _mm_dollar_vol = int(_mm_day_vol * _mm_price) if _mm_day_vol and _mm_price else 0
                    _mm_vol_vs_prev = (_mm_day_vol / _mm_prev_vol) if _mm_prev_vol > 0 else None

                    if _tick_session_type == "regular":
                        _mm_ta_min = float(_cfg("PAPER_MARKET_MOVER_MIN_TIME_ADJ_VOLUME_RATIO"))
                        _mm_entry_vol_gate_type = "time_adjusted"
                        if _ta_ratio is None:
                            _mm_blockers.append("missing_time_adjusted_volume")
                        elif _ta_ratio < _mm_ta_min:
                            _mm_blockers.append(f"ta_vol_{round(_ta_ratio, 4)}_below_{_mm_ta_min}")
                            _mm_entry_vol_ratio_used = _ta_ratio
                        else:
                            _mm_entry_vol_ratio_used = _ta_ratio

                    elif _tick_session_type == "premarket":
                        _mm_pm_vol_min = float(_cfg("PAPER_MARKET_MOVER_MIN_PREMARKET_VOLUME_VS_PREV_DAY_RATIO"))
                        _mm_dollar_min = int(_cfg("PAPER_MARKET_MOVER_MIN_DOLLAR_VOLUME"))
                        if _mm_vol_vs_prev is not None and _mm_vol_vs_prev >= _mm_pm_vol_min:
                            _mm_entry_vol_gate_type = "premarket_volume_vs_prev"
                            _mm_entry_vol_ratio_used = _mm_vol_vs_prev
                        elif _mm_dollar_vol >= _mm_dollar_min:
                            _mm_entry_vol_gate_type = "premarket_dollar_volume"
                            _mm_entry_vol_ratio_used = float(_mm_dollar_vol)
                        else:
                            _mm_entry_vol_gate_type = "premarket"
                            _mm_blockers.append(
                                f"premarket_volume_insufficient:"
                                f"vol_vs_prev={round(_mm_vol_vs_prev, 4) if _mm_vol_vs_prev is not None else None}"
                                f"_dollar_vol={_mm_dollar_vol}"
                            )

                    if not _mm_blockers:
                        _mm_entry_eligible = True
                        _mm_entry_reason = "eligible"
                        _mm_entry_size_mult = float(_cfg("PAPER_MARKET_MOVER_POSITION_SIZE_MULTIPLIER"))
                    else:
                        _mm_entry_eligible = False
                        _mm_entry_reason = "blocked"
                        _mm_entry_blockers = _mm_blockers

                _mm_eval = {
                    "eligible": _mm_entry_eligible,
                    "session": _mm_entry_session,
                    "blockers": _mm_entry_blockers,
                    "reason": _mm_entry_reason,
                    "volume_gate_type": _mm_entry_vol_gate_type,
                    "volume_ratio_used": _mm_entry_vol_ratio_used,
                    "size_multiplier": _mm_entry_size_mult,
                }

            # ── Phase M1-H4: market-trend telemetry is now set ONLY from the
            # actual selected entry branch (see _final_selected_path below).
            # These four variables are initialized to the conservative
            # rejected_before_path defaults so the candidate dict can be
            # constructed; the real values are written after the branch chain
            # runs, via _trend_usage_for_path(_final_selected_path, …).
            _initial_trend_usage = _trend_usage_for_path(
                "rejected_before_path",
                _tick_regime,
                _tick_regime_adjusted,
                apply_legacy=_trend_apply_legacy,
                apply_no_cat=_trend_apply_no_cat,
                apply_mm=_trend_apply_mm,
                apply_catalyst=_trend_apply_catalyst,
            )
            _trend_path_name = _initial_trend_usage["path_name"]
            _trend_path_consumed = _initial_trend_usage["consumed"]
            _trend_path_regime_used = _initial_trend_usage["regime_used"]
            _trend_path_regime_label_used = _initial_trend_usage["regime_label_used"]

            candidate: dict[str, Any] = {
                "symbol": sym,
                "eligible": False,
                "rejection_reason": hard_rejection,
                "action": None,
                "quality_tradable": q.get("tradable"),
                "spread_percent": q.get("spread_percent"),
                "change_percent": q.get("change_percent"),
                "volume_ratio": q.get("volume_ratio"),
                # S1-V1: time-adjusted volume fields
                "time_adjusted_volume_enabled": _use_ta_vol,
                "time_adjusted_volume_ratio": _ta_ratio,
                "expected_volume_now": _expected_volume_now,
                "prev_day_volume": q.get("previous_day_volume"),
                "session_elapsed_ratio": _tick_session_elapsed_ratio,
                "volume_gate_type": "time_adjusted" if _use_ta_vol else "raw",
                "volume_gate_ratio_used": _ta_ratio if _use_ta_vol else q.get("volume_ratio"),
                "volume_gate_threshold_used": float(_cfg("PAPER_TIME_ADJUSTED_VOLUME_RATIO_MIN")) if _use_ta_vol else float(_cfg("PAPER_MIN_VOLUME_RATIO")),
                "catalyst_count": len(cats),
                "catalyst_type": cat_type,
                "catalyst_type_blocked": _blocked_cat_type is not None,
                "blocked_catalyst_type": _blocked_cat_type,
                "catalyst_type_weight": None,
                # Phase I4-B: candidate source metadata
                "candidate_sources": _cand_sources,
                "market_mover_rank":        _mm_meta["market_mover_rank"]        if _mm_meta else None,
                "market_mover_gap_percent": _mm_meta["market_mover_gap_percent"] if _mm_meta else None,
                "market_mover_session":     _mm_meta["market_mover_session"]     if _mm_meta else None,
                "market_mover_mode":        _mm_meta["market_mover_mode"]        if _mm_meta else None,
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
                # Intelligence adjustments (Phase I6 — fake-money only, transparent)
                "base_score_before_intelligence_adjustments": scoring.get("base_score_before_intelligence_adjustments"),
                "intelligence_score_adjustment": scoring.get("intelligence_score_adjustment"),
                "final_score_after_intelligence_adjustments": scoring.get("final_score_after_intelligence_adjustments"),
                "earnings_scoring_enabled": scoring.get("earnings_scoring_enabled"),
                "earnings_next_date": scoring.get("earnings_next_date"),
                "earnings_days_until": scoring.get("earnings_days_until"),
                "earnings_score_adjustment": scoring.get("earnings_score_adjustment"),
                "earnings_reason": scoring.get("earnings_reason"),
                "earnings_blocked": scoring.get("earnings_blocked"),
                "insider_scoring_enabled": scoring.get("insider_scoring_enabled"),
                "insider_recent_buy_count": scoring.get("insider_recent_buy_count"),
                "insider_recent_buy_value": scoring.get("insider_recent_buy_value"),
                "insider_score_adjustment": scoring.get("insider_score_adjustment"),
                "insider_reason": scoring.get("insider_reason"),
                "insider_latest_transaction_date": scoring.get("insider_latest_transaction_date"),
                "insider_transaction_codes": scoring.get("insider_transaction_codes"),
                # Market trend overlay (Phase M1 + M1-H1 — ETF proxy, telemetry on every row)
                "market_trend_enabled": (_tick_trend or {}).get("market_trend_enabled"),
                "market_trend_source": (_tick_trend or {}).get("market_trend_source"),
                "market_trend_direction": (_tick_trend or {}).get("market_trend_direction"),
                "market_trend_strength": (_tick_trend or {}).get("market_trend_strength"),
                "market_trend_adjustment": (_tick_trend or {}).get("market_trend_adjustment"),
                "market_trend_reason": (_tick_trend or {}).get("market_trend_reason"),
                "market_regime_score_before_trend": (_tick_trend or {}).get("market_regime_score_before_trend"),
                "market_regime_score_after_trend": (_tick_trend or {}).get("market_regime_score_after_trend"),
                "market_trend_collecting": (_tick_trend or {}).get("market_trend_collecting"),
                "market_trend_has_5m_window": (_tick_trend or {}).get("market_trend_has_5m_window"),
                "market_trend_has_10m_window": (_tick_trend or {}).get("market_trend_has_10m_window"),
                "market_trend_has_15m_window": (_tick_trend or {}).get("market_trend_has_15m_window"),
                "market_trend_consumers": (_tick_trend or {}).get("trend_consumers"),
                # Phase M1-H2: derive path telemetry from the actual entry-
                # evaluation path, not from candidate source metadata. The
                # invariant is: which evaluator's regime input actually drove
                # this candidate's decision.
                "market_trend_path_name": _trend_path_name,
                "market_trend_consumed_by_path": _trend_path_consumed,
                "market_trend_regime_used": _trend_path_regime_used,
                # Raw vs adjusted regime LABELS at the tick, plus the label
                # that the candidate's actual path consumed.
                "market_regime_label_before_trend": (_tick_regime or {}).get("regime"),
                "market_regime_label_after_trend": (_tick_regime_adjusted or {}).get("regime") if _tick_regime_adjusted is not None else None,
                "market_trend_regime_label_used": _trend_path_regime_label_used,
                # Market mover: which regime did we use, what score/label
                "market_mover_regime_used": _mm_regime_used_kind,
                "market_mover_risk_score_used": _mm_risk_score_used,
                "market_mover_regime_label_used": _mm_regime_label_used,
                # Shadow: which regime drove the shadow scorer
                "market_trend_shadow_consumed": bool(_trend_apply_shadow and _tick_regime_adjusted is not None),
                "market_trend_shadow_regime_used": (
                    "trend_adjusted"
                    if _trend_apply_shadow and _tick_regime_adjusted is not None
                    else "raw"
                ),
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
                # Phase N1: market mover no-catalyst entry evaluation fields
                "market_mover_entry_checked": _mm_entry_checked,
                "market_mover_entry_eligible": _mm_entry_eligible,
                "market_mover_entry_reason": _mm_entry_reason,
                "market_mover_entry_blockers": _mm_entry_blockers,
                "market_mover_entry_session": _mm_entry_session,
                "market_mover_entry_volume_gate_type": _mm_entry_vol_gate_type,
                "market_mover_entry_volume_ratio_used": _mm_entry_vol_ratio_used,
                "market_mover_entry_position_size_multiplier": _mm_entry_size_mult,
                "market_mover_unsafe_sessions_warning": _mm_unsafe_sessions_warning,
                "market_mover_risk_off_allowed": _mm_risk_off_allowed,
                # Premarket volume metrics (useful for market mover diagnostics)
                "volume_vs_previous_day_ratio": (
                    round((q.get("day_volume") or 0) / (q.get("previous_day_volume") or 1), 4)
                    if (q.get("previous_day_volume") or 0) > 0 else None
                ),
                "dollar_volume": (
                    int((q.get("day_volume") or 0) * (q.get("last_trade_price") or q.get("ask") or 0))
                    if (q.get("day_volume") or 0) > 0 else 0
                ),
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
            # Phase M1-H4: track which entry branch is actually selected for
            # THIS candidate. Updated INSIDE each branch (not before). After
            # the branch chain, _trend_usage_for_path() writes the final
            # market-trend telemetry. No pre-branch inference.
            _final_selected_path = "rejected_before_path"

            # Phase G1B-H1 Part E: short-circuit ALL entry paths inside the
            # end-of-day cutoff window. Scoring/decision logic upstream is
            # untouched — we only refuse to act. Applies when overnight
            # holding is disabled and EOD flatten is enabled (defaults).
            try:
                from paper import eod as _eod
                _eod_block, _eod_reason = _eod.entries_blocked()
            except Exception:
                _eod_block, _eod_reason = (False, None)
            if _eod_block:
                candidate["eligible"] = False
                candidate["action"] = _eod_reason
                candidate["rejection_reason"] = _eod_reason
                # Skip the branch chain entirely; the rest of the per-
                # candidate enrichment (trend telemetry, shadow, LLM) still
                # runs so dashboards remain coherent.
                pass
            # Path A: Catalyst entry (existing logic, unchanged)
            elif hard_rejection is None and scoring["score_pass"]:
                _final_selected_path = "catalyst"
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

            # Path D: Market mover no-catalyst entry (Phase N1 — fake-money only, no broker, no real orders)
            # Fires for full_market_movers candidates without accepted catalyst coverage.
            # Session-aware: premarket and regular only. Afterhours/closed/non_regular blocked.
            elif (
                hard_rejection is not None
                and is_no_catalyst_rejection
                and _mm_eval is not None
                and _mm_eval["eligible"]
            ):
                _final_selected_path = "market_mover_no_catalyst"
                # Market mover daily limit gate
                _mm_day_max = int(_cfg("PAPER_MARKET_MOVER_MAX_TRADES_PER_DAY"))
                if today_market_mover_count >= _mm_day_max:
                    candidate["action"] = f"market_mover_blocked: daily limit {_mm_day_max}"
                    candidate["rejection_reason"] = hard_rejection
                elif _guard["triggered"]:
                    candidate["action"] = "daily_max_loss_guard"
                    candidate["rejection_reason"] = "daily_max_loss_guard"
                else:
                    candidate["eligible"] = True
                    candidate["entry_mode"] = "market_mover_no_catalyst"
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
                            size_multiplier = float(_cfg("PAPER_MARKET_MOVER_POSITION_SIZE_MULTIPLIER"))
                            normal_budget = min(
                                _account.cash * (pos_pct / 100.0),
                                settings.PAPER_MAX_POSITION_SIZE_USD,
                            )
                            position_budget = normal_budget * size_multiplier
                            pos = _account.enter_position(
                                sym, entry_price,
                                position_budget,
                                "market_mover_no_catalyst",
                                entry_score=scoring["total_score"],
                                entry_mode="market_mover_no_catalyst",
                            )
                            if pos:
                                today_market_mover_count += 1
                                result["today_market_mover_no_catalyst_entry_count"] = today_market_mover_count
                                candidate["action"] = "entered"
                                result["entries"].append({
                                    "symbol": sym,
                                    "entry_price": round(entry_price, 4),
                                    "shares": round(pos.shares, 6),
                                    "cost_basis": round(pos.cost_basis, 4),
                                    "catalyst_type": "market_mover_no_catalyst",
                                    "total_score": scoring["total_score"],
                                    "entry_mode": "market_mover_no_catalyst",
                                    "position_id": pos.position_id,
                                    "market_mover_rank": _mm_meta.get("market_mover_rank") if _mm_meta else None,
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

            # Path C: No-catalyst momentum entry (Phase 2R)
            elif (
                hard_rejection is not None
                and is_no_catalyst_rejection
                and nc_eval is not None
                and nc_eval["eligible"]
            ):
                _final_selected_path = "no_catalyst"
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
                _final_selected_path = "legacy_momentum"
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

            # ── Phase M1-H4: write final market-trend telemetry from the
            # actual selected entry branch. No pre-branch inference: a
            # catalyst-eligible candidate that is also momentum-eligible
            # reports "catalyst" (Path A wins). A no-catalyst candidate that
            # ultimately enters via legacy momentum fallback reports
            # "legacy_momentum" (Path B wins). When no branch was selected,
            # _final_selected_path stays "rejected_before_path".
            _final_trend_usage = _trend_usage_for_path(
                _final_selected_path,
                _tick_regime,
                _tick_regime_adjusted,
                apply_legacy=_trend_apply_legacy,
                apply_no_cat=_trend_apply_no_cat,
                apply_mm=_trend_apply_mm,
                apply_catalyst=_trend_apply_catalyst,
            )
            candidate["market_trend_path_name"]        = _final_trend_usage["path_name"]
            candidate["market_trend_consumed_by_path"] = _final_trend_usage["consumed"]
            candidate["market_trend_regime_used"]      = _final_trend_usage["regime_used"]
            candidate["market_trend_regime_label_used"] = _final_trend_usage["regime_label_used"]

            # ── Phase I4-A: Enhanced shadow scoring (diagnostic only) ────────
            # Shadow fields are appended after all real decisions are finalized.
            # They do not affect eligible, action, entry_mode, or any account state.
            # Phase M1-H2: route raw vs trend-adjusted regime to the shadow
            # scorer according to MARKET_TREND_APPLY_TO_SHADOW.
            _shadow_regime = _regime_for(_trend_apply_shadow)
            try:
                from intelligence.shadow_scoring import compute_shadow_score
                _shadow = compute_shadow_score(
                    symbol=sym,
                    quality=q,
                    scoring=scoring,
                    tick_regime=_shadow_regime,
                    premarket_snap=_shadow_premarket_snap,
                    reddit_snap=_shadow_reddit_snap,
                    blocked_cat_types=_blocked_cat_types,
                    premarket_lookup=_shadow_pm_lookup,
                    reddit_lookup=_shadow_rd_lookup,
                )
                candidate.update(_shadow)
            except Exception:
                candidate["enhanced_shadow_score"] = None
                candidate["enhanced_shadow_decision"] = None
                candidate["enhanced_shadow_reason"] = "shadow_scoring_error"
                candidate["enhanced_shadow_components"] = {}
                candidate["enhanced_shadow_blockers"] = []
                candidate["enhanced_shadow_confidence"] = "low"
                candidate["premarket_rank"] = None
                candidate["premarket_gap_percent"] = None
                candidate["premarket_dollar_volume"] = None
                candidate["premarket_volume"] = None
                candidate["premarket_source"] = None
                candidate["premarket_mode"] = None
                candidate["premarket_boost"] = 0
                candidate["reddit_rank"] = None
                candidate["reddit_mentions"] = None
                candidate["reddit_spike_ratio"] = None
                candidate["reddit_boost"] = 0

            result["candidates"].append(candidate)

    # ── 4b. Shadow aggregate stats (diagnostic only, Phase I4-A) ─────────────
    _shadow_would_enter = [
        c for c in result["candidates"] if c.get("enhanced_shadow_decision") == "WOULD_ENTER"
    ]
    _shadow_watch = [
        c for c in result["candidates"] if c.get("enhanced_shadow_decision") == "WATCH"
    ]
    _shadow_reject = [
        c for c in result["candidates"] if c.get("enhanced_shadow_decision") == "WOULD_REJECT"
    ]
    _missed = [
        c for c in _shadow_would_enter if not c.get("eligible")
    ]
    _top_shadow = sorted(
        _shadow_would_enter,
        key=lambda c: c.get("enhanced_shadow_score") or 0,
        reverse=True,
    )[:10]
    result["enhanced_shadow_stats"] = {
        "enhanced_shadow_would_enter_count": len(_shadow_would_enter),
        "enhanced_shadow_watch_count":       len(_shadow_watch),
        "enhanced_shadow_reject_count":      len(_shadow_reject),
        "missed_opportunity_count":          len(_missed),
        "enhanced_shadow_top_symbols": [
            {
                "symbol":                  c["symbol"],
                "enhanced_shadow_score":   c.get("enhanced_shadow_score"),
                "enhanced_shadow_decision": c.get("enhanced_shadow_decision"),
                "eligible":                c.get("eligible"),
                "premarket_rank":          c.get("premarket_rank"),
                "premarket_gap_percent":   c.get("premarket_gap_percent"),
                "reddit_rank":             c.get("reddit_rank"),
            }
            for c in _top_shadow
        ],
        "disclaimer": "Shadow only — not used for trading decisions.",
    }
    _state["last_shadow_stats"] = result["enhanced_shadow_stats"]

    # ── 4c. Phase L1: LLM Shadow Analyst (diagnostic only) ──────────────────
    # Initializes safe defaults on every candidate, then — only when enabled
    # AND the API key is present — picks up to N candidates and analyzes them.
    # The LLM output never modifies eligible/action/entry_mode.
    try:
        from intelligence import llm_shadow as _llm_mod
        # Phase G1A-H1: provider-aware readiness. Replaces the cloud-LLM-era
        # api_key_present() gate which blocked the local-provider path.
        # See intelligence.llm_shadow.simulator_ready() for the full matrix.
        _llm_default = _llm_mod.default_not_selected_result()
        _llm_ready, _llm_default_status = _llm_mod.simulator_ready()
        _llm_default = {**_llm_default, "llm_status": _llm_default_status}
        for c in result["candidates"]:
            for k, v in _llm_default.items():
                c.setdefault(k, v)
        _llm_mod.reset_tick_counters()

        if _llm_ready:
            try:
                _open_syms = {p.symbol for p in _account.positions.values()}
            except Exception:
                _open_syms = set()
            _blocked_set = set(_blocked_cat_types or [])
            _picked = _llm_mod.select_candidates_for_llm(
                result["candidates"],
                open_position_symbols=_open_syms,
                blocked_catalyst_types=_blocked_set,
            )
            _acct_summary = {
                "open_position_count": len(_open_syms),
                "symbols_open": _open_syms,
                "account_cash": getattr(_account, "cash", None),
                "account_equity": getattr(_account, "equity", None),
                "daily_realized_pnl": getattr(_account, "daily_realized_pnl", None),
                "daily_loss_guard_triggered": bool(_guard.get("triggered")) if _guard else None,
            }

            # Build news_items_by_symbol from the catalysts the engine already
            # accepted for the selected symbols. No new news fetches; capped
            # per LLM_SHADOW_MAX_NEWS_ITEMS_PER_SYMBOL.
            _llm_news_cap = max(1, int(_cfg("LLM_SHADOW_MAX_NEWS_ITEMS_PER_SYMBOL")))
            _llm_news_by_sym: dict[str, list[dict]] = {}
            for _c in _picked:
                _sym = (_c.get("symbol") or "").upper()
                _rows = catalyst_map.get(_sym) or []
                if _rows:
                    _llm_news_by_sym[_sym] = list(_rows)[:_llm_news_cap]
                else:
                    _llm_news_by_sym[_sym] = []  # explicit "no news for this symbol"

            async def _analyze_one(c: dict) -> tuple[str, dict]:
                _sym_for_pkt = (c.get("symbol") or "").upper()
                packet = _llm_mod.build_candidate_packet(
                    c,
                    market_regime=_tick_regime,
                    market_trend=_tick_trend,
                    account_summary=_acct_summary,
                    news_items_by_symbol=_llm_news_by_sym,
                    earnings_by_symbol=_earnings_by_symbol,
                    insiders_by_symbol=_insider_txns_by_symbol,
                    reddit_lookup=_shadow_reddit_snap,
                    premarket_lookup=_shadow_pm_lookup,
                    intraday_history=None,  # falls through to llm_shadow.get_cached_intraday_history
                    quality=quality_map.get(_sym_for_pkt),
                )
                res = await _llm_mod.analyze_candidate_packet(packet)
                _llm_mod.record_tick_call()
                return (c.get("symbol") or "").upper(), res

            _results = await asyncio.gather(
                *[_analyze_one(c) for c in _picked], return_exceptions=True
            )
            _by_sym: dict[str, dict] = {}
            for r in _results:
                if isinstance(r, Exception):
                    continue
                sym, payload = r
                if sym:
                    _by_sym[sym] = payload
            for c in result["candidates"]:
                sym = (c.get("symbol") or "").upper()
                if sym in _by_sym:
                    for k, v in _by_sym[sym].items():
                        c[k] = v
    except Exception as exc:
        # Defensive: LLM layer must never break a tick.
        logger.warning("LLM shadow layer failed defensively: %s", type(exc).__name__)

    # ── 4d. Phase G1B Part C: parallel fake wallets ─────────────────────────
    # Off by default; gated by settings.PAPER_SHADOW_WALLETS_ENABLED. Runs
    # independent DETERMINISTIC_SHADOW + AI_SHADOW ledgers using the same
    # sizing/TP/SL/max-hold as the engine wallet. Never touches _account.
    try:
        from paper import shadow_wallets as _sw
        if _sw.enabled():
            _sw_out = _sw.process_tick(
                result["candidates"], quality_map, intrabar_map
            )
            result["shadow_entries"] = _sw_out.get("entries", [])
            result["shadow_exits"] = _sw_out.get("exits", [])
            result["shadow_wallets_snapshot"] = _sw_out.get("snapshots", {})
            # Surface EOD flatten warnings (missing exit price etc.) so the
            # dashboard can warn instead of silently leaving a position open.
            for w in _sw_out.get("warnings") or []:
                result.setdefault("eod_flatten_warnings", []).append(w)
        else:
            result["shadow_entries"] = []
            result["shadow_exits"] = []
            result["shadow_wallets_snapshot"] = {}
    except Exception as exc:
        logger.warning("Shadow wallets layer failed defensively: %s", exc)
        result["shadow_entries"] = []
        result["shadow_exits"] = []
        result["shadow_wallets_snapshot"] = {}

    # ── 5. Update in-memory state ─────────────────────────────────────────────
    result["exits_made"] = len(result["exits"])
    result["entries_made"] = len(result["entries"])
    _state["last_tick_at"] = tick_start.isoformat()
    _state["last_tick_symbols_evaluated"] = result["symbols_evaluated"]
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

    # ── 7. Persist Redis snapshot AFTER confirmed journal success ─────────────
    # _save_state is skipped when journal persistence fails or raises so that
    # saved_after_journal:true is only stamped on snapshots whose positions are
    # guaranteed to have a matching journal entry row (Phase 2U-H1).
    _journal_ok = isinstance(result["journal"], dict) and result["journal"].get("ok") is True
    if _journal_ok:
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
