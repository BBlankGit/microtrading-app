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

    G1B-H3: the universal session gate fires first — entries are blocked
    entirely outside Mon–Fri 09:30–16:00 ET (PAPER_REGULAR_SESSION_ONLY).
    The legacy EOD cutoff (10 min before close) then narrows the window
    further inside a live session.
    """
    d = now or _session.now_ny()
    # G1B-H3: universal session gate — block all entries outside regular hours.
    if getattr(settings, "PAPER_REGULAR_SESSION_ONLY", True):
        if not getattr(settings, "PAPER_ALLOW_EXTENDED_HOURS_ENTRIES", False):
            reason = _session.entry_block_reason(d)
            if reason:
                return (True, reason)
    # Legacy EOD cutoff inside regular session (G1B-H1).
    if not getattr(settings, "PAPER_EOD_FLATTEN_ENABLED", True):
        return (False, None)
    if getattr(settings, "PAPER_ALLOW_OVERNIGHT_POSITIONS", False):
        return (False, None)
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


# ── Phase G1B-H2 Part F: late EOD flatten ────────────────────────────────────
# The G1B-H1 close-of-day sweep only runs while a tick is being processed.
# If the simulator was stopped before 16:00 ET (or auto-stopped over the
# weekend), positions stay open into the next session and the dashboard
# shows yesterday's trade as a normal open position. The helpers below let
# every later tick / status / dashboard refresh detect those carryover
# positions and either close them or mark them stale.

def position_is_stale_overnight(
    entry_time_iso: str | None, now: datetime | None = None
) -> bool:
    """
    True when:
      - overnight holding is disabled (default), AND
      - the position was entered strictly BEFORE the most recent regular
        US close that has already occurred (16:00 ET, weekday).

    This catches three failure modes the dashboard previously couldn't:
      1. The simulator was stopped before 16:00 ET and never ran a close
         tick, so EOD flatten never fired (G1B-H1 gap).
      2. The position was opened *after* the close (e.g. 17:30 ET on a
         weekday or 02:00 ET on a Saturday) — the session-date rollback
         rule maps it to the prior session, but it should still be
         flattened on the next tick because no live session has reopened.
      3. A weekend has rolled over without any tick.

    Used both at tick-time (to trigger force-close) and at API/status time
    (to surface stale-overnight warnings on the dashboard).
    """
    from datetime import datetime, timezone
    if not getattr(settings, "PAPER_EOD_FLATTEN_ENABLED", True):
        return False
    if getattr(settings, "PAPER_ALLOW_OVERNIGHT_POSITIONS", False):
        return False
    if not entry_time_iso:
        return False
    try:
        entry_dt = datetime.fromisoformat(str(entry_time_iso).replace("Z", "+00:00"))
    except ValueError:
        return False
    if entry_dt.tzinfo is None:
        entry_dt = entry_dt.replace(tzinfo=timezone.utc)
    entry_ny = entry_dt.astimezone(_session._ny_tz())
    last_close = _session.latest_completed_close_ny(now)
    return entry_ny < last_close


LATE_FLATTEN_REASON = "eod_flatten_late"

# ── Phase G1B-H3 Part C: out-of-session position remediation ─────────────────

OUT_OF_SESSION_REASON = "invalid_out_of_session_entry_flatten"


def position_entry_is_out_of_session(entry_time_iso: str | None) -> bool:
    """
    True when the position was entered outside a regular US session
    (Mon–Fri 09:30–16:00 ET) and the session gate is enabled.

    Used to remediate positions that slipped through before G1B-H3
    enforced the universal session gate (e.g. TSLA opened at 00:08 ET
    Saturday 2026-06-13 before this patch was deployed).

    Note: this is distinct from `position_is_stale_overnight` — a
    position can be out-of-session (opened at midnight Saturday) without
    being stale (its entry timestamp is after the last Friday close).
    """
    if not getattr(settings, "PAPER_REGULAR_SESSION_ONLY", True):
        return False
    if getattr(settings, "PAPER_ALLOW_EXTENDED_HOURS_ENTRIES", False):
        return False
    if not entry_time_iso:
        return False
    # Corrupt / unparseable timestamps must not trigger a force-close.
    try:
        from datetime import datetime as _dt
        _dt.fromisoformat(str(entry_time_iso).replace("Z", "+00:00"))
    except ValueError:
        return False
    return not _session.is_valid_entry_time(entry_time_iso)
