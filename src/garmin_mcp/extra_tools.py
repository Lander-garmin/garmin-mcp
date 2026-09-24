"""Extended read-only tools covering the rest of the Garmin Connect surface.

The core tools in ``server.py`` return tightly typed daily summaries. These
tools widen coverage to intraday timelines (heart rate, steps), wellness
metrics not in the core set (SpO2, hydration, floors, intensity minutes,
weigh-ins, blood pressure), devices and sync state, goals and badges,
performance markers (lactate threshold, FTP, running tolerance, fitness age),
training calendar and plans, nutrition, and richer per-activity data.

Most of them return a :class:`GarminData` envelope with the (compacted) raw
Garmin payload under ``data``. Long arrays are downsampled and ``null`` fields
are dropped so responses stay small enough for the model to reason over.
Every tool here is read-only; the client-side allowlist enforces that.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

from pydantic import Field

from garmin_mcp import server as _s
from garmin_mcp.cache import TTLCache
from garmin_mcp.garmin_client import GarminClientError
from garmin_mcp.models import _StrictBase

mcp = _s.mcp
log = _s.log

_DEFAULT_TTL = 900  # 15 minutes: intraday data changes as the watch syncs.
_SLOW_TTL = 3600  # devices, gear, badges, profile.


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class GarminData(_StrictBase):
    """Generic envelope for a Garmin Connect payload."""

    source: str = Field(description="Garmin Connect API method the data came from.")
    params: dict[str, Any] = Field(default_factory=dict, description="Parameters used.")
    data: Any = Field(default=None, description="Compacted Garmin payload; null if unavailable.")
    note: str | None = Field(default=None, description="Explains missing data or truncation.")


class HeartRateReading(_StrictBase):
    time: str = Field(description="Local time of the reading, ISO-8601.")
    bpm: int


class HeartRateTimeline(_StrictBase):
    date: str
    resting_hr: int | None = None
    min_hr: int | None = None
    max_hr: int | None = None
    last_seven_days_avg_resting_hr: int | None = None
    last_reading_bpm: int | None = Field(
        default=None,
        description="Most recent heart rate the watch synced. The closest thing to 'current' HR.",
    )
    last_reading_time: str | None = Field(default=None, description="Local time of last reading.")
    readings_count: int = Field(default=0, description="Number of raw readings Garmin returned.")
    readings: list[HeartRateReading] = Field(
        default_factory=list, description="Downsampled intraday readings (~2 min apart)."
    )
    note: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compact(obj: Any, max_items: int = 120) -> Any:
    """Drop nulls and downsample long lists so payloads stay model-sized."""
    if isinstance(obj, list):
        if len(obj) > max_items:
            step = math.ceil(len(obj) / max_items)
            obj = obj[::step]
        return [_compact(item, max_items) for item in obj]
    if isinstance(obj, dict):
        return {k: _compact(v, max_items) for k, v in obj.items() if v is not None}
    return obj


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    return isinstance(value, (list, dict, str)) and len(value) == 0


def _days_ago_iso(days: int) -> str:
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


async def _fetch(
    tool: str,
    method: str,
    *args: Any,
    params: dict[str, Any] | None = None,
    ttl: int = _DEFAULT_TTL,
    transform: Any = None,
    max_items: int = 120,
    **kwargs: Any,
) -> GarminData:
    """Call one allowlisted Garmin method, compact the payload, cache the result.

    Failures are not cached: a transient Garmin error returns a ``GarminData``
    with a ``note`` and the next call retries.
    """
    params = params or {}
    cache_key = TTLCache.make_key(tool, params)

    async def compute() -> GarminData:
        client = _s._get_garmin()
        raw = await client.call(method, *args, **kwargs)
        data = transform(raw) if transform else raw
        note = None
        if _is_empty(data):
            note = "Garmin returned no data for this request (not recorded, or watch not synced)."
        return GarminData(source=method, params=params, data=_compact(data, max_items), note=note)

    try:
        result: GarminData = await _s._cache.get_or_compute(cache_key, ttl, compute)
    except GarminClientError as exc:
        log.warning("extra_tool.failed", tool=tool, method=method, error=str(exc)[:200])
        return GarminData(
            source=method,
            params=params,
            data=None,
            note=f"Garmin call failed: {str(exc)[:200]}",
        )
    return result


def _parse_heart_rates(raw: Any, date: str, max_points: int) -> HeartRateTimeline:
    if not isinstance(raw, dict):
        return HeartRateTimeline(date=date, note="No heart rate data returned for this date.")
    values = raw.get("heartRateValues") or []
    readings: list[HeartRateReading] = []
    for entry in values:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        ts, bpm = entry[0], entry[1]
        if bpm is None or ts is None:
            continue
        local = _s._seconds_to_iso_local(ts)
        if local is None:
            continue
        readings.append(HeartRateReading(time=local, bpm=int(bpm)))

    last = readings[-1] if readings else None
    total = len(readings)
    if total > max_points:
        step = math.ceil(total / max_points)
        sampled = readings[::step]
        if sampled[-1] is not last and last is not None:
            sampled.append(last)
        readings = sampled

    note = None
    if total == 0:
        note = "No intraday readings: the watch may not have synced yet for this date."
    elif date == _s._today_iso() and last is not None:
        note = (
            "last_reading is the newest value the watch has synced to Garmin Connect; "
            "it can lag real time by minutes to hours depending on sync."
        )

    def _as_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return HeartRateTimeline(
        date=date,
        resting_hr=_as_int(raw.get("restingHeartRate")),
        min_hr=_as_int(raw.get("minHeartRate")),
        max_hr=_as_int(raw.get("maxHeartRate")),
        last_seven_days_avg_resting_hr=_as_int(raw.get("lastSevenDaysAvgRestingHeartRate")),
        last_reading_bpm=last.bpm if last else None,
        last_reading_time=last.time if last else None,
        readings_count=total,
        readings=readings,
        note=note,
    )


def _activity_timeseries(raw: Any, max_points: int) -> dict[str, Any]:
    """Turn Garmin's columnar activity detail chart into named, downsampled series."""
    if not isinstance(raw, dict):
        return {}
    descriptors = raw.get("metricDescriptors") or []
    metrics = raw.get("activityDetailMetrics") or []
    names: dict[int, str] = {}
    units: dict[str, str] = {}
    for d in descriptors:
        if not isinstance(d, dict):
            continue
        idx = d.get("metricsIndex")
        key = d.get("key")
        if idx is None or key is None:
            continue
        names[int(idx)] = str(key)
        unit = d.get("unit") or {}
        if isinstance(unit, dict) and unit.get("key"):
            units[str(key)] = str(unit["key"])

    rows: list[list[Any]] = [
        list(m["metrics"]) for m in metrics if isinstance(m, dict) and m.get("metrics")
    ]
    total = len(rows)
    if total > max_points:
        step = math.ceil(total / max_points)
        rows = rows[::step]

    series: dict[str, list[Any]] = {name: [] for name in names.values()}
    for row in rows:
        for idx, name in names.items():
            value = row[idx] if idx < len(row) else None
            if isinstance(value, float):
                value = round(value, 3)
            series[name].append(value)
    # Drop series that are entirely empty.
    series = {k: v for k, v in series.items() if any(x is not None for x in v)}

    return {
        "activity_id": raw.get("activityId"),
        "points_total": total,
        "points_returned": len(rows),
        "units": {k: units[k] for k in series if k in units},
        "series": series,
    }


