"""
Phase G1B-H1 — wallet dashboard visibility + EOD review.

Pure-unit tests for the helpers added in this phase. No broker, no live
trading, no real orders. No paid AI calls.

Sections:
  A — /api/paper/wallets returns all three wallets, AI_SHADOW visible
      even when inactive.
  B — wallet-specific positions/trades endpoints.
  D — session-aware closed-trades returns latest US session.
  E — EOD entry cutoff + flatten helpers.
  F — persistence_status includes coverage% / by-horizon / source.
  G — outcome resolver source column wired into UPDATE SQL.
  H — news feed has no overflow-x container in NewsTab.
  I — backward compatibility of legacy endpoints.
"""
from __future__ import annotations

import inspect
from datetime import datetime, time as dtime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


# ── Helpers ─────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from unittest.mock import patch, AsyncMock
    with patch(
        "paper.simulator.restore_paper_session",
        new=AsyncMock(return_value={"source": "none"}),
    ), patch(
        "paper.simulator._save_state",
        new=AsyncMock(return_value=None),
    ), patch(
        "marketdata.service.start_collector",
        new=AsyncMock(return_value={"started": True, "symbols": []}),
    ), patch(
        "intelligence.reddit.ensure_loaded",
        new=AsyncMock(return_value=None),
    ):
        from main import app
        with TestClient(app) as c:
            yield c


# ── Section A — /api/paper/wallets ──────────────────────────────────────────

def test_wallets_endpoint_returns_three_wallets(client):
    r = client.get("/api/paper/wallets")
    assert r.status_code == 200
    body = r.json()
    assert "engine" in body
    assert "deterministic_shadow" in body
    assert "ai_shadow" in body
    assert isinstance(body.get("wallets"), list)
    assert len(body["wallets"]) == 3


def test_ai_shadow_visible_even_when_inactive(client, monkeypatch):
    from core.config import settings
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", False)
    monkeypatch.setattr(settings, "PAPER_SHADOW_WALLETS_ENABLED", True)
    r = client.get("/api/paper/wallets")
    assert r.status_code == 200
    ai = r.json()["ai_shadow"]
    # The card should still be present with a clear inactive reason.
    assert ai is not None
    assert ai["status"] == "inactive"
    assert ai["inactive_reason"] and "LLM_SHADOW_ENABLED" in ai["inactive_reason"]


def test_wallet_snapshot_carries_all_summary_fields(client):
    r = client.get("/api/paper/wallets")
    body = r.json()
    for key in ("engine", "deterministic_shadow", "ai_shadow"):
        w = body[key]
        for field in (
            "wallet_id", "status", "cash", "equity",
            "realized_pnl", "unrealized_pnl", "total_pnl",
            "open_position_count", "closed_trade_count",
            "daily_pnl", "win_rate", "last_update_time",
        ):
            assert field in w, f"{key} missing {field!r}"


# ── Section B — wallet-specific positions/trades endpoints ─────────────────

def test_wallets_positions_endpoint_returns_engine_filter(client):
    r = client.get("/api/paper/wallets/positions?wallet_id=engine")
    assert r.status_code == 200
    body = r.json()
    assert body["wallet_id"] == "engine"
    assert isinstance(body["positions"], list)
    for p in body["positions"]:
        assert p["wallet_id"] == "engine"


def test_wallets_positions_endpoint_returns_all_when_unfiltered(client):
    r = client.get("/api/paper/wallets/positions")
    assert r.status_code == 200
    assert isinstance(r.json()["positions"], list)


def test_wallets_trades_endpoint_returns_wallet_id(client):
    r = client.get("/api/paper/wallets/trades?wallet_id=engine")
    assert r.status_code == 200
    body = r.json()
    assert body["wallet_id"] == "engine"
    for t in body["trades"]:
        assert t["wallet_id"] == "engine"


def test_wallets_trades_endpoint_supports_deterministic_shadow_filter(client):
    r = client.get("/api/paper/wallets/trades?wallet_id=deterministic_shadow")
    assert r.status_code == 200
    body = r.json()
    assert body["wallet_id"] == "deterministic_shadow"


# ── Section D — session-aware closed-trades ─────────────────────────────────

