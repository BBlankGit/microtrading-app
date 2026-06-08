"""
Market session readiness endpoint.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM. Readiness checks are operational guidance for fake-money
simulation monitoring only.
"""

import logging
import math
import re
import time
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api/readiness", tags=["readiness"])
logger = logging.getLogger(__name__)

DISCLAIMER = (
    "Readiness is operational guidance for fake-money simulation monitoring only. "
    "It does not enable broker trading or real orders."
)

# ── Polygon data check cache (60-second TTL) ──────────────────────────────────
_polygon_cache: dict[str, Any] | None = None
_polygon_cache_time: float | None = None
_POLYGON_CACHE_TTL = 60.0


# ── Sensitive error redaction ─────────────────────────────────────────────────

# Matches a quoted or bare value: "value", 'value', or non-whitespace
_QOB = r'(?:"[^"]*"|\'[^\']*\'|\S+)'

_REDACT_PATTERNS: list[tuple[re.Pattern, str]] = [
    # ── Equal-sign forms ──────────────────────────────────────────────────────
    (re.compile(r'(?i)(api[_-]?key)\s*=\s*\S+'),                      r'\1=[REDACTED]'),
    (re.compile(r'(?i)(access[_-]?token)\s*=\s*\S+'),                 r'\1=[REDACTED]'),
    (re.compile(r'(?i)(refresh[_-]?token)\s*=\s*\S+'),                r'\1=[REDACTED]'),
    (re.compile(r'(?i)(client[_-]?secret)\s*=\s*\S+'),                r'\1=[REDACTED]'),
    (re.compile(r'(?i)\b(token)\s*=\s*\S+'),                          r'\1=[REDACTED]'),
    (re.compile(r'(?i)\b(password)\s*=\s*\S+'),                       r'\1=[REDACTED]'),
    (re.compile(r'(?i)\b(secret)\s*=\s*\S+'),                         r'\1=[REDACTED]'),
    # URL query param: ?key=VALUE or &key=VALUE
    (re.compile(r'([?&]key)\s*=\s*\S+'),                               r'\1=[REDACTED]'),
    # ── HTTP header forms ─────────────────────────────────────────────────────
    (re.compile(r'(?i)(Authorization:\s*Bearer\s+)\S+'),               r'\1[REDACTED]'),
    (re.compile(r'(?i)\b(Bearer)\s+\S+'),                              r'\1 [REDACTED]'),
    # ── Colon/JSON forms: "key": "value", key: value, 'key': 'value' ─────────
    (re.compile(rf'(?i)(?:["\']?)(api[_-]?key)(?:["\']?)\s*:\s*{_QOB}'),       r'\1: [REDACTED]'),
    (re.compile(rf'(?i)(?:["\']?)(access[_-]?token)(?:["\']?)\s*:\s*{_QOB}'),  r'\1: [REDACTED]'),
    (re.compile(rf'(?i)(?:["\']?)(refresh[_-]?token)(?:["\']?)\s*:\s*{_QOB}'), r'\1: [REDACTED]'),
    (re.compile(rf'(?i)(?:["\']?)(client[_-]?secret)(?:["\']?)\s*:\s*{_QOB}'), r'\1: [REDACTED]'),
    (re.compile(rf'(?i)(?:["\']?)\b(token)\b(?:["\']?)\s*:\s*{_QOB}'),         r'\1: [REDACTED]'),
    (re.compile(rf'(?i)(?:["\']?)\b(password)\b(?:["\']?)\s*:\s*{_QOB}'),      r'\1: [REDACTED]'),
    (re.compile(rf'(?i)(?:["\']?)\b(secret)\b(?:["\']?)\s*:\s*{_QOB}'),        r'\1: [REDACTED]'),
]


def redact_sensitive_error(value: Any) -> str:
    """Redact secrets from exception strings before including in API responses."""
    s = str(value)
    try:
        from core.config import settings
        key = getattr(settings, "POLYGON_API_KEY", None)
        if key and len(key) > 4:
            s = s.replace(key, "[REDACTED]")
    except Exception:
        pass
    for pat, repl in _REDACT_PATTERNS:
        s = pat.sub(repl, s)
    return s[:200]