def _profile_number(profile: Any) -> str | None:
    if not isinstance(profile, dict):
        return None
    for key in ("userProfileNumber", "profileId", "id", "userProfileId"):
        value = profile.get(key)
        if value is not None:
            return str(value)
    return None


# ---------------------------------------------------------------------------
# Intraday and wellness
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_heart_rate_timeline(
    date: str | None = None, max_points: int = 96
) -> HeartRateTimeline:
    """Intraday heart rate for a day, including the most recent reading the watch synced.

    Use this for "what is my heart rate now / this morning / at 15:30". The
    last_reading fields give the newest value Garmin has; readings are
    downsampled to ~max_points evenly spaced samples.

    Args:
        date: Calendar date in YYYY-MM-DD format. Defaults to today.
        max_points: Maximum number of readings to return (default 96, i.e. ~15 min apart).
    """
    target_date = _s._normalise_date(date, _s._today_iso())
    max_points = max(10, min(int(max_points), 720))
    cache_key = TTLCache.make_key("get_heart_rate_timeline", {"date": target_date, "n": max_points})

    async def fetch() -> HeartRateTimeline:
        client = _s._get_garmin()
        raw = await client.call("get_heart_rates", target_date)
        return _parse_heart_rates(raw, target_date, max_points)

    ttl = 300 if target_date == _s._today_iso() else _SLOW_TTL
    result: HeartRateTimeline = await _s._cache.get_or_compute(cache_key, ttl, fetch)
    return result