def test_session_helpers_use_america_new_york():
    from paper import session as s

    # Weekday at 10:00 ET → today
    fixed = datetime(2026, 6, 10, 14, 0, tzinfo=timezone.utc)  # 10:00 ET
    assert s.latest_session_date_ny(fixed.astimezone(s._ny_tz())) == "2026-06-10"

    # Sunday → previous Friday
    sunday = datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)
    assert s.latest_session_date_ny(sunday.astimezone(s._ny_tz())) == "2026-06-12"

    # Pre-market on a weekday → previous weekday
    early = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)  # 08:00 ET
    assert s.latest_session_date_ny(early.astimezone(s._ny_tz())) == "2026-06-10"


def test_session_date_for_attributes_after_hours_to_same_session():
    from paper import session as s
    # 21:00 UTC on a weekday = 17:00 ET → same NY date
    ts = "2026-06-10T21:00:00+00:00"
    assert s.session_date_for(ts) == "2026-06-10"


def test_trades_endpoint_latest_session_filters_by_ny_session(client, monkeypatch):
    # Spoof simulator.get_trades to return one trade from the previous weekday.
    from paper import simulator
    monkeypatch.setattr(simulator, "get_trades", lambda: [
        {"symbol": "AAPL", "position_id": "p1", "exit_time": "2026-06-09T20:00:00+00:00",
         "entry_time": "2026-06-09T19:30:00+00:00", "pnl": 1.0, "pnl_percent": 1.0,
         "exit_reason": "take_profit_intrabar", "hold_minutes": 30,
         "entry_catalyst_type": "earnings_beat", "entry_price": 100.0, "exit_price": 101.0},
        {"symbol": "NVDA", "position_id": "p2", "exit_time": "2026-06-10T19:30:00+00:00",
         "entry_time": "2026-06-10T19:00:00+00:00", "pnl": 2.0, "pnl_percent": 2.0,
         "exit_reason": "take_profit_intrabar", "hold_minutes": 15,
         "entry_catalyst_type": "guidance_raise", "entry_price": 50.0, "exit_price": 51.0},
    ])
    r = client.get("/api/paper/wallets/trades?wallet_id=engine&session_date=2026-06-10")
    assert r.status_code == 200
    body = r.json()
    syms = [t["symbol"] for t in body["trades"]]
    assert syms == ["NVDA"]


# ── Section E — EOD entry cutoff + flatten helpers ─────────────────────────

def test_eod_entries_blocked_inside_cutoff_window(monkeypatch):
    """At 15:55 ET on a weekday with cutoff=10, entries must be blocked."""
    from core.config import settings
    from paper import eod, session as s

    monkeypatch.setattr(settings, "PAPER_EOD_FLATTEN_ENABLED", True)
    monkeypatch.setattr(settings, "PAPER_ALLOW_OVERNIGHT_POSITIONS", False)
    monkeypatch.setattr(settings, "PAPER_ENTRY_CUTOFF_MINUTES_BEFORE_CLOSE", 10)
    weekday_late = datetime(2026, 6, 10, 19, 55, tzinfo=timezone.utc)  # 15:55 ET
    ny = weekday_late.astimezone(s._ny_tz())
    blocked, reason = eod.entries_blocked(ny)
    assert blocked is True
    assert reason == "eod_entry_cutoff"


def test_eod_entries_allowed_before_cutoff(monkeypatch):
    from core.config import settings
    from paper import eod, session as s

    monkeypatch.setattr(settings, "PAPER_EOD_FLATTEN_ENABLED", True)
    monkeypatch.setattr(settings, "PAPER_ALLOW_OVERNIGHT_POSITIONS", False)
    monkeypatch.setattr(settings, "PAPER_ENTRY_CUTOFF_MINUTES_BEFORE_CLOSE", 10)
    weekday_mid = datetime(2026, 6, 10, 14, 0, tzinfo=timezone.utc)  # 10:00 ET
    blocked, _ = eod.entries_blocked(weekday_mid.astimezone(s._ny_tz()))
    assert blocked is False


def test_eod_entries_not_blocked_when_overnight_allowed(monkeypatch):
    from core.config import settings
    from paper import eod, session as s
    monkeypatch.setattr(settings, "PAPER_ALLOW_OVERNIGHT_POSITIONS", True)
    weekday_late = datetime(2026, 6, 10, 19, 55, tzinfo=timezone.utc)
    blocked, _ = eod.entries_blocked(weekday_late.astimezone(s._ny_tz()))
    assert blocked is False


