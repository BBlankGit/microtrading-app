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
from paper.runtime_config import effective_value as _cfg
from data.market_quality import evaluate_market_quality
from data.polygon_client import PolygonError
from data.redis_client import make_redis
from paper.account import PaperAccount
from paper.journal import persist_tick_result as _persist_journal_tick
from paper.momentum import evaluate_momentum_entry
from paper.risk import daily_loss_guard_triggered as _daily_loss_guard
from paper.scoring import score_candidate
from paper.universe import get_active_paper_universe, get_cached_universe

logger = logging.getLogger(__name__)

_REDIS_KEY = "paper:state"


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
}


# ── Public API ────────────────────────────────────────────────────────────────

def get_state() -> dict[str, Any]:
    if _simulator_task is not None and _simulator_task.done():
        _state["running"] = False
    return dict(_state)


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
        "state_restored_from_snapshot": False,
        "restart_persistent": False,
        "mode": "research_paper_simulation",
        "live_trading_enabled": False,
        "broker_connected": False,
    })
    # Daily loss guard status (fake-money only, observational)
    try:
        status["daily_loss_guard"] = _daily_loss_guard(_account, _last_prices)
    except Exception:
        status["daily_loss_guard"] = {"triggered": False, "reason": None, "enabled": False}
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
    global _account, _last_prices
    await stop_simulator()
    async with _lock:
        _account.reset()
        _account.daily_baseline_date = _ny_trading_date()
        _account.daily_start_equity = _account.starting_cash
        _last_prices = {}
        _state["last_tick_at"] = None
        _state["last_error"] = None
        _state["last_candidates"] = []
        _state["snapshot_storage"] = "memory"
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
        "daily_loss_guard": {"triggered": False, "reason": None, "enabled": False},
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

    # ── 1. Fetch market quality for all symbols concurrently ──────────────────
    quality_map: dict[str, dict] = {}

    async def _fetch_quality(sym: str) -> None:
        try:
            snapshot = await polygon_client.get_ticker_snapshot(sym)
            prev = await polygon_client.get_previous_close(sym)
            q = evaluate_market_quality(snapshot, prev)
            quality_map[sym] = q
            # Track last known price
            price = q.get("bid") or q.get("last_trade_price")
            if price and price > 0:
                _last_prices[sym] = price
        except PolygonError as exc:
            result["errors"].append({"symbol": sym, "error": str(exc)})
        except Exception as exc:
            result["errors"].append({"symbol": sym, "error": f"{type(exc).__name__}: {exc}"})

    await asyncio.gather(*[_fetch_quality(sym) for sym in symbols])
    result["symbols_evaluated"] = len(quality_map)

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

    # ── 3 & 4. Process exits then entries — single lock, no awaits inside ─────
    async with _lock:
        # Exits first
        for sym in list(_account.positions.keys()):
            pos = _account.positions.get(sym)
            if pos is None:
                continue
            q = quality_map.get(sym)
            exit_price = None
            if q:
                exit_price = q.get("bid") or q.get("last_trade_price")
            if not exit_price or exit_price <= 0:
                exit_price = _last_prices.get(sym, pos.entry_price)

            tp = pos.entry_price * (1 + _cfg("PAPER_TAKE_PROFIT_PERCENT") / 100)
            sl = pos.entry_price * (1 - _cfg("PAPER_STOP_LOSS_PERCENT") / 100)
            entry_dt = datetime.fromisoformat(pos.entry_time)
            hold_min = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 60

            exit_reason: str | None = None
            if exit_price >= tp:
                exit_reason = "take_profit"
            elif exit_price <= sl:
                exit_reason = "stop_loss"
            elif hold_min >= _cfg("PAPER_MAX_HOLD_MINUTES"):
                exit_reason = "max_hold_time"

            if exit_reason:
                trade = _account.exit_position(sym, exit_price, exit_reason)
                if trade:
                    result["exits"].append({
                        "symbol": sym,
                        "exit_reason": exit_reason,
                        "entry_price": round(pos.entry_price, 4),
                        "exit_price": round(exit_price, 4),
                        "pnl": round(trade.pnl, 4),
                        "pnl_percent": round(trade.pnl_percent, 4),
                        "hold_minutes": trade.hold_minutes,
                        "catalyst_type": trade.entry_catalyst_type,
                        "total_score": trade.entry_score,
                        "entry_mode": trade.entry_mode,
                    })

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

            cat_type = cats[0].get("classified_event_type") if cats else None

            # ── Momentum evaluation (always computed when mode enabled) ────────
            momentum_eval: dict | None = None
            if _cfg("PAPER_MOMENTUM_MODE_ENABLED"):
                try:
                    momentum_eval = evaluate_momentum_entry(sym, q, _tick_regime)
                except Exception:
                    momentum_eval = None

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
                # Daily loss guard (Phase 2N)
                "daily_loss_guard_triggered": _guard["triggered"],
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
                                })
                            else:
                                candidate["action"] = "entry_failed"
                        else:
                            candidate["action"] = "no_valid_price"
                    else:
                        candidate["action"] = f"blocked: {block}"

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

    # ── 5. Persist and update state ───────────────────────────────────────────
    result["exits_made"] = len(result["exits"])
    result["entries_made"] = len(result["entries"])
    await _save_state()
    _state["last_tick_at"] = tick_start.isoformat()
    _state["last_error"] = None
    _state["last_candidates"] = result["candidates"]

    # ── 6. Journal write (non-fatal, must not affect simulation) ─────────────
    result["journal"] = {"ok": False, "skipped": True, "reason": "not attempted"}
    try:
        result["journal"] = await _persist_journal_tick(
            result, get_status(), get_cached_universe()
        )
    except Exception as exc:
        result["journal"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # ── 7. Market regime already fetched in step 2b (observational only) ────────
    # result["market_regime"] is already set from step 2b.

    return result


# ── Redis persistence (best-effort) ──────────────────────────────────────────

async def _save_state() -> None:
    async with _lock:
        snapshot = {
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
