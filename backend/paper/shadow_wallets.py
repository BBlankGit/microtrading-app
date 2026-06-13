"""
Phase G1B Part C — parallel fake wallets.

Two additional `PaperAccount` ledgers run alongside the engine wallet:

  - DETERMINISTIC_SHADOW: enters when a candidate's
    ``enhanced_shadow_decision == "WOULD_ENTER"``.
  - AI_SHADOW: enters when ``llm_decision == "WOULD_ENTER"`` AND the LLM
    is enabled (``LLM_SHADOW_ENABLED``).

Both wallets:
  - Start with ``settings.PAPER_STARTING_CASH``.
  - Use the same sizing (``PAPER_POSITION_SIZE_PERCENT`` capped by
    ``PAPER_MAX_POSITION_SIZE_USD``).
  - Use the same TP/SL/max-hold via :func:`evaluate_virtual_bracket_exit`.
  - Have their own positions and trades — a symbol open in one wallet does
    NOT block another.

The engine wallet (``paper.simulator._account``) is untouched.

No broker. No real orders. Research fake-money only.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.config import settings
from paper.account import PaperAccount
from paper.exits import evaluate_virtual_bracket_exit
from paper.runtime_config import effective_value as _cfg

logger = logging.getLogger(__name__)


# Module-scope ledgers — created lazily on first enabled tick.
_deterministic: PaperAccount | None = None
_ai: PaperAccount | None = None

# G1B-H10 Part C: track true last_decision_at for each shadow wallet,
# updated every time a candidate is evaluated (WOULD_ENTER / WATCH /
# WOULD_REJECT / no_decision) — not only when an entry happens.
_last_decision_at: dict[str, str | None] = {
    "deterministic_shadow": None,
    "ai_shadow": None,
}

# G1B-H11 Part F: durable persisted last_decision_at, sourced from
# paper_candidates.extras_json. Cached with a short TTL so we don't
# hit Postgres on every dashboard refresh.
_persisted_last_decision_at: dict[str, str | None] = {
    "deterministic_shadow": None,
    "ai_shadow": None,
}
_persisted_cache_fetched_at: float = 0.0
_PERSISTED_CACHE_TTL_SECONDS: int = 60


WALLET_DETERMINISTIC = "deterministic_shadow"
WALLET_AI = "ai_shadow"


def enabled() -> bool:
    return bool(getattr(settings, "PAPER_SHADOW_WALLETS_ENABLED", False))


def _ensure_wallets() -> tuple[PaperAccount, PaperAccount]:
    global _deterministic, _ai
    if _deterministic is None:
        _deterministic = PaperAccount(settings.PAPER_STARTING_CASH)
    if _ai is None:
        _ai = PaperAccount(settings.PAPER_STARTING_CASH)
    return _deterministic, _ai


def reset() -> None:
    """Reset both shadow wallets to starting cash, no positions, no trades."""
    det, ai = _ensure_wallets()
    det.reset()
    ai.reset()


def _wallet(name: str) -> PaperAccount:
    det, ai = _ensure_wallets()
    if name == WALLET_DETERMINISTIC:
        return det
    if name == WALLET_AI:
        return ai
    raise KeyError(name)


def _quote_entry_price(q: dict | None) -> float | None:
    if not q:
        return None
    p = q.get("ask") or q.get("last_trade_price")
    try:
        p = float(p) if p is not None else None
    except (TypeError, ValueError):
        return None
    return p if p and p > 0 else None


def _quote_point_price(q: dict | None) -> float | None:
    if not q:
        return None
    p = q.get("bid") or q.get("last_trade_price")
    try:
        p = float(p) if p is not None else None
    except (TypeError, ValueError):
        return None
    return p if p and p > 0 else None


def _position_budget(account: PaperAccount) -> float:
    pos_pct = float(_cfg("PAPER_POSITION_SIZE_PERCENT"))
    return min(
        account.cash * (pos_pct / 100.0),
        float(settings.PAPER_MAX_POSITION_SIZE_USD),
    )


def _llm_enabled() -> bool:
    return bool(getattr(settings, "LLM_SHADOW_ENABLED", False))


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _stamp_decision(wallet_id: str, candidates: list[dict]) -> None:
    """G1B-H10 Part C: record true last_decision_at whenever the shadow
    wallet evaluates ANY candidate decision (WOULD_ENTER, WATCH,
    WOULD_REJECT, no_decision). Independent of last_entry_at."""
    if not candidates:
        return
    if wallet_id == WALLET_DETERMINISTIC:
        # any candidate that carries enhanced_shadow_decision (or was
        # evaluated for shadow scoring) counts as a decision touch
        touched = any(
            c.get("enhanced_shadow_decision") is not None
            or c.get("enhanced_shadow_score") is not None
            for c in candidates
        )
        if touched:
            _last_decision_at[WALLET_DETERMINISTIC] = _now_iso()
    elif wallet_id == WALLET_AI:
        touched = any(
            c.get("llm_decision") is not None
            or c.get("llm_status") is not None
            for c in candidates
        )
        if touched:
            _last_decision_at[WALLET_AI] = _now_iso()


def get_last_decision_at(wallet_id: str) -> str | None:
    """Public accessor for the in-memory last_decision_at tracker."""
    return _last_decision_at.get(wallet_id)


def _reset_last_decision_at() -> None:
    """Test-only helper: clear in-memory + persisted-cache decision state."""
    global _persisted_cache_fetched_at
    _last_decision_at[WALLET_DETERMINISTIC] = None
    _last_decision_at[WALLET_AI] = None
    _persisted_last_decision_at[WALLET_DETERMINISTIC] = None
    _persisted_last_decision_at[WALLET_AI] = None
    _persisted_cache_fetched_at = 0.0


async def refresh_persisted_last_decision_cache(force: bool = False) -> None:
    """
    G1B-H11 Part F: refresh the durable persisted last_decision_at values
    from paper_candidates.extras_json. TTL-cached so dashboard polling
    doesn't hit Postgres every refresh. Never raises — degrades silently
    on DB error.
    """
    global _persisted_cache_fetched_at
    import time as _time
    now = _time.time()
    if not force and now - _persisted_cache_fetched_at < _PERSISTED_CACHE_TTL_SECONDS:
        return
    try:
        from paper import db as _db
        pool = await _db.get_pool()
        if pool is None:
            return
        async with pool.acquire() as conn:
            det_max = await conn.fetchval(
                """
                SELECT MAX(created_at) FROM paper_candidates
                 WHERE extras_json ? 'enhanced_shadow_decision'
                    OR extras_json ? 'enhanced_shadow_score'
                """
            )
            ai_max = await conn.fetchval(
                """
                SELECT MAX(created_at) FROM paper_candidates
                 WHERE extras_json ? 'llm_decision'
                    OR extras_json ? 'llm_status'
                """
            )
        _persisted_last_decision_at[WALLET_DETERMINISTIC] = (
            det_max.isoformat() if det_max else None
        )
        _persisted_last_decision_at[WALLET_AI] = (
            ai_max.isoformat() if ai_max else None
        )
        _persisted_cache_fetched_at = now
    except Exception as exc:
        logger.debug("refresh_persisted_last_decision_cache failed: %s", exc)


def get_last_decision_source(wallet_id: str) -> dict:
    """G1B-H11 Part F: resolved last_decision_at with provenance.

    Priority:
      1. runtime (in-memory _last_decision_at, freshest signal)
      2. persisted_candidate_extras (durable across restarts)
      3. last_entry_fallback (best-effort; entry IS a decision but
         WATCH/WOULD_REJECT/no-entry signals are missed by this path)
      4. none
    """
    runtime_ts = _last_decision_at.get(wallet_id)
    persisted_ts = _persisted_last_decision_at.get(wallet_id)
    if runtime_ts:
        return {
            "last_decision_at": runtime_ts,
            "last_decision_at_runtime": runtime_ts,
            "last_decision_at_persisted": persisted_ts,
            "last_decision_at_source": "runtime",
        }
    if persisted_ts:
        return {
            "last_decision_at": persisted_ts,
            "last_decision_at_runtime": None,
            "last_decision_at_persisted": persisted_ts,
            "last_decision_at_source": "persisted_candidate_extras",
        }
    # Fallback handled by _wallet_snapshot using last_entry_at
    return {
        "last_decision_at": None,
        "last_decision_at_runtime": None,
        "last_decision_at_persisted": None,
        "last_decision_at_source": "none",
    }


def _process_exits_for(
    wallet_id: str,
    quality_map: dict[str, dict],
    intrabar_map: dict[str, dict | None],
) -> list[dict]:
    """Run TP/SL/max-hold exits for one shadow wallet."""
    account = _wallet(wallet_id)
    tp_pct = float(_cfg("PAPER_TAKE_PROFIT_PERCENT"))
    sl_pct = float(_cfg("PAPER_STOP_LOSS_PERCENT"))
    max_hold = float(_cfg("PAPER_MAX_HOLD_MINUTES"))
    now = datetime.now(timezone.utc)
    exits: list[dict] = []
    for sym in list(account.positions.keys()):
        pos = account.positions.get(sym)
        if pos is None:
            continue
        q = quality_map.get(sym)
        bracket = evaluate_virtual_bracket_exit(
            entry_price=pos.entry_price,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            quote=q,
            intrabar=intrabar_map.get(sym),
        )
        try:
            entry_dt = datetime.fromisoformat(pos.entry_time)
            hold_min = (now - entry_dt).total_seconds() / 60.0
        except Exception:
            hold_min = 0.0

        exit_reason: str | None = bracket["exit_reason"] if bracket["should_exit"] else None
        exit_price: float = bracket["exit_price"] if bracket["should_exit"] else 0.0

        if not exit_reason and hold_min >= max_hold:
            exit_reason = "max_hold_time"
            exit_price = _quote_point_price(q) or pos.entry_price

        if not exit_reason:
            continue

        trade = account.exit_position(sym, exit_price, exit_reason)
        if trade is None:
            continue
        exits.append({
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
            "position_id": pos.position_id,
            "shares": round(pos.shares, 6),
            "cost_basis": round(pos.cost_basis, 4),
            "wallet_id": wallet_id,
            "strategy_id": wallet_id,
        })
    return exits


def _process_entries_for(
    wallet_id: str,
    signal_field: str,
    candidates: list[dict],
    quality_map: dict[str, dict],
) -> list[dict]:
    """Enter positions on `wallet_id` for candidates whose signal == WOULD_ENTER."""
    account = _wallet(wallet_id)
    max_pos = int(_cfg("PAPER_MAX_OPEN_POSITIONS"))
    max_trades = int(_cfg("PAPER_MAX_TRADES_PER_DAY"))
    entries: list[dict] = []
    for c in candidates:
        if c.get(signal_field) != "WOULD_ENTER":
            continue
        sym = c.get("symbol")
        if not sym:
            continue
        # Independent gating — don't consult the engine wallet.
        can, _block = account.can_enter(sym, max_pos, max_trades)
        if not can:
            continue
        q = quality_map.get(sym)
        entry_price = _quote_entry_price(q)
        if entry_price is None:
            continue
        budget = _position_budget(account)
        if budget <= 0:
            continue
        pos = account.enter_position(
            sym,
            entry_price,
            budget,
            c.get("catalyst_type") or wallet_id,
            entry_score=c.get("total_score"),
            entry_mode=wallet_id,
        )
        if pos is None:
            continue
        entries.append({
            "symbol": sym,
            "entry_price": round(entry_price, 4),
            "shares": round(pos.shares, 6),
            "cost_basis": round(pos.cost_basis, 4),
            "catalyst_type": c.get("catalyst_type"),
            "total_score": c.get("total_score"),
            "entry_mode": wallet_id,
            "position_id": pos.position_id,
            "wallet_id": wallet_id,
            "strategy_id": wallet_id,
        })
    return entries


def _eod_flatten_for(
    wallet_id: str,
    quality_map: dict[str, dict],
    *,
    exit_reason: str = "eod_flatten",
    only_stale_overnight: bool = False,
    only_out_of_session: bool = False,
) -> tuple[list[dict], list[dict]]:
    """Close positions on `wallet_id` and return (exit_records, warnings).

    With ``only_stale_overnight=True`` we close ONLY positions whose entry
    NY trading-session date is strictly older than the latest session —
    the Phase G1B-H2 Part F "late flatten" path.

    With ``only_out_of_session=True`` we close ONLY positions whose entry
    timestamp falls outside regular session hours — the Phase G1B-H3
    Part C remediation path.

    Without either flag we close everything open (the Phase G1B-H1 Part E
    close-of-day path).
    """
    from paper import eod as _eod_mod
    account = _wallet(wallet_id)
    exits: list[dict] = []
    warnings: list[dict] = []
    for sym in list(account.positions.keys()):
        pos = account.positions.get(sym)
        if pos is None:
            continue
        if only_stale_overnight and not _eod_mod.position_is_stale_overnight(pos.entry_time):
            continue
        if only_out_of_session and not _eod_mod.position_entry_is_out_of_session(pos.entry_time):
            continue
        q = quality_map.get(sym) or {}
        exit_price = q.get("bid") or q.get("last_trade_price")
        if not exit_price:
            warnings.append({
                "wallet_id": wallet_id,
                "symbol": sym,
                "entry_time": pos.entry_time,
                "reason": (
                    "missing_exit_price_invalid_session"
                    if only_out_of_session
                    else "missing_exit_price_late_flatten"
                    if only_stale_overnight
                    else "missing_exit_price"
                ),
            })
            continue
        trade = account.exit_position(sym, float(exit_price), exit_reason)
        if trade is None:
            continue
        exits.append({
            "symbol": sym,
            "exit_reason": exit_reason,
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
            "wallet_id": wallet_id,
            "strategy_id": wallet_id,
        })
    return exits, warnings


def process_tick(
    candidates: list[dict],
    quality_map: dict[str, dict],
    intrabar_map: dict[str, dict | None] | None = None,
) -> dict:
    """
    Run one tick across both shadow wallets.

    Order matches the engine: exits first, then entries; an end-of-day
    flatten sweep runs last so any position still open at close exits at
    the cached point-in-time price. Returns a dict with `entries`,
    `exits`, `warnings`, and `snapshots`. Never raises — falls back to
    an empty result on any error.
    """
    if not enabled():
        return {"entries": [], "exits": [], "warnings": [], "snapshots": {},
                "skipped": "disabled"}

    # G1B-H10 Part C: record true last_decision_at independently of entries.
    # This stamps a decision touch whenever the shadow strategy evaluated any
    # candidate, even when no entry happened.
    _stamp_decision(WALLET_DETERMINISTIC, candidates)
    if _llm_enabled():
        _stamp_decision(WALLET_AI, candidates)

    intrabar_map = intrabar_map or {}
    try:
        from paper import eod as _eod
        exits: list[dict] = []
        warnings: list[dict] = []

        # Phase G1B-H2 Part F: every tick, close any position carried over
        # from a prior NY session. Runs before regular intrabar exits so
        # stale positions don't soak up exit slots.
        late_det, late_det_warn = _eod_flatten_for(
            WALLET_DETERMINISTIC, quality_map,
            exit_reason=_eod.LATE_FLATTEN_REASON, only_stale_overnight=True,
        )
        exits.extend(late_det)
        warnings.extend(late_det_warn)
        late_ai, late_ai_warn = _eod_flatten_for(
            WALLET_AI, quality_map,
            exit_reason=_eod.LATE_FLATTEN_REASON, only_stale_overnight=True,
        )
        exits.extend(late_ai)
        warnings.extend(late_ai_warn)

        # Phase G1B-H3 Part C: close positions entered outside regular session.
        oos_det, oos_det_warn = _eod_flatten_for(
            WALLET_DETERMINISTIC, quality_map,
            exit_reason=_eod.OUT_OF_SESSION_REASON, only_out_of_session=True,
        )
        exits.extend(oos_det)
        warnings.extend(oos_det_warn)
        oos_ai, oos_ai_warn = _eod_flatten_for(
            WALLET_AI, quality_map,
            exit_reason=_eod.OUT_OF_SESSION_REASON, only_out_of_session=True,
        )
        exits.extend(oos_ai)
        warnings.extend(oos_ai_warn)

        exits.extend(_process_exits_for(WALLET_DETERMINISTIC, quality_map, intrabar_map))
        if _llm_enabled():
            exits.extend(_process_exits_for(WALLET_AI, quality_map, intrabar_map))

        # Block entries inside the EOD cutoff window for the shadow wallets too.
        entries: list[dict] = []
        _entries_blocked, _ = _eod.entries_blocked()
        if not _entries_blocked:
            entries.extend(
                _process_entries_for(
                    WALLET_DETERMINISTIC,
                    "enhanced_shadow_decision",
                    candidates,
                    quality_map,
                )
            )
            if _llm_enabled():
                entries.extend(
                    _process_entries_for(
                        WALLET_AI, "llm_decision", candidates, quality_map
                    )
                )

        if _eod.flatten_due():
            flat_exits, flat_warn = _eod_flatten_for(WALLET_DETERMINISTIC, quality_map)
            exits.extend(flat_exits)
            warnings.extend(flat_warn)
            if _llm_enabled():
                ai_exits, ai_warn = _eod_flatten_for(WALLET_AI, quality_map)
                exits.extend(ai_exits)
                warnings.extend(ai_warn)

        return {
            "entries": entries,
            "exits": exits,
            "warnings": warnings,
            "snapshots": snapshot(),
        }
    except Exception as exc:
        logger.warning("shadow_wallets.process_tick failed defensively: %s", exc)
        return {"entries": [], "exits": [], "warnings": [], "snapshots": {},
                "error": str(exc)}


def _last_prices_for(account: PaperAccount, quality_map: dict[str, dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for sym, pos in account.positions.items():
        q = quality_map.get(sym) or {}
        p = q.get("last_trade_price") or q.get("bid") or pos.entry_price
        try:
            out[sym] = float(p)
        except (TypeError, ValueError):
            out[sym] = pos.entry_price
    return out


def _win_rate(account: PaperAccount) -> float | None:
    if not account.trades:
        return None
    wins = sum(1 for t in account.trades if t.pnl > 0)
    return round(wins / len(account.trades) * 100.0, 2)


def _last_update_time(account: PaperAccount) -> str | None:
    """Most recent activity timestamp on this wallet (entry or exit)."""
    times: list[str] = []
    for p in account.positions.values():
        if p.entry_time:
            times.append(p.entry_time)
    for t in account.trades:
        if t.exit_time:
            times.append(t.exit_time)
        elif t.entry_time:
            times.append(t.entry_time)
    return max(times) if times else None


def _deterministic_shadow_enabled() -> bool:
    """G1B-H9: deterministic shadow has its own switch (default True),
    plus the master `PAPER_SHADOW_WALLETS_ENABLED` switch."""
    return enabled() and bool(
        getattr(settings, "PAPER_DETERMINISTIC_SHADOW_ENABLED", True)
    )


def _wallet_status(wallet_id: str) -> tuple[str, str | None]:
    """Return (status, inactive_reason). G1B-H9: deterministic shadow no
    longer depends on LLM availability; only on its own switch and the
    master switch."""
    if not enabled():
        return ("inactive", "PAPER_SHADOW_WALLETS_ENABLED=false")
    if wallet_id == WALLET_DETERMINISTIC and not _deterministic_shadow_enabled():
        return ("inactive", "PAPER_DETERMINISTIC_SHADOW_ENABLED=false")
    if wallet_id == WALLET_AI and not _llm_enabled():
        return ("inactive", "LLM_SHADOW_ENABLED=false")
    return ("active", None)


def _wallet_processing_info(wallet_id: str) -> dict:
    """G1B-H9 Part A: per-wallet enabled / processing_enabled / config-flag fields."""
    if wallet_id == WALLET_DETERMINISTIC:
        master = enabled()
        own = bool(getattr(settings, "PAPER_DETERMINISTIC_SHADOW_ENABLED", True))
        return {
            "enabled": master and own,
            "processing_enabled": master and own,
            "enabled_by_config": [
                {"flag": "PAPER_SHADOW_WALLETS_ENABLED", "value": master},
                {"flag": "PAPER_DETERMINISTIC_SHADOW_ENABLED", "value": own},
            ],
            "depends_on_llm": False,
        }
    if wallet_id == WALLET_AI:
        master = enabled()
        llm = _llm_enabled()
        return {
            "enabled": master and llm,
            "processing_enabled": master and llm,
            "enabled_by_config": [
                {"flag": "PAPER_SHADOW_WALLETS_ENABLED", "value": master},
                {"flag": "LLM_SHADOW_ENABLED", "value": llm},
            ],
            "depends_on_llm": True,
            "no_paid_ai_calls": True,
        }
    return {
        "enabled": True,
        "processing_enabled": True,
        "enabled_by_config": [],
        "depends_on_llm": False,
    }


def get_positions(wallet_id: str, quality_map: dict[str, dict] | None = None) -> list[dict]:
    """Open positions on `wallet_id`, formatted for the dashboard API."""
    if wallet_id not in (WALLET_DETERMINISTIC, WALLET_AI):
        return []
    account = _wallet(wallet_id)
    qmap = quality_map or {}
    out: list[dict] = []
    for sym, pos in account.positions.items():
        q = qmap.get(sym) or {}
        current = (
            q.get("last_trade_price") or q.get("bid") or pos.entry_price
        )
        try:
            current = float(current)
        except (TypeError, ValueError):
            current = pos.entry_price
        d = pos.to_dict()
        d["current_price"] = current
        d["unrealized_pnl"] = round(pos.unrealized_pnl(current), 4)
        d["unrealized_pnl_percent"] = round(
            (pos.unrealized_pnl(current) / pos.cost_basis * 100) if pos.cost_basis else 0,
            4,
        )
        d["wallet_id"] = wallet_id
        d["strategy_id"] = wallet_id
        out.append(d)
    return out


def get_trades(wallet_id: str) -> list[dict]:
    """Closed trades on `wallet_id`."""
    if wallet_id not in (WALLET_DETERMINISTIC, WALLET_AI):
        return []
    account = _wallet(wallet_id)
    out: list[dict] = []
    for t in account.trades:
        d = t.to_dict()
        d["wallet_id"] = wallet_id
        d["strategy_id"] = wallet_id
        out.append(d)
    return out


def _wallet_snapshot(wallet_id: str, quality_map: dict[str, dict]) -> dict:
    account = _wallet(wallet_id)
    base = account.to_status(_last_prices_for(account, quality_map))
    status, inactive_reason = _wallet_status(wallet_id)
    proc = _wallet_processing_info(wallet_id)
    daily_baseline = account.daily_start_equity or account.starting_cash
    daily_pnl = round(base["equity"] - daily_baseline, 4) if daily_baseline else 0.0
    # G1B-H9 Part A: per-wallet last_entry_at / last_decision_at (best-effort
    # from in-memory ledger; deeper history lives in DB).
    last_entry_at = None
    if account.positions:
        last_entry_at = max(
            (p.entry_time for p in account.positions.values() if p.entry_time),
            default=None,
        )
    last_exit_at = None
    if account.trades:
        last_exit_at = max(
            (t.exit_time for t in account.trades if t.exit_time),
            default=None,
        )
    base.update({
        "wallet_id": wallet_id,
        "strategy_id": wallet_id,
        "status": status,
        "inactive_reason": inactive_reason,
        "daily_pnl": daily_pnl,
        "win_rate": _win_rate(account),
        "last_update_time": _last_update_time(account),
        # G1B-H9 Part A new fields
        "enabled": proc["enabled"],
        "processing_enabled": proc["processing_enabled"],
        "enabled_by_config": proc["enabled_by_config"],
        "depends_on_llm": proc["depends_on_llm"],
        "last_entry_at": last_entry_at,
        "last_exit_at": last_exit_at,
    })
    # G1B-H11 Part F: resolved last_decision_at with provenance.
    # Priority: runtime > persisted_candidate_extras > last_entry_fallback > none.
    src = get_last_decision_source(wallet_id)
    if src["last_decision_at"] is None and last_entry_at:
        # Fallback: entries are decisions but this is the lossy path.
        src = {
            "last_decision_at": last_entry_at,
            "last_decision_at_runtime": None,
            "last_decision_at_persisted": None,
            "last_decision_at_source": "last_entry_fallback",
        }
    base.update(src)
    if wallet_id == WALLET_AI:
        base["no_paid_ai_calls"] = True
    return base


def snapshot(quality_map: dict[str, dict] | None = None) -> dict:
    """Return a status dict for both shadow wallets (engine wallet not included)."""
    _ensure_wallets()
    qmap = quality_map or {}
    return {
        WALLET_DETERMINISTIC: _wallet_snapshot(WALLET_DETERMINISTIC, qmap),
        WALLET_AI: _wallet_snapshot(WALLET_AI, qmap),
        "enabled": enabled(),
        "llm_enabled": _llm_enabled(),
    }
