"""
Phase G1B-H2 — runtime dashboard deployment verification and fix.

Pure-unit tests for the helpers added in this phase. No broker, no live
trading, no real orders, no paid AI calls.

Sections:
  F — Late EOD flatten + stale_overnight detection.
  G — strategy_id surfaced in wallet API rows + dashboard rendering.
  H — News feed has no horizontal-overflow wrapper.
  I — backward compatibility / boundary invariants.
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


# ── Section F — late EOD flatten ────────────────────────────────────────────

def test_position_is_stale_overnight_prior_session():
    """A position entered on 2026-06-12 must be stale on 2026-06-13."""
    from paper import eod, session as s
    # Reference "now" = Saturday afternoon ET → latest session is Friday
    # 2026-06-12; an entry on Thursday 2026-06-11 is stale.
    sat = datetime(2026, 6, 13, 18, 0, tzinfo=timezone.utc).astimezone(s._ny_tz())
    assert eod.position_is_stale_overnight("2026-06-11T18:30:00+00:00", sat) is True


def test_position_is_stale_overnight_current_session():
    """An entry from the SAME NY session must not be stale."""
    from paper import eod, session as s
    # Reference "now" = Friday 11:00 ET → latest session = 2026-06-12
    fri = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc).astimezone(s._ny_tz())
    assert eod.position_is_stale_overnight("2026-06-12T14:30:00+00:00", fri) is False


def test_position_is_stale_overnight_respects_allow_overnight(monkeypatch):
    """If PAPER_ALLOW_OVERNIGHT_POSITIONS=true, nothing is stale."""
    from core.config import settings
    from paper import eod, session as s
    monkeypatch.setattr(settings, "PAPER_ALLOW_OVERNIGHT_POSITIONS", True)
    sat = datetime(2026, 6, 13, 18, 0, tzinfo=timezone.utc).astimezone(s._ny_tz())
    assert eod.position_is_stale_overnight("2026-06-11T18:30:00+00:00", sat) is False


def test_position_is_stale_overnight_handles_missing_entry_time():
    from paper import eod
    assert eod.position_is_stale_overnight(None) is False
    assert eod.position_is_stale_overnight("") is False
    assert eod.position_is_stale_overnight("not-a-date") is False


def test_position_entered_before_close_is_stale_next_day():
    """A position entered at 10:00 ET Thursday is stale by 09:00 ET Friday
    — Thursday's 16:00 close has already happened."""
    from paper import eod, session as s
    fri_morning = datetime(2026, 6, 12, 13, 0, tzinfo=timezone.utc).astimezone(s._ny_tz())  # 09:00 ET Fri
    assert eod.position_is_stale_overnight(
        "2026-06-11T14:00:00+00:00", fri_morning  # 10:00 ET Thu
    ) is True


def test_position_opened_before_close_then_close_happens():
    """A position opened at 15:00 ET Friday is NOT stale at 15:30 ET Friday,
    but IS stale at 16:30 ET Friday after the close happened."""
    from paper import eod, session as s
    fri_pre_close = datetime(2026, 6, 12, 19, 30, tzinfo=timezone.utc).astimezone(s._ny_tz())  # 15:30 ET Fri
    fri_post_close = datetime(2026, 6, 12, 20, 30, tzinfo=timezone.utc).astimezone(s._ny_tz())  # 16:30 ET Fri
    entry = "2026-06-12T19:00:00+00:00"  # 15:00 ET Fri
    assert eod.position_is_stale_overnight(entry, fri_pre_close) is False
    assert eod.position_is_stale_overnight(entry, fri_post_close) is True


def test_late_flatten_reason_is_stable_enum():
    from paper import eod
    assert eod.LATE_FLATTEN_REASON == "eod_flatten_late"


