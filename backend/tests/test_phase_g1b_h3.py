"""
Phase G1B-H3 — universal regular-session entry gate and out-of-session
position remediation.

Pure-unit tests — no broker, no live trading, no real orders, no paid AI calls.

Sections:
  A — entries_allowed_now / entry_block_reason (session.py helpers).
  B — updated entries_blocked() gate in eod.py.
  C — position_entry_is_out_of_session + remediation sweeps.
  D — API surfaces session status and OOS annotations.
  I — boundary invariants.
"""
from __future__ import annotations

import inspect
import pathlib
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


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


# ── Section A — session helpers ─────────────────────────────────────────────

def test_entries_allowed_now_during_session():
    """True at 10:00 ET Friday (regular session)."""
    from paper.session import entries_allowed_now
    fri_10 = datetime(2026, 6, 12, 14, 0, tzinfo=timezone.utc)  # 10:00 ET
    assert entries_allowed_now(fri_10.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))) is True


def test_entries_allowed_now_weekend():
    """False on Saturday."""
    from paper.session import entries_allowed_now
    sat = datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc)  # 10:00 ET Saturday
    assert entries_allowed_now(sat.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))) is False


def test_entry_block_reason_weekend():
    from paper.session import entry_block_reason
    sat = datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc)
    assert entry_block_reason(sat.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))) == "market_closed_weekend"


def test_entry_block_reason_preopen():
    from paper.session import entry_block_reason
    # Friday 08:00 ET = preopen
    fri_preopen = datetime(2026, 6, 13 - 1, 12, 0, tzinfo=timezone.utc)  # Fri 08:00 ET
    assert entry_block_reason(fri_preopen.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))) == "market_preopen"


def test_entry_block_reason_postclose():
    from paper.session import entry_block_reason
    # Friday 17:00 ET = postclose
    fri_post = datetime(2026, 6, 12, 21, 0, tzinfo=timezone.utc)  # 17:00 ET
    assert entry_block_reason(fri_post.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))) == "market_postclose"


def test_entry_block_reason_none_during_session():
    from paper.session import entry_block_reason
    fri_10 = datetime(2026, 6, 12, 14, 0, tzinfo=timezone.utc)  # 10:00 ET
    assert entry_block_reason(fri_10.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))) is None


def test_is_valid_entry_time_saturday():
    from paper.session import is_valid_entry_time
    assert is_valid_entry_time("2026-06-13T04:08:59+00:00") is False  # 00:08 ET Saturday


def test_is_valid_entry_time_regular_session():
    from paper.session import is_valid_entry_time
    assert is_valid_entry_time("2026-06-12T14:00:00+00:00") is True  # 10:00 ET Friday


def test_is_valid_entry_time_handles_edge_cases():
    from paper.session import is_valid_entry_time
    assert is_valid_entry_time(None) is False
    assert is_valid_entry_time("") is False
    assert is_valid_entry_time("not-a-date") is False


# ── Section B — updated entries_blocked() gate ──────────────────────────────

def test_entries_blocked_weekend():
    """Weekend → (True, 'market_closed_weekend')."""
    from paper import eod, session as s
    sat = datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc).astimezone(s._ny_tz())
    blocked, reason = eod.entries_blocked(sat)
    assert blocked is True
    assert reason == "market_closed_weekend"


def test_entries_blocked_preopen():
    """Pre-open weekday → (True, 'market_preopen')."""
    from paper import eod, session as s
    fri_preopen = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc).astimezone(s._ny_tz())  # 08:00 ET
    blocked, reason = eod.entries_blocked(fri_preopen)
    assert blocked is True
    assert reason == "market_preopen"


def test_entries_blocked_postclose():
    """Post-close weekday → (True, 'market_postclose')."""
    from paper import eod, session as s
    fri_post = datetime(2026, 6, 12, 21, 0, tzinfo=timezone.utc).astimezone(s._ny_tz())  # 17:00 ET
    blocked, reason = eod.entries_blocked(fri_post)
    assert blocked is True
    assert reason == "market_postclose"


def test_entries_blocked_false_during_regular_session():
    """10:00 ET Friday → (False, None) — entries are open."""
    from paper import eod, session as s
    fri_10 = datetime(2026, 6, 12, 14, 0, tzinfo=timezone.utc).astimezone(s._ny_tz())
    blocked, reason = eod.entries_blocked(fri_10)
    assert blocked is False
    assert reason is None


def test_entries_blocked_respects_allow_extended_hours(monkeypatch):
    """PAPER_ALLOW_EXTENDED_HOURS_ENTRIES=True disables the universal gate."""
    from core.config import settings
    from paper import eod, session as s
    monkeypatch.setattr(settings, "PAPER_ALLOW_EXTENDED_HOURS_ENTRIES", True)
    sat = datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc).astimezone(s._ny_tz())
    blocked, _ = eod.entries_blocked(sat)
    assert blocked is False