def make_json_safe(value: Any) -> Any:
    """Recursively sanitize a value for JSON serialization. Never raises."""
    try:
        if value is None:
            return value
        if isinstance(value, bool):  # bool before int — bool is a subclass of int
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, str):
            if any(pat.search(value) for pat, _ in _REDACT_PATTERNS):
                return redact_sensitive_error(value)
            return value
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(k): make_json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set, frozenset)):
            return [make_json_safe(item) for item in value]
        return redact_sensitive_error(value)
    except Exception:
        return "[make_json_safe error]"


# ── Check result constructors ─────────────────────────────────────────────────

def _pass(name: str, message: str, details: dict | None = None) -> dict:
    return {"name": name, "status": "pass", "message": message, "details": details or {}}


def _warn(name: str, message: str, details: dict | None = None) -> dict:
    return {"name": name, "status": "warn", "message": message, "details": details or {}}


def _fail(name: str, message: str, details: dict | None = None) -> dict:
    return {"name": name, "status": "fail", "message": message, "details": details or {}}


# ── Shared market-session helper ──────────────────────────────────────────────

def _market_session_now() -> dict:
    from datetime import time as dtime
    try:
        from zoneinfo import ZoneInfo
        ny_tz = ZoneInfo("America/New_York")
        now_ny = datetime.now(ny_tz)
        tz_label = "America/New_York"
    except Exception:
        from datetime import timedelta
        now_ny = datetime.now(timezone(timedelta(hours=-4)))
        tz_label = "UTC-4 (approximate)"

    is_weekday = now_ny.weekday() < 5
    t = now_ny.time()
    is_session = is_weekday and dtime(9, 30) <= t < dtime(16, 0)
    return {
        "timezone": tz_label,
        "is_regular_session_now": is_session,
        "regular_open": "09:30",
        "regular_close": "16:00",
        "note": "Best-effort weekday/session check; holidays not included yet.",
    }


# ── Individual checks ─────────────────────────────────────────────────────────

def _check_backend() -> dict:
    return _pass("backend", "Backend API reachable.")


def _check_simulator(market_open: bool) -> dict:
    try:
        import paper.simulator as _sim
        state = _sim.get_state()
        running = bool(state.get("running", False))
        last_tick = state.get("last_tick_at")
        if running:
            if not market_open:
                return _warn("simulator",
                             "Simulator running outside regular market session.",
                             {"running": True, "market_open": False, "last_tick_at": last_tick})
            return _pass("simulator",
                         "Simulator running during market session.",
                         {"running": True, "market_open": True, "last_tick_at": last_tick})
        if market_open:
            return _fail("simulator",
                         "Market is open but paper simulator is stopped.",
                         {"running": False, "market_open": True})
        return _warn("simulator",
                     "Simulator stopped (market closed).",
                     {"running": False, "market_open": False})
    except Exception as exc:
        return _warn("simulator", f"Could not check simulator state: {type(exc).__name__}: {exc}")


def _check_polygon_key() -> dict:
    try:
        from core.config import settings
        if settings.POLYGON_API_KEY and len(settings.POLYGON_API_KEY) > 4:
            return _pass("polygon_key", "POLYGON_API_KEY is configured.", {"configured": True})
        return _fail("polygon_key", "POLYGON_API_KEY is missing or empty.", {"configured": False})
    except Exception as exc:
        return _fail("polygon_key", f"Could not check Polygon key: {type(exc).__name__}: {exc}")


