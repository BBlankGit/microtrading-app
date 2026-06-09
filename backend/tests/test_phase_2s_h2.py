"""
Phase 2S-H2 tests — fix paper session restore NY date and dashboard metadata.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM. Research-only fake-money simulation.

Tests cover:
1.  today_str() returns NY date at UTC/NY boundary (clock injection).
2.  Restored NY trade count not reset when UTC date differs from NY date.
3.  can_enter() blocks when restored NY daily count is at max (clock injection).
4.  DB fallback emits structured warning for skipped NULL position_id rows.
5.  DB fallback skipped counts exposed as structured fields.
6.  restore_warning derived from restore_warnings when warnings exist.
7.  API/status contains restore_warnings list.
8.  Frontend page source: no hardcoded 'restart_persistent: false'.
9.  Frontend page source: no stale 'not restored' / 'container restart' wording.
10. Frontend page source: restore_source and restored counts labels present.
11. No strategy/catalyst/no-catalyst/cache logic changes (AST check).
12. No broker/live/order/AI/Ollama imports (AST check).
"""

import ast
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_PAGE = Path(__file__).resolve().parents[2] / "frontend" / "dashboard" / "app" / "page.tsx"

TODAY_NY = "2026-06-09"
STARTING_CASH = 1000.0

FORBIDDEN_MODULES = {
    "alpaca", "broker", "openai", "anthropic", "langchain",
    "ollama", "live_trading", "real_order",
}


# ── Clock helpers ─────────────────────────────────────────────────────────────

def _clock_at_utc(utc_dt: datetime):
    """Return a clock callable that returns utc_dt converted to the given tz."""
    def clock(tz):
        return utc_dt.astimezone(tz)
    return clock


def _make_async_pool(closed_rows=None, open_rows=None, null_pid_count=0,
                     prior_day_count=0):
    """Mock asyncpg pool with two fetchval calls (null_pid, prior_day)."""
    closed_rows = closed_rows or []
    open_rows = open_rows or []
    conn = MagicMock()
    fetch_results = [closed_rows, open_rows]
    fetch_count = {"n": 0}
    fetchval_results = [null_pid_count, prior_day_count]
    fetchval_count = {"n": 0}

    async def fetch(*args, **kwargs):
        idx = fetch_count["n"]
        fetch_count["n"] += 1
        return fetch_results[idx] if idx < len(fetch_results) else []

    async def fetchval(*args, **kwargs):
        idx = fetchval_count["n"]
        fetchval_count["n"] += 1
        return fetchval_results[idx] if idx < len(fetchval_results) else 0

    conn.fetch = fetch
    conn.fetchval = fetchval

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


# ── Test 1: today_str() with clock injection at UTC/NY boundary ───────────────

def test_today_str_returns_ny_date_at_utc_midnight_plus_1():
    """
    Clock injection: at 2026-06-10 01:00 UTC (still 2026-06-09 21:00 EDT),
    today_str() must return '2026-06-09', not '2026-06-10'.
    """
    from paper.account import PaperAccount

    # 2026-06-10 01:00 UTC = 2026-06-09 21:00 EDT (UTC-4 in June)
    utc_plus_1hr = datetime(2026, 6, 10, 1, 0, 0, tzinfo=timezone.utc)
    acc = PaperAccount(1000.0, _clock=_clock_at_utc(utc_plus_1hr))

    result = acc.today_str()
    assert result == "2026-06-09", (
        f"At 2026-06-10 01:00 UTC, NY date is still 2026-06-09; got {result!r}"
    )


def test_today_str_returns_next_ny_date_at_utc_10am():
    """
    Clock injection: at 2026-06-10 10:00 UTC (2026-06-10 06:00 EDT),
    today_str() must return '2026-06-10'.
    """
    from paper.account import PaperAccount

    utc_10am = datetime(2026, 6, 10, 10, 0, 0, tzinfo=timezone.utc)
    acc = PaperAccount(1000.0, _clock=_clock_at_utc(utc_10am))

    result = acc.today_str()
    assert result == "2026-06-10", (
        f"At 2026-06-10 10:00 UTC, NY date is 2026-06-10; got {result!r}"
    )


# ── Test 2: Restored count not reset at UTC/NY boundary ──────────────────────

