"""
Tests for paper simulator analytics module.

No broker. No real orders. No real Polygon calls.
All tests are pure computation — no mocking required.
"""

import pytest
from paper.analytics import get_trade_analytics


# ── Helpers ───────────────────────────────────────────────────────────────────

def _status(**kw) -> dict:
    base = {
        "running": False,
        "last_tick_at": None,
        "daily_trade_count": 0,
        "max_trades_per_day": 20,
        "open_position_count": 0,
        "closed_trade_count": 0,
        "realized_pnl": 0,
        "unrealized_pnl": 0,
        "total_pnl": 0,
        "total_pnl_percent": 0.0,
    }
    return {**base, **kw}


def _trade(pnl: float, hold: float = 5.0, catalyst: str = "earnings") -> dict:
    return {
        "position_id": f"pos_{pnl}",
        "symbol": "AAPL",
        "entry_price": 100.0,
        "exit_price": 100.0 + pnl,
        "shares": 1.0,
        "pnl": pnl,
        "pnl_percent": pnl / 100.0,
        "exit_reason": "take_profit" if pnl > 0 else ("stop_loss" if pnl < 0 else "max_hold_time"),
        "entry_catalyst_type": catalyst,
        "hold_minutes": hold,
        "exit_time": "2026-01-01T10:00:00+00:00",
    }


def _candidate(
    sym: str = "AAPL",
    action: str | None = None,
    rejection_reason: str | None = None,
    eligible: bool = False,
    total_score: int = 50,
    score_threshold: int = 70,
    catalyst_type: str | None = "earnings",
) -> dict:
    return {
        "symbol": sym,
        "eligible": eligible,
        "action": action,
        "rejection_reason": rejection_reason,
        "total_score": total_score,
        "score_threshold": score_threshold,
        "catalyst_type": catalyst_type,
        "quality_tradable": True,
        "spread_percent": 0.1,
        "change_percent": 1.0,
        "catalyst_count": 1,
    }


def _universe(active_count: int = 10, errors: list | None = None) -> dict:
    errs = errors or []
    return {
        "active_symbols": [f"SYM{i}" for i in range(active_count)],
        "active_count": active_count,
        "max_symbols_per_tick": 50,
        "last_refreshed_at": "2026-01-01T09:00:00+00:00",
        "refresh_reason": "ttl",
        "errors": errs,
    }


# ── No-data baseline ──────────────────────────────────────────────────────────

def test_analytics_no_trades_returns_null_rates():
    result = get_trade_analytics(_status(), [], [], [], None)
    perf = result["performance"]
    assert perf["win_rate_percent"] is None
    assert perf["profit_factor"] is None
    assert perf["average_win"] is None
    assert perf["average_loss"] is None
    assert perf["average_hold_minutes"] is None


def test_analytics_no_candidates_returns_zero_funnel():
    result = get_trade_analytics(_status(), [], [], [], None)
    funnel = result["candidate_funnel"]
    assert funnel["total_candidates"] == 0
    assert funnel["eligible"] == 0
    assert funnel["entered"] == 0


def test_analytics_no_universe_returns_null_health():
    result = get_trade_analytics(_status(), [], [], [], None)
    uh = result["universe_health"]
    assert uh["active_count"] is None
    assert uh["refresh_reason"] == "not built"
    assert uh["error_count"] == 0


# ── Performance calculations ──────────────────────────────────────────────────

def test_analytics_win_rate_two_wins_one_loss():
    trades = [_trade(1.0), _trade(2.0), _trade(-0.5)]
    result = get_trade_analytics(_status(), [], trades, [], None)
    perf = result["performance"]
    assert perf["wins"] == 2
    assert perf["losses"] == 1
    assert perf["breakeven"] == 0
    assert abs(perf["win_rate_percent"] - 66.67) < 0.1


def test_analytics_win_rate_all_wins_no_losses():
    trades = [_trade(1.0), _trade(2.0)]
    result = get_trade_analytics(_status(), [], trades, [], None)
    perf = result["performance"]
    assert perf["win_rate_percent"] == 100.0
    assert perf["profit_factor"] is None  # no losses to form denominator


def test_analytics_profit_factor_two_to_one():
    trades = [_trade(10.0), _trade(-5.0)]
    result = get_trade_analytics(_status(), [], trades, [], None)
    perf = result["performance"]
    assert abs(perf["profit_factor"] - 2.0) < 0.01