def test_entries_blocked_respects_regular_session_only_false(monkeypatch):
    """PAPER_REGULAR_SESSION_ONLY=False skips the universal gate."""
    from core.config import settings
    from paper import eod, session as s
    monkeypatch.setattr(settings, "PAPER_REGULAR_SESSION_ONLY", False)
    sat = datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc).astimezone(s._ny_tz())
    blocked, _ = eod.entries_blocked(sat)
    assert blocked is False


# ── Section C — position_entry_is_out_of_session + remediation ──────────────

def test_position_entry_is_out_of_session_saturday():
    """TSLA case — 00:08 ET Saturday → out of session."""
    from paper import eod
    assert eod.position_entry_is_out_of_session("2026-06-13T04:08:59+00:00") is True


def test_position_entry_is_out_of_session_regular_session():
    """10:00 ET Friday → valid session, NOT out of session."""
    from paper import eod
    assert eod.position_entry_is_out_of_session("2026-06-12T14:00:00+00:00") is False


def test_position_entry_is_out_of_session_handles_missing():
    from paper import eod
    assert eod.position_entry_is_out_of_session(None) is False
    assert eod.position_entry_is_out_of_session("") is False
    assert eod.position_entry_is_out_of_session("bad-date") is False


def test_position_entry_is_out_of_session_respects_allow_extended(monkeypatch):
    from core.config import settings
    from paper import eod
    monkeypatch.setattr(settings, "PAPER_ALLOW_EXTENDED_HOURS_ENTRIES", True)
    assert eod.position_entry_is_out_of_session("2026-06-13T04:08:59+00:00") is False


def test_out_of_session_reason_is_stable_enum():
    from paper import eod
    assert eod.OUT_OF_SESSION_REASON == "invalid_out_of_session_entry_flatten"


def test_shadow_oos_flatten_closes_out_of_session_position(monkeypatch):
    """A shadow position entered at 00:08 ET Saturday must be force-closed."""
    from core.config import settings
    from paper import shadow_wallets as sw, eod

    monkeypatch.setattr(settings, "PAPER_SHADOW_WALLETS_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", False)
    sw.reset()
    det = sw._wallet(sw.WALLET_DETERMINISTIC)
    pos = det.enter_position("TSLA", 300.0, 100.0, "test", entry_score=70)
    pos.entry_time = "2026-06-13T04:08:59+00:00"  # 00:08 ET Saturday
    det.positions["TSLA"] = pos

    exits, warnings = sw._eod_flatten_for(
        sw.WALLET_DETERMINISTIC,
        {"TSLA": {"bid": 301.0, "last_trade_price": 301.0}},
        exit_reason=eod.OUT_OF_SESSION_REASON,
        only_out_of_session=True,
    )
    assert len(exits) == 1
    assert exits[0]["exit_reason"] == "invalid_out_of_session_entry_flatten"
    assert exits[0]["wallet_id"] == sw.WALLET_DETERMINISTIC
    assert warnings == []
    assert det.positions == {}


def test_shadow_oos_flatten_skips_regular_session_position(monkeypatch):
    """A position entered at 10:00 ET Friday must NOT be touched by the OOS sweep."""
    from core.config import settings
    from paper import shadow_wallets as sw, eod

    monkeypatch.setattr(settings, "PAPER_SHADOW_WALLETS_ENABLED", True)
    sw.reset()
    det = sw._wallet(sw.WALLET_DETERMINISTIC)
    pos = det.enter_position("AAPL", 200.0, 100.0, "test", entry_score=70)
    pos.entry_time = "2026-06-12T14:00:00+00:00"  # 10:00 ET Friday — valid session
    det.positions["AAPL"] = pos

    exits, _ = sw._eod_flatten_for(
        sw.WALLET_DETERMINISTIC,
        {"AAPL": {"bid": 200.0, "last_trade_price": 200.0}},
        exit_reason=eod.OUT_OF_SESSION_REASON,
        only_out_of_session=True,
    )
    assert exits == []
    assert "AAPL" in det.positions


def test_shadow_oos_flatten_warns_when_no_price(monkeypatch):
    """Missing exit price → warning with reason=missing_exit_price_invalid_session."""
    from core.config import settings
    from paper import shadow_wallets as sw, eod

    monkeypatch.setattr(settings, "PAPER_SHADOW_WALLETS_ENABLED", True)
    sw.reset()
    det = sw._wallet(sw.WALLET_DETERMINISTIC)
    pos = det.enter_position("XYZ", 50.0, 100.0, "test", entry_score=70)
    pos.entry_time = "2026-06-13T04:08:59+00:00"
    det.positions["XYZ"] = pos

    exits, warnings = sw._eod_flatten_for(
        sw.WALLET_DETERMINISTIC,
        {"XYZ": {}},
        exit_reason=eod.OUT_OF_SESSION_REASON,
        only_out_of_session=True,
    )
    assert exits == []
    assert warnings
    assert warnings[0]["reason"] == "missing_exit_price_invalid_session"