@mcp.tool()
async def get_daily_summary(date: str | None = None) -> GarminData:
    """Everything Garmin records for one day in a single call.

    Steps, distance, calories (active/BMR/total), floors, intensity minutes,
    heart rate (resting/min/max/last), stress, Body Battery, SpO2, respiration,
    sleep seconds and more. Best first call for "how was my day".

    Args:
        date: Calendar date in YYYY-MM-DD format. Defaults to today.
    """
    d = _s._normalise_date(date, _s._today_iso())
    return await _fetch("get_daily_summary", "get_user_summary", d, params={"date": d})


@mcp.tool()
async def get_steps_timeline(date: str | None = None) -> GarminData:
    """Steps in 15-minute buckets across the day, with activity level per bucket.

    Args:
        date: Calendar date in YYYY-MM-DD format. Defaults to today.
    """
    d = _s._normalise_date(date, _s._today_iso())
    return await _fetch("get_steps_timeline", "get_steps_data", d, params={"date": d})


@mcp.tool()
async def get_floors(date: str | None = None) -> GarminData:
    """Floors climbed and descended for a day, with the intraday timeline.

    Args:
        date: Calendar date in YYYY-MM-DD format. Defaults to today.
    """
    d = _s._normalise_date(date, _s._today_iso())
    return await _fetch("get_floors", "get_floors", d, params={"date": d})


@mcp.tool()
async def get_intensity_minutes(date: str | None = None) -> GarminData:
    """Moderate and vigorous intensity minutes for a day and the weekly goal progress.

    Args:
        date: Calendar date in YYYY-MM-DD format. Defaults to today.
    """
    d = _s._normalise_date(date, _s._today_iso())
    return await _fetch(
        "get_intensity_minutes", "get_intensity_minutes_data", d, params={"date": d}
    )


@mcp.tool()
async def get_spo2(date: str | None = None) -> GarminData:
    """Blood oxygen (SpO2 / pulse ox) for a day: average, lowest, latest, sleep average, timeline.

    Args:
        date: Calendar date in YYYY-MM-DD format. Defaults to today.
    """
    d = _s._normalise_date(date, _s._today_iso())
    return await _fetch("get_spo2", "get_spo2_data", d, params={"date": d})


@mcp.tool()
async def get_hydration(date: str | None = None) -> GarminData:
    """Hydration log for a day: intake in ml, goal, sweat loss estimate.

    Args:
        date: Calendar date in YYYY-MM-DD format. Defaults to today.
    """
    d = _s._normalise_date(date, _s._today_iso())
    return await _fetch("get_hydration", "get_hydration_data", d, params={"date": d})