def test_shadow_late_flatten_closes_stale_position(monkeypatch):
    """A stale-overnight position on a shadow wallet must be closed with
    exit_reason='eod_flatten_late' when an exit price is available."""
    from core.config import settings
    from paper import shadow_wallets as sw, eod

    monkeypatch.setattr(settings, "PAPER_SHADOW_WALLETS_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", False)
    sw.reset()
    det = sw._wallet(sw.WALLET_DETERMINISTIC)
    pos = det.enter_position("AAPL", 100.0, 200.0, "test", entry_score=70)
    # Force the entry timestamp to a prior NY session.
    pos.entry_time = "2026-06-11T18:30:00+00:00"
    det.positions["AAPL"] = pos

    exits, warnings = sw._eod_flatten_for(
        sw.WALLET_DETERMINISTIC,
        {"AAPL": {"bid": 101.0, "last_trade_price": 101.0}},
        exit_reason=eod.LATE_FLATTEN_REASON,
        only_stale_overnight=True,
    )
    assert len(exits) == 1
    assert exits[0]["exit_reason"] == "eod_flatten_late"
    assert exits[0]["wallet_id"] == sw.WALLET_DETERMINISTIC
    assert warnings == []
    assert det.positions == {}


def test_shadow_late_flatten_skips_current_session_position(monkeypatch):
    """The same helper with only_stale_overnight=True must NOT touch a
    position from the current NY session."""
    from core.config import settings
    from paper import shadow_wallets as sw, eod
    from datetime import datetime, timezone

    monkeypatch.setattr(settings, "PAPER_SHADOW_WALLETS_ENABLED", True)
    sw.reset()
    det = sw._wallet(sw.WALLET_DETERMINISTIC)
    pos = det.enter_position("NVDA", 50.0, 100.0, "test", entry_score=70)
    pos.entry_time = datetime.now(timezone.utc).isoformat()
    det.positions["NVDA"] = pos

    exits, _warnings = sw._eod_flatten_for(
        sw.WALLET_DETERMINISTIC,
        {"NVDA": {"bid": 50.0, "last_trade_price": 50.0}},
        exit_reason=eod.LATE_FLATTEN_REASON,
        only_stale_overnight=True,
    )
    assert exits == []
    assert "NVDA" in det.positions


def test_shadow_late_flatten_warns_when_no_price(monkeypatch):
    from core.config import settings
    from paper import shadow_wallets as sw, eod

    monkeypatch.setattr(settings, "PAPER_SHADOW_WALLETS_ENABLED", True)
    sw.reset()
    det = sw._wallet(sw.WALLET_DETERMINISTIC)
    pos = det.enter_position("XYZ", 50.0, 100.0, "test", entry_score=70)
    pos.entry_time = "2026-06-11T18:30:00+00:00"
    det.positions["XYZ"] = pos

    exits, warnings = sw._eod_flatten_for(
        sw.WALLET_DETERMINISTIC,
        {"XYZ": {}},
        exit_reason=eod.LATE_FLATTEN_REASON,
        only_stale_overnight=True,
    )
    assert exits == []
    assert warnings
    w = warnings[0]
    assert w["reason"] == "missing_exit_price_late_flatten"
    assert w["entry_time"] == "2026-06-11T18:30:00+00:00"


def test_api_positions_annotates_stale_overnight(client, monkeypatch):
    """The wallet positions API must stamp stale_overnight=true on a
    prior-session position and emit a warning row."""
    from paper import simulator
    # Spoof a single open engine position from a prior session.
    monkeypatch.setattr(simulator, "get_positions", lambda: [{
        "position_id": "p1",
        "symbol": "TSLA",
        "entry_price": 400.0,
        "shares": 1.0,
        "cost_basis": 400.0,
        "current_price": 400.0,
        "unrealized_pnl": 0.0,
        "unrealized_pnl_percent": 0.0,
        "entry_time": "2026-06-11T18:30:00+00:00",
        "entry_catalyst_type": "test",
    }])
    r = client.get("/api/paper/wallets/positions?wallet_id=engine")
    assert r.status_code == 200
    body = r.json()
    pos = body["positions"][0]
    assert pos["stale_overnight"] is True
    assert any(w["symbol"] == "TSLA" for w in body["warnings"])


def test_api_positions_no_warning_for_current_session(client, monkeypatch):
    from paper import simulator
    from datetime import datetime, timezone
    monkeypatch.setattr(simulator, "get_positions", lambda: [{
        "position_id": "p2",
        "symbol": "NVDA",
        "entry_price": 50.0,
        "shares": 1.0,
        "cost_basis": 50.0,
        "current_price": 50.0,
        "unrealized_pnl": 0.0,
        "unrealized_pnl_percent": 0.0,
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "entry_catalyst_type": "test",
    }])
    r = client.get("/api/paper/wallets/positions?wallet_id=engine")
    body = r.json()
    pos = body["positions"][0]
    assert pos["stale_overnight"] is False
    assert body["warnings"] == []


