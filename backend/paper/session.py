"""
US trading-session helpers (Phase G1B-H1).

All times are computed in America/New_York. Holidays are not yet handled —
only weekday + 09:30–16:00 detection. This is the single source of truth
for session/date logic shared by:

  - the EOD flatten / entry cutoff in :mod:`paper.simulator`
  - the wallet APIs (/api/paper/wallets/* session_date filter)
  - the per-wallet trades endpoint
  - the dashboard's "latest session" closed-trade view

Fake-money / paper simulation only. No broker.
"""

from __future__ import annotations

from datetime import datetime, time as dtime, timedelta, timezone


def _ny_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:
        # Conservative fallback: EDT-ish. Holidays/DST may be off.
        return timezone(timedelta(hours=-4))


def now_ny() -> datetime:
    return datetime.now(_ny_tz())


def is_weekday(d: datetime | None = None) -> bool:
    d = d or now_ny()
    return d.weekday() < 5


def is_regular_session_now(d: datetime | None = None) -> bool:
    d = d or now_ny()
    if not is_weekday(d):
        return False
    t = d.time()
    return dtime(9, 30) <= t < dtime(16, 0)


def regular_close_today_ny(d: datetime | None = None) -> datetime:
    d = d or now_ny()
    return d.replace(hour=16, minute=0, second=0, microsecond=0)


def regular_open_today_ny(d: datetime | None = None) -> datetime:
    d = d or now_ny()
    return d.replace(hour=9, minute=30, second=0, microsecond=0)


def minutes_to_close(d: datetime | None = None) -> float:
    """
    Minutes from `d` (default now) to the next 16:00 ET on the same NY date.
    Negative once the market has closed for the day.
    """
    d = d or now_ny()
    return (regular_close_today_ny(d) - d).total_seconds() / 60.0


def latest_completed_close_ny(d: datetime | None = None) -> datetime:
    """
    Return the most recent 16:00 ET timestamp on a weekday that is at or
    before `d`. Used by the late-flatten/stale-overnight logic — a
    position is "stale" iff its entry timestamp is strictly before this
    value (the regular close after which it could not legitimately remain
    open with PAPER_ALLOW_OVERNIGHT_POSITIONS=false).
    """
    d = d or now_ny()
    if is_weekday(d) and d.time() >= dtime(16, 0):
        return d.replace(hour=16, minute=0, second=0, microsecond=0)
    probe = d - timedelta(days=1)
    while probe.weekday() >= 5:
        probe -= timedelta(days=1)
    return probe.replace(hour=16, minute=0, second=0, microsecond=0)


def latest_session_date_ny(d: datetime | None = None) -> str:
    """
    Return the YYYY-MM-DD of the *latest* US trading session relative to `d`.

    Rules:
      - During or after 09:30 ET on a weekday → today.
      - Before 09:30 ET on a weekday          → previous weekday.
      - Weekend                                → previous Friday.

    Used by the after-hours "latest closed positions" view so the dashboard
    keeps showing today's trades until the next NY open instead of going
    blank because UTC has rolled into tomorrow.
    """
    d = d or now_ny()
    candidate = d
    if is_weekday(candidate) and candidate.time() >= dtime(9, 30):
        return candidate.strftime("%Y-%m-%d")
    # Roll back to the previous weekday.
    probe = candidate - timedelta(days=1)
    while probe.weekday() >= 5:
        probe -= timedelta(days=1)
    return probe.strftime("%Y-%m-%d")


def entries_allowed_now(d: datetime | None = None) -> bool:
    """True iff `d` (default: now) falls within the regular US session."""
    return is_regular_session_now(d)


def entry_block_reason(d: datetime | None = None) -> str | None:
    """Return a stable block-reason string, or None when entries are allowed."""
    d = d or now_ny()
    if not is_weekday(d):
        return "market_closed_weekend"
    t = d.time()
    if t < dtime(9, 30):
        return "market_preopen"
    if t >= dtime(16, 0):
        return "market_postclose"
    return None


def is_valid_entry_time(entry_time_iso: str | None) -> bool:
    """True iff the timestamp falls within a regular US session (Mon–Fri 09:30–16:00 ET)."""
    if not entry_time_iso:
        return False
    try:
        dt = datetime.fromisoformat(str(entry_time_iso).replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ny = dt.astimezone(_ny_tz())
    if not is_weekday(ny):
        return False
    t = ny.time()
    return dtime(9, 30) <= t < dtime(16, 0)


def session_date_for(timestamp_iso: str | None) -> str | None:
    """Compute the NY trading-session date for an ISO-8601 timestamp."""
    if not timestamp_iso:
        return None
    try:
        dt = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ny_dt = dt.astimezone(_ny_tz())
    # A trade closed before 09:30 ET counts toward the previous session.
    if is_weekday(ny_dt) and ny_dt.time() < dtime(9, 30):
        probe = ny_dt - timedelta(days=1)
        while probe.weekday() >= 5:
            probe -= timedelta(days=1)
        return probe.strftime("%Y-%m-%d")
    if not is_weekday(ny_dt):
        probe = ny_dt - timedelta(days=1)
        while probe.weekday() >= 5:
            probe -= timedelta(days=1)
        return probe.strftime("%Y-%m-%d")
    return ny_dt.strftime("%Y-%m-%d")
