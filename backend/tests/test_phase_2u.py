"""
Phase 2U tests — paper Redis state integrity and test isolation guard.

No broker. No live trading. No real orders. No real-money execution.
Research-only fake-money simulation.
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

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


def _make_v2_snapshot(today: str, positions: dict | None = None, trades: list | None = None) -> dict:
    """Build a minimal valid Phase-2U v2 snapshot dict."""
    return {
        "schema_version": 2,
        "namespace": "paper:prod",
        "saved_after_journal": True,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "tick_id": None,
        "daily_baseline_date": today,
        "cash": 1000.0,
        "starting_cash": 1000.0,
        "positions": positions or {},
        "trades": trades or [],
        "daily_trade_count": 0,
        "daily_date": today,
        "daily_start_equity": 1000.0,
        "last_prices": {},
    }


def _make_position(pid: str, entry_mode: str | None = "catalyst") -> dict:
    return {
        "position_id": pid,
        "symbol": "AMD",
        "entry_price": 120.0,
        "shares": 2.0,
        "cost_basis": 240.0,
        "entry_time": "2026-06-10T14:00:00+00:00",
        "entry_catalyst_type": "earnings",
        "entry_score": 80,
        "entry_mode": entry_mode,
    }


# ── 1. Namespaced key builder ─────────────────────────────────────────────────

def test_simulator_redis_key_format():
    """_REDIS_KEY must be {namespace}:state:v2."""
    import paper.simulator as sim
    from core.config import settings

    expected = f"{settings.PAPER_STATE_REDIS_NAMESPACE}:state:v2"
    assert sim._REDIS_KEY == expected


def test_session_restore_redis_key_format():
    """session_restore._REDIS_KEY must match simulator._REDIS_KEY."""
    import paper.simulator as sim
    import paper.session_restore as sr

    assert sr._REDIS_KEY == sim._REDIS_KEY
    assert sr._REDIS_KEY.endswith(":state:v2")


# ── 2. Legacy keys ignored ────────────────────────────────────────────────────

def test_legacy_bare_paper_state_key_not_active():
    """Active key must not be the legacy bare 'paper:state'."""
    import paper.simulator as sim

    assert sim._REDIS_KEY != "paper:state"


def test_legacy_v1_paper_prod_state_key_not_active():
    """Active key must not be the Phase-2U-v1 'paper:prod:state' (without :v2)."""
    import paper.simulator as sim
    from core.config import settings

    v1_key = f"{settings.PAPER_STATE_REDIS_NAMESPACE}:state"
    assert sim._REDIS_KEY != v1_key


# ── 3. Test namespace cannot overwrite production namespace ───────────────────

def test_test_namespace_key_differs_from_prod_key():
    """
    A test-specific namespace must produce a different key than the production
    namespace, so test Redis writes can never overwrite paper:prod:state:v2.
    """
    from core.config import settings

    prod_key = f"{settings.PAPER_STATE_REDIS_NAMESPACE}:state:v2"
    test_key = "paper:test:abc123:state:v2"
    assert prod_key != test_key


def test_client_fixture_patches_save_state(client):
    """
    conftest client fixture must patch _save_state to AsyncMock so tick-driven
    integration tests never write to the production Redis namespace.
    """
    import paper.simulator as sim

    assert isinstance(sim._save_state, AsyncMock)


# ── 4. Snapshot metadata written by _save_state ───────────────────────────────

@pytest.mark.asyncio
async def test_save_state_snapshot_contains_required_metadata():
    """
    _save_state must write schema_version=2, namespace, saved_after_journal=True,
    saved_at, and tick_id into the Redis snapshot.
    """
    import paper.simulator as sim

    captured: list[str] = []

    async def fake_set(key, value):
        captured.append(value)

    mock_redis = AsyncMock()
    mock_redis.set = fake_set
    mock_redis.aclose = AsyncMock()

    with patch("paper.simulator.make_redis", return_value=mock_redis):
        await sim._save_state(tick_id="abc-tick-001")

    assert len(captured) == 1
    data = json.loads(captured[0])
    assert data["schema_version"] == 2
    assert data["namespace"] == sim.settings.PAPER_STATE_REDIS_NAMESPACE
    assert data["saved_after_journal"] is True
    assert "saved_at" in data
    assert data["tick_id"] == "abc-tick-001"


# ── 5. Redis restore: saved_after_journal gate ────────────────────────────────

@pytest.mark.asyncio
async def test_try_redis_restore_rejects_snapshot_without_saved_after_journal():
    """
    Snapshots missing saved_after_journal (pre-Phase-2U) must be rejected.
    """
    from paper.session_restore import try_redis_restore

    today = "2026-06-10"
    old_snapshot = {
        "daily_baseline_date": today,
        "cash": 1000.0,
        "positions": {},
        "trades": [],
        # no saved_after_journal field
    }
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(old_snapshot))
    mock_redis.aclose = AsyncMock()

    with patch("paper.session_restore.make_redis", return_value=mock_redis):
        result = await try_redis_restore(today)

    assert result is None


@pytest.mark.asyncio
async def test_try_redis_restore_rejects_snapshot_with_saved_after_journal_false():
    """saved_after_journal=False must also be rejected."""
    from paper.session_restore import try_redis_restore

    today = "2026-06-10"
    snapshot = _make_v2_snapshot(today)
    snapshot["saved_after_journal"] = False

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(snapshot))
    mock_redis.aclose = AsyncMock()

    with patch("paper.session_restore.make_redis", return_value=mock_redis):
        result = await try_redis_restore(today)

    assert result is None


# ── 6. Redis restore: null / invalid entry_mode skipped ──────────────────────

@pytest.mark.asyncio
async def test_try_redis_restore_skips_null_entry_mode():
    """
    entry_mode=None emits missing_entry_mode_skipped and drops the position.
    Null entry_mode is the fingerprint of test pollution.
    """
    from paper.session_restore import try_redis_restore

    today = "2026-06-10"
    pid = "abc12345"
    pos = _make_position(pid, entry_mode=None)
    pos["symbol"] = "TSLA"
    snapshot = _make_v2_snapshot(today, positions={"TSLA": pos})

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(snapshot))
    mock_redis.aclose = AsyncMock()

    with patch("paper.session_restore.make_redis", return_value=mock_redis), \
         patch("paper.session_restore._get_valid_journal_position_ids",
               new=AsyncMock(return_value={pid})), \
         patch("paper.session_restore._get_closed_journal_position_ids",
               new=AsyncMock(return_value=set())):
        result = await try_redis_restore(today)

    assert result is not None
    assert "TSLA" not in result["positions"]
    assert any(f"missing_entry_mode_skipped:TSLA:{pid}" in w
               for w in result["restore_warnings"])


@pytest.mark.asyncio
async def test_try_redis_restore_skips_unknown_entry_mode():
    """entry_mode not in {catalyst, momentum, momentum_no_catalyst} is also skipped."""
    from paper.session_restore import try_redis_restore

    today = "2026-06-10"
    pid = "badbad01"
    pos = _make_position(pid, entry_mode="unknown_mode")
    pos["symbol"] = "NVDA"
    snapshot = _make_v2_snapshot(today, positions={"NVDA": pos})

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(snapshot))
    mock_redis.aclose = AsyncMock()

    with patch("paper.session_restore.make_redis", return_value=mock_redis), \
         patch("paper.session_restore._get_valid_journal_position_ids",
               new=AsyncMock(return_value={pid})), \
         patch("paper.session_restore._get_closed_journal_position_ids",
               new=AsyncMock(return_value=set())):
        result = await try_redis_restore(today)

    assert result is not None
    assert "NVDA" not in result["positions"]
    assert any("missing_entry_mode_skipped:NVDA:" in w for w in result["restore_warnings"])


# ── 7. Redis restore: orphaned position (no journal entry) skipped ────────────

@pytest.mark.asyncio
async def test_try_redis_restore_skips_orphaned_position_id():
    """
    Position whose position_id has no journal entry row emits
    orphaned_redis_position_skipped and is dropped.
    """
    from paper.session_restore import try_redis_restore

    today = "2026-06-10"
    pid = "dead0000"
    pos = _make_position(pid, entry_mode="catalyst")
    pos["symbol"] = "SMCI"
    snapshot = _make_v2_snapshot(today, positions={"SMCI": pos})

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(snapshot))
    mock_redis.aclose = AsyncMock()

    with patch("paper.session_restore.make_redis", return_value=mock_redis), \
         patch("paper.session_restore._get_valid_journal_position_ids",
               new=AsyncMock(return_value=set())), \
         patch("paper.session_restore._get_closed_journal_position_ids",
               new=AsyncMock(return_value=set())):
        result = await try_redis_restore(today)

    assert result is not None
    assert "SMCI" not in result["positions"]
    assert any(f"orphaned_redis_position_skipped:SMCI:{pid}" in w
               for w in result["restore_warnings"])


# ── 8. Redis restore: valid position with journal entry restores ──────────────

@pytest.mark.asyncio
async def test_try_redis_restore_keeps_valid_position():
    """
    Position with valid entry_mode, matching journal entry, and no exit row
    is kept and emits no warnings.
    """
    from paper.session_restore import try_redis_restore

    today = "2026-06-10"
    pid = "cafe1234"
    pos = _make_position(pid, entry_mode="catalyst")
    pos["symbol"] = "AMD"
    snapshot = _make_v2_snapshot(today, positions={"AMD": pos})

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(snapshot))
    mock_redis.aclose = AsyncMock()

    with patch("paper.session_restore.make_redis", return_value=mock_redis), \
         patch("paper.session_restore._get_valid_journal_position_ids",
               new=AsyncMock(return_value={pid})), \
         patch("paper.session_restore._get_closed_journal_position_ids",
               new=AsyncMock(return_value=set())):
        result = await try_redis_restore(today)

    assert result is not None
    assert "AMD" in result["positions"]
    assert result["restore_warnings"] == []


@pytest.mark.asyncio
async def test_try_redis_restore_accepts_momentum_entry_mode():
    """entry_mode='momentum' is in the allowed set and must be kept."""
    from paper.session_restore import try_redis_restore

    today = "2026-06-10"
    pid = "mom00001"
    pos = _make_position(pid, entry_mode="momentum")
    pos["symbol"] = "AAPL"
    snapshot = _make_v2_snapshot(today, positions={"AAPL": pos})

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(snapshot))
    mock_redis.aclose = AsyncMock()

    with patch("paper.session_restore.make_redis", return_value=mock_redis), \
         patch("paper.session_restore._get_valid_journal_position_ids",
               new=AsyncMock(return_value={pid})), \
         patch("paper.session_restore._get_closed_journal_position_ids",
               new=AsyncMock(return_value=set())):
        result = await try_redis_restore(today)

    assert result is not None
    assert "AAPL" in result["positions"]


# ── 9. Redis restore: position with exit row not restored ─────────────────────

@pytest.mark.asyncio
async def test_try_redis_restore_skips_position_with_exit_row():
    """
    A Redis position that has a matching journal exit row must be dropped with
    closed_position_skipped warning — it was already closed this session.
    """
    from paper.session_restore import try_redis_restore

    today = "2026-06-10"
    pid = "closed01"
    pos = _make_position(pid, entry_mode="catalyst")
    pos["symbol"] = "PLTR"
    snapshot = _make_v2_snapshot(today, positions={"PLTR": pos})

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(snapshot))
    mock_redis.aclose = AsyncMock()

    with patch("paper.session_restore.make_redis", return_value=mock_redis), \
         patch("paper.session_restore._get_valid_journal_position_ids",
               new=AsyncMock(return_value={pid})), \
         patch("paper.session_restore._get_closed_journal_position_ids",
               new=AsyncMock(return_value={pid})):  # exit row exists
        result = await try_redis_restore(today)

    assert result is not None
    assert "PLTR" not in result["positions"]
    assert any(f"closed_position_skipped:PLTR:{pid}" in w
               for w in result["restore_warnings"])


# ── 10. Redis restore: stale date returns None ────────────────────────────────

@pytest.mark.asyncio
async def test_try_redis_restore_stale_date_returns_none():
    """Snapshot for a different day must be rejected."""
    from paper.session_restore import try_redis_restore

    snapshot = _make_v2_snapshot("2026-06-09")

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(snapshot))
    mock_redis.aclose = AsyncMock()

    with patch("paper.session_restore.make_redis", return_value=mock_redis):
        result = await try_redis_restore("2026-06-10")

    assert result is None


# ── 11. Redis restore: DB unavailable → fail-open ────────────────────────────

@pytest.mark.asyncio
async def test_try_redis_restore_db_unavailable_keeps_valid_entry_mode_positions():
    """
    When DB is unavailable (valid_pids=None, closed_pids=None), journal/exit
    checks are skipped and positions with valid entry_mode are kept (fail-open).
    """
    from paper.session_restore import try_redis_restore

    today = "2026-06-10"
    pid = "aa112233"
    pos = _make_position(pid, entry_mode="catalyst")
    pos["symbol"] = "AAPL"
    snapshot = _make_v2_snapshot(today, positions={"AAPL": pos})

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(snapshot))
    mock_redis.aclose = AsyncMock()

    with patch("paper.session_restore.make_redis", return_value=mock_redis), \
         patch("paper.session_restore._get_valid_journal_position_ids",
               new=AsyncMock(return_value=None)), \
         patch("paper.session_restore._get_closed_journal_position_ids",
               new=AsyncMock(return_value=None)):
        result = await try_redis_restore(today)

    assert result is not None
    assert "AAPL" in result["positions"]


# ── 12. Write ordering: journal before Redis ──────────────────────────────────

@pytest.mark.asyncio
async def test_write_ordering_journal_called_before_save_state(reset_simulator_state):
    """
    _persist_journal_tick must be called before _save_state in run_tick.
    Also verifies _save_state receives the tick_id returned by the journal.
    """
    import paper.simulator as sim

    call_order: list[str] = []
    captured_tick_id: list[str | None] = []

    async def fake_journal(*_a, **_kw):
        call_order.append("journal")
        return {"ok": True, "tick_id": "test-tick-id-001"}

    async def fake_save(tick_id=None):
        call_order.append("redis")
        captured_tick_id.append(tick_id)

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
        patch("paper.simulator.evaluate_virtual_bracket_exit", return_value=None),
        patch("paper.simulator._daily_loss_guard",
              return_value={"triggered": False, "reason": None, "enabled": False}),
        patch("paper.simulator.get_intrabar_data", new=AsyncMock(return_value=[])),
        patch.object(sim.polygon_client, "get_ticker_snapshot",
                     new=AsyncMock(return_value={})),
        patch.object(sim.polygon_client, "get_previous_close",
                     new=AsyncMock(return_value={})),
        patch("paper.marketdata_adapter.try_cache_for_quality",
              new=AsyncMock(return_value=(None, {}))),
    ):
        await sim.run_tick()

    assert call_order.index("journal") < call_order.index("redis"), \
        "journal must be written before Redis snapshot"
    assert captured_tick_id == ["test-tick-id-001"], \
        "_save_state must receive tick_id from journal result"


# ── 13. Reset clears only paper state namespace ───────────────────────────────

@pytest.mark.asyncio
async def test_reset_simulator_writes_only_to_namespaced_key():
    """
    reset_simulator() must write state only to the paper:prod:state:v2 key,
    not to market:snapshot:*, runtime config, or any other namespace.
    """
    import paper.simulator as sim

    written_keys: list[str] = []

    async def fake_set(key, value):
        written_keys.append(key)

    mock_redis = AsyncMock()
    mock_redis.set = fake_set
    mock_redis.aclose = AsyncMock()

    with patch("paper.simulator.make_redis", return_value=mock_redis), \
         patch("paper.simulator.stop_simulator", new=AsyncMock()):
        await sim.reset_simulator()

    assert len(written_keys) == 1
    assert written_keys[0] == sim._REDIS_KEY
    assert "paper:prod:state:v2" in written_keys[0]
    assert "market" not in written_keys[0]


# ── 14. No strategy / catalyst / marketdata logic changes ─────────────────────

def test_session_restore_contains_no_scoring_imports():
    """
    session_restore must not import scoring, catalyst, momentum, or market-data
    modules. Its only job is restore, not strategy evaluation.
    """
    import paper.session_restore as mod
    import inspect

    src = inspect.getsource(mod)
    forbidden = [
        "from paper.scoring", "import scoring",
        "from paper.momentum", "import momentum",
        "from catalysts", "import catalysts",
        "evaluate_market_quality",
    ]
    for f in forbidden:
        assert f not in src, f"session_restore imports forbidden module: {f!r}"


# ── 15. No broker / live / real-order / AI / Ollama imports ──────────────────

def test_simulator_contains_no_broker_or_ai_imports():
    """
    simulator.py must not import broker, live-trading, real-order, or AI/LLM
    modules. Checks import statements only (not comments/docstrings).
    """
    import paper.simulator as mod
    import ast
    import inspect

    src = inspect.getsource(mod)
    tree = ast.parse(src)

    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.append(alias.name.lower())
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.append(node.module.lower())

    forbidden_modules = [
        "alpaca", "ibkr", "interactive_brokers",
        "openai", "anthropic", "langchain", "ollama",
        "torch", "tensorflow",
    ]
    for f in forbidden_modules:
        for imported in imported_names:
            assert f not in imported, \
                f"simulator.py imports forbidden module: {f!r} (found in {imported!r})"


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2U-H1 regression tests
# ═══════════════════════════════════════════════════════════════════════════════

# ── H1-1: missing / empty position_id is skipped ─────────────────────────────

@pytest.mark.asyncio
async def test_try_redis_restore_skips_empty_position_id():
    """
    A position with a valid entry_mode but empty/missing position_id must be
    dropped regardless of valid_pids, because journal checks are gated on pid.
    Warning must be missing_position_id_skipped:<symbol>.
    """
    from paper.session_restore import try_redis_restore

    today = "2026-06-10"
    # Position has valid entry_mode but no position_id
    pos_no_pid = {
        "position_id": "",  # empty — the bug case
        "symbol": "TSLA",
        "entry_price": 300.0,
        "shares": 0.8,
        "cost_basis": 240.0,
        "entry_time": "2026-06-10T14:00:00+00:00",
        "entry_catalyst_type": "earnings",
        "entry_score": 75,
        "entry_mode": "catalyst",
    }
    snapshot = _make_v2_snapshot(today, positions={"TSLA": pos_no_pid})

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(snapshot))
    mock_redis.aclose = AsyncMock()

    with patch("paper.session_restore.make_redis", return_value=mock_redis), \
         patch("paper.session_restore._get_valid_journal_position_ids",
               new=AsyncMock(return_value=set())), \
         patch("paper.session_restore._get_closed_journal_position_ids",
               new=AsyncMock(return_value=set())):
        result = await try_redis_restore(today)

    assert result is not None
    assert "TSLA" not in result["positions"]
    assert any("missing_position_id_skipped:TSLA" in w
               for w in result["restore_warnings"])


@pytest.mark.asyncio
async def test_try_redis_restore_skips_null_position_id():
    """position_id=None (not in dict at all) must also be skipped."""
    from paper.session_restore import try_redis_restore

    today = "2026-06-10"
    pos = {
        # "position_id" key absent entirely
        "symbol": "NVDA",
        "entry_price": 900.0,
        "shares": 0.25,
        "cost_basis": 225.0,
        "entry_time": "2026-06-10T13:00:00+00:00",
        "entry_catalyst_type": "earnings",
        "entry_score": 80,
        "entry_mode": "catalyst",
    }
    snapshot = _make_v2_snapshot(today, positions={"NVDA": pos})

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(snapshot))
    mock_redis.aclose = AsyncMock()

    with patch("paper.session_restore.make_redis", return_value=mock_redis), \
         patch("paper.session_restore._get_valid_journal_position_ids",
               new=AsyncMock(return_value=set())), \
         patch("paper.session_restore._get_closed_journal_position_ids",
               new=AsyncMock(return_value=set())):
        result = await try_redis_restore(today)

    assert result is not None
    assert "NVDA" not in result["positions"]
    assert any("missing_position_id_skipped:NVDA" in w
               for w in result["restore_warnings"])


# ── H1-2: Redis restore warnings propagate through restore_session ────────────

@pytest.mark.asyncio
async def test_restore_session_propagates_redis_restore_warnings():
    """
    restore_session() Redis branch must copy snapshot restore_warnings into
    result["restore_warnings"] and set result["warning"] when warnings exist.
    """
    from paper.session_restore import restore_session

    today = "2026-06-10"
    # Build a snapshot that already has a warning (as try_redis_restore would produce)
    snapshot = _make_v2_snapshot(today)
    snapshot["restore_warnings"] = ["orphaned_redis_position_skipped:TSLA:bad00001"]

    with patch("paper.session_restore.try_redis_restore",
               new=AsyncMock(return_value=snapshot)):
        result = await restore_session(today, 1000.0)

    assert result["source"] == "redis"
    assert "orphaned_redis_position_skipped:TSLA:bad00001" in result["restore_warnings"]
    assert result["warning"] is not None
    assert "redis_restore_warnings" in result["warning"]


@pytest.mark.asyncio
async def test_restore_session_no_warning_when_redis_restore_warnings_empty():
    """restore_session() must not set result["warning"] when there are no Redis warnings."""
    from paper.session_restore import restore_session

    today = "2026-06-10"
    snapshot = _make_v2_snapshot(today)
    snapshot["restore_warnings"] = []

    with patch("paper.session_restore.try_redis_restore",
               new=AsyncMock(return_value=snapshot)):
        result = await restore_session(today, 1000.0)

    assert result["source"] == "redis"
    assert result["restore_warnings"] == []
    assert result["warning"] is None


# ── H1-3: _save_state only called after journal ok:true ──────────────────────

@pytest.mark.asyncio
async def test_save_state_not_called_when_journal_raises(reset_simulator_state):
    """_persist_journal_tick raises → _save_state must NOT be called."""
    import paper.simulator as sim

    save_called = []

    async def fake_save(tick_id=None):
        save_called.append(True)

    sym = "AAPL"
    sim._last_prices[sym] = 190.0

    with (
        patch("paper.simulator._persist_journal_tick",
              side_effect=RuntimeError("journal exploded")),
        patch("paper.simulator._save_state", side_effect=fake_save),
        patch("paper.simulator.get_active_paper_universe", return_value=[sym]),
        patch("paper.simulator.get_cached_universe", return_value=[sym]),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch("paper.simulator.evaluate_market_quality",
              return_value={"eligible": False, "reason": "test_skip", "ask": 190.0,
                            "bid": 189.9, "spread_pct": 0.05, "volume_ratio": 1.0,
                            "day_volume": 1_000_000, "price": 190.0}),
        patch("paper.simulator.evaluate_virtual_bracket_exit", return_value=None),
        patch("paper.simulator._daily_loss_guard",
              return_value={"triggered": False, "reason": None, "enabled": False}),
        patch("paper.simulator.get_intrabar_data", new=AsyncMock(return_value=[])),
        patch.object(sim.polygon_client, "get_ticker_snapshot",
                     new=AsyncMock(return_value={})),
        patch.object(sim.polygon_client, "get_previous_close",
                     new=AsyncMock(return_value={})),
        patch("paper.marketdata_adapter.try_cache_for_quality",
              new=AsyncMock(return_value=(None, {}))),
    ):
        result = await sim.run_tick()

    assert not save_called, "_save_state must not be called when journal raises"
    assert result["journal"].get("ok") is not True


@pytest.mark.asyncio
async def test_save_state_not_called_when_journal_returns_ok_false(reset_simulator_state):
    """_persist_journal_tick returns {"ok": False} → _save_state must NOT be called."""
    import paper.simulator as sim

    save_called = []

    async def fake_save(tick_id=None):
        save_called.append(True)

    sym = "AAPL"
    sim._last_prices[sym] = 190.0

    with (
        patch("paper.simulator._persist_journal_tick",
              new=AsyncMock(return_value={"ok": False, "error": "db unavailable"})),
        patch("paper.simulator._save_state", side_effect=fake_save),
        patch("paper.simulator.get_active_paper_universe", return_value=[sym]),
        patch("paper.simulator.get_cached_universe", return_value=[sym]),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch("paper.simulator.evaluate_market_quality",
              return_value={"eligible": False, "reason": "test_skip", "ask": 190.0,
                            "bid": 189.9, "spread_pct": 0.05, "volume_ratio": 1.0,
                            "day_volume": 1_000_000, "price": 190.0}),
        patch("paper.simulator.evaluate_virtual_bracket_exit", return_value=None),
        patch("paper.simulator._daily_loss_guard",
              return_value={"triggered": False, "reason": None, "enabled": False}),
        patch("paper.simulator.get_intrabar_data", new=AsyncMock(return_value=[])),
        patch.object(sim.polygon_client, "get_ticker_snapshot",
                     new=AsyncMock(return_value={})),
        patch.object(sim.polygon_client, "get_previous_close",
                     new=AsyncMock(return_value={})),
        patch("paper.marketdata_adapter.try_cache_for_quality",
              new=AsyncMock(return_value=(None, {}))),
    ):
        result = await sim.run_tick()

    assert not save_called, "_save_state must not be called when journal returns ok:false"
    assert result["journal"].get("ok") is False


@pytest.mark.asyncio
async def test_save_state_called_when_journal_returns_ok_true(reset_simulator_state):
    """_persist_journal_tick returns {"ok": True} → _save_state MUST be called."""
    import paper.simulator as sim

    save_called = []

    async def fake_save(tick_id=None):
        save_called.append(tick_id)

    sym = "AAPL"
    sim._last_prices[sym] = 190.0

    with (
        patch("paper.simulator._persist_journal_tick",
              new=AsyncMock(return_value={"ok": True, "tick_id": "t-ok-001"})),
        patch("paper.simulator._save_state", side_effect=fake_save),
        patch("paper.simulator.get_active_paper_universe", return_value=[sym]),
        patch("paper.simulator.get_cached_universe", return_value=[sym]),
        patch("paper.simulator.collect_news_for_symbols",
              new=AsyncMock(return_value={"filter": {"accepted": []}})),
        patch("paper.simulator.evaluate_market_quality",
              return_value={"eligible": False, "reason": "test_skip", "ask": 190.0,
                            "bid": 189.9, "spread_pct": 0.05, "volume_ratio": 1.0,
                            "day_volume": 1_000_000, "price": 190.0}),
        patch("paper.simulator.evaluate_virtual_bracket_exit", return_value=None),
        patch("paper.simulator._daily_loss_guard",
              return_value={"triggered": False, "reason": None, "enabled": False}),
        patch("paper.simulator.get_intrabar_data", new=AsyncMock(return_value=[])),
        patch.object(sim.polygon_client, "get_ticker_snapshot",
                     new=AsyncMock(return_value={})),
        patch.object(sim.polygon_client, "get_previous_close",
                     new=AsyncMock(return_value={})),
        patch("paper.marketdata_adapter.try_cache_for_quality",
              new=AsyncMock(return_value=(None, {}))),
    ):
        result = await sim.run_tick()

    assert len(save_called) == 1, "_save_state must be called exactly once"
    assert save_called[0] == "t-ok-001", "_save_state must receive tick_id from journal"