async def _check_polygon_data() -> dict:
    global _polygon_cache, _polygon_cache_time
    now = time.monotonic()
    if _polygon_cache is not None and _polygon_cache_time is not None:
        if now - _polygon_cache_time < _POLYGON_CACHE_TTL:
            return dict(_polygon_cache)

    try:
        from data import polygon_client
        snapshot = await polygon_client.get_ticker_snapshot("SPY")
        last_price = snapshot.get("last_trade_price")
        change_pct = snapshot.get("change_percent")
        if last_price and last_price > 0:
            result = _pass("polygon_data",
                           "Polygon REST reachable — SPY data returned.",
                           {"symbol": "SPY", "last_price": last_price,
                            "change_percent": change_pct})
        else:
            result = _warn("polygon_data",
                           "Polygon returned data but price fields empty (market may be closed).",
                           {"symbol": "SPY", "snapshot_keys": sorted(snapshot.keys())})
    except Exception as exc:
        safe_err = redact_sensitive_error(exc)
        err_lower = str(exc).lower()
        if any(k in err_lower for k in ("403", "401", "auth", "not configured", "api key")):
            result = _fail("polygon_data",
                           f"Polygon auth/config error: {safe_err}",
                           {"error": safe_err})
        else:
            result = _warn("polygon_data",
                           f"Polygon data check failed: {safe_err}",
                           {"error": safe_err})

    _polygon_cache = result
    _polygon_cache_time = now
    return dict(result)


def _check_journal(market_open: bool) -> dict:
    try:
        from paper.journal import get_journal_status
        j = get_journal_status()
        enabled = j.get("enabled", False)
        db_ok = j.get("database_connected", False)
        tables_ok = j.get("tables_ready", False)
        details = {"enabled": enabled, "database_connected": db_ok, "tables_ready": tables_ok}
        if enabled and db_ok and tables_ok:
            return _pass("journal", "Journal enabled, database connected, tables ready.", details)
        if not enabled:
            return _warn("journal", "Journal disabled — tick data not persisted.", details)
        if market_open:
            return _fail("journal", "Journal database unavailable during market session.", details)
        return _warn("journal", "Journal database unavailable.", details)
    except Exception as exc:
        return _warn("journal", f"Could not check journal: {type(exc).__name__}: {exc}")


def _check_runtime_config() -> dict:
    try:
        from paper.runtime_config import get_runtime_status
        rc = get_runtime_status()
        count = rc.get("override_count", 0)
        if rc.get("overrides_active"):
            return _warn("runtime_config",
                         f"{count} runtime override(s) active.",
                         {"overrides_active": True, "override_count": count})
        return _pass("runtime_config",
                     "Runtime config loaded. No overrides active.",
                     {"overrides_active": False, "override_count": 0})
    except Exception as exc:
        return _fail("runtime_config",
                     f"Runtime config unavailable: {type(exc).__name__}: {exc}")


def _check_universe() -> dict:
    try:
        from paper.universe import get_cached_universe
        uni = get_cached_universe()
        if uni is None:
            return _warn("universe",
                         "No universe cached yet — run a tick or universe refresh.",
                         {"active_count": 0, "errors_count": 0, "discovery_count": 0})
        active_count = uni.get("active_count", 0) or 0
        errors_count = len(uni.get("errors") or [])
        disc = uni.get("discovery") or {}
        discovery_count = disc.get("discovered_count", 0) if disc else 0
        details = {"active_count": active_count, "errors_count": errors_count,
                   "discovery_count": discovery_count}
        if active_count == 0:
            return _fail("universe", "Active universe is empty.", details)
        if active_count < 10:
            return _warn("universe", f"Active universe is small ({active_count} symbols).", details)
        return _pass("universe", f"Active universe has {active_count} symbols.", details)
    except Exception as exc:
        return _warn("universe", f"Could not check universe: {type(exc).__name__}: {exc}")