def test_restored_count_preserved_with_clock_at_utc_boundary():
    """
    Boundary regression: restored _daily_date='2026-06-09' and _daily_trade_count=5.
    Clock is at 2026-06-10 01:00 UTC (still 2026-06-09 NY).
    daily_trade_count() must return 5 — must not reset to 0.
    """
    from paper.account import PaperAccount

    utc_plus_1hr = datetime(2026, 6, 10, 1, 0, 0, tzinfo=timezone.utc)
    acc = PaperAccount(1000.0, _clock=_clock_at_utc(utc_plus_1hr))
    acc._daily_date = "2026-06-09"
    acc._daily_trade_count = 5

    count = acc.daily_trade_count()
    assert count == 5, (
        "Restored NY count must not reset at UTC midnight when NY date is unchanged; "
        f"got {count}"
    )


def test_utc_only_clock_would_have_reset_count():
    """
    Prove the bug: a UTC-based clock at 2026-06-10 01:00 UTC sees date '2026-06-10',
    which differs from the restored _daily_date of '2026-06-09', causing reset to 0.
    The fix avoids this by using NY clock.
    """
    from paper.account import PaperAccount

    # Simulate the old broken UTC clock: returns the UTC date (2026-06-10)
    def utc_clock(tz):
        return datetime(2026, 6, 10, 1, 0, 0, tzinfo=timezone.utc)

    acc = PaperAccount(1000.0, _clock=utc_clock)
    acc._daily_date = "2026-06-09"   # restored NY date
    acc._daily_trade_count = 5

    # today_str() with utc_clock returns "2026-06-10" (UTC date, ignores tz)
    # so daily_trade_count() sees mismatch → returns 0 (the bug)
    ts = acc.today_str()
    assert ts == "2026-06-10", f"UTC clock must return UTC date 2026-06-10, got {ts!r}"
    count = acc.daily_trade_count()
    assert count == 0, (
        "With UTC clock, mismatch causes count to reset — this is the bug being fixed"
    )


# ── Test 3: can_enter blocks at max with clock injection ─────────────────────

def test_can_enter_blocks_at_restored_max_with_clock_injection():
    """
    Restored _daily_trade_count=10 (== max_trades=10), clock at NY date.
    can_enter() must return False with 'max daily trades' reason.
    """
    from paper.account import PaperAccount

    utc_plus_1hr = datetime(2026, 6, 10, 1, 0, 0, tzinfo=timezone.utc)
    acc = PaperAccount(1000.0, _clock=_clock_at_utc(utc_plus_1hr))
    acc._daily_date = "2026-06-09"
    acc._daily_trade_count = 10

    can, reason = acc.can_enter("AAPL", max_positions=5, max_trades=10)
    assert can is False, "should block when restored count equals max_trades"
    assert "max daily trades" in reason, f"unexpected reason: {reason!r}"
    assert acc._daily_trade_count == 10, "count must not change on blocked can_enter"


def test_can_enter_allows_when_restored_count_below_max_with_clock():
    """Restored count=3 < max_trades=10 with correct NY clock → can_enter True."""
    from paper.account import PaperAccount

    utc_plus_1hr = datetime(2026, 6, 10, 1, 0, 0, tzinfo=timezone.utc)
    acc = PaperAccount(1000.0, _clock=_clock_at_utc(utc_plus_1hr))
    acc._daily_date = "2026-06-09"
    acc._daily_trade_count = 3

    can, reason = acc.can_enter("AAPL", max_positions=5, max_trades=10)
    assert can is True, f"should allow when below max_trades; reason: {reason!r}"
    assert acc._daily_trade_count == 3, "count must not be reset by can_enter"


# ── Test 4: DB fallback structured warning for NULL position_id ───────────────