@mcp.tool()
async def get_body_battery_events(date: str | None = None) -> GarminData:
    """Body Battery charge/drain events for a day (sleep, activities, stress) with their impact.

    Args:
        date: Calendar date in YYYY-MM-DD format. Defaults to today.
    """
    d = _s._normalise_date(date, _s._today_iso())
    return await _fetch("get_body_battery_events", "get_body_battery_events", d, params={"date": d})


@mcp.tool()
async def get_all_day_events(date: str | None = None) -> GarminData:
    """Timeline of everything Garmin detected during the day: activities, naps, sleep, stress events.

    Args:
        date: Calendar date in YYYY-MM-DD format. Defaults to today.
    """
    d = _s._normalise_date(date, _s._today_iso())
    return await _fetch("get_all_day_events", "get_all_day_events", d, params={"date": d})


@mcp.tool()
async def get_stats_and_body(date: str | None = None) -> GarminData:
    """Daily stats merged with body composition (weight, BMI, body fat) for a date.

    Args:
        date: Calendar date in YYYY-MM-DD format. Defaults to today.
    """
    d = _s._normalise_date(date, _s._today_iso())
    return await _fetch("get_stats_and_body", "get_stats_and_body", d, params={"date": d})


@mcp.tool()
async def get_lifestyle_log(date: str | None = None) -> GarminData:
    """Lifestyle logging entries for a day (caffeine, alcohol, illness, travel, mood, etc.).

    Args:
        date: Calendar date in YYYY-MM-DD format. Defaults to today.
    """
    d = _s._normalise_date(date, _s._today_iso())
    return await _fetch("get_lifestyle_log", "get_lifestyle_logging_data", d, params={"date": d})


@mcp.tool()
async def get_nutrition(date: str | None = None) -> GarminData:
    """Food log and meals for a day (calories, macros) if nutrition tracking is used.

    Args:
        date: Calendar date in YYYY-MM-DD format. Defaults to today.
    """
    d = _s._normalise_date(date, _s._today_iso())
    food = await _fetch("get_nutrition.food", "get_nutrition_daily_food_log", d, params={"date": d})
    meals = await _fetch("get_nutrition.meals", "get_nutrition_daily_meals", d, params={"date": d})
    notes = [n for n in (food.note, meals.note) if n]
    return GarminData(
        source="get_nutrition_daily_food_log+get_nutrition_daily_meals",
        params={"date": d},
        data={"food_log": food.data, "meals": meals.data},
        note="; ".join(notes) or None,
    )


@mcp.tool()
async def get_menstrual_data(date: str | None = None) -> GarminData:
    """Menstrual cycle tracking data for a date, if the feature is used.

    Args:
        date: Calendar date in YYYY-MM-DD format. Defaults to today.
    """
    d = _s._normalise_date(date, _s._today_iso())
    return await _fetch("get_menstrual_data", "get_menstrual_data_for_date", d, params={"date": d})


# ---------------------------------------------------------------------------
# Ranges and trends
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_daily_steps_range(
    start_date: str | None = None, end_date: str | None = None
) -> GarminData:
    """Steps, distance and step goal per day over a date range (default last 14 days).

    Args:
        start_date: YYYY-MM-DD. Defaults to 14 days ago.
        end_date: YYYY-MM-DD. Defaults to today.
    """
    start = _s._normalise_date(start_date, _days_ago_iso(14))
    end = _s._normalise_date(end_date, _s._today_iso())
    return await _fetch(
        "get_daily_steps_range", "get_daily_steps", start, end, params={"start": start, "end": end}
    )


@mcp.tool()
async def get_weigh_ins(start_date: str | None = None, end_date: str | None = None) -> GarminData:
    """Every weigh-in (weight, BMI, body fat, muscle mass...) in a date range (default last 30 days).

    Args:
        start_date: YYYY-MM-DD. Defaults to 30 days ago.
        end_date: YYYY-MM-DD. Defaults to today.
    """
    start = _s._normalise_date(start_date, _days_ago_iso(30))
    end = _s._normalise_date(end_date, _s._today_iso())
    return await _fetch(
        "get_weigh_ins", "get_weigh_ins", start, end, params={"start": start, "end": end}
    )