def test_analytics_profit_factor_below_one():
    trades = [_trade(2.0), _trade(-10.0)]
    result = get_trade_analytics(_status(), [], trades, [], None)
    assert result["performance"]["profit_factor"] < 1.0


def test_analytics_average_hold_time():
    trades = [_trade(1.0, hold=5.0), _trade(-1.0, hold=10.0), _trade(0.5, hold=15.0)]
    result = get_trade_analytics(_status(), [], trades, [], None)
    assert abs(result["performance"]["average_hold_minutes"] - 10.0) < 0.01


def test_analytics_average_win_and_loss():
    trades = [_trade(4.0), _trade(6.0), _trade(-2.0), _trade(-8.0)]
    result = get_trade_analytics(_status(), [], trades, [], None)
    perf = result["performance"]
    assert abs(perf["average_win"] - 5.0) < 0.01
    assert abs(perf["average_loss"] - (-5.0)) < 0.01


def test_analytics_best_and_worst_trade():
    trades = [_trade(10.0), _trade(-3.0), _trade(1.5)]
    result = get_trade_analytics(_status(), [], trades, [], None)
    pnl = result["pnl"]
    assert pnl["best_trade_pnl"] == 10.0
    assert pnl["worst_trade_pnl"] == -3.0


def test_analytics_breakeven_trades():
    trades = [_trade(0.0), _trade(1.0), _trade(-1.0)]
    result = get_trade_analytics(_status(), [], trades, [], None)
    perf = result["performance"]
    assert perf["breakeven"] == 1
    assert perf["wins"] == 1
    assert perf["losses"] == 1


# ── Candidate funnel ──────────────────────────────────────────────────────────

def test_analytics_candidate_funnel_entered():
    candidates = [
        _candidate("AAPL", action="entered", eligible=True),
        _candidate("MSFT", action="score_rejected", rejection_reason="score 60 < threshold 70: foo"),
        _candidate("NVDA", action=None, rejection_reason="not tradable: low volume"),
        _candidate("TSLA", action="blocked: max positions reached"),
    ]
    result = get_trade_analytics(_status(), [], [], candidates, None)
    funnel = result["candidate_funnel"]
    assert funnel["total_candidates"] == 4
    assert funnel["entered"] == 1
    assert funnel["score_rejected"] == 1
    assert funnel["hard_rejected"] == 1
    assert funnel["blocked"] == 1
    assert funnel["eligible"] == 1  # only the entered one is eligible


def test_analytics_candidate_funnel_entry_failed():
    candidates = [
        _candidate("AAPL", action="entry_failed"),
        _candidate("MSFT", action="no_valid_price"),
    ]
    result = get_trade_analytics(_status(), [], [], candidates, None)
    assert result["candidate_funnel"]["entry_failed"] == 2


# ── Score distribution ────────────────────────────────────────────────────────

def test_analytics_score_distribution_buckets():
    candidates = [
        _candidate(total_score=85),   # 80+, above threshold
        _candidate(total_score=72),   # 70-79, above threshold
        _candidate(total_score=60),   # 50-69, below threshold
        _candidate(total_score=40),   # below 50
        _candidate(total_score=90),   # 80+, above threshold
    ]
    result = get_trade_analytics(_status(), [], [], candidates, None)
    dist = result["score_distribution"]
    assert dist["score_80_plus"] == 2
    assert dist["score_70_to_79"] == 1
    assert dist["score_50_to_69"] == 1
    assert dist["below_50"] == 1
    assert dist["above_threshold"] == 3  # 85, 72, 90 >= 70
    assert abs(dist["average_score"] - (85 + 72 + 60 + 40 + 90) / 5) < 0.1


# ── Catalyst breakdown ────────────────────────────────────────────────────────

def test_analytics_catalyst_breakdown_counts():
    candidates = [
        _candidate("A", catalyst_type="earnings"),
        _candidate("B", catalyst_type="earnings"),
        _candidate("C", catalyst_type="analyst_rating"),
        _candidate("D", catalyst_type=None),
    ]
    trades = [_trade(1.0, catalyst="earnings"), _trade(-0.5, catalyst="guidance")]
    result = get_trade_analytics(_status(), [], trades, candidates, None)
    by_type = {r["type"]: r["count"] for r in result["catalysts"]["by_type"]}
    assert by_type.get("earnings", 0) == 3   # 2 candidates + 1 trade
    assert by_type.get("analyst_rating", 0) == 1
    assert by_type.get("guidance", 0) == 1
    assert "None" not in by_type  # None catalyst_type not counted


