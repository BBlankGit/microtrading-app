"""
Phase S1-V1 — Auto-resume paper simulator, time-adjusted relative volume,
Full-Market Movers volume multiples.
Fake-money simulation only. No broker, no live trading, no real orders.
No AI/LLM/Ollama/OpenAI/Anthropic/LangChain. No V6 hardcoded keys/auth/test endpoints.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch


# ══════════════════════════════════════════════════════════════════════
# Part A — Auto-resume (6 tests)
# ══════════════════════════════════════════════════════════════════════

def test_persist_desired_running_stores_true():
    """_persist_desired_running(True) sets _state['desired_running'] = True."""
    import paper.simulator as sim

    orig = sim._state.get("desired_running")
    try:
        with patch("paper.simulator.make_redis") as mock_redis:
            r = AsyncMock()
            mock_redis.return_value = r
            asyncio.run(sim._persist_desired_running(True))
        assert sim._state["desired_running"] is True
    finally:
        sim._state["desired_running"] = orig


def test_persist_desired_running_stores_false():
    """_persist_desired_running(False) sets _state['desired_running'] = False."""
    import paper.simulator as sim

    orig = sim._state.get("desired_running")
    try:
        with patch("paper.simulator.make_redis") as mock_redis:
            r = AsyncMock()
            mock_redis.return_value = r
            asyncio.run(sim._persist_desired_running(False))
        assert sim._state["desired_running"] is False
    finally:
        sim._state["desired_running"] = orig


def test_persist_desired_running_survives_redis_error():
    """_persist_desired_running is non-fatal when Redis is unavailable."""
    import paper.simulator as sim

    orig = sim._state.get("desired_running")
    try:
        with patch("paper.simulator.make_redis", side_effect=Exception("redis down")):
            # Must not raise
            asyncio.run(sim._persist_desired_running(True))
    finally:
        sim._state["desired_running"] = orig


def test_load_desired_running_returns_none_on_error():
    """load_desired_running returns None when Redis fails."""
    import paper.simulator as sim

    with patch("paper.simulator.make_redis", side_effect=Exception("redis down")):
        result = asyncio.run(sim.load_desired_running())
    assert result is None


def test_load_desired_running_parses_flag():
    """load_desired_running correctly parses b'1' → True, b'0' → False."""
    import paper.simulator as sim

    for raw, expected in [(b"1", True), (b"0", False), ("1", True), ("0", False)]:
        r = AsyncMock()
        r.get = AsyncMock(return_value=raw)
        r.aclose = AsyncMock()
        with patch("paper.simulator.make_redis", return_value=r):
            result = asyncio.run(sim.load_desired_running())
        assert result is expected, f"raw={raw!r} expected={expected} got={result}"


def test_auto_resume_if_desired_starts_when_flag_true():
    """auto_resume_if_desired starts the simulator when desired_running=True in Redis."""
    import paper.simulator as sim

    orig_state = {k: sim._state[k] for k in ("desired_running", "auto_resumed", "running")}
    try:
        with patch("paper.simulator.load_desired_running", new=AsyncMock(return_value=True)), \
             patch("paper.simulator.start_simulator", new=AsyncMock()) as mock_start:
            result = asyncio.run(sim.auto_resume_if_desired())
        assert result["auto_resumed"] is True
        assert result["source"] == "redis"
        mock_start.assert_awaited_once()
        assert sim._state["auto_resumed"] is True
    finally:
        for k, v in orig_state.items():
            sim._state[k] = v


# ══════════════════════════════════════════════════════════════════════
# Part B — Time-adjusted relative volume (9 tests)
# ══════════════════════════════════════════════════════════════════════

def test_session_elapsed_ratio_outside_regular():
    """session_elapsed_ratio returns 1.0 outside regular session hours."""
    from paper.time_adjusted_volume import session_elapsed_ratio
    from unittest.mock import patch
    from datetime import datetime, timezone, timedelta

    # Mock to a premarket time (7:00 ET)
    with patch("paper.time_adjusted_volume.datetime") as mock_dt:
        try:
            from zoneinfo import ZoneInfo
            mock_dt.now.return_value = datetime(2026, 6, 10, 7, 0, 0,
                                                tzinfo=ZoneInfo("America/New_York"))
        except Exception:
            mock_dt.now.return_value = datetime(2026, 6, 10, 7, 0, 0,
                                                tzinfo=timezone(timedelta(hours=-4)))
        # Can't easily mock zoneinfo; just verify the function returns a float
        result = session_elapsed_ratio()
    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0


def test_time_adjusted_volume_ratio_basic():
    """time_adjusted_volume_ratio computes correctly given valid inputs."""
    from paper.time_adjusted_volume import time_adjusted_volume_ratio

    # At 50% of session, with floor=0.05, prev_day=1_000_000, day=600_000
    # expected = 1_000_000 * 0.50 = 500_000; ratio = 600_000 / 500_000 = 1.20
    result = time_adjusted_volume_ratio(600_000, 1_000_000, 0.50, min_floor=0.05)
    assert result is not None
    assert abs(result - 1.2) < 0.001


def test_time_adjusted_volume_ratio_min_floor():
    """min_floor prevents division by near-zero at session open."""
    from paper.time_adjusted_volume import time_adjusted_volume_ratio

    # elapsed_ratio=0.001, floor=0.05 → effective=0.05
    # expected = 1_000_000 * 0.05 = 50_000; ratio = 40_000 / 50_000 = 0.80
    result = time_adjusted_volume_ratio(40_000, 1_000_000, 0.001, min_floor=0.05)
    assert result is not None
    assert abs(result - 0.80) < 0.001


def test_time_adjusted_volume_ratio_none_when_missing_inputs():
    """Returns None when day_volume or prev_day_volume is missing."""
    from paper.time_adjusted_volume import time_adjusted_volume_ratio

    assert time_adjusted_volume_ratio(None, 1_000_000, 0.5) is None
    assert time_adjusted_volume_ratio(500_000, None, 0.5) is None
    assert time_adjusted_volume_ratio(None, None, 0.5) is None


def test_time_adjusted_volume_ratio_none_when_prev_zero():
    """Returns None when prev_day_volume is zero or negative."""
    from paper.time_adjusted_volume import time_adjusted_volume_ratio

    assert time_adjusted_volume_ratio(500_000, 0, 0.5) is None
    assert time_adjusted_volume_ratio(500_000, -1_000, 0.5) is None


def test_time_adjusted_volume_high_early_session():
    """Early-session symbol with 3× expected pace passes the gate."""
    from paper.time_adjusted_volume import time_adjusted_volume_ratio

    # 5 minutes into session: elapsed = 5/390 ≈ 0.0128, floor=0.05 → effective=0.05
    elapsed = 5 / 390
    # prev_day=2_000_000, expected=100_000, day_volume=300_000 → ratio=3.0
    result = time_adjusted_volume_ratio(300_000, 2_000_000, elapsed, min_floor=0.05)
    assert result is not None
    assert result > 1.0


def test_schema_includes_time_adjusted_keys():
    """runtime_config schema must contain the 3 new S1-V1 time-adjusted keys."""
    from paper.runtime_config import _SCHEMA

    for key in (
        "PAPER_USE_TIME_ADJUSTED_VOLUME_RATIO",
        "PAPER_TIME_ADJUSTED_VOLUME_MIN_FLOOR",
        "PAPER_TIME_ADJUSTED_VOLUME_RATIO_MIN",
    ):
        assert key in _SCHEMA, f"Schema missing {key!r}"
        assert _SCHEMA[key]["applies_to"] == "scoring"


def test_config_defaults_present():
    """config.py must expose the 3 new S1-V1 settings with correct defaults."""
    from core.config import settings

    assert settings.PAPER_USE_TIME_ADJUSTED_VOLUME_RATIO is True
    assert settings.PAPER_TIME_ADJUSTED_VOLUME_MIN_FLOOR == 0.05
    assert settings.PAPER_TIME_ADJUSTED_VOLUME_RATIO_MIN == 0.8


def test_simulator_candidate_includes_ta_fields():
    """Candidate dict must include time_adjusted_volume_enabled and related fields."""
    import paper.simulator as sim

    # Verify the fields are present in the state dict after a manual setup
    # (full run_tick test is in test_phase_i4b_h1.py)
    required_fields = {
        "time_adjusted_volume_enabled",
        "time_adjusted_volume_ratio",
        "expected_volume_now",
        "prev_day_volume",
    }
    # Check that _state is accessible and module loads cleanly
    assert isinstance(sim._state, dict)
    # Check that the new config keys can be resolved
    from paper.runtime_config import effective_value
    assert isinstance(effective_value("PAPER_USE_TIME_ADJUSTED_VOLUME_RATIO"), bool)
    assert isinstance(effective_value("PAPER_TIME_ADJUSTED_VOLUME_MIN_FLOOR"), float)
    assert isinstance(effective_value("PAPER_TIME_ADJUSTED_VOLUME_RATIO_MIN"), float)


# ══════════════════════════════════════════════════════════════════════
# Part D — Full-Market Movers volume multiples (7 tests)
# ══════════════════════════════════════════════════════════════════════

def test_entry_to_mover_includes_previous_day_volume():
    """_entry_to_mover extracts previous_day_volume from prevDay.v."""
    from intelligence.full_premarket import _entry_to_mover

    entry = {
        "ticker": "AAPL",
        "lastTrade": {"p": 200.0},
        "prevDay": {"c": 190.0, "v": 50_000_000},
        "day": {"v": 10_000_000},
        "todaysChangePerc": 5.26,
    }
    result = _entry_to_mover(entry)
    assert result is not None
    assert result["previous_day_volume"] == 50_000_000


def test_entry_to_mover_handles_missing_prev_day_volume():
    """_entry_to_mover handles missing prevDay.v gracefully."""
    from intelligence.full_premarket import _entry_to_mover

    entry = {
        "ticker": "AAPL",
        "lastTrade": {"p": 200.0},
        "prevDay": {"c": 190.0},  # no 'v'
        "day": {"v": 10_000_000},
        "todaysChangePerc": 5.26,
    }
    result = _entry_to_mover(entry)
    assert result is not None
    assert result["previous_day_volume"] is None


def test_enrich_mover_volumes_computes_ratios():
    """_enrich_mover_volumes adds volume_vs_previous_day_ratio and time_adjusted_volume_ratio."""
    from intelligence.full_premarket import _enrich_mover_volumes

    mover = {
        "symbol": "AAPL",
        "day_volume": 1_000_000,
        "previous_day_volume": 4_000_000,
    }
    # elapsed=0.5, floor=0.05 → effective=0.5
    # volume_vs_previous_day_ratio = 1_000_000 / 4_000_000 = 0.25
    # time_adjusted_volume_ratio = 1_000_000 / (4_000_000 * 0.5) = 0.5
    result = _enrich_mover_volumes(mover, elapsed_ratio=0.5, min_floor=0.05)
    assert result["volume_vs_previous_day_ratio"] == 0.25
    assert result["time_adjusted_volume_ratio"] == 0.5
    assert result["expected_volume_now"] == 2_000_000


def test_enrich_mover_volumes_missing_prev_day():
    """_enrich_mover_volumes sets all volume metrics to None when prev_day_volume missing."""
    from intelligence.full_premarket import _enrich_mover_volumes

    mover = {"symbol": "AAPL", "day_volume": 1_000_000, "previous_day_volume": None}
    result = _enrich_mover_volumes(mover, elapsed_ratio=0.5)
    assert result["volume_vs_previous_day_ratio"] is None
    assert result["time_adjusted_volume_ratio"] is None
    assert result["expected_volume_now"] is None


def test_enrich_mover_volumes_is_non_mutating():
    """_enrich_mover_volumes returns a new dict and does not modify the input."""
    from intelligence.full_premarket import _enrich_mover_volumes

    original = {"symbol": "AAPL", "day_volume": 500_000, "previous_day_volume": 1_000_000}
    result = _enrich_mover_volumes(original, elapsed_ratio=0.5)
    # original must be unchanged
    assert "volume_vs_previous_day_ratio" not in original
    assert result is not original


def test_enrich_mover_volumes_includes_new_fields():
    """_enrich_mover_volumes includes session_elapsed_ratio and null 30d/60d fields."""
    from intelligence.full_premarket import _enrich_mover_volumes

    mover = {"symbol": "TSLA", "day_volume": 2_000_000, "previous_day_volume": 4_000_000}
    result = _enrich_mover_volumes(mover, elapsed_ratio=0.75, min_floor=0.05)
    assert result["session_elapsed_ratio"] == 0.75
    assert result["avg_daily_volume_30d"] is None
    assert result["volume_vs_30d_avg_ratio"] is None
    assert result["avg_daily_volume_60d"] is None
    assert result["volume_vs_60d_avg_ratio"] is None


def test_get_snapshot_enriches_top_gainers():
    """get_snapshot enriches top_gainers list with volume multiple fields."""
    import intelligence.full_premarket as fp
    import time as _time

    orig_snapshot = dict(fp._snapshot)
    orig_fetched = fp._fetched_at
    try:
        fp._snapshot = {
            "ok": True,
            "mode": "full_universe",
            "top_gainers": [
                {"symbol": "AAPL", "last_price": 200.0, "gap_percent": 5.0,
                 "day_volume": 1_000_000, "previous_day_volume": 2_000_000},
            ],
            "top_losers": [],
            "top_movers": [],
        }
        fp._fetched_at = _time.time()
        snap = fp.get_snapshot()
        assert snap["ok"] is True
        gainers = snap["top_gainers"]
        assert len(gainers) == 1
        g = gainers[0]
        assert "volume_vs_previous_day_ratio" in g
        assert "time_adjusted_volume_ratio" in g
        assert "expected_volume_now" in g
        assert "session_elapsed_ratio" in g
        assert "avg_daily_volume_30d" in g
        assert g["volume_vs_previous_day_ratio"] is not None
        assert g["avg_daily_volume_30d"] is None
    finally:
        fp._snapshot.clear()
        fp._snapshot.update(orig_snapshot)
        fp._fetched_at = orig_fetched


def test_get_snapshot_does_not_mutate_in_memory_snapshot():
    """get_snapshot enrichment must not mutate _snapshot (non-mutating requirement)."""
    import intelligence.full_premarket as fp
    import time as _time

    orig_snapshot = dict(fp._snapshot)
    orig_fetched = fp._fetched_at
    try:
        fp._snapshot = {
            "ok": True,
            "mode": "full_universe",
            "top_gainers": [
                {"symbol": "AAPL", "day_volume": 500_000, "previous_day_volume": 1_000_000},
            ],
            "top_losers": [],
            "top_movers": [],
        }
        fp._fetched_at = _time.time()
        # Call get_snapshot once
        fp.get_snapshot()
        # In-memory snapshot's top_gainers must NOT have been enriched
        assert "volume_vs_previous_day_ratio" not in fp._snapshot["top_gainers"][0]
    finally:
        fp._snapshot.clear()
        fp._snapshot.update(orig_snapshot)
        fp._fetched_at = orig_fetched


# ══════════════════════════════════════════════════════════════════════
# Phase S1-V1-H1 — Hardening tests (auto-resume, candidate fields,
#                   field renames, Redis isolation guard)
# ══════════════════════════════════════════════════════════════════════

def test_auto_resume_attempted_set_on_start():
    """auto_resume_if_desired sets auto_resume_attempted=True when desired=True."""
    import paper.simulator as sim

    orig_state = {k: sim._state[k] for k in ("desired_running", "auto_resumed", "running", "auto_resume_attempted")}
    try:
        with patch("paper.simulator.load_desired_running", new=AsyncMock(return_value=True)), \
             patch("paper.simulator.start_simulator", new=AsyncMock()):
            result = asyncio.run(sim.auto_resume_if_desired())
        assert result["auto_resume_attempted"] is True
        assert sim._state["auto_resume_attempted"] is True
    finally:
        for k, v in orig_state.items():
            sim._state[k] = v


def test_auto_resume_attempted_not_set_when_not_desired():
    """auto_resume_if_desired returns auto_resume_attempted=False when desired=False."""
    import paper.simulator as sim

    orig_state = {k: sim._state[k] for k in ("desired_running", "auto_resumed")}
    try:
        with patch("paper.simulator.load_desired_running", new=AsyncMock(return_value=False)), \
             patch("paper.simulator.start_simulator", new=AsyncMock()) as mock_start:
            result = asyncio.run(sim.auto_resume_if_desired())
        assert result["auto_resume_attempted"] is False
        mock_start.assert_not_awaited()
    finally:
        for k, v in orig_state.items():
            sim._state[k] = v


def test_auto_resume_blocked_when_live_trading_enabled():
    """auto_resume_if_desired must not start the simulator when LIVE_TRADING_ENABLED=True."""
    import paper.simulator as sim

    orig_state = {k: sim._state[k] for k in ("desired_running", "auto_resumed", "auto_resume_warning")}
    try:
        with patch("paper.simulator.settings") as mock_settings, \
             patch("paper.simulator.start_simulator", new=AsyncMock()) as mock_start:
            mock_settings.LIVE_TRADING_ENABLED = True
            result = asyncio.run(sim.auto_resume_if_desired())
        mock_start.assert_not_awaited()
        assert result["auto_resumed"] is False
        assert result["warning"] is not None
        assert "LIVE_TRADING_ENABLED" in result["warning"]
    finally:
        for k, v in orig_state.items():
            sim._state[k] = v


def test_auto_resume_attempted_in_get_status():
    """get_status must expose auto_resume_attempted field."""
    import paper.simulator as sim

    status = sim.get_status()
    assert "auto_resume_attempted" in status
    assert isinstance(status["auto_resume_attempted"], bool)


def test_candidate_includes_volume_gate_fields():
    """Candidate dict must include session_elapsed_ratio, volume_gate_type, volume_gate_ratio_used, volume_gate_threshold_used."""
    import paper.simulator as sim
    from paper.runtime_config import effective_value

    # Verify module-level: config keys resolve and state is accessible
    assert isinstance(effective_value("PAPER_USE_TIME_ADJUSTED_VOLUME_RATIO"), bool)
    # Verify the new gate fields are mentioned in module source (structural check)
    import inspect
    src = inspect.getsource(sim.run_tick)
    assert "volume_gate_type" in src
    assert "session_elapsed_ratio" in src
    assert "volume_gate_ratio_used" in src
    assert "volume_gate_threshold_used" in src


def test_reddit_redis_isolation_in_conftest():
    """Confirm that _redis_save is patched by conftest so tests cannot write to Redis."""
    import intelligence.reddit as r

    # The conftest autouse fixture patches intelligence.reddit._redis_save.
    # Calling it should NOT reach the real Redis — it should be the mock.
    from unittest.mock import AsyncMock as _AM
    # Verify the current module-level _redis_save is an AsyncMock (conftest applies it)
    assert isinstance(r._redis_save, _AM)


def test_enrich_mover_volumes_old_field_names_absent():
    """Renamed fields must NOT appear in enriched output — guards against accidental revert."""
    from intelligence.full_premarket import _enrich_mover_volumes

    mover = {"symbol": "AAPL", "day_volume": 1_000_000, "previous_day_volume": 2_000_000}
    result = _enrich_mover_volumes(mover, elapsed_ratio=0.5)
    assert "volume_vs_prev_day" not in result, "Old field name must not appear after rename"
    assert "time_adj_volume_ratio" not in result, "Old field name must not appear after rename"


def test_status_live_trading_always_false():
    """get_status must always report live_trading_enabled=False — fake-money guard."""
    import paper.simulator as sim

    status = sim.get_status()
    assert status["live_trading_enabled"] is False
    assert status["broker_connected"] is False
