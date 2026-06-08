"""
Monitoring status endpoint for the paper simulator.
No auth required (read-only; no sensitive data exposed).
Research-only fake-money simulation. No live trading. No real orders.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from core.config import settings
from paper import db as _db
from paper.journal import get_journal_status

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/status")
async def monitoring_status():
    # ── Simulator state ───────────────────────────────────────────────────────
    sim_status: dict = {}
    try:
        import paper.simulator as _sim
        sim_status = _sim.get_status()
    except Exception:
        pass

    paper_running: bool = bool(sim_status.get("running", False))
    last_tick_at: str | None = sim_status.get("last_tick_at")
    last_error: str | None = sim_status.get("last_error")

    # ── Tick age and freshness ────────────────────────────────────────────────
    age: float | None = None
    if last_tick_at:
        try:
            lt = datetime.fromisoformat(last_tick_at)
            if lt.tzinfo is None:
                lt = lt.replace(tzinfo=timezone.utc)
            age = round((datetime.now(timezone.utc) - lt).total_seconds(), 1)
        except Exception:
            pass

    stale_threshold = 2 * settings.PAPER_POLL_INTERVAL_SECONDS + 30
    if not paper_running:
        last_tick_fresh = True
    elif age is None:
        last_tick_fresh = True  # running but no tick yet — expected at startup
    else:
        last_tick_fresh = age <= stale_threshold

    # ── Journal state ─────────────────────────────────────────────────────────
    j = get_journal_status()
    journal_enabled: bool = j["enabled"]
    journal_db_connected: bool = j["database_connected"]
    journal_tables_ready: bool = j["tables_ready"]
    last_journal_ok: bool | None = j.get("last_persist_ok")

    # ── Market session ────────────────────────────────────────────────────────
    ms = _market_session_now()

    # ── Candidate count for retention warning ─────────────────────────────────
    total_candidates: int | None = None
    try:
        if journal_db_connected:
            pool = await _db.get_pool()
            if pool:
                async with pool.acquire() as conn:
                    total_candidates = await conn.fetchval(
                        "SELECT COUNT(*)::int FROM paper_candidates"
                    )
    except Exception:
        pass

    # ── Warnings ─────────────────────────────────────────────────────────────
    warnings: list[str] = []

    if not journal_enabled:
        warnings.append("Journal is disabled — tick data is not being persisted to PostgreSQL.")
    elif not journal_db_connected:
        warnings.append("Journal: database not connected.")
    elif not journal_tables_ready:
        warnings.append("Journal: tables not ready.")

    if last_journal_ok is False:
        warnings.append("Last journal write failed — check database connectivity and logs.")

    if paper_running and not last_tick_fresh:
        warnings.append(
            f"Simulator is running but last tick is stale "
            f"({age:.0f}s old; threshold {stale_threshold}s)."
        )

    if ms["is_regular_session_now"] and not paper_running:
        warnings.append(
            "Market session is currently open but the paper simulator is stopped."
        )

    if total_candidates is not None and total_candidates > 100_000:
        warnings.append(
            f"High candidate row count ({total_candidates:,}) with no auto-cleanup enabled. "
            f"Retention policy is read-only (JOURNAL_RETENTION_DAYS={settings.JOURNAL_RETENTION_DAYS})."
        )

    # ── Market regime ─────────────────────────────────────────────────────────
    from paper.runtime_config import effective_value as _cfg
    regime_summary: dict = {"enabled": _cfg("MARKET_REGIME_ENABLED")}
    if _cfg("MARKET_REGIME_ENABLED"):
        try:
            from market.regime import get_market_regime
            regime_data = await get_market_regime()
            risk = regime_data.get("risk", {})
            regime_summary.update({
                "regime": risk.get("regime"),
                "risk_on_score": risk.get("risk_on_score"),
                "confidence": risk.get("confidence"),
                "as_of": regime_data.get("as_of"),
                "symbols_fetched": len(regime_data.get("symbols_fetched", [])),
                "symbols_failed": len(regime_data.get("symbols_failed", [])),
                "error": regime_data.get("error"),
            })
            regime = risk.get("regime")
            confidence = risk.get("confidence")
            score = risk.get("risk_on_score")
            if regime_data.get("error"):
                warnings.append(
                    "Market regime data unavailable — check Polygon API configuration."
                )
            elif regime == "risk_off":
                warnings.append(
                    f"Market regime is RISK_OFF (score {score}) — "
                    "observational only, no strategy changes."
                )
            elif confidence in ("unknown", "low"):
                warnings.append(
                    f"Market regime confidence is {confidence} — "
                    "insufficient symbol data fetched."
                )
        except Exception as exc:
            regime_summary["error"] = f"{type(exc).__name__}: {exc}"
            warnings.append("Market regime monitor unavailable — check Polygon API configuration.")

    # ── Runtime config status ─────────────────────────────────────────────────
    runtime_config_status: dict = {}
    try:
        from paper.runtime_config import get_runtime_status
        runtime_config_status = get_runtime_status()
        if runtime_config_status.get("warnings"):
            warnings.extend(runtime_config_status["warnings"])
    except Exception:
        runtime_config_status = {"overrides_active": False, "override_count": 0,
                                 "persistent": False, "warnings": []}

    # ── Momentum mode status ──────────────────────────────────────────────────
    momentum_mode: dict = {}
    try:
        from paper.runtime_config import effective_value as _cfg_m
        enabled = bool(_cfg_m("PAPER_MOMENTUM_MODE_ENABLED"))
        momentum_mode = {
            "enabled": enabled,
            "entry_score_threshold": _cfg_m("PAPER_MOMENTUM_ENTRY_SCORE_THRESHOLD"),
            "min_change_percent": _cfg_m("PAPER_MOMENTUM_MIN_CHANGE_PERCENT"),
            "min_volume_ratio": _cfg_m("PAPER_MOMENTUM_MIN_VOLUME_RATIO"),
            "max_spread_percent": _cfg_m("PAPER_MOMENTUM_MAX_SPREAD_PERCENT"),
            "require_market_risk_on": _cfg_m("PAPER_MOMENTUM_REQUIRE_MARKET_RISK_ON"),
            "min_market_risk_score": _cfg_m("PAPER_MOMENTUM_MIN_MARKET_RISK_SCORE"),
            "position_size_multiplier": _cfg_m("PAPER_MOMENTUM_POSITION_SIZE_MULTIPLIER"),
            "max_trades_per_day": _cfg_m("PAPER_MOMENTUM_MAX_TRADES_PER_DAY"),
            "disclaimer": (
                "Momentum mode is fake-money simulation only. "
                "No live trading. No real-money execution."
            ),
        }
        if enabled:
            warnings.append(
                "Momentum entry mode is ENABLED — fake-money simulation only. "
                "No live trading. No real-money execution."
            )
    except Exception as exc:
        momentum_mode = {"enabled": False, "error": f"{type(exc).__name__}: {exc}"}

    daily_loss_guard: dict = {}
    try:
        import paper.simulator as _sim_dlg
        _status_dlg = _sim_dlg.get_status()
        daily_loss_guard = _status_dlg.get("daily_loss_guard", {})
        if daily_loss_guard.get("triggered"):
            warnings.append(
                "Daily max loss guard triggered — new fake-money entries blocked. "
                f"Daily P&L: {daily_loss_guard.get('daily_pnl_percent', 0):.2f}%"
            )
    except Exception as exc:
        daily_loss_guard = {"triggered": False, "enabled": False, "error": f"{type(exc).__name__}: {exc}"}

    # ── Market-data cache status (Phase D2) ───────────────────────────────────
    marketdata_cache: dict = {}
    try:
        from paper.runtime_config import effective_value as _cfg_md
        _use_cache = _cfg_md("PAPER_USE_MARKETDATA_CACHE")
        _fallback = _cfg_md("PAPER_MARKETDATA_CACHE_FALLBACK_ENABLED")
        _max_age = _cfg_md("PAPER_MARKETDATA_CACHE_MAX_AGE_SECONDS")
        _require_fresh = _cfg_md("PAPER_MARKETDATA_CACHE_REQUIRE_FRESH_FOR_ENTRY")
        from marketdata import service as _md_svc
        _md_svc_status = _md_svc.get_service_status()
        _collector_running = _md_svc_status.get("running", False)
        marketdata_cache = {
            "enabled": _use_cache,
            "collector_running": _collector_running,
            "max_age_seconds": _max_age,
            "fallback_to_polygon": _fallback,
            "require_fresh_for_entry": _require_fresh,
        }
        if _use_cache and not _collector_running:
            if _fallback:
                warnings.append(
                    "Market-data cache enabled but collector not running — "
                    "falling back to direct Polygon polling."
                )
            else:
                warnings.append(
                    "Market-data cache enabled but collector not running and fallback disabled — "
                    "new fake-money entries will be rejected for missing cache data."
                )
    except Exception as exc:
        marketdata_cache = {"enabled": False, "error": f"{type(exc).__name__}: {exc}"}

    return {
        "backend_ok": True,
        "paper_running": paper_running,
        "journal_enabled": journal_enabled,
        "journal_database_connected": journal_db_connected,
        "journal_tables_ready": journal_tables_ready,
        "last_tick_at": last_tick_at,
        "last_tick_age_seconds": age,
        "last_tick_fresh": last_tick_fresh,
        "last_journal_ok": last_journal_ok,
        "last_error": last_error,
        "market_session": ms,
        "market_regime": regime_summary,
        "runtime_config": runtime_config_status,
        "momentum_mode": momentum_mode,
        "daily_loss_guard": daily_loss_guard,
        "marketdata_cache": marketdata_cache,
        "warnings": warnings,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _market_session_now() -> dict:
    from datetime import time
    try:
        from zoneinfo import ZoneInfo
        ny_tz = ZoneInfo("America/New_York")
        now_ny = datetime.now(ny_tz)
        tz_label = "America/New_York"
    except Exception:
        now_ny = datetime.now(timezone(timedelta(hours=-4)))
        tz_label = "UTC-4 (approximate)"

    is_weekday = now_ny.weekday() < 5
    t = now_ny.time()
    is_session = is_weekday and time(9, 30) <= t < time(16, 0)

    return {
        "timezone": tz_label,
        "is_regular_session_now": is_session,
        "regular_open": "09:30",
        "regular_close": "16:00",
        "note": "Best-effort weekday/session check; holidays not included yet.",
    }
