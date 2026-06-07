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
from data.market_quality import evaluate_market_quality
from data.polygon_client import PolygonError
from data.redis_client import make_redis
from paper.account import PaperAccount
from paper.journal import persist_tick_result as _persist_journal_tick
from paper.scoring import score_candidate
from paper.universe import get_active_paper_universe, get_cached_universe

logger = logging.getLogger(__name__)

_REDIS_KEY = "paper:state"

# Module-level state — one instance per process
_account: PaperAccount = PaperAccount(settings.PAPER_STARTING_CASH)
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
            "max_positions": settings.PAPER_MAX_POSITIONS,
            "max_trades_per_day": settings.PAPER_MAX_TRADES_PER_DAY,
            "max_position_size_usd": settings.PAPER_MAX_POSITION_SIZE_USD,
            "take_profit_percent": settings.PAPER_TAKE_PROFIT_PERCENT,
            "stop_loss_percent": settings.PAPER_STOP_LOSS_PERCENT,
            "max_hold_minutes": settings.PAPER_MAX_HOLD_MINUTES,
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
        symbols = settings.paper_base_universe_list()[:settings.PAPER_MAX_SYMBOLS_PER_TICK]
        result["universe_refresh_reason"] = "error_fallback"
        result["errors"].append({"phase": "universe", "error": str(exc)})

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

            tp = pos.entry_price * (1 + settings.PAPER_TAKE_PROFIT_PERCENT / 100)
            sl = pos.entry_price * (1 - settings.PAPER_STOP_LOSS_PERCENT / 100)
            entry_dt = datetime.fromisoformat(pos.entry_time)
            hold_min = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 60

            exit_reason: str | None = None
            if exit_price >= tp:
                exit_reason = "take_profit"
            elif exit_price <= sl:
                exit_reason = "stop_loss"
            elif hold_min >= settings.PAPER_MAX_HOLD_MINUTES:
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
                    })

        # Entries
        for sym in symbols:
            q = quality_map.get(sym)
            if not q:
                continue
            cats = catalyst_map.get(sym, [])

            # Score every candidate (transparent, always computed)
            scoring = score_candidate(sym, q, cats)

            # Hard safety gates (checked before score)
            hard_rejection: str | None = None
            if not q.get("tradable"):
                reasons = q.get("rejection_reasons", [])
                hard_rejection = f"not tradable: {reasons[0] if reasons else 'failed quality gate'}"
            elif (q.get("spread_percent") or 999) > 0.50:
                hard_rejection = f"spread {q.get('spread_percent')}% > 0.50%"
            elif (q.get("change_percent") or 0) <= 0:
                hard_rejection = f"change_percent {q.get('change_percent')} not positive"
            elif q.get("volume_ratio") is not None and q.get("volume_ratio", 1.0) < 0.8:
                hard_rejection = f"volume_ratio {q.get('volume_ratio')} < 0.8"
            elif not cats:
                hard_rejection = "no accepted catalysts"
            elif all(c.get("classified_event_type") == "generic_news" for c in cats):
                hard_rejection = "only generic_news catalysts"
            elif (
                settings.PAPER_REJECT_STRONG_BEARISH_CATALYST
                and scoring.get("catalyst_sentiment") == "bearish"
                and (scoring.get("catalyst_materiality_score") or 0.0)
                >= settings.PAPER_BEARISH_CATALYST_REJECT_MATERIALITY
            ):
                hard_rejection = "strong_bearish_catalyst"

            cat_type = cats[0].get("classified_event_type") if cats else None
            candidate: dict[str, Any] = {
                "symbol": sym,
                "eligible": hard_rejection is None and scoring["score_pass"],
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
            }

            if hard_rejection is not None:
                # Hard gate failed — don't attempt entry
                pass
            elif not scoring["score_pass"]:
                candidate["action"] = "score_rejected"
                candidate["rejection_reason"] = scoring["decision_reason"]
            else:
                can, block = _account.can_enter(
                    sym,
                    settings.PAPER_MAX_POSITIONS,
                    settings.PAPER_MAX_TRADES_PER_DAY,
                )
                if can:
                    entry_price = q.get("ask") or q.get("last_trade_price", 0)
                    if entry_price and entry_price > 0:
                        pos = _account.enter_position(
                            sym, entry_price,
                            settings.PAPER_MAX_POSITION_SIZE_USD,
                            cat_type or "unknown",
                            entry_score=scoring["total_score"],
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
                            })
                        else:
                            candidate["action"] = "entry_failed"
                    else:
                        candidate["action"] = "no_valid_price"
                else:
                    candidate["action"] = f"blocked: {block}"

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

    # ── 7. Market regime metadata (observational only — no strategy changes) ──
    result["market_regime"] = None
    try:
        from core.config import settings as _settings
        if _settings.MARKET_REGIME_ENABLED:
            from market.regime import get_market_regime
            regime_data = await get_market_regime()
            result["market_regime"] = {
                "regime": regime_data["risk"]["regime"],
                "risk_on_score": regime_data["risk"]["risk_on_score"],
                "confidence": regime_data["risk"]["confidence"],
                "as_of": regime_data["as_of"],
            }
    except Exception:
        pass

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
            "last_prices": dict(_last_prices),
        }
    try:
        r = make_redis()
        await r.set(_REDIS_KEY, json.dumps(snapshot))
        await r.aclose()
        _state["snapshot_storage"] = "redis_best_effort"
    except Exception:
        _state["snapshot_storage"] = "memory"
