"""
End-of-day fake-position management (Phase G1B-H1 Part E).

Microtrading is intraday. By default the simulator must NOT carry fake
positions across the regular US close. This module provides two pure
helpers used by :mod:`paper.simulator`:

  - :func:`entries_blocked` — True inside the entry cutoff window before
    16:00 ET, so the simulator can short-circuit catalyst/momentum/etc.
    entry decisions without changing the scoring code.
  - :func:`flatten_due` — True at or after the configured flatten offset
    around 16:00 ET; the caller is expected to close every open position
    using the standard exit machinery and emit ``exit_reason="eod_flatten"``.

Independent of intrabar TP/SL — they keep their existing semantics until
the cutoff. No broker, no live trading, no real orders.
"""

from __future__ import annotations

from datetime import datetime

from core.config import settings
from paper import session as _session


def entries_blocked(now: datetime | None = None) -> tuple[bool, str | None]:
    """
    Should the simulator refuse new entries right now?

    Returns (blocked, reason). reason is a short stable string suitable
    for `candidate["rejection_reason"]` and dashboard surfacing.
    Only blocks during the regular US session window; outside session
    the entry path is already gated by the normal session checks.
    """
    if not getattr(settings, "PAPER_EOD_FLATTEN_ENABLED", True):
        return (False, None)
    if getattr(settings, "PAPER_ALLOW_OVERNIGHT_POSITIONS", False):
        return (False, None)
    d = now or _session.now_ny()
    if not _session.is_regular_session_now(d):
        return (False, None)
    cutoff = float(getattr(settings, "PAPER_ENTRY_CUTOFF_MINUTES_BEFORE_CLOSE", 10))
    mins_left = _session.minutes_to_close(d)
    if mins_left <= cutoff:
        return (True, "eod_entry_cutoff")
    return (False, None)


def flatten_due(now: datetime | None = None) -> bool:
    """
    True when the simulator should close every open fake position on the
    next tick. Triggers once the regular close is within the configured
    flatten offset and overnight holding is disabled.
    """
    if not getattr(settings, "PAPER_EOD_FLATTEN_ENABLED", True):
        return False
    if getattr(settings, "PAPER_ALLOW_OVERNIGHT_POSITIONS", False):
        return False
    d = now or _session.now_ny()
    if not _session.is_weekday(d):
        return False
    flatten_offset = float(getattr(settings, "PAPER_EOD_FLATTEN_MINUTES_BEFORE_CLOSE", 0))
    mins_left = _session.minutes_to_close(d)
    # Trigger from `flatten_offset` minutes before close until end of NY day.
    return mins_left <= flatten_offset