def _check_discovery() -> dict:
    try:
        from paper.runtime_config import effective_value as _cfg
        enabled = _cfg("PAPER_MARKET_DISCOVERY_ENABLED")
        if not enabled:
            return _pass("discovery", "Market discovery disabled by configuration.",
                         {"enabled": False})
        from paper.universe import get_cached_universe
        uni = get_cached_universe()
        if uni is None:
            return _warn("discovery", "Discovery enabled but no cached universe data yet.",
                         {"enabled": True})
        disc = uni.get("discovery") or {}
        disc_count = disc.get("discovered_count", 0) if disc else 0
        errors = disc.get("errors") or [] if disc else []
        if errors and disc_count == 0:
            return _warn("discovery",
                         f"Discovery enabled but all sources failed ({len(errors)} error(s)).",
                         {"enabled": True, "discovered_count": disc_count, "errors": len(errors)})
        return _pass("discovery",
                     f"Discovery enabled — {disc_count} symbol(s) found.",
                     {"enabled": True, "discovered_count": disc_count, "errors": len(errors)})
    except Exception as exc:
        return _warn("discovery", f"Could not check discovery: {type(exc).__name__}: {exc}")


def _check_market_regime() -> dict:
    try:
        from paper.runtime_config import effective_value as _cfg
        if not _cfg("MARKET_REGIME_ENABLED"):
            return _pass("market_regime",
                         "Market regime monitoring disabled by configuration.",
                         {"enabled": False})
        import market.regime as _mr
        cached = _mr._cache
        if cached is None:
            return _warn("market_regime",
                         "Market regime enabled but not yet fetched.",
                         {"enabled": True})
        error = cached.get("error")
        risk = cached.get("risk", {})
        confidence = risk.get("confidence")
        regime = risk.get("regime")
        if error:
            return _warn("market_regime",
                         "Market regime data has error.",
                         {"enabled": True, "error": str(error)[:200]})
        if confidence in ("unknown", None):
            return _warn("market_regime",
                         f"Market regime confidence is {confidence!r}.",
                         {"enabled": True, "regime": regime, "confidence": confidence})
        return _pass("market_regime",
                     f"Regime: {regime}, confidence: {confidence}.",
                     {"enabled": True, "regime": regime, "confidence": confidence})
    except Exception as exc:
        return _warn("market_regime",
                     f"Could not check market regime: {type(exc).__name__}: {exc}")


def _check_tick_freshness(market_open: bool) -> dict:
    try:
        from core.config import settings
        import paper.simulator as _sim
        state = _sim.get_state()
        running = bool(state.get("running", False))
        last_tick_at = state.get("last_tick_at")

        if not running:
            if market_open:
                return _fail("tick_freshness",
                             "Simulator stopped during market session — no ticks produced.",
                             {"running": False, "last_tick_at": last_tick_at})
            return _warn("tick_freshness",
                         "Simulator stopped — no recent tick.",
                         {"running": False, "last_tick_at": last_tick_at})

        if last_tick_at is None:
            return _warn("tick_freshness",
                         "Simulator running but no tick yet (starting up).",
                         {"running": True, "last_tick_at": None})

        lt = datetime.fromisoformat(last_tick_at)
        if lt.tzinfo is None:
            lt = lt.replace(tzinfo=timezone.utc)
        age_s = round((datetime.now(timezone.utc) - lt).total_seconds(), 1)
        threshold = 2 * settings.PAPER_POLL_INTERVAL_SECONDS + 30
        details = {"running": True, "last_tick_age_seconds": age_s,
                   "threshold_seconds": threshold}
        if age_s <= threshold:
            return _pass("tick_freshness",
                         f"Last tick {age_s}s ago (threshold {threshold}s).", details)
        return _warn("tick_freshness",
                     f"Last tick stale: {age_s}s ago (threshold {threshold}s).", details)
    except Exception as exc:
        return _warn("tick_freshness",
                     f"Could not check tick freshness: {type(exc).__name__}: {exc}")


def _check_dashboard() -> dict:
    try:
        import paper.simulator as _sim
        _sim.get_status()
        return _pass("dashboard", "Dashboard data structures accessible.")
    except Exception as exc:
        return _fail("dashboard", f"Dashboard check failed: {type(exc).__name__}: {exc}")