@mcp.tool()
async def get_blood_pressure(
    start_date: str | None = None, end_date: str | None = None
) -> GarminData:
    """Blood pressure readings logged in Garmin Connect over a date range (default last 30 days).

    Args:
        start_date: YYYY-MM-DD. Defaults to 30 days ago.
        end_date: YYYY-MM-DD. Defaults to today.
    """
    start = _s._normalise_date(start_date, _days_ago_iso(30))
    end = _s._normalise_date(end_date, _s._today_iso())
    return await _fetch(
        "get_blood_pressure", "get_blood_pressure", start, end, params={"start": start, "end": end}
    )


@mcp.tool()
async def get_progress_summary(
    start_date: str | None = None,
    end_date: str | None = None,
    metric: str = "distance",
) -> GarminData:
    """Totals per activity type between two dates: distance, duration, elevation gain or moving time.

    Use for "how many km did I run this month" or "hours of cycling this year".

    Args:
        start_date: YYYY-MM-DD. Defaults to 30 days ago.
        end_date: YYYY-MM-DD. Defaults to today.
        metric: One of distance, duration, movingDuration, elevationGain, elevationLoss.
    """
    start = _s._normalise_date(start_date, _days_ago_iso(30))
    end = _s._normalise_date(end_date, _s._today_iso())
    allowed = {"distance", "duration", "movingDuration", "elevationGain", "elevationLoss"}
    if metric not in allowed:
        raise ValueError(f"metric must be one of {sorted(allowed)}")
    return await _fetch(
        "get_progress_summary",
        "get_progress_summary_between_dates",
        start,
        end,
        metric,
        True,
        params={"start": start, "end": end, "metric": metric},
    )


@mcp.tool()
async def get_running_tolerance(
    start_date: str | None = None, end_date: str | None = None
) -> GarminData:
    """Garmin running tolerance (weekly mileage your body tolerates) over a range (default 12 weeks).

    Args:
        start_date: YYYY-MM-DD. Defaults to 84 days ago.
        end_date: YYYY-MM-DD. Defaults to today.
    """
    start = _s._normalise_date(start_date, _days_ago_iso(84))
    end = _s._normalise_date(end_date, _s._today_iso())
    return await _fetch(
        "get_running_tolerance",
        "get_running_tolerance",
        start,
        end,
        params={"start": start, "end": end},
        ttl=_SLOW_TTL,
    )


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_activities_by_date(
    start_date: str | None = None,
    end_date: str | None = None,
    activity_type: str | None = None,
) -> GarminData:
    """Activities between two dates, optionally filtered by type (running, cycling, swimming, ...).

    Args:
        start_date: YYYY-MM-DD. Defaults to 30 days ago.
        end_date: YYYY-MM-DD. Defaults to today.
        activity_type: Garmin type key such as running, cycling, walking, strength_training.
    """
    start = _s._normalise_date(start_date, _days_ago_iso(30))
    end = _s._normalise_date(end_date, _s._today_iso())
    params: dict[str, Any] = {"start": start, "end": end}
    if activity_type:
        params["type"] = activity_type
    return await _fetch(
        "get_activities_by_date",
        "get_activities_by_date",
        start,
        end,
        activity_type,
        params=params,
        max_items=60,
    )


@mcp.tool()
async def get_last_activity() -> GarminData:
    """The most recent activity recorded, with its summary metrics."""
    return await _fetch("get_last_activity", "get_last_activity", ttl=300)