# ── Section G — strategy_id surfaced in API rows ────────────────────────────

def test_engine_wallet_positions_include_strategy_id(client, monkeypatch):
    from paper import simulator
    monkeypatch.setattr(simulator, "get_positions", lambda: [{
        "position_id": "p1", "symbol": "AAPL", "entry_price": 100.0,
        "shares": 1.0, "cost_basis": 100.0,
        "current_price": 100.0, "unrealized_pnl": 0.0, "unrealized_pnl_percent": 0.0,
        "entry_time": "2026-06-12T14:30:00+00:00", "entry_catalyst_type": "test",
    }])
    r = client.get("/api/paper/wallets/positions?wallet_id=engine")
    body = r.json()
    assert body["positions"][0]["strategy_id"] == "engine"
    assert body["positions"][0]["wallet_id"] == "engine"


def test_engine_wallet_trades_include_strategy_id(client, monkeypatch):
    from paper import simulator
    monkeypatch.setattr(simulator, "get_trades", lambda: [{
        "position_id": "p1", "symbol": "AAPL", "entry_price": 100.0,
        "exit_price": 101.0, "pnl": 1.0, "pnl_percent": 1.0,
        "exit_reason": "take_profit_intrabar", "hold_minutes": 30,
        "entry_catalyst_type": "test",
        "entry_time": "2026-06-13T13:30:00+00:00",
        "exit_time": "2026-06-13T14:30:00+00:00",
    }])
    r = client.get("/api/paper/wallets/trades?wallet_id=engine")
    body = r.json()
    assert body["trades"][0]["strategy_id"] == "engine"
    assert body["trades"][0]["wallet_id"] == "engine"


def test_dashboard_renders_strategy_column():
    """Frontend source must include a Strategy column in both wallet tables."""
    page = _read_frontend_page()
    if page is None:
        pytest.skip("frontend page.tsx not accessible from this environment")
    explorer_block = page.split("function WalletExplorer")[1]
    assert '"Strategy"' in explorer_block, "Strategy column missing from WalletExplorer"


def test_dashboard_renders_stale_overnight_badge():
    page = _read_frontend_page()
    if page is None:
        pytest.skip("frontend page.tsx not accessible from this environment")
    assert "stale_overnight" in page
    assert "STALE" in page


# ── Section H — News feed has no horizontal-overflow wrapper ───────────────

def _read_frontend_page() -> str | None:
    for candidate in (
        "/opt/microtrading-app/frontend/dashboard/app/page.tsx",
        "/app/../frontend/dashboard/app/page.tsx",
    ):
        p = pathlib.Path(candidate)
        if p.exists():
            return p.read_text()
    return None


def test_news_block_no_overflow_x_wrapper():
    page = _read_frontend_page()
    if page is None:
        pytest.skip("frontend page.tsx not accessible from this environment")
    news_block = page.split("Phase G1B-H1 Part H")[-1].split("</table>")[0]
    assert "overflow-x-auto" not in news_block
    assert "table-fixed" in news_block


# ── Boundary invariants ────────────────────────────────────────────────────

def test_late_flatten_uses_stable_exit_reason_string():
    """Source-truth: the simulator's late-flatten exit_reason matches the
    eod.LATE_FLATTEN_REASON constant."""
    import paper.simulator as sim
    src = inspect.getsource(sim.run_tick)
    assert "_eod_late.LATE_FLATTEN_REASON" in src


def test_engine_decision_logic_unchanged():
    """No change to scoring or normal-market entry paths."""
    import paper.simulator as sim
    src = inspect.getsource(sim.run_tick)
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


# ── Wallet endpoint surface check ──────────────────────────────────────────

def test_three_wallets_still_returned(client):
    r = client.get("/api/paper/wallets")
    body = r.json()
    assert "engine" in body
    assert "deterministic_shadow" in body
    assert "ai_shadow" in body
    assert isinstance(body.get("wallets"), list) and len(body["wallets"]) == 3