# ── Section D — API surfaces session status + OOS annotations ───────────────

def test_api_wallets_includes_session_status(client):
    r = client.get("/api/paper/wallets")
    assert r.status_code == 200
    body = r.json()
    assert "market_session_open" in body
    assert "entries_allowed" in body
    assert "entry_block_reason" in body
    assert "out_of_session_open_positions" in body
    assert isinstance(body["market_session_open"], bool)
    assert isinstance(body["entries_allowed"], bool)


def test_api_positions_annotates_out_of_session(client, monkeypatch):
    """Position entered at 00:08 ET Saturday must have out_of_session=True."""
    from paper import simulator
    monkeypatch.setattr(simulator, "get_positions", lambda: [{
        "position_id": "oos1",
        "symbol": "TSLA",
        "entry_price": 300.0,
        "shares": 0.33,
        "cost_basis": 100.0,
        "current_price": 302.0,
        "unrealized_pnl": 0.66,
        "unrealized_pnl_percent": 0.66,
        "entry_time": "2026-06-13T04:08:59+00:00",
        "entry_catalyst_type": "test",
    }])
    r = client.get("/api/paper/wallets/positions?wallet_id=engine")
    assert r.status_code == 200
    body = r.json()
    pos = body["positions"][0]
    assert pos["out_of_session"] is True
    assert any(
        w["reason"] == "invalid_out_of_session_open_position" and w["symbol"] == "TSLA"
        for w in body["warnings"]
    )


def test_api_positions_no_oos_flag_for_regular_session(client, monkeypatch):
    """Position entered at 10:00 ET Friday must have out_of_session=False."""
    from paper import simulator
    monkeypatch.setattr(simulator, "get_positions", lambda: [{
        "position_id": "sess1",
        "symbol": "NVDA",
        "entry_price": 100.0,
        "shares": 1.0,
        "cost_basis": 100.0,
        "current_price": 101.0,
        "unrealized_pnl": 1.0,
        "unrealized_pnl_percent": 1.0,
        "entry_time": "2026-06-12T14:00:00+00:00",
        "entry_catalyst_type": "test",
    }])
    r = client.get("/api/paper/wallets/positions?wallet_id=engine")
    body = r.json()
    pos = body["positions"][0]
    assert pos["out_of_session"] is False
    assert not any(
        w.get("reason") == "invalid_out_of_session_open_position"
        for w in body["warnings"]
    )


# ── Section I — boundary invariants ─────────────────────────────────────────

def test_out_of_session_sweep_uses_stable_reason_string():
    """Simulator source must reference _eod_oos.OUT_OF_SESSION_REASON."""
    import paper.simulator as sim
    src = inspect.getsource(sim.run_tick)
    assert "_eod_oos.OUT_OF_SESSION_REASON" in src


def test_entries_blocked_called_before_all_entry_paths():
    """The _eod_block gate must appear before Path A (existing invariant still holds)."""
    import paper.simulator as sim
    src = inspect.getsource(sim.run_tick)
    assert "_eod_block, _eod_reason = _eod.entries_blocked()" in src
    assert "Path A: Catalyst entry (existing logic, unchanged)" in src
    assert "Path D: Market mover no-catalyst entry" in src


def test_no_broker_or_live_imports_in_new_modules():
    import ast as _ast
    forbidden = ("alpaca", "broker", "live_trading", "real_order", "place_order")
    import paper.eod, paper.session, paper.shadow_wallets, paper.simulator, api.paper
    for mod in (paper.eod, paper.session, paper.shadow_wallets, api.paper):
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
            assert needle not in joined, f"{mod.__name__} contains forbidden token {needle!r}"


def _read_frontend_page() -> str | None:
    for candidate in (
        "/opt/microtrading-app/frontend/dashboard/app/page.tsx",
        "/app/../frontend/dashboard/app/page.tsx",
    ):
        p = pathlib.Path(candidate)
        if p.exists():
            return p.read_text()
    return None


def test_dashboard_renders_market_closed_banner():
    page = _read_frontend_page()
    if page is None:
        pytest.skip("frontend page.tsx not accessible from this environment")
    assert "Market closed" in page
    assert "fake entries disabled" in page


def test_dashboard_renders_out_of_session_badge():
    page = _read_frontend_page()
    if page is None:
        pytest.skip("frontend page.tsx not accessible from this environment")
    assert "out_of_session" in page
    assert "OOS" in page