@mcp.tool()
async def get_activity_timeseries(activity_id: str, max_points: int = 120) -> GarminData:
    """Second-by-second chart data of an activity as named series (heart rate, pace, altitude,
    cadence, power, temperature...), downsampled to max_points.

    Args:
        activity_id: Garmin activity ID (from get_recent_activities).
        max_points: Maximum samples per series (default 120).
    """
    max_points = max(10, min(int(max_points), 1000))
    return await _fetch(
        "get_activity_timeseries",
        "get_activity_details",
        activity_id,
        params={"activity_id": activity_id, "n": max_points},
        ttl=_SLOW_TTL,
        transform=lambda raw: _activity_timeseries(raw, max_points),
        max_items=max_points,
    )


@mcp.tool()
async def get_activity_power_zones(activity_id: str) -> GarminData:
    """Time spent in each power zone for a cycling or running-power activity.

    Args:
        activity_id: Garmin activity ID.
    """
    return await _fetch(
        "get_activity_power_zones",
        "get_activity_power_in_timezones",
        activity_id,
        params={"activity_id": activity_id},
        ttl=_SLOW_TTL,
    )


@mcp.tool()
async def get_activity_split_summaries(activity_id: str) -> GarminData:
    """Per-split summaries of an activity (laps, intervals, rest) with pace, HR and power.

    Args:
        activity_id: Garmin activity ID.
    """
    return await _fetch(
        "get_activity_split_summaries",
        "get_activity_split_summaries",
        activity_id,
        params={"activity_id": activity_id},
        ttl=_SLOW_TTL,
    )


@mcp.tool()
async def get_activity_typed_splits(activity_id: str) -> GarminData:
    """Typed splits of an activity (e.g. climb/descent segments, swim lengths, interval work/rest).

    Args:
        activity_id: Garmin activity ID.
    """
    return await _fetch(
        "get_activity_typed_splits",
        "get_activity_typed_splits",
        activity_id,
        params={"activity_id": activity_id},
        ttl=_SLOW_TTL,
    )


@mcp.tool()
async def get_activity_gear(activity_id: str) -> GarminData:
    """Gear (shoes, bike) linked to an activity.

    Args:
        activity_id: Garmin activity ID.
    """
    return await _fetch(
        "get_activity_gear",
        "get_activity_gear",
        activity_id,
        params={"activity_id": activity_id},
        ttl=_SLOW_TTL,
    )


# ---------------------------------------------------------------------------
# Performance markers
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_lactate_threshold() -> GarminData:
    """Latest lactate threshold estimate (heart rate and pace/power) from Garmin."""
    return await _fetch(
        "get_lactate_threshold", "get_lactate_threshold", ttl=_SLOW_TTL, latest=True
    )


@mcp.tool()
async def get_cycling_ftp() -> GarminData:
    """Cycling Functional Threshold Power (FTP) and power zones."""
    return await _fetch("get_cycling_ftp", "get_cycling_ftp", ttl=_SLOW_TTL)


@mcp.tool()
async def get_fitness_age(date: str | None = None) -> GarminData:
    """Garmin fitness age with its components (VO2 max, BMI/body fat, RHR, vigorous days).

    Args:
        date: Calendar date in YYYY-MM-DD format. Defaults to today.
    """
    d = _s._normalise_date(date, _s._today_iso())
    return await _fetch(
        "get_fitness_age", "get_fitnessage_data", d, params={"date": d}, ttl=_SLOW_TTL
    )


# ---------------------------------------------------------------------------
# Training calendar, goals, badges
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_scheduled_workouts(year: int | None = None, month: int | None = None) -> GarminData:
    """Training calendar for a month: scheduled workouts, completed activities, plan items.

    Args:
        year: Four-digit year. Defaults to the current year.
        month: 1-12. Defaults to the current month.
    """
    today = dt.date.today()
    y = int(year) if year else today.year
    m = int(month) if month else today.month
    if not 1 <= m <= 12:
        raise ValueError("month must be between 1 and 12")
    return await _fetch(
        "get_scheduled_workouts",
        "get_scheduled_workouts",
        y,
        m,
        params={"year": y, "month": m},
        max_items=200,
    )