def _check_momentum_mode() -> dict:
    try:
        from paper.runtime_config import effective_value as _cfg
        enabled = bool(_cfg("PAPER_MOMENTUM_MODE_ENABLED"))
        threshold = _cfg("PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD")
        max_trades = _cfg("PAPER_MOMENTUM_MAX_TRADES_PER_DAY")
        details = {
            "enabled": enabled,
            "momentum_score_threshold": threshold,
            "momentum_max_trades_per_day": max_trades,
        }
        if enabled:
            return _warn(
                "momentum_mode",
                "Momentum entry mode is ENABLED. Fake-money simulation only — no broker, no real orders.",
                details,
            )
        return _pass(
            "momentum_mode",
            "Momentum entry mode disabled (default). Catalyst-only entry path active.",
            details,
        )
    except Exception as exc:
        return _warn("momentum_mode", f"Could not check momentum mode: {type(exc).__name__}: {exc}")


def _check_daily_loss_guard() -> dict:
    try:
        import paper.simulator as _sim
        status = _sim.get_status()
        guard = status.get("daily_loss_guard", {})
        enabled = bool(guard.get("enabled", False))
        triggered = bool(guard.get("triggered", False))
        details = {
            "enabled": enabled,
            "triggered": triggered,
            "trading_date": guard.get("trading_date"),
            "daily_start_equity": guard.get("daily_start_equity"),
            "current_equity": guard.get("current_equity"),
            "daily_pnl": guard.get("daily_pnl", 0.0),
            "daily_pnl_percent": guard.get("daily_pnl_percent", 0.0),
            "threshold_percent": guard.get("threshold_percent"),
            "threshold_usd": guard.get("threshold_usd"),
            "reason": guard.get("reason"),
        }
        if triggered:
            return _warn(
                "daily_loss_guard",
                "Daily max loss guard triggered — new fake-money entries blocked.",
                details,
            )
        if enabled:
            return _pass(
                "daily_loss_guard",
                "Daily max loss guard active — daily P&L within threshold.",
                details,
            )
        return _pass(
            "daily_loss_guard",
            "Daily max loss guard disabled.",
            details,
        )
    except Exception as exc:
        return _warn("daily_loss_guard", f"Could not check daily loss guard: {type(exc).__name__}: {exc}")


def _check_safety_invariants() -> dict:
    try:
        import paper.simulator as _sim
        status = _sim.get_status()
        live = bool(status.get("live_trading_enabled", False))
        broker = bool(status.get("broker_connected", False))
        # execution_enabled is hard-coded False: this platform never enables real execution.
        details = {"live_trading_enabled": live, "broker_connected": broker,
                   "execution_enabled": False}
        if live or broker:
            return _fail("safety_invariants",
                         "SAFETY VIOLATION: live_trading or broker_connected is True.",
                         details)
        return _pass("safety_invariants",
                     "Safety invariants hold: no live trading, no broker, no execution.",
                     details)
    except Exception as exc:
        return _warn("safety_invariants",
                     f"Could not verify safety invariants: {type(exc).__name__}: {exc}")


# ── Aggregation helpers ───────────────────────────────────────────────────────

async def _run_all_checks(market_open: bool) -> list[dict]:
    checks: list[dict] = []
    checks.append(_check_backend())
    checks.append(_check_simulator(market_open))
    checks.append(_check_polygon_key())
    checks.append(await _check_polygon_data())
    checks.append(_check_journal(market_open))
    checks.append(_check_runtime_config())
    checks.append(_check_universe())
    checks.append(_check_discovery())
    checks.append(_check_market_regime())
    checks.append(_check_tick_freshness(market_open))
    checks.append(_check_dashboard())
    checks.append(_check_momentum_mode())
    checks.append(_check_daily_loss_guard())
    checks.append(_check_safety_invariants())
    return checks


def _overall_status(checks: list[dict]) -> str:
    statuses = {c["status"] for c in checks}
    if "fail" in statuses:
        return "not_ready"
    if "warn" in statuses:
        return "warning"
    return "ready"


