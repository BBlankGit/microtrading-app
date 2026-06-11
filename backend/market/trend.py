"""
Market regime trend momentum — ETF-proxy rolling history layer.

Wraps the existing point-in-time market regime score with a small in-memory
rolling history so we can detect whether ETF proxy momentum is *improving*
or *deteriorating* over the last 5–15 minutes.

Fake-money simulation only. No broker, no live trading, no real orders,
no AI/LLM. True Nasdaq/SPX futures are NOT supported here — we read only
the same ETFs the regime module already fetches (QQQ, SPY, IWM, …).

Public API:
    record_snapshot(regime_data)  — append the latest regime dict if past interval
    get_trend()                   — compute deltas + classification + adjustment
    clear()                       — drop history (tests)
"""
from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from core.config import settings

logger = logging.getLogger(__name__)

# Each entry: dict with timestamp_monotonic, as_of, risk_on_score, regime,
# confidence, breadth_positive_percent, leader_count, primary_change (dict
# symbol -> change_percent), proxy_change (dict).
_history: deque[dict] = deque()
_last_snapshot_time: float | None = None


def clear() -> None:
    """Reset state. For tests."""
    global _last_snapshot_time
    _history.clear()
    _last_snapshot_time = None


def _primary_symbols() -> list[str]:
    return [s.strip().upper() for s in (settings.MARKET_TREND_PRIMARY_SYMBOLS or "").split(",") if s.strip()]


def _context_symbols() -> list[str]:
    return [s.strip().upper() for s in (settings.MARKET_TREND_CONTEXT_SYMBOLS or "").split(",") if s.strip()]


def _optional_proxy_symbols() -> list[str]:
    return [s.strip().upper() for s in (settings.MARKET_TREND_OPTIONAL_PROXY_SYMBOLS or "").split(",") if s.strip()]


def _windows_minutes() -> list[int]:
    out: list[int] = []
    for tok in (settings.MARKET_TREND_WINDOWS_MINUTES or "").split(","):
        tok = tok.strip()
        if tok.isdigit():
            v = int(tok)
            if v > 0:
                out.append(v)
    return out or [5, 10, 15]


def _prune() -> None:
    """Drop snapshots older than MARKET_TREND_HISTORY_MINUTES."""
    horizon = settings.MARKET_TREND_HISTORY_MINUTES * 60
    now = time.monotonic()
    while _history and (now - _history[0]["timestamp_monotonic"]) > horizon:
        _history.popleft()


def record_snapshot(regime_data: dict) -> bool:
    """
    Append a regime snapshot to history. Returns True iff a new snapshot
    was actually recorded (False if we're still inside the interval).
    """
    global _last_snapshot_time
    if not settings.MARKET_TREND_ENABLED:
        return False
    interval = max(1, int(settings.MARKET_TREND_SNAPSHOT_INTERVAL_SECONDS))
    now_mono = time.monotonic()
    if _last_snapshot_time is not None and (now_mono - _last_snapshot_time) < interval:
        return False

    risk = (regime_data or {}).get("risk") or {}
    breadth = (regime_data or {}).get("breadth") or {}
    leaders = (regime_data or {}).get("leaders") or {}

    primary_change: dict[str, float | None] = {}
    primary_price: dict[str, float | None] = {}
    leaders_data = leaders.get("data") or {}
    for sym in _primary_symbols():
        entry = leaders_data.get(sym)
        if entry:
            primary_change[sym] = entry.get("change_percent")
            primary_price[sym] = entry.get("last_trade_price")
        else:
            primary_change[sym] = None
            primary_price[sym] = None

    snapshot = {
        "timestamp_monotonic": now_mono,
        "as_of": regime_data.get("as_of") or datetime.now(timezone.utc).isoformat(),
        "risk_on_score": risk.get("risk_on_score"),
        "regime": risk.get("regime"),
        "confidence": risk.get("confidence"),
        "breadth_positive_percent": breadth.get("positive_percent"),
        "leader_count": (leaders.get("bullish_count") or 0) - (leaders.get("bearish_count") or 0),
        "primary_change": primary_change,
        "primary_price": primary_price,
    }
    _history.append(snapshot)
    _last_snapshot_time = now_mono
    _prune()
    return True