@mcp.tool()
async def get_training_plans() -> GarminData:
    """Training plans the user is enrolled in (Garmin Coach and custom plans)."""
    return await _fetch("get_training_plans", "get_training_plans", ttl=_SLOW_TTL)


@mcp.tool()
async def get_goals(status: str = "active") -> GarminData:
    """Goals set in Garmin Connect (steps, distance, weight...) with progress.

    Args:
        status: active, future or past. Defaults to active.
    """
    if status not in {"active", "future", "past"}:
        raise ValueError("status must be active, future or past")
    return await _fetch("get_goals", "get_goals", status, params={"status": status}, ttl=_SLOW_TTL)


@mcp.tool()
async def get_badges() -> GarminData:
    """Badges earned and badges in progress, with points and dates."""
    earned = await _fetch("get_badges.earned", "get_earned_badges", ttl=_SLOW_TTL, max_items=200)
    progress = await _fetch("get_badges.in_progress", "get_in_progress_badges", ttl=_SLOW_TTL)
    notes = [n for n in (earned.note, progress.note) if n]
    return GarminData(
        source="get_earned_badges+get_in_progress_badges",
        data={"earned": earned.data, "in_progress": progress.data},
        note="; ".join(notes) or None,
    )


# ---------------------------------------------------------------------------
# Devices, gear, profile
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_devices() -> GarminData:
    """Registered Garmin devices and the last-used device with its last sync time.

    Use this to know how fresh the data is: if the watch has not synced
    recently, intraday values will be stale.
    """
    devices = await _fetch("get_devices.list", "get_devices", ttl=_SLOW_TTL)
    last_used = await _fetch("get_devices.last_used", "get_device_last_used", ttl=300)
    sync_iso = None
    if isinstance(last_used.data, dict):
        sync_iso = _s._seconds_to_iso_local(last_used.data.get("lastUsedDeviceUploadTime"))
    notes = [n for n in (devices.note, last_used.note) if n]
    return GarminData(
        source="get_devices+get_device_last_used",
        data={
            "devices": devices.data,
            "last_used": last_used.data,
            "last_sync_local_time": sync_iso,
        },
        note="; ".join(notes) or None,
    )


@mcp.tool()
async def get_gear() -> GarminData:
    """Gear registered in Garmin Connect (shoes, bikes) with total distance and activity counts."""
    profile = await _fetch("get_gear.profile", "get_user_profile", ttl=_SLOW_TTL)
    number = _profile_number(profile.data)
    if number is None:
        return GarminData(
            source="get_gear",
            data=None,
            note="Could not resolve the user profile number needed to list gear.",
        )
    gear = await _fetch(
        "get_gear.list", "get_gear", number, params={"profile": number}, ttl=_SLOW_TTL
    )
    stats: list[Any] = []
    if isinstance(gear.data, list):
        for item in gear.data[:20]:
            uuid = item.get("uuid") if isinstance(item, dict) else None
            if not uuid:
                continue
            s = await _fetch(
                "get_gear.stats", "get_gear_stats", uuid, params={"uuid": uuid}, ttl=_SLOW_TTL
            )
            stats.append({"uuid": uuid, "stats": s.data})
    return GarminData(
        source="get_gear+get_gear_stats",
        data={"gear": gear.data, "stats": stats},
        note=gear.note,
    )


@mcp.tool()
async def get_user_profile() -> GarminData:
    """User profile basics: display name, unit system, birth year, gender, height, weight."""
    profile = await _fetch("get_user_profile", "get_user_profile", ttl=_SLOW_TTL)
    units = await _fetch("get_user_profile.units", "get_unit_system", ttl=_SLOW_TTL)
    return GarminData(
        source="get_user_profile+get_unit_system",
        data={"profile": profile.data, "unit_system": units.data},
        note=profile.note,
    )