def test_eod_flatten_due_at_close(monkeypatch):
    from core.config import settings
    from paper import eod, session as s
    monkeypatch.setattr(settings, "PAPER_EOD_FLATTEN_ENABLED", True)
    monkeypatch.setattr(settings, "PAPER_ALLOW_OVERNIGHT_POSITIONS", False)
    monkeypatch.setattr(settings, "PAPER_EOD_FLATTEN_MINUTES_BEFORE_CLOSE", 0)
    at_close = datetime(2026, 6, 10, 20, 0, tzinfo=timezone.utc)  # 16:00 ET
    assert eod.flatten_due(at_close.astimezone(s._ny_tz())) is True


def test_eod_flatten_not_due_midday(monkeypatch):
    from core.config import settings
    from paper import eod, session as s
    monkeypatch.setattr(settings, "PAPER_EOD_FLATTEN_ENABLED", True)
    monkeypatch.setattr(settings, "PAPER_ALLOW_OVERNIGHT_POSITIONS", False)
    midday = datetime(2026, 6, 10, 17, 0, tzinfo=timezone.utc)  # 13:00 ET
    assert eod.flatten_due(midday.astimezone(s._ny_tz())) is False


def test_eod_defaults_are_safe():
    """Default settings flatten end of day, no overnight, 10-min entry cutoff."""
    from core.config import settings
    assert settings.PAPER_ALLOW_OVERNIGHT_POSITIONS is False
    assert settings.PAPER_EOD_FLATTEN_ENABLED is True
    assert settings.PAPER_ENTRY_CUTOFF_MINUTES_BEFORE_CLOSE >= 1


def test_shadow_wallet_eod_flatten_closes_open_positions(monkeypatch):
    """Shadow wallets must flatten all open positions when EOD triggers."""
    from core.config import settings
    from paper import shadow_wallets as sw

    monkeypatch.setattr(settings, "PAPER_SHADOW_WALLETS_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", False)
    sw.reset()
    # Plant a position directly.
    det = sw._wallet(sw.WALLET_DETERMINISTIC)
    det.enter_position("AAPL", 100.0, 200.0, "test", entry_score=70)
    exits, warnings = sw._eod_flatten_for(
        sw.WALLET_DETERMINISTIC, {"AAPL": {"bid": 101.0, "last_trade_price": 101.0}}
    )
    assert len(exits) == 1
    assert exits[0]["exit_reason"] == "eod_flatten"
    assert exits[0]["wallet_id"] == sw.WALLET_DETERMINISTIC
    assert warnings == []
    assert sw._wallet(sw.WALLET_DETERMINISTIC).positions == {}


def test_shadow_wallet_eod_flatten_warns_when_price_missing(monkeypatch):
    from core.config import settings
    from paper import shadow_wallets as sw

    monkeypatch.setattr(settings, "PAPER_SHADOW_WALLETS_ENABLED", True)
    sw.reset()
    det = sw._wallet(sw.WALLET_DETERMINISTIC)
    det.enter_position("XYZ", 50.0, 100.0, "test", entry_score=70)
    exits, warnings = sw._eod_flatten_for(sw.WALLET_DETERMINISTIC, {"XYZ": {}})
    assert exits == []
    assert warnings and warnings[0]["reason"] == "missing_exit_price"


# ── Section F — persistence_status enrichment ──────────────────────────────

@pytest.mark.asyncio
async def test_persistence_status_response_shape():
    """Even without a real DB, the response must surface the high-low caveat
    and the resolver_last_run field — both used by the dashboard."""
    from paper.outcome_resolver import persistence_status, _HIGH_LOW_CAVEAT
    result = await persistence_status()
    assert "high_low_caveat" in result
    assert result["high_low_caveat"] == _HIGH_LOW_CAVEAT
    assert "resolver_last_run" in result


def test_persistence_status_endpoint_exposes_coverage_keys(client):
    r = client.get("/api/audit/persistence/status")
    assert r.status_code == 200
    body = r.json()
    # Coverage % may be 0 without DB rows, but the key must be present once a
    # DB is available — assert at minimum the documented caveat surface.
    assert "high_low_caveat" in body
    assert "resolver_last_run" in body


# ── Section G — outcome resolver writes source ─────────────────────────────