def _recommended_actions(checks: list[dict], market_open: bool, sim_running: bool) -> list[str]:
    actions: list[str] = []
    m = {c["name"]: c["status"] for c in checks}
    if m.get("safety_invariants") == "fail":
        actions.append("URGENT: Safety invariant violated — check simulator configuration immediately.")
    if m.get("polygon_key") == "fail":
        actions.append("Set POLYGON_API_KEY in .env and restart the backend.")
    if m.get("polygon_data") == "fail":
        actions.append("Check Polygon API key validity and REST access permissions.")
    if m.get("journal") == "fail":
        actions.append("Check PostgreSQL connectivity and journal table initialization.")
    if m.get("journal") == "warn":
        actions.append("Investigate journal status — database may be unavailable or journal disabled.")
    if m.get("simulator") == "fail" and market_open and not sim_running:
        actions.append("Start the paper simulator via the dashboard or POST /api/paper/start.")
    if m.get("tick_freshness") in ("fail", "warn") and sim_running:
        actions.append("Check simulator loop for errors — last tick may be stale.")
    if m.get("universe") == "fail":
        actions.append("Refresh the universe via POST /api/paper/universe/refresh.")
    if m.get("runtime_config") == "warn":
        actions.append("Runtime overrides active — review or reset via POST /api/config/runtime/reset.")
    if m.get("momentum_mode") == "warn":
        actions.append(
            "Momentum mode is ENABLED — fake-money only. "
            "Disable with PAPER_MOMENTUM_MODE_ENABLED=false when not testing."
        )
    if m.get("daily_loss_guard") == "warn":
        actions.append(
            "Daily max loss guard triggered — new fake-money entries are blocked. "
            "Reset the simulator or adjust PAPER_DAILY_MAX_LOSS_PERCENT to resume entries."
        )
    return actions


def _sanitize_checks(raw: list) -> list[dict]:
    """Coerce every check to a well-formed dict before aggregation."""
    sanitized: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            sanitized.append(_fail("malformed_check",
                                   "Check returned a non-dict result.",
                                   {"raw_type": type(item).__name__}))
            continue
        name = item.get("name")
        status = item.get("status")
        raw_details = item.get("details")
        sanitized.append({
            "name":    name if isinstance(name, str) else "unknown_check",
            "status":  status if status in ("pass", "warn", "fail") else "fail",
            "message": item.get("message", "") if isinstance(item.get("message"), str) else "",
            "details": make_json_safe(raw_details) if isinstance(raw_details, dict) else {},
        })
    return sanitized


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/session")
async def readiness_session():
    """
    Full market-session readiness check.
    No broker. No live trading. No real orders. Observational only.
    """
    as_of: str = datetime.now(timezone.utc).isoformat()
    safe_ms: dict = {
        "timezone": "America/New_York",
        "is_regular_session_now": False,
        "regular_open": "09:30",
        "regular_close": "16:00",
        "note": "Best-effort weekday/session check; holidays not included yet.",
    }
    try:
        ms = _market_session_now()
        safe_ms = ms
        market_open: bool = bool(ms.get("is_regular_session_now", False))

        try:
            checks = await _run_all_checks(market_open)
        except Exception as exc:
            logger.exception("Readiness check runner failed")
            safe_err = redact_sensitive_error(exc)
            return make_json_safe({
                "overall_status": "not_ready",
                "as_of": as_of,
                "market_session": ms,
                "checks": [_fail("readiness_internal",
                                 "Readiness check runner failed safely.",
                                 {"error": safe_err})],
                "summary": {"pass": 0, "warn": 0, "fail": 1},
                "recommended_actions": ["Check backend logs and readiness check dependencies."],
                "disclaimer": DISCLAIMER,
            })

        safe_checks = _sanitize_checks(checks)
        overall = _overall_status(safe_checks)
        summary = {
            "pass": sum(1 for c in safe_checks if c["status"] == "pass"),
            "warn": sum(1 for c in safe_checks if c["status"] == "warn"),
            "fail": sum(1 for c in safe_checks if c["status"] == "fail"),
        }

        sim_running = False
        try:
            import paper.simulator as _sim
            sim_running = bool(_sim.get_state().get("running", False))
        except Exception:
            pass

        return make_json_safe({
            "overall_status": overall,
            "as_of": as_of,
            "market_session": ms,
            "checks": safe_checks,
            "summary": summary,
            "recommended_actions": _recommended_actions(safe_checks, market_open, sim_running),
            "disclaimer": DISCLAIMER,
        })
    except Exception as exc:
        logger.exception("Readiness response assembly failed")
        safe_err = redact_sensitive_error(exc)
        return make_json_safe({
            "overall_status": "not_ready",
            "as_of": as_of,
            "market_session": safe_ms,
            "checks": [_fail("readiness_internal",
                             "Readiness response assembly failed safely.",
                             {"error": safe_err})],
            "summary": {"pass": 0, "warn": 0, "fail": 1},
            "recommended_actions": ["Check backend logs and readiness response assembly."],
            "disclaimer": DISCLAIMER,
        })