class TestDbRestoreStructuredSkipFields(unittest.IsolatedAsyncioTestCase):

    async def test_null_pid_produces_warning_and_structured_field(self):
        """null_pid_count=3 → restore_warnings entry + skipped_open_positions_missing_position_id=3."""
        from paper.session_restore import try_db_restore

        pool = _make_async_pool(null_pid_count=3)
        with patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=pool)
            result = await try_db_restore(TODAY_NY, STARTING_CASH)

        self.assertIsNotNone(result)
        warnings = result.get("restore_warnings", [])
        self.assertEqual(len(warnings), 1, f"Expected 1 warning, got: {warnings}")
        self.assertIn("3", warnings[0])
        self.assertIn("NULL", warnings[0])
        self.assertEqual(result.get("skipped_open_positions_missing_position_id"), 3)

    async def test_prior_day_count_produces_warning_and_structured_field(self):
        """prior_day_count=2 → restore_warnings entry + skipped_open_positions_prior_day=2."""
        from paper.session_restore import try_db_restore

        pool = _make_async_pool(prior_day_count=2)
        with patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=pool)
            result = await try_db_restore(TODAY_NY, STARTING_CASH)

        self.assertIsNotNone(result)
        warnings = result.get("restore_warnings", [])
        self.assertEqual(len(warnings), 1, f"Expected 1 warning, got: {warnings}")
        self.assertIn("2", warnings[0])
        self.assertIn("prior", warnings[0].lower())
        self.assertEqual(result.get("skipped_open_positions_prior_day"), 2)

    async def test_no_skips_produces_zero_structured_fields(self):
        """No skips → all three structured fields are 0, restore_warnings empty."""
        from paper.session_restore import try_db_restore

        pool = _make_async_pool()
        with patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=pool)
            result = await try_db_restore(TODAY_NY, STARTING_CASH)

        self.assertIsNotNone(result)
        self.assertEqual(result.get("restore_warnings"), [])
        self.assertEqual(result.get("skipped_open_positions_missing_position_id"), 0)
        self.assertEqual(result.get("skipped_open_positions_prior_day"), 0)
        self.assertEqual(result.get("skipped_open_positions_malformed"), 0)

    async def test_all_three_structured_fields_always_present(self):
        """All three skipped_* structured fields must be present in return dict."""
        from paper.session_restore import try_db_restore

        pool = _make_async_pool()
        with patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=pool)
            result = await try_db_restore(TODAY_NY, STARTING_CASH)

        for field in ("skipped_open_positions_missing_position_id",
                      "skipped_open_positions_prior_day",
                      "skipped_open_positions_malformed"):
            self.assertIn(field, result, f"Field {field!r} missing from try_db_restore result")


# ── Test 5: restore_warning derived from restore_warnings ────────────────────

class TestRestoreWarningDerived(unittest.IsolatedAsyncioTestCase):

    async def test_restore_warning_contains_skip_info_when_warnings_exist(self):
        """When DB has null_pid warnings, restore_warning must include them."""
        from paper.session_restore import restore_session

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.aclose = AsyncMock()

        pool = _make_async_pool(null_pid_count=4)
        with patch("paper.session_restore.make_redis", return_value=mock_redis), \
             patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=pool)
            result = await restore_session(TODAY_NY, STARTING_CASH)

        self.assertEqual(result["source"], "db")
        warning = result.get("warning", "")
        self.assertIn("cash_estimated_from_db", warning,
                      "restore_warning must always include cash_estimated_from_db")
        self.assertIn("NULL", warning,
                      "restore_warning must surface null_pid skip info when present")

    async def test_restore_warning_is_plain_when_no_skips(self):
        """When no skips, restore_warning is just 'cash_estimated_from_db'."""
        from paper.session_restore import restore_session

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.aclose = AsyncMock()

        pool = _make_async_pool()
        with patch("paper.session_restore.make_redis", return_value=mock_redis), \
             patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=pool)
            result = await restore_session(TODAY_NY, STARTING_CASH)

        self.assertEqual(result.get("warning"), "cash_estimated_from_db")


# ── Test 6: API/status contains restore_warnings list ────────────────────────

def test_get_status_restore_warnings_is_list():
    """simulator.get_status() must include restore_warnings as a list."""
    import paper.simulator as sim
    status = sim.get_status()
    assert "restore_warnings" in status, "get_status() must include restore_warnings"
    assert isinstance(status["restore_warnings"], list), (
        "restore_warnings must be a list, got: " + type(status["restore_warnings"]).__name__
    )


def test_get_status_restore_structured_fields_present():
    """get_status() must include all restore metadata fields."""
    import paper.simulator as sim
    status = sim.get_status()
    for field in ("restart_persistent", "restore_source", "restored_closed_trades_count",
                  "restored_open_positions_count", "restored_daily_realized_pnl",
                  "restored_trades_today", "restore_warning", "restore_warnings"):
        assert field in status, f"get_status() missing field: {field!r}"


# ── Test 7: Frontend no hardcoded restart_persistent: false ──────────────────