# ── Rejection reasons ─────────────────────────────────────────────────────────

def test_analytics_top_rejection_reasons():
    candidates = [
        _candidate("A", rejection_reason="not tradable: low volume"),
        _candidate("B", rejection_reason="not tradable: low volume"),
        _candidate("C", rejection_reason="only generic_news catalysts"),
        _candidate("D", rejection_reason="not tradable: low volume"),
    ]
    result = get_trade_analytics(_status(), [], [], candidates, None)
    reasons = result["rejections"]["top_rejection_reasons"]
    top = reasons[0]
    assert top["reason"] == "not tradable: low volume"
    assert top["count"] == 3


# ── Universe health ───────────────────────────────────────────────────────────

def test_analytics_universe_health_with_errors():
    uni = _universe(active_count=48, errors=[
        {"symbol": "BAD1", "error": "404"},
        {"symbol": "BAD2", "error": "timeout"},
    ])
    result = get_trade_analytics(_status(), [], [], [], uni)
    uh = result["universe_health"]
    assert uh["active_count"] == 48
    assert uh["error_count"] == 2
    assert len(uh["top_errors"]) == 2
    assert uh["top_errors"][0]["symbol"] == "BAD1"


def test_analytics_universe_health_no_errors():
    result = get_trade_analytics(_status(), [], [], [], _universe(errors=[]))
    assert result["universe_health"]["error_count"] == 0
    assert result["universe_health"]["top_errors"] == []


# ── Market session ────────────────────────────────────────────────────────────

def test_analytics_market_session_has_required_fields():
    result = get_trade_analytics(_status(), [], [], [], None)
    ms = result["market_session"]
    assert "is_regular_session_now" in ms
    assert isinstance(ms["is_regular_session_now"], bool)
    assert ms["regular_open"] == "09:30"
    assert ms["regular_close"] == "16:00"
    assert "timezone" in ms
    assert "note" in ms


# ── Robustness: never raises ──────────────────────────────────────────────────

def test_analytics_never_raises_on_empty_inputs():
    result = get_trade_analytics({}, [], [], [], None)
    assert isinstance(result, dict)
    assert "error" not in result or result.get("session") is not None


def test_analytics_never_raises_on_null_fields_in_trades():
    bad_trades = [
        {"pnl": None, "hold_minutes": None, "entry_catalyst_type": None},
        {},
    ]
    result = get_trade_analytics(_status(), [], bad_trades, [], None)
    assert isinstance(result, dict)


def test_analytics_never_raises_on_null_fields_in_candidates():
    bad_candidates = [
        {"total_score": None, "action": None, "rejection_reason": None, "eligible": None},
        {},
    ]
    result = get_trade_analytics(_status(), [], [], bad_candidates, None)
    assert isinstance(result, dict)


# ── Config: SQ removed, XYZ present ──────────────────────────────────────────

def test_sq_not_in_paper_base_universe():
    from core.config import settings
    base = settings.paper_base_universe_list()
    assert "SQ" not in base, "SQ (old Block Inc ticker) must not be in PAPER_BASE_UNIVERSE"


def test_xyz_present_in_paper_base_universe():
    from core.config import settings
    base = settings.paper_base_universe_list()
    assert "XYZ" in base, "XYZ (Block Inc new ticker) must be in PAPER_BASE_UNIVERSE"


# ── API integration ───────────────────────────────────────────────────────────

_TOKEN = "test_admin_token_analytics"


@pytest.fixture(autouse=True)
def set_admin_token(monkeypatch):
    from core import config
    monkeypatch.setattr(config.settings, "ADMIN_API_TOKEN", _TOKEN)


def test_dashboard_includes_analytics_key(client):
    resp = client.get("/api/paper/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "analytics" in data
    analytics = data["analytics"]
    for key in ("session", "pnl", "performance", "candidate_funnel",
                "score_distribution", "rejections", "catalysts",
                "universe_health", "market_session"):
        assert key in analytics, f"Missing analytics key: {key}"


def test_analytics_endpoint_returns_all_top_level_keys(client):
    resp = client.get("/api/paper/analytics")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("session", "pnl", "performance", "candidate_funnel",
                "score_distribution", "rejections", "catalysts",
                "universe_health", "market_session"):
        assert key in data, f"Missing top-level key: {key}"


def test_analytics_endpoint_requires_no_token(client):
    resp = client.get("/api/paper/analytics")
    assert resp.status_code == 200
