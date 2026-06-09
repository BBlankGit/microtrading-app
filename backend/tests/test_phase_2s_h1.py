"""
Phase 2S-H1 tests — Complete paper session restore reliability.

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM. Research-only fake-money simulation.

Tests cover:
1.  PaperAccount.today_str() uses New York timezone, not UTC.
2.  Restored NY daily trade count preserved when today_str() matches NY date.
3.  can_enter() does not reset restored NY daily count.
4.  DB fallback produces restore_warnings for skipped NULL position_id entries.
5.  restore_session result includes restore_warnings list (populated for DB).
6.  /api/paper/status (get_status) includes restore_warnings field.
7.  Frontend page.tsx no longer hardcodes restart_persistent: false.
8.  Frontend page.tsx includes restore_source and restore_warnings rendering.
9.  No strategy/catalyst/no-catalyst/cache logic changes (AST check).
10. No broker/live/order/AI/Ollama imports in restore modules (AST check).
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_open_row(symbol="MSFT", shares=2.0, cost_basis=200.0,
                   entry_price=100.0, position_id="def456"):
    now = datetime.now(timezone.utc)
    return {
        "symbol": symbol,
        "entry_price": entry_price,
        "shares": shares,
        "cost_basis": cost_basis,
        "catalyst_type": "momentum",
        "total_score": 80,
        "opened_at": now - timedelta(minutes=10),
        "entry_mode": "catalyst",
        "position_id": position_id,
    }


def _make_async_pool(closed_rows=None, open_rows=None, null_pid_count=0):
    """Mock asyncpg pool with fetchval for null_pid_count diagnostic."""
    closed_rows = closed_rows or []
    open_rows = open_rows or []
    conn = MagicMock()
    fetch_results = [closed_rows, open_rows]
    call_count = {"n": 0}

    async def fetch(*args, **kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        return fetch_results[idx] if idx < len(fetch_results) else []

    async def fetchval(*args, **kwargs):
        return null_pid_count

    conn.fetch = fetch
    conn.fetchval = fetchval

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


# ── Test 1: today_str() uses NY timezone ──────────────────────────────────────

def test_today_str_uses_ny_timezone():
    """PaperAccount.today_str() must return America/New_York date, not UTC."""
    from paper.account import PaperAccount
    from zoneinfo import ZoneInfo
    acc = PaperAccount(1000.0)
    expected_ny = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    assert acc.today_str() == expected_ny, (
        f"today_str() returned {acc.today_str()!r}, expected NY date {expected_ny!r}"
    )


# ── Test 2: NY daily count preserved when today_str() matches NY date ─────────

def test_restored_ny_daily_count_preserved_when_date_matches():
    """
    When _daily_date is set to the NY date and today_str() also returns the NY
    date, daily_trade_count() must return the restored value without resetting.

    This covers the UTC/NY boundary: old UTC-based today_str() could return
    a different date than the NY-based _daily_date, causing a spurious reset.
    """
    from paper.account import PaperAccount
    acc = PaperAccount(1000.0)
    ny_date = TODAY_NY
    acc._daily_date = ny_date
    acc._daily_trade_count = 7

    # Simulate today_str() returning same NY date (normal operation after fix)
    with patch.object(acc, "today_str", return_value=ny_date):
        count = acc.daily_trade_count()
        assert count == 7, "Count must be preserved when today_str() == _daily_date"


def test_daily_count_resets_when_date_changes():
    """daily_trade_count() resets to 0 when today_str() returns a different date."""
    from paper.account import PaperAccount
    acc = PaperAccount(1000.0)
    acc._daily_date = "2026-06-09"
    acc._daily_trade_count = 7

    # tomorrow — date has rolled over
    with patch.object(acc, "today_str", return_value="2026-06-10"):
        count = acc.daily_trade_count()
        assert count == 0, "Count must reset when date changes"


def test_utc_ny_boundary_scenario():
    """
    Regression: at 00:30 UTC on 2026-06-10, UTC date is '2026-06-10' but
    NY date is still '2026-06-09'. The old UTC-based today_str() would have
    reset the trade count even though the NY trading day had not changed.

    After fix: today_str() returns NY date, so count is preserved.
    """
    from paper.account import PaperAccount
    acc = PaperAccount(1000.0)
    ny_date = "2026-06-09"
    acc._daily_date = ny_date
    acc._daily_trade_count = 5

    # Patch today_str to return the NY date (what the fix produces)
    with patch.object(acc, "today_str", return_value=ny_date):
        count = acc.daily_trade_count()
        assert count == 5, (
            "NY date fix: trade count preserved at UTC midnight boundary"
        )

    # Prove what the OLD behavior would have done: UTC date = next day → reset
    with patch.object(acc, "today_str", return_value="2026-06-10"):
        count = acc.daily_trade_count()
        assert count == 0, (
            "Old UTC behavior: count would have reset at UTC midnight, "
            "even though the NY trading day had not changed"
        )


# ── Test 3: can_enter() does not reset restored NY daily count ────────────────

def test_can_enter_does_not_reset_restored_ny_count():
    """
    After restore sets _daily_date=ny_today and _daily_trade_count=N,
    can_enter() must not reset the count when today_str() returns ny_today.
    """
    from paper.account import PaperAccount
    acc = PaperAccount(1000.0)
    ny_date = TODAY_NY
    acc._daily_date = ny_date
    acc._daily_trade_count = 3

    with patch.object(acc, "today_str", return_value=ny_date):
        can, reason = acc.can_enter("AAPL", max_positions=5, max_trades=10)
        assert can is True, f"can_enter should allow entry; reason: {reason}"
        # Count should NOT have been reset
        assert acc._daily_trade_count == 3, (
            "can_enter must not reset _daily_trade_count when NY date matches"
        )


def test_can_enter_blocks_at_restored_limit():
    """If restored daily count is already at max_trades, can_enter must block."""
    from paper.account import PaperAccount
    acc = PaperAccount(1000.0)
    ny_date = TODAY_NY
    acc._daily_date = ny_date
    acc._daily_trade_count = 5  # at the limit

    with patch.object(acc, "today_str", return_value=ny_date):
        can, reason = acc.can_enter("AAPL", max_positions=5, max_trades=5)
        assert can is False
        assert "max daily trades" in reason


# ── Test 4: DB fallback warning for NULL position_id open entries ─────────────

class TestDbRestoreNullPidWarning(unittest.IsolatedAsyncioTestCase):

    async def test_null_pid_open_entries_produce_restore_warnings(self):
        """
        When null_pid_count > 0, try_db_restore must include a warning in
        restore_warnings describing how many open entries were skipped.
        """
        from paper.session_restore import try_db_restore

        pool = _make_async_pool(closed_rows=[], open_rows=[], null_pid_count=3)
        with patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=pool)
            result = await try_db_restore(TODAY_NY, STARTING_CASH)

        self.assertIsNotNone(result)
        warnings = result.get("restore_warnings", [])
        self.assertEqual(len(warnings), 1, f"Expected 1 warning, got: {warnings}")
        self.assertIn("3", warnings[0])
        self.assertIn("NULL", warnings[0])

    async def test_no_null_pid_entries_no_warning(self):
        """When null_pid_count is 0, restore_warnings must be an empty list."""
        from paper.session_restore import try_db_restore

        pool = _make_async_pool(closed_rows=[], open_rows=[], null_pid_count=0)
        with patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=pool)
            result = await try_db_restore(TODAY_NY, STARTING_CASH)

        self.assertIsNotNone(result)
        warnings = result.get("restore_warnings", [])
        self.assertEqual(warnings, [], f"Expected no warnings, got: {warnings}")

    async def test_restore_warnings_key_always_present_in_db_result(self):
        """try_db_restore must always return restore_warnings key (list)."""
        from paper.session_restore import try_db_restore

        pool = _make_async_pool()
        with patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=pool)
            result = await try_db_restore(TODAY_NY, STARTING_CASH)

        self.assertIn("restore_warnings", result)
        self.assertIsInstance(result["restore_warnings"], list)


# ── Test 5: restore_session propagates restore_warnings ──────────────────────

class TestRestoreSessionWarnings(unittest.IsolatedAsyncioTestCase):

    async def test_restore_session_has_restore_warnings_key(self):
        """restore_session result must always include restore_warnings list."""
        from paper.session_restore import restore_session

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # no Redis snapshot
        mock_redis.aclose = AsyncMock()

        with patch("paper.session_restore.make_redis", return_value=mock_redis), \
             patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=None)  # no DB
            result = await restore_session(TODAY_NY, STARTING_CASH)

        self.assertIn("restore_warnings", result)
        self.assertIsInstance(result["restore_warnings"], list)

    async def test_restore_session_db_propagates_null_pid_warnings(self):
        """restore_session must propagate restore_warnings from DB fallback."""
        from paper.session_restore import restore_session

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.aclose = AsyncMock()

        pool = _make_async_pool(null_pid_count=2)
        with patch("paper.session_restore.make_redis", return_value=mock_redis), \
             patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=pool)
            result = await restore_session(TODAY_NY, STARTING_CASH)

        self.assertEqual(result["source"], "db")
        warnings = result.get("restore_warnings", [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("2", warnings[0])

    async def test_restore_session_redis_has_empty_restore_warnings(self):
        """Redis restore path returns empty restore_warnings (no DB diagnostics)."""
        import json
        from paper.session_restore import restore_session

        snapshot = json.dumps({
            "cash": 950.0, "starting_cash": STARTING_CASH,
            "positions": {}, "trades": [],
            "daily_trade_count": 0, "daily_date": TODAY_NY,
            "daily_baseline_date": TODAY_NY,
            "daily_start_equity": STARTING_CASH,
            "last_prices": {},
        })
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=snapshot)
        mock_redis.aclose = AsyncMock()

        with patch("paper.session_restore.make_redis", return_value=mock_redis):
            result = await restore_session(TODAY_NY, STARTING_CASH)

        self.assertEqual(result["source"], "redis")
        self.assertEqual(result.get("restore_warnings", []), [])


# ── Test 6: get_status() includes restore_warnings ───────────────────────────

def test_get_status_includes_restore_warnings():
    """simulator.get_status() must include restore_warnings list."""
    import paper.simulator as sim
    status = sim.get_status()
    assert "restore_warnings" in status, "get_status() must include restore_warnings"
    assert isinstance(status["restore_warnings"], list), (
        "restore_warnings must be a list"
    )


# ── Test 7: Frontend no longer hardcodes restart_persistent: false ───────────

def test_frontend_does_not_hardcode_restart_persistent_false():
    """page.tsx must not contain the literal string 'restart_persistent: false'."""
    if not FRONTEND_PAGE.exists():
        pytest.skip("Frontend page.tsx not found")
    source = FRONTEND_PAGE.read_text()
    assert "restart_persistent: false" not in source, (
        "page.tsx must not hardcode 'restart_persistent: false'; "
        "use dynamic value from status API"
    )


# ── Test 8: Frontend renders restore_source and restore_warnings ─────────────

def test_frontend_renders_restore_source():
    """page.tsx must reference restore_source for dynamic restore display."""
    if not FRONTEND_PAGE.exists():
        pytest.skip("Frontend page.tsx not found")
    source = FRONTEND_PAGE.read_text()
    assert "restore_source" in source, (
        "page.tsx must reference restore_source to show dynamic restore status"
    )


def test_frontend_renders_restore_warnings():
    """page.tsx must reference restore_warnings for dynamic warning display."""
    if not FRONTEND_PAGE.exists():
        pytest.skip("Frontend page.tsx not found")
    source = FRONTEND_PAGE.read_text()
    assert "restore_warnings" in source, (
        "page.tsx must reference restore_warnings to display restore diagnostics"
    )


def test_frontend_paperstatus_type_has_restore_fields():
    """PaperStatus interface in page.tsx must declare restore metadata fields."""
    if not FRONTEND_PAGE.exists():
        pytest.skip("Frontend page.tsx not found")
    source = FRONTEND_PAGE.read_text()
    required = [
        "restart_persistent",
        "restore_source",
        "restored_closed_trades_count",
        "restore_warnings",
    ]
    for field in required:
        assert field in source, (
            f"PaperStatus type in page.tsx must include field '{field}'"
        )


# ── Test 9: No strategy/catalyst/cache logic changes ─────────────────────────

def test_account_py_does_not_import_polygon():
    """account.py must not import polygon (no market-data side effects)."""
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


def test_session_restore_does_not_touch_strategy_logic():
    """session_restore.py must not import scoring, momentum, or no_catalyst modules."""
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


# ── Test 10: No broker/live/order/AI/Ollama imports ─────────────────────────

def _check_no_forbidden_imports(path: Path) -> None:
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
    _check_no_forbidden_imports(BACKEND_ROOT / "paper" / "account.py")


def test_session_restore_py_no_forbidden_imports():
    _check_no_forbidden_imports(BACKEND_ROOT / "paper" / "session_restore.py")


def test_simulator_py_no_forbidden_imports():
    _check_no_forbidden_imports(BACKEND_ROOT / "paper" / "simulator.py")
