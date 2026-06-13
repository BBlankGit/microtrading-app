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


def process_tick(
    candidates: list[dict],
    quality_map: dict[str, dict],
    intrabar_map: dict[str, dict | None] | None = None,
) -> dict:
    """
    Run one tick across both shadow wallets.

    Order matches the engine: exits first, then entries.
    Returns a dict with `entries` and `exits` lists (each tagged with
    wallet_id/strategy_id) plus a `snapshots` dict for status reporting.
    Never raises — falls back to empty result on any error.
    """
    if not enabled():
        return {"entries": [], "exits": [], "snapshots": {}, "skipped": "disabled"}

    intrabar_map = intrabar_map or {}
    try:
        exits: list[dict] = []
        exits.extend(_process_exits_for(WALLET_DETERMINISTIC, quality_map, intrabar_map))
        if _llm_enabled():
            exits.extend(_process_exits_for(WALLET_AI, quality_map, intrabar_map))

        entries: list[dict] = []
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

        return {
            "entries": entries,
            "exits": exits,
            "snapshots": snapshot(),
        }
    except Exception as exc:
        logger.warning("shadow_wallets.process_tick failed defensively: %s", exc)
        return {"entries": [], "exits": [], "snapshots": {}, "error": str(exc)}


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


def snapshot(quality_map: dict[str, dict] | None = None) -> dict:
    """Return a status dict for both shadow wallets (engine wallet not included)."""
    det, ai = _ensure_wallets()
    qmap = quality_map or {}
    return {
        WALLET_DETERMINISTIC: det.to_status(_last_prices_for(det, qmap)),
        WALLET_AI: ai.to_status(_last_prices_for(ai, qmap)),
        "enabled": enabled(),
        "llm_enabled": _llm_enabled(),
    }