@router.get("/session/compact")
async def readiness_session_compact():
    """
    Compact readiness summary for quick polling.
    No broker. No live trading. No real orders. Observational only.
    """
    safe_market_open = False
    try:
        ms = _market_session_now()
        market_open: bool = bool(ms.get("is_regular_session_now", False))
        safe_market_open = market_open

        try:
            checks = await _run_all_checks(market_open)
        except Exception:
            logger.exception("Readiness compact check runner failed")
            return make_json_safe({
                "overall_status": "not_ready",
                "market_open": market_open,
                "simulator_running": False,
                "journal_ok": False,
                "polygon_ok": False,
                "universe_count": None,
                "last_tick_age_seconds": None,
                "fail_count": 1,
                "warn_count": 0,
                "recommended_actions": ["Check backend logs and readiness check dependencies."],
                "disclaimer": DISCLAIMER,
            })

        safe_checks = _sanitize_checks(checks)
        overall = _overall_status(safe_checks)
        fail_count = sum(1 for c in safe_checks if c["status"] == "fail")
        warn_count = sum(1 for c in safe_checks if c["status"] == "warn")

        sim_running = False
        last_tick_age: float | None = None
        journal_ok = False
        polygon_ok = False
        universe_count: int | None = None

        try:
            import paper.simulator as _sim
            state = _sim.get_state()
            sim_running = bool(state.get("running", False))
            last_tick_at = state.get("last_tick_at")
            if last_tick_at:
                lt = datetime.fromisoformat(last_tick_at)
                if lt.tzinfo is None:
                    lt = lt.replace(tzinfo=timezone.utc)
                last_tick_age = round((datetime.now(timezone.utc) - lt).total_seconds(), 1)
        except Exception:
            pass

        try:
            from paper.journal import get_journal_status
            j = get_journal_status()
            journal_ok = bool(j.get("enabled") and j.get("database_connected") and j.get("tables_ready"))
        except Exception:
            pass

        try:
            from core.config import settings
            polygon_ok = bool(settings.POLYGON_API_KEY)
        except Exception:
            pass

        try:
            from paper.universe import get_cached_universe
            uni = get_cached_universe()
            if uni is not None:
                universe_count = uni.get("active_count")
        except Exception:
            pass

        return make_json_safe({
            "overall_status": overall,
            "market_open": market_open,
            "simulator_running": sim_running,
            "journal_ok": journal_ok,
            "polygon_ok": polygon_ok,
            "universe_count": universe_count,
            "last_tick_age_seconds": last_tick_age,
            "fail_count": fail_count,
            "warn_count": warn_count,
            "recommended_actions": _recommended_actions(safe_checks, market_open, sim_running),
            "disclaimer": DISCLAIMER,
        })
    except Exception:
        logger.exception("Readiness compact response assembly failed")
        return make_json_safe({
            "overall_status": "not_ready",
            "market_open": safe_market_open,
            "simulator_running": False,
            "journal_ok": False,
            "polygon_ok": False,
            "universe_count": None,
            "last_tick_age_seconds": None,
            "fail_count": 1,
            "warn_count": 0,
            "recommended_actions": ["Check backend logs and readiness response assembly."],
            "disclaimer": DISCLAIMER,
        })
