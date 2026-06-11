"""
Phase S1-V1-H2 — Hardening tests:
  Part A: score_candidate / evaluate_momentum / evaluate_no_catalyst receive adjusted q
  Part B: missing/invalid TA vol rejects safely with clear reason
  Part C: Reddit Redis-loaded cache validation
  Part D: reset_simulator clears auto-resume telemetry

Fake-money simulation only. No broker, no live trading, no real orders.
No AI/LLM/Ollama. No V6 keys/auth/test endpoints.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


# ══════════════════════════════════════════════════════════════════════
# Part A — score_candidate receives adjusted q
# ══════════════════════════════════════════════════════════════════════

def test_score_candidate_called_with_adjusted_q_in_source():
    """
    score_candidate is called after _q_for_paths is built and receives it
    as the second positional argument — verified via AST so the assertion
    is tolerant of multiline call formatting and added kwargs.
    """
    import ast
    import inspect
    import paper.simulator as sim

    src = inspect.getsource(sim.run_tick)
    tree = ast.parse(src)

    # _q_for_paths must be assigned somewhere in the function.
    assigned_line: int | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "_q_for_paths":
                    assigned_line = node.lineno
                    break
            if assigned_line is not None:
                break
    assert assigned_line is not None, "_q_for_paths must be assigned in run_tick"

    # Find every score_candidate(...) call and assert one of them gets
    # _q_for_paths as the second positional argument and appears after the
    # assignment.
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Name) and fn.id == "score_candidate"):
            continue
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Name) \
                and node.args[1].id == "_q_for_paths" \
                and node.lineno > assigned_line:
            found = True
            break
    assert found, (
        "score_candidate must be called AFTER _q_for_paths is computed and "
        "must receive _q_for_paths as the second positional argument"
    )


def test_evaluate_momentum_called_with_q_for_paths():
    """evaluate_momentum_entry receives _q_for_paths in run_tick source."""
    import inspect
    import paper.simulator as sim

    src = inspect.getsource(sim.run_tick)
    assert "evaluate_momentum_entry(sym, _q_for_paths," in src


def test_evaluate_no_catalyst_called_with_q_for_paths():
    """evaluate_no_catalyst_entry receives _q_for_paths in run_tick source."""
    import inspect
    import paper.simulator as sim

    src = inspect.getsource(sim.run_tick)
    assert "evaluate_no_catalyst_entry(sym, _q_for_paths," in src


def test_raw_volume_ratio_preserved_in_candidate():
    """Candidate dict must still include raw volume_ratio even when TA vol is active."""
    import inspect
    import paper.simulator as sim

    src = inspect.getsource(sim.run_tick)
    # volume_ratio key must reference q (raw), not _q_for_paths
    assert '"volume_ratio": q.get("volume_ratio")' in src


# ══════════════════════════════════════════════════════════════════════
# Part B — missing/invalid TA vol rejects safely
# ══════════════════════════════════════════════════════════════════════

def test_ta_vol_missing_flag_set_when_inputs_missing():
    """_ta_vol_missing is computed in run_tick when TA vol config is on but inputs absent."""
    import inspect
    import paper.simulator as sim

    src = inspect.getsource(sim.run_tick)
    assert "_ta_vol_missing" in src
    assert "missing_time_adjusted_volume" in src


def test_missing_time_adjusted_volume_rejection_reason():
    """missing_time_adjusted_volume rejection is in the hard gate chain."""
    import inspect
    import paper.simulator as sim

    src = inspect.getsource(sim.run_tick)
    # Check that _ta_vol_missing leads to the rejection string
    assert '_ta_vol_missing' in src
    assert '"missing_time_adjusted_volume"' in src


def test_ta_vol_missing_rejects_before_raw_fallback():
    """_ta_vol_missing check must appear before raw volume fallback in source order."""
    import inspect
    import paper.simulator as sim

    src = inspect.getsource(sim.run_tick)
    pos_missing = src.index('"missing_time_adjusted_volume"')
    pos_raw = src.index('"PAPER_MIN_VOLUME_RATIO")')
    assert pos_missing < pos_raw, (
        "missing_time_adjusted_volume gate must be evaluated BEFORE raw volume gate "
        "to prevent silent fallback when TA vol config is enabled but inputs are missing"
    )


def test_time_adjusted_volume_ratio_none_when_prev_day_missing():
    """time_adjusted_volume_ratio() returns None when prev_day_volume is missing."""
    from paper.time_adjusted_volume import time_adjusted_volume_ratio

    result = time_adjusted_volume_ratio(
        day_volume=1_000_000,
        prev_day_volume=None,
        elapsed_ratio=0.5,
    )
    assert result is None


def test_time_adjusted_volume_ratio_none_when_day_volume_missing():
    """time_adjusted_volume_ratio() returns None when day_volume is missing."""
    from paper.time_adjusted_volume import time_adjusted_volume_ratio

    result = time_adjusted_volume_ratio(
        day_volume=None,
        prev_day_volume=2_000_000,
        elapsed_ratio=0.5,
    )
    assert result is None


def test_time_adjusted_volume_ratio_none_when_prev_zero():
    """time_adjusted_volume_ratio() returns None when prev_day_volume is 0."""
    from paper.time_adjusted_volume import time_adjusted_volume_ratio

    result = time_adjusted_volume_ratio(
        day_volume=500_000,
        prev_day_volume=0,
        elapsed_ratio=0.5,
    )
    assert result is None


def test_time_adjusted_volume_ratio_none_when_prev_negative():
    """time_adjusted_volume_ratio() returns None for negative prev_day_volume."""
    from paper.time_adjusted_volume import time_adjusted_volume_ratio

    result = time_adjusted_volume_ratio(
        day_volume=500_000,
        prev_day_volume=-100,
        elapsed_ratio=0.5,
    )
    assert result is None


def test_no_polygon_import_in_time_adjusted_volume_module():
    """time_adjusted_volume module must not import polygon (no new API calls)."""
    import inspect
    from paper import time_adjusted_volume

    src = inspect.getsource(time_adjusted_volume)
    assert "polygon" not in src.lower(), "time_adjusted_volume must not use Polygon"


# ══════════════════════════════════════════════════════════════════════
# Part C — Reddit Redis-loaded cache validation
# ══════════════════════════════════════════════════════════════════════

def test_is_valid_cached_row_rejects_company_name():
    """Rows with 'Company N' name are rejected by validation."""
    from intelligence.reddit import _is_valid_cached_row

    row = {"ticker": "NVDA", "name": "Company 0", "rank": 1, "mentions": 500}
    assert _is_valid_cached_row(row) is False


def test_is_valid_cached_row_rejects_company_name_variants():
    """'Company 1', 'Company 99' etc. are all rejected."""
    from intelligence.reddit import _is_valid_cached_row

    for i in range(5):
        row = {"ticker": "TSLA", "name": f"Company {i}", "rank": i + 1, "mentions": 100}
        assert _is_valid_cached_row(row) is False, f"Company {i} should be rejected"


def test_is_valid_cached_row_rejects_missing_ticker():
    """Rows with empty/missing ticker are rejected."""
    from intelligence.reddit import _is_valid_cached_row

    assert _is_valid_cached_row({"ticker": "", "name": "Real Inc", "rank": 1, "mentions": 100}) is False
    assert _is_valid_cached_row({"ticker": None, "name": "Real Inc", "rank": 1, "mentions": 100}) is False
    assert _is_valid_cached_row({"name": "Real Inc", "rank": 1, "mentions": 100}) is False


def test_is_valid_cached_row_rejects_missing_rank():
    """Rows without rank are rejected."""
    from intelligence.reddit import _is_valid_cached_row

    row = {"ticker": "NVDA", "name": "Nvidia", "mentions": 100}
    assert _is_valid_cached_row(row) is False


def test_is_valid_cached_row_rejects_missing_mentions():
    """Rows without mentions are rejected."""
    from intelligence.reddit import _is_valid_cached_row

    row = {"ticker": "NVDA", "name": "Nvidia", "rank": 1}
    assert _is_valid_cached_row(row) is False


def test_is_valid_cached_row_accepts_real_row():
    """Valid ApeWisdom rows pass validation."""
    from intelligence.reddit import _is_valid_cached_row

    row = {"ticker": "NVDA", "name": "Nvidia Corporation", "rank": 1, "mentions": 5000}
    assert _is_valid_cached_row(row) is True


def test_is_valid_cached_row_accepts_empty_name():
    """Rows with blank name (not 'Company N') are accepted."""
    from intelligence.reddit import _is_valid_cached_row

    row = {"ticker": "GME", "name": "", "rank": 5, "mentions": 300}
    assert _is_valid_cached_row(row) is True


def test_ensure_loaded_rejects_test_fixture_data():
    """ensure_loaded clears and re-fetches when Redis contains 'Company N' fixture data."""
    import intelligence.reddit as r

    orig_current = list(r._current)
    orig_fetched = r._fetched_at
    try:
        r._current = []
        r._fetched_at = 0.0

        fixture_rows = [
            {"ticker": "NVDA", "name": "Company 0", "rank": 1, "mentions": 100},
            {"ticker": "TSLA", "name": "Company 1", "rank": 2, "mentions": 90},
        ]
        fresh_rows = [
            {"ticker": "NVDA", "name": "Nvidia Corporation", "rank": 1, "mentions": 5000},
        ]

        async def run_test():
            with patch("intelligence.reddit._redis_load", new=AsyncMock(return_value=(fixture_rows, []))), \
                 patch("intelligence.reddit.fetch_and_refresh", new=AsyncMock(return_value={"ok": True, "results": fresh_rows})):
                await r.ensure_loaded()

        asyncio.run(run_test())
        # After ensure_loaded, _current should NOT contain the Company N fixtures
        for row in r._current:
            assert not (row.get("name") or "").startswith("Company "), (
                f"Fixture row {row} should have been rejected by ensure_loaded"
            )
    finally:
        r._current = orig_current
        r._fetched_at = orig_fetched


def test_ensure_loaded_accepts_valid_redis_rows():
    """ensure_loaded accepts valid ApeWisdom rows from Redis without re-fetching."""
    import intelligence.reddit as r

    orig_current = list(r._current)
    orig_fetched = r._fetched_at
    try:
        r._current = []
        r._fetched_at = 0.0

        valid_rows = [
            {"ticker": "NVDA", "name": "Nvidia Corporation", "rank": 1, "mentions": 5000},
            {"ticker": "TSLA", "name": "Tesla Inc", "rank": 2, "mentions": 3000},
        ]

        fetch_called = False

        async def run_test():
            nonlocal fetch_called
            with patch("intelligence.reddit._redis_load", new=AsyncMock(return_value=(valid_rows, []))), \
                 patch("intelligence.reddit.fetch_and_refresh") as mock_fetch:
                await r.ensure_loaded()
                fetch_called = mock_fetch.called

        asyncio.run(run_test())
        # Should NOT have called fetch_and_refresh since Redis had valid data
        assert not fetch_called, "ensure_loaded should not re-fetch when Redis has valid data"
        assert r._current == valid_rows
    finally:
        r._current = orig_current
        r._fetched_at = orig_fetched


# ══════════════════════════════════════════════════════════════════════
# Part D — reset_simulator clears auto-resume telemetry
# ══════════════════════════════════════════════════════════════════════

def test_reset_clears_auto_resume_fields():
    """reset_simulator must clear all auto-resume telemetry fields."""
    import paper.simulator as sim

    orig_state = {k: sim._state[k] for k in (
        "auto_resumed", "auto_resumed_at", "auto_resume_attempted",
        "auto_resume_source", "auto_resume_warning", "desired_running",
    )}
    try:
        # Simulate auto-resume having happened
        sim._state["auto_resumed"] = True
        sim._state["auto_resumed_at"] = "2026-06-10T12:00:00+00:00"
        sim._state["auto_resume_attempted"] = True
        sim._state["auto_resume_source"] = "redis"
        sim._state["auto_resume_warning"] = "some warning"
        sim._state["desired_running"] = True

        with patch("paper.simulator._save_state", new=AsyncMock()), \
             patch("paper.simulator.stop_simulator", new=AsyncMock()):
            asyncio.run(sim.reset_simulator())

        assert sim._state["auto_resumed"] is False
        assert sim._state["auto_resumed_at"] is None
        assert sim._state["auto_resume_attempted"] is False
        assert sim._state["auto_resume_source"] is None
        assert sim._state["auto_resume_warning"] is None
        # desired_running must be False after reset
        assert sim._state["desired_running"] is False
    finally:
        for k, v in orig_state.items():
            sim._state[k] = v


def test_reset_does_not_set_desired_running_true():
    """reset_simulator must never set desired_running=True."""
    import paper.simulator as sim

    orig_desired = sim._state["desired_running"]
    try:
        with patch("paper.simulator._save_state", new=AsyncMock()), \
             patch("paper.simulator.stop_simulator", new=AsyncMock()):
            asyncio.run(sim.reset_simulator())
        assert sim._state["desired_running"] is False
    finally:
        sim._state["desired_running"] = orig_desired