def _snapshot_at_or_before(target_age_seconds: float) -> dict | None:
    """Return the most recent snapshot whose age is >= target_age_seconds."""
    if not _history:
        return None
    now = time.monotonic()
    # Walk newest → oldest; pick the first snapshot at least target seconds old.
    for snap in reversed(_history):
        age = now - snap["timestamp_monotonic"]
        if age >= target_age_seconds:
            return snap
    return None


def _classify(
    risk_delta_5: float | None,
    risk_delta_10: float | None,
    qqq_delta_5: float | None,
    qqq_delta_10: float | None,
    snapshot_count: int,
) -> tuple[str, str, int, str]:
    """
    Return (direction, strength, adjustment_points, reason).

    Thresholds per spec:
      strong improving:      risk_delta_10 >= +10 OR qqq_delta_10 >= +0.40%
      moderate improving:    risk_delta_10 >= +5  OR qqq_delta_10 >= +0.25%
      weak improving:        risk_delta_5  > 0     OR qqq_delta_5  > +0.10%
      strong deteriorating:  risk_delta_10 <= -10 OR qqq_delta_10 <= -0.40%
      moderate deteriorating: risk_delta_10 <= -5 OR qqq_delta_10 <= -0.25%
      weak deteriorating:    risk_delta_5  < 0    OR qqq_delta_5  < -0.10%
      else: flat
      insufficient history: unknown
    """
    if snapshot_count < int(settings.MARKET_TREND_MIN_SNAPSHOTS):
        return "unknown", "unknown", 0, f"collecting trend history ({snapshot_count} snapshots)"

    r10 = risk_delta_10 if risk_delta_10 is not None else 0.0
    q10 = qqq_delta_10 if qqq_delta_10 is not None else 0.0
    r5 = risk_delta_5 if risk_delta_5 is not None else 0.0
    q5 = qqq_delta_5 if qqq_delta_5 is not None else 0.0

    if r10 >= 10 or q10 >= 0.40:
        return "improving", "strong", 8, f"risk_delta_10m={r10:+.1f}, qqq_delta_10m={q10:+.2f}% (strong improving)"
    if r10 <= -10 or q10 <= -0.40:
        return "deteriorating", "strong", -10, f"risk_delta_10m={r10:+.1f}, qqq_delta_10m={q10:+.2f}% (strong deteriorating)"
    if r10 >= 5 or q10 >= 0.25:
        return "improving", "moderate", 4, f"risk_delta_10m={r10:+.1f}, qqq_delta_10m={q10:+.2f}% (moderate improving)"
    if r10 <= -5 or q10 <= -0.25:
        return "deteriorating", "moderate", -6, f"risk_delta_10m={r10:+.1f}, qqq_delta_10m={q10:+.2f}% (moderate deteriorating)"
    if r5 > 0 or q5 > 0.10:
        return "improving", "weak", 2, f"risk_delta_5m={r5:+.1f}, qqq_delta_5m={q5:+.2f}% (weak improving)"
    if r5 < 0 or q5 < -0.10:
        return "deteriorating", "weak", -3, f"risk_delta_5m={r5:+.1f}, qqq_delta_5m={q5:+.2f}% (weak deteriorating)"
    return "flat", "weak", 0, f"risk_delta_5m={r5:+.1f}, qqq_delta_5m={q5:+.2f}% (flat)"