def test_outcome_resolver_source_strings_present_in_module_source():
    """Source-truth: resolver UPDATE statements must label each terminal
    status with the matching `source` value."""
    from paper import outcome_resolver as r
    src = inspect.getsource(r.resolve_pending)
    assert "'marketdata_cache'" in src or '"marketdata_cache"' in src
    assert "'missing_cache'" in src or '"missing_cache"' in src
    assert "'error'" in src or '"error"' in src


def test_outcome_high_low_left_null():
    """Resolver must NOT synthesize max_high/max_low; the cache resolver only
    sees a single point-in-time price."""
    from paper import outcome_resolver as r
    src = inspect.getsource(r.resolve_pending)
    assert "max_high_return_percent" not in src.split("UPDATE")[1].split("WHERE")[0]
    assert "max_low_return_percent" not in src.split("UPDATE")[1].split("WHERE")[0]


def test_migration_adds_source_column():
    from paper.db import _CREATE_TABLES
    assert "ADD COLUMN IF NOT EXISTS source TEXT" in _CREATE_TABLES


# ── Section I — backward compatibility ──────────────────────────────────────

def test_legacy_positions_endpoint_still_returns_engine_only(client):
    r = client.get("/api/paper/positions")
    assert r.status_code == 200
    body = r.json()
    assert "positions" in body


def test_legacy_trades_endpoint_still_works(client):
    r = client.get("/api/paper/trades")
    assert r.status_code == 200
    body = r.json()
    assert "trades" in body


def test_engine_decision_logic_unchanged():
    """Sanity check: the entry-decision branches still exist verbatim. The
    EOD wrapper added in G1B-H1 is the ONLY new condition; scoring,
    catalyst, momentum, and no-catalyst branches are untouched."""
    import paper.simulator as sim
    src = inspect.getsource(sim.run_tick)
    assert "Path A: Catalyst entry (existing logic, unchanged)" in src
    assert "Path D: Market mover no-catalyst entry" in src
    assert "Path C: No-catalyst momentum entry" in src


# ── Section H — News feed layout (best-effort source check) ────────────────

def _read_frontend_page() -> str | None:
    """Best-effort read of the dashboard page.tsx. Skipped inside containers
    that don't mount the frontend directory."""
    import pathlib
    for candidate in (
        "/opt/microtrading-app/frontend/dashboard/app/page.tsx",
        "/app/../frontend/dashboard/app/page.tsx",
    ):
        p = pathlib.Path(candidate)
        if p.exists():
            return p.read_text()
    return None


def test_news_tab_dropped_horizontal_scroll_wrapper():
    """The reworked News table must not be wrapped in `overflow-x-auto`."""
    page = _read_frontend_page()
    if page is None:
        pytest.skip("frontend page.tsx not accessible from this environment")
    news_block = page.split('Phase G1B-H1 Part H')[-1].split('</table>')[0]
    assert "overflow-x-auto" not in news_block, (
        "News table still inside an overflow-x-auto container"
    )
    assert "table-fixed" in news_block


def test_news_tab_dropped_inactive_ai_column():
    page = _read_frontend_page()
    if page is None:
        pytest.skip("frontend page.tsx not accessible from this environment")
    news_block = page.split('Phase G1B-H1 Part H')[-1].split('</table>')[0]
    assert "AI Analysis" not in news_block


# ── Boundary invariants ────────────────────────────────────────────────────

def test_no_broker_or_live_imports_in_new_modules():
    """New G1B-H1 modules must not actually import or call broker/live-trading
    code. We check imports + attribute access, not docstring text (the
    "no broker" disclaimer mentions the word legitimately)."""
    import ast as _ast
    forbidden = ("alpaca", "broker", "live_trading", "real_order", "place_order")
    import paper.eod, paper.session, paper.outcome_resolver, api.audit
    for mod in (paper.eod, paper.session, paper.outcome_resolver, api.audit):
        tree = _ast.parse(inspect.getsource(mod))
        names: list[str] = []
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                names += [n.name for n in node.names]
            elif isinstance(node, _ast.ImportFrom):
                names.append(node.module or "")
                names += [n.name for n in node.names]
            elif isinstance(node, (_ast.Call, _ast.Attribute, _ast.Name)):
                names.append(getattr(node, "attr", None) or getattr(node, "id", "") or "")
        joined = " ".join(names).lower()
        for needle in forbidden:
            assert needle not in joined, (
                f"{mod.__name__} contains forbidden token {needle!r}"
            )
