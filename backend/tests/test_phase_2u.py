"""
Phase 2U tests — paper Redis state integrity and test isolation guard.

No broker. No live trading. No real orders. No real-money execution.
Research-only fake-money simulation.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def reset_simulator_state():
    """Reset global simulator state before and after each tick test."""
    import paper.simulator as sim
    sim._account.reset()
    sim._last_prices.clear()
    sim._state["last_candidates"] = []
    sim._state["last_tick_at"] = None
    sim._state["last_error"] = None
    yield
    sim._account.reset()
    sim._last_prices.clear()


# ── 1. Redis key uses namespace ───────────────────────────────────────────────

def test_simulator_redis_key_uses_namespace():
    """_REDIS_KEY in simulator must include the configured namespace, not bare 'paper:state'."""
    import paper.simulator as sim
    from core.config import settings

    expected = f"{settings.PAPER_STATE_REDIS_NAMESPACE}:state"
    assert sim._REDIS_KEY == expected
    assert sim._REDIS_KEY != "paper:state"


def test_session_restore_redis_key_uses_namespace():
    """_REDIS_KEY in session_restore must match the namespace-derived key."""
    import paper.session_restore as sr
    from core.config import settings

    expected = f"{settings.PAPER_STATE_REDIS_NAMESPACE}:state"
    assert sr._REDIS_KEY == expected
    assert sr._REDIS_KEY != "paper:state"


def test_simulator_and_session_restore_keys_match():
    """simulator._REDIS_KEY and session_restore._REDIS_KEY must be identical."""
    import paper.simulator as sim
    import paper.session_restore as sr

    assert sim._REDIS_KEY == sr._REDIS_KEY


# ── 2. conftest _save_state isolation ────────────────────────────────────────

def test_client_fixture_patches_save_state(client):
    """
    The client fixture must patch _save_state so tick-driven tests never write
    to the production Redis namespace.
    """
    import paper.simulator as sim

    # _save_state should be an AsyncMock (no real Redis call possible)
    assert isinstance(sim._save_state, AsyncMock)


# ── 3. try_redis_restore: entry_mode=None skipped ────────────────────────────

@pytest.mark.asyncio
async def test_try_redis_restore_skips_null_entry_mode():
    """
    Positions with entry_mode=None are dropped and recorded in restore_warnings.
    This is the fingerprint of test pollution (test code calls enter_position
    without passing entry_mode).
    """
    from paper.session_restore import try_redis_restore

    today = "2026-06-10"
    snapshot = {
        "daily_baseline_date": today,
        "cash": 800.0,
        "positions": {
            "TSLA": {
                "position_id": "abc12345",
                "symbol": "TSLA",
                "entry_price": 200.0,
                "shares": 1.0,
                "cost_basis": 200.0,
                "entry_time": "2026-06-10T14:00:00+00:00",
                "entry_catalyst_type": "earnings",
                "entry_score": None,
                "entry_mode": None,  # test pollution fingerprint
            }
        },
        "trades": [],
    }

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(snapshot))
    mock_redis.aclose = AsyncMock()

    with patch("paper.session_restore.make_redis", return_value=mock_redis), \
         patch("paper.session_restore._get_valid_journal_position_ids", new=AsyncMock(return_value={"abc12345"})):
        result = await try_redis_restore(today)

    assert result is not None
    assert "TSLA" not in result["positions"]
    assert any("orphaned_redis_position_skipped:TSLA:abc12345" in w for w in result["restore_warnings"])


# ── 4. try_redis_restore: orphaned position_id skipped ───────────────────────

@pytest.mark.asyncio
async def test_try_redis_restore_skips_orphaned_position_id():
    """
    Positions whose position_id has no matching journal entry row are dropped.
    This catches the case where Redis was written but the journal write failed
    (the pre-fix write-ordering bug).
    """
    from paper.session_restore import try_redis_restore

    today = "2026-06-10"
    orphan_pid = "dead0000"
    snapshot = {
        "daily_baseline_date": today,
        "cash": 750.0,
        "positions": {
            "NVDA": {
                "position_id": orphan_pid,
                "symbol": "NVDA",
                "entry_price": 900.0,
                "shares": 0.25,
                "cost_basis": 225.0,
                "entry_time": "2026-06-10T13:00:00+00:00",
                "entry_catalyst_type": "earnings",
                "entry_score": 80,
                "entry_mode": "catalyst",
            }
        },
        "trades": [],
    }

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(snapshot))
    mock_redis.aclose = AsyncMock()

    # Journal has NO entry for this position_id
    with patch("paper.session_restore.make_redis", return_value=mock_redis), \
         patch("paper.session_restore._get_valid_journal_position_ids",
               new=AsyncMock(return_value=set())):
        result = await try_redis_restore(today)

    assert result is not None
    assert "NVDA" not in result["positions"]
    assert any(f"orphaned_redis_position_skipped:NVDA:{orphan_pid}" in w
               for w in result["restore_warnings"])


# ── 5. try_redis_restore: valid position kept ─────────────────────────────────

@pytest.mark.asyncio
async def test_try_redis_restore_keeps_valid_position():
    """
    Positions with a non-None entry_mode and a matching journal entry are kept.
    """
    from paper.session_restore import try_redis_restore

    today = "2026-06-10"
    valid_pid = "cafe1234"
    snapshot = {
        "daily_baseline_date": today,
        "cash": 750.0,
        "positions": {
            "AMD": {
                "position_id": valid_pid,
                "symbol": "AMD",
                "entry_price": 120.0,
                "shares": 2.0,
                "cost_basis": 240.0,
                "entry_time": "2026-06-10T13:30:00+00:00",
                "entry_catalyst_type": "earnings",
                "entry_score": 85,
                "entry_mode": "catalyst",
            }
        },
        "trades": [],
    }

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(snapshot))
    mock_redis.aclose = AsyncMock()

    with patch("paper.session_restore.make_redis", return_value=mock_redis), \
         patch("paper.session_restore._get_valid_journal_position_ids",
               new=AsyncMock(return_value={valid_pid})):
        result = await try_redis_restore(today)

    assert result is not None
    assert "AMD" in result["positions"]
    assert result["restore_warnings"] == []


# ── 6. try_redis_restore: restore_warnings accumulate ────────────────────────

@pytest.mark.asyncio
async def test_try_redis_restore_accumulates_warnings_for_multiple_skipped():
    """Multiple skipped positions each emit one warning."""
    from paper.session_restore import try_redis_restore

    today = "2026-06-10"
    snapshot = {
        "daily_baseline_date": today,
        "cash": 1000.0,
        "positions": {
            "TSLA": {
                "position_id": "bad00001",
                "symbol": "TSLA",
                "entry_price": 200.0,
                "shares": 1.0,
                "cost_basis": 200.0,
                "entry_time": "2026-06-10T14:00:00+00:00",
                "entry_catalyst_type": "earnings",
                "entry_score": None,
                "entry_mode": None,  # null entry_mode → skip
            },
            "SMCI": {
                "position_id": "bad00002",
                "symbol": "SMCI",
                "entry_price": 50.0,
                "shares": 4.0,
                "cost_basis": 200.0,
                "entry_time": "2026-06-10T14:05:00+00:00",
                "entry_catalyst_type": "earnings",
                "entry_score": 72,
                "entry_mode": "catalyst",  # entry_mode ok but no journal row → skip
            },
        },
        "trades": [],
    }

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(snapshot))
    mock_redis.aclose = AsyncMock()

    with patch("paper.session_restore.make_redis", return_value=mock_redis), \
         patch("paper.session_restore._get_valid_journal_position_ids",
               new=AsyncMock(return_value=set())):
        result = await try_redis_restore(today)

    assert result is not None
    assert result["positions"] == {}
    assert len(result["restore_warnings"]) == 2


# ── 7. try_redis_restore: stale date returns None ────────────────────────────

@pytest.mark.asyncio
async def test_try_redis_restore_stale_date_returns_none():
    """Snapshot for a different day must be rejected outright."""
    from paper.session_restore import try_redis_restore

    snapshot = {
        "daily_baseline_date": "2026-06-09",  # yesterday
        "cash": 1000.0,
        "positions": {},
        "trades": [],
    }

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(snapshot))
    mock_redis.aclose = AsyncMock()

    with patch("paper.session_restore.make_redis", return_value=mock_redis):
        result = await try_redis_restore("2026-06-10")

    assert result is None


# ── 8. try_redis_restore: DB unavailable → fail-open (position not dropped) ──

@pytest.mark.asyncio
async def test_try_redis_restore_db_unavailable_keeps_positions_with_valid_entry_mode():
    """
    When the DB is unavailable (valid_pids=None), journal verification is skipped
    and positions with a non-None entry_mode are kept (fail-open on DB error).
    """
    from paper.session_restore import try_redis_restore

    today = "2026-06-10"
    snapshot = {
        "daily_baseline_date": today,
        "cash": 800.0,
        "positions": {
            "AAPL": {
                "position_id": "aa112233",
                "symbol": "AAPL",
                "entry_price": 190.0,
                "shares": 1.3,
                "cost_basis": 247.0,
                "entry_time": "2026-06-10T14:00:00+00:00",
                "entry_catalyst_type": "earnings",
                "entry_score": 78,
                "entry_mode": "catalyst",
            }
        },
        "trades": [],
    }

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(snapshot))
    mock_redis.aclose = AsyncMock()

    with patch("paper.session_restore.make_redis", return_value=mock_redis), \
         patch("paper.session_restore._get_valid_journal_position_ids",
               new=AsyncMock(return_value=None)):  # DB unavailable
        result = await try_redis_restore(today)

    assert result is not None
    assert "AAPL" in result["positions"]


# ── 9. Write ordering: journal before Redis ───────────────────────────────────

@pytest.mark.asyncio
async def test_write_ordering_journal_called_before_save_state(reset_simulator_state):
    """
    _persist_journal_tick must be called before _save_state in run_tick.
    Verified by recording call order via side_effect.
    """
    import paper.simulator as sim

    call_order: list[str] = []

    async def fake_journal(*_a, **_kw):
        call_order.append("journal")
        return {"ok": True}

    async def fake_save():
        call_order.append("redis")

    sym = "AAPL"
    sim._last_prices[sym] = 190.0

    with (
        patch("paper.simulator._persist_journal_tick", side_effect=fake_journal),
        patch("paper.simulator._save_state", side_effect=fake_save),
        patch("paper.simulator.get_active_paper_universe", return_value=[sym]),
        patch("paper.simulator.get_cached_universe", return_value=[sym]),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch("paper.simulator.evaluate_market_quality",
              return_value={"eligible": False, "reason": "test_skip", "ask": 190.0,
                            "bid": 189.9, "spread_pct": 0.05, "volume_ratio": 1.0,
                            "day_volume": 1_000_000, "price": 190.0}),
        patch("paper.simulator.evaluate_virtual_bracket_exit",
              return_value=None),
        patch("paper.simulator._daily_loss_guard", return_value={"triggered": False, "reason": None, "enabled": False}),
        patch("paper.simulator.get_intrabar_data", new=AsyncMock(return_value=[])),
        patch.object(sim.polygon_client, "get_ticker_snapshot",
                     new=AsyncMock(return_value={})),
        patch.object(sim.polygon_client, "get_previous_close",
                     new=AsyncMock(return_value={})),
        patch("paper.marketdata_adapter.try_cache_for_quality",
              new=AsyncMock(return_value=(None, {}))),
    ):
        await sim.run_tick()

    assert "journal" in call_order, "journal was not called"
    assert "redis" in call_order, "_save_state was not called"
    assert call_order.index("journal") < call_order.index("redis"), (
        "journal must be written before Redis snapshot"
    )


# ── 10. Namespace: legacy paper:state key is not the active key ───────────────

def test_legacy_paper_state_key_is_not_active():
    """
    The active Redis key must NOT be the pre-Phase-2U bare 'paper:state' key.
    If namespace is 'paper:prod' (default), the key is 'paper:prod:state', not 'paper:state'.
    This ensures any data left in 'paper:state' is silently ignored.
    """
    import paper.simulator as sim

    assert sim._REDIS_KEY != "paper:state", (
        "Active Redis key is still the legacy 'paper:state'. "
        "Deploy will re-expose old contaminated data."
    )
