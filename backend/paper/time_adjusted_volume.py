"""
Time-adjusted relative volume for early-session trading gate.

Formula:
  elapsed_ratio = elapsed_regular_session_seconds / (390 * 60)
  expected_volume_now = prev_day_volume * max(elapsed_ratio, min_floor)
  time_adjusted_volume_ratio = day_volume / expected_volume_now

No broker. No live trading. No real orders. No real-money execution.
"""
from __future__ import annotations

import math
from datetime import datetime, time as dtime, timedelta, timezone


def session_elapsed_ratio() -> float:
    """
    Return fraction of the regular session (9:30–16:00 ET) elapsed (0.0–1.0).
    Returns 1.0 outside regular session hours.
    """
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.now(timezone(timedelta(hours=-4)))
    t = now.time()
    if t < dtime(9, 30) or t >= dtime(16, 0):
        return 1.0
    elapsed = (t.hour - 9) * 3600 + (t.minute - 30) * 60 + t.second
    return min(elapsed / (390 * 60), 1.0)


def time_adjusted_volume_ratio(
    day_volume: int | float | None,
    prev_day_volume: int | float | None,
    elapsed_ratio: float,
    min_floor: float = 0.05,
) -> float | None:
    """
    Compute time-adjusted volume ratio.

    Returns day_volume / (prev_day_volume * max(elapsed_ratio, min_floor)).
    Returns None if inputs are missing or produce an invalid result.
    """
    if day_volume is None or prev_day_volume is None:
        return None
    try:
        dv = float(day_volume)
        pdv = float(prev_day_volume)
    except (TypeError, ValueError):
        return None
    if pdv <= 0 or dv < 0 or not math.isfinite(pdv) or not math.isfinite(dv):
        return None
    effective = max(elapsed_ratio, min_floor)
    if effective <= 0:
        return None
    result = dv / (pdv * effective)
    return round(result, 4) if math.isfinite(result) else None