def get_trend() -> dict:
    """
    Compute deltas + classification using the current history buffer.
    Never raises. Always returns a dict with consistent keys.
    """
    _prune()
    enabled = bool(settings.MARKET_TREND_ENABLED)
    primary = _primary_symbols()
    context = _context_symbols()
    proxies = _optional_proxy_symbols()

    deltas: dict[str, Any] = {}
    qqq_delta_5 = qqq_delta_10 = qqq_delta_15 = None
    risk_delta_5 = risk_delta_10 = risk_delta_15 = None
    latest: dict | None = _history[-1] if _history else None

    if latest is not None:
        risk_now = latest.get("risk_on_score")
        qqq_now = (latest.get("primary_change") or {}).get("QQQ")
        spy_now = (latest.get("primary_change") or {}).get("SPY")
        iwm_now = (latest.get("primary_change") or {}).get("IWM")

        def _delta(now_val, ago_snap, key: str | None = None, sym: str | None = None):
            if now_val is None or ago_snap is None:
                return None
            if key == "primary" and sym is not None:
                old = (ago_snap.get("primary_change") or {}).get(sym)
            else:
                old = ago_snap.get("risk_on_score")
            if old is None:
                return None
            try:
                return round(float(now_val) - float(old), 3)
            except (TypeError, ValueError):
                return None

        windows = _windows_minutes()
        for w in windows:
            sec = w * 60
            old = _snapshot_at_or_before(sec)
            deltas[f"{w}m"] = {
                "ago_snapshot_as_of": (old or {}).get("as_of"),
                "risk_on_score_ago": (old or {}).get("risk_on_score") if old else None,
                "risk_on_score_delta": _delta(risk_now, old),
                "qqq_change_ago": ((old or {}).get("primary_change") or {}).get("QQQ") if old else None,
                "qqq_delta": _delta(qqq_now, old, "primary", "QQQ"),
                "spy_change_ago": ((old or {}).get("primary_change") or {}).get("SPY") if old else None,
                "spy_delta": _delta(spy_now, old, "primary", "SPY"),
                "iwm_change_ago": ((old or {}).get("primary_change") or {}).get("IWM") if old else None,
                "iwm_delta": _delta(iwm_now, old, "primary", "IWM"),
            }
        risk_delta_5 = deltas.get("5m", {}).get("risk_on_score_delta")
        risk_delta_10 = deltas.get("10m", {}).get("risk_on_score_delta")
        risk_delta_15 = deltas.get("15m", {}).get("risk_on_score_delta")
        qqq_delta_5 = deltas.get("5m", {}).get("qqq_delta")
        qqq_delta_10 = deltas.get("10m", {}).get("qqq_delta")
        qqq_delta_15 = deltas.get("15m", {}).get("qqq_delta")

    direction, strength, adjustment, reason = _classify(
        risk_delta_5, risk_delta_10, qqq_delta_5, qqq_delta_10, len(_history),
    )

    raw_score = latest.get("risk_on_score") if latest else None
    if raw_score is None:
        adjusted_score = None
    else:
        adjusted_score = max(0, min(100, int(raw_score) + int(adjustment)))

    warnings: list[str] = [
        "True Nasdaq futures are not configured/available; using ETF proxies QQQ/SPY/IWM."
    ]
    if len(_history) < int(settings.MARKET_TREND_MIN_SNAPSHOTS):
        warnings.append(
            f"Collecting trend history — needs at least {settings.MARKET_TREND_MIN_SNAPSHOTS} snapshots."
        )

    return {
        "ok": True,
        "enabled": enabled,
        "source": settings.MARKET_TREND_SOURCE,
        "futures_available": False,
        "provider_status": "using_etf_proxy",
        "primary_symbols": primary,
        "context_symbols": context,
        "optional_proxy_symbols": proxies,
        "include_leveraged_proxies_in_score": bool(settings.MARKET_TREND_INCLUDE_LEVERAGED_PROXIES_IN_SCORE),
        "snapshot_count": len(_history),
        "snapshot_interval_seconds": int(settings.MARKET_TREND_SNAPSHOT_INTERVAL_SECONDS),
        "history_minutes": int(settings.MARKET_TREND_HISTORY_MINUTES),
        "windows_minutes": _windows_minutes(),
        "latest_snapshot": latest,
        "deltas": deltas,
        "market_regime_score_before_trend": raw_score,
        "market_regime_score_after_trend": adjusted_score,
        "trend_direction": direction,
        "trend_strength": strength,
        "market_trend_adjustment": adjustment,
        "market_trend_reason": reason,
        "warnings": warnings,
        "as_of": (latest or {}).get("as_of") if latest else None,
    }


def build_trend_overlay() -> dict:
    """
    Compact dict for embedding into the simulator's _tick_regime and into
    individual candidate rows. Mirrors the field names listed in Phase M1
    Part D so the dashboard can render them without extra plumbing.
    """
    t = get_trend()
    return {
        "market_trend_enabled": t.get("enabled"),
        "market_trend_source": t.get("source"),
        "market_trend_primary_symbols": t.get("primary_symbols"),
        "market_trend_direction": t.get("trend_direction"),
        "market_trend_strength": t.get("trend_strength"),
        "market_trend_adjustment": t.get("market_trend_adjustment"),
        "market_trend_reason": t.get("market_trend_reason"),
        "market_regime_score_before_trend": t.get("market_regime_score_before_trend"),
        "market_regime_score_after_trend": t.get("market_regime_score_after_trend"),
        "market_trend_snapshot_count": t.get("snapshot_count"),
    }