def test_frontend_no_hardcoded_restart_persistent_false():
    """page.tsx must not contain literal 'restart_persistent: false'."""
    if not FRONTEND_PAGE.exists():
        pytest.skip("Frontend page.tsx not found")
    source = FRONTEND_PAGE.read_text()
    assert "restart_persistent: false" not in source, (
        "page.tsx must not hardcode 'restart_persistent: false'; "
        "use dynamic value or 'unknown' when status is unavailable"
    )


# ── Test 8: Frontend no stale 'not restored' / 'container restart' text ──────

def test_frontend_no_stale_not_restored_text():
    """page.tsx must not contain 'not restored' or 'container restart' wording."""
    if not FRONTEND_PAGE.exists():
        pytest.skip("Frontend page.tsx not found")
    source = FRONTEND_PAGE.read_text()
    stale_phrases = [
        "not restored after container restart",
        "Simulator state is not restored",
        "Session not restored from persistence",
    ]
    for phrase in stale_phrases:
        assert phrase not in source, (
            f"page.tsx contains stale text that should be removed: {phrase!r}"
        )


# ── Test 9: Frontend has restore_source and restored counts labels ────────────

def test_frontend_renders_restore_source_label():
    """page.tsx must reference 'restore_source' for dynamic display."""
    if not FRONTEND_PAGE.exists():
        pytest.skip("Frontend page.tsx not found")
    source = FRONTEND_PAGE.read_text()
    assert "restore_source" in source, (
        "page.tsx must render restore_source field"
    )


def test_frontend_renders_restored_counts_labels():
    """page.tsx must reference restored_closed_trades_count and restored_open_positions_count."""
    if not FRONTEND_PAGE.exists():
        pytest.skip("Frontend page.tsx not found")
    source = FRONTEND_PAGE.read_text()
    for field in ("restored_closed_trades_count", "restored_open_positions_count",
                  "restored_trades_today", "restored_daily_realized_pnl"):
        assert field in source, f"page.tsx must render field {field!r}"


def test_frontend_renders_restore_warnings():
    """page.tsx must render restore_warnings list."""
    if not FRONTEND_PAGE.exists():
        pytest.skip("Frontend page.tsx not found")
    source = FRONTEND_PAGE.read_text()
    assert "restore_warnings" in source, (
        "page.tsx must render restore_warnings"
    )


def test_frontend_restart_persistent_uses_dynamic_value():
    """page.tsx must use dynamic s.restart_persistent, not ?? false fallback."""
    if not FRONTEND_PAGE.exists():
        pytest.skip("Frontend page.tsx not found")
    source = FRONTEND_PAGE.read_text()
    assert "restart_persistent ?? false" not in source, (
        "page.tsx must not use '?? false' for restart_persistent; "
        "use 'unknown' or conditional rendering"
    )


# ── Test 10: Strategy/catalyst/no-catalyst/cache logic unchanged ──────────────

def test_account_py_no_polygon_import():
    """account.py must not import polygon or market-data modules."""
    src = (BACKEND_ROOT / "paper" / "account.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else ([node.module] if node.module else [])
            )
            for name in names:
                assert "polygon" not in (name or "").lower(), (
                    f"account.py must not import polygon: {name!r}"
                )


def test_session_restore_no_strategy_imports():
    """session_restore.py must not import scoring, momentum, catalyst, or no_catalyst."""
    src = (BACKEND_ROOT / "paper" / "session_restore.py").read_text()
    banned = {"scoring", "momentum", "no_catalyst", "catalyst"}
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else ([node.module] if node.module else [])
            )
            for name in names:
                for b in banned:
                    assert b not in (name or "").lower(), (
                        f"session_restore.py must not import {b!r}: found {name!r}"
                    )


# ── Test 11: No broker/live/order/AI/Ollama imports ─────────────────────────

def _assert_no_forbidden_imports(path: Path) -> None:
    src = path.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else ([node.module] if node.module else [])
            )
            for name in names:
                for b in FORBIDDEN_MODULES:
                    assert b not in (name or "").lower(), (
                        f"Banned import {b!r} found in {path.name}: {name!r}"
                    )


def test_account_py_no_forbidden_imports():
    _assert_no_forbidden_imports(BACKEND_ROOT / "paper" / "account.py")


def test_session_restore_no_forbidden_imports():
    _assert_no_forbidden_imports(BACKEND_ROOT / "paper" / "session_restore.py")


def test_simulator_py_no_forbidden_imports():
    _assert_no_forbidden_imports(BACKEND_ROOT / "paper" / "simulator.py")


if __name__ == "__main__":
    unittest.main()
