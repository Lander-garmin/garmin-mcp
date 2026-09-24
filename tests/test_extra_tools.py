"""Tests for the extended read-only tools in ``garmin_mcp.extra_tools``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from garmin_mcp import extra_tools
from garmin_mcp import server as server_module
from garmin_mcp.extra_tools import GarminData, HeartRateTimeline, _compact
from garmin_mcp.garmin_client import _READ_METHODS, _WRITE_METHODS, GarminClientError
from tests.test_tools import FakeGarminClient


def _ms(hour: int, minute: int) -> int:
    return int(datetime(2026, 5, 10, hour, minute).timestamp() * 1000)


HEART_RATE_PAYLOAD: dict[str, Any] = {
    "calendarDate": "2026-05-10",
    "restingHeartRate": 44,
    "minHeartRate": 41,
    "maxHeartRate": 152,
    "lastSevenDaysAvgRestingHeartRate": 46,
    "heartRateValues": [[_ms(0, 0) + i * 120_000, 50 + (i % 7)] for i in range(500)]
    + [[_ms(17, 0), None], [_ms(17, 2), 63]],
}


@pytest.mark.asyncio
async def test_heart_rate_timeline_downsamples_and_keeps_last_reading() -> None:
    fake = FakeGarminClient({"get_heart_rates": HEART_RATE_PAYLOAD})
    server_module.set_garmin_client_for_testing(fake)

    result = await extra_tools.get_heart_rate_timeline(date="2026-05-10", max_points=50)
    assert isinstance(result, HeartRateTimeline)
    assert result.resting_hr == 44
    assert result.min_hr == 41
    assert result.max_hr == 152
    assert result.last_seven_days_avg_resting_hr == 46
    assert result.readings_count == 501  # the None reading is skipped
    assert result.last_reading_bpm == 63
    assert result.last_reading_time is not None
    assert result.last_reading_time.startswith("2026-05-10T17:02")
    assert 10 <= len(result.readings) <= 52
    assert result.readings[-1].bpm == 63
    assert fake.call_log[0][0] == "get_heart_rates"


@pytest.mark.asyncio
async def test_heart_rate_timeline_handles_empty_payload() -> None:
    fake = FakeGarminClient({"get_heart_rates": {"heartRateValues": None}})
    server_module.set_garmin_client_for_testing(fake)

    result = await extra_tools.get_heart_rate_timeline(date="2026-05-10")
    assert result.last_reading_bpm is None
    assert result.readings == []
    assert result.note is not None


@pytest.mark.asyncio
async def test_generic_tool_wraps_payload_and_drops_nulls() -> None:
    payload = {"totalSteps": 8123, "floorsAscended": None, "nested": {"a": 1, "b": None}}
    fake = FakeGarminClient({"get_user_summary": payload})
    server_module.set_garmin_client_for_testing(fake)

    result = await extra_tools.get_daily_summary(date="2026-05-10")
    assert isinstance(result, GarminData)
    assert result.source == "get_user_summary"
    assert result.params == {"date": "2026-05-10"}
    assert result.data == {"totalSteps": 8123, "nested": {"a": 1}}
    assert result.note is None
    assert fake.call_log == [("get_user_summary", ("2026-05-10",), {})]


@pytest.mark.asyncio
async def test_generic_tool_reports_empty_data() -> None:
    fake = FakeGarminClient({"get_spo2_data": {}})
    server_module.set_garmin_client_for_testing(fake)

    result = await extra_tools.get_spo2(date="2026-05-10")
    assert result.data == {}
    assert result.note is not None and "no data" in result.note


@pytest.mark.asyncio
async def test_generic_tool_failure_is_reported_and_not_cached() -> None:
    calls = {"n": 0}

    def flaky(*_args: Any, **_kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise GarminClientError("boom")
        return {"ok": True}

    fake = FakeGarminClient({"get_floors": flaky})
    server_module.set_garmin_client_for_testing(fake)

    first = await extra_tools.get_floors(date="2026-05-10")
    assert first.data is None
    assert first.note is not None and "boom" in first.note

    second = await extra_tools.get_floors(date="2026-05-10")
    assert second.data == {"ok": True}
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_range_tools_default_to_today_and_pass_dates() -> None:
    fake = FakeGarminClient({"get_weigh_ins": {"dailyWeightSummaries": []}})
    server_module.set_garmin_client_for_testing(fake)

    result = await extra_tools.get_weigh_ins(start_date="2026-04-01", end_date="2026-04-30")
    assert result.params == {"start": "2026-04-01", "end": "2026-04-30"}
    assert fake.call_log == [("get_weigh_ins", ("2026-04-01", "2026-04-30"), {})]


@pytest.mark.asyncio
async def test_progress_summary_validates_metric() -> None:
    with pytest.raises(ValueError):
        await extra_tools.get_progress_summary(metric="bogus")


@pytest.mark.asyncio
async def test_activity_timeseries_builds_named_series() -> None:
    raw = {
        "activityId": 123,
        "metricDescriptors": [
            {"metricsIndex": 0, "key": "directHeartRate", "unit": {"key": "bpm"}},
            {"metricsIndex": 1, "key": "directSpeed", "unit": {"key": "mps"}},
            {"metricsIndex": 2, "key": "directPower", "unit": {"key": "watt"}},
        ],
        "activityDetailMetrics": [{"metrics": [120 + i, 3.1234, None]} for i in range(300)],
    }
    fake = FakeGarminClient({"get_activity_details": raw})
    server_module.set_garmin_client_for_testing(fake)

    result = await extra_tools.get_activity_timeseries(activity_id="123", max_points=50)
    assert result.source == "get_activity_details"
    data = result.data
    assert data["activity_id"] == 123
    assert data["points_total"] == 300
    assert data["points_returned"] <= 50
    assert set(data["series"]) == {"directHeartRate", "directSpeed"}  # all-null power dropped
    assert data["units"] == {"directHeartRate": "bpm", "directSpeed": "mps"}
    assert data["series"]["directSpeed"][0] == 3.123


@pytest.mark.asyncio
async def test_devices_combines_list_and_last_sync() -> None:
    fake = FakeGarminClient(
        {
            "get_devices": [{"deviceId": 1, "productDisplayName": "Forerunner 265"}],
            "get_device_last_used": {
                "lastUsedDeviceUploadTime": _ms(8, 30),
                "lastUsedDeviceName": "FR",
            },
        }
    )
    server_module.set_garmin_client_for_testing(fake)

    result = await extra_tools.get_devices()
    assert result.data["devices"][0]["productDisplayName"] == "Forerunner 265"
    assert result.data["last_sync_local_time"].startswith("2026-05-10T08:30")


@pytest.mark.asyncio
async def test_gear_resolves_profile_number_and_stats() -> None:
    fake = FakeGarminClient(
        {
            "get_user_profile": {"userProfileNumber": 987},
            "get_gear": [{"uuid": "abc", "displayName": "Pegasus"}],
            "get_gear_stats": {"totalDistance": 412000.0},
        }
    )
    server_module.set_garmin_client_for_testing(fake)

    result = await extra_tools.get_gear()
    assert result.data["gear"][0]["displayName"] == "Pegasus"
    assert result.data["stats"] == [{"uuid": "abc", "stats": {"totalDistance": 412000.0}}]
    assert ("get_gear", ("987",), {}) in fake.call_log


def test_compact_downsamples_long_lists_and_drops_nulls() -> None:
    out = _compact(
        {"a": None, "b": list(range(1000)), "c": [None, {"x": None, "y": 1}]}, max_items=100
    )
    assert "a" not in out
    assert len(out["b"]) <= 100
    assert out["b"][0] == 0
    assert out["c"] == [None, {"y": 1}]


def test_extra_tools_only_use_read_methods() -> None:
    """Every Garmin method referenced by extra_tools must be on the read allowlist."""
    import inspect
    import re

    source = inspect.getsource(extra_tools)
    referenced = set(re.findall(r'"(get_[a-z_]+)"', source))
    # Tool/cache names share the get_ prefix; keep only real Garmin methods.
    garmin_methods = {m for m in referenced if m in _READ_METHODS or m in _WRITE_METHODS}
    assert garmin_methods, "expected extra_tools to reference Garmin methods"
    assert not (garmin_methods & _WRITE_METHODS)
    for method in (
        "get_heart_rates",
        "get_user_summary",
        "get_steps_data",
        "get_spo2_data",
        "get_devices",
        "get_activity_details",
    ):
        assert method in _READ_METHODS


def test_extended_tools_are_registered() -> None:
    names = {t.name for t in server_module.mcp._tool_manager.list_tools()}
    for expected in (
        "get_heart_rate_timeline",
        "get_daily_summary",
        "get_steps_timeline",
        "get_spo2",
        "get_hydration",
        "get_weigh_ins",
        "get_activities_by_date",
        "get_activity_timeseries",
        "get_devices",
        "get_gear",
        "get_goals",
        "get_badges",
        "get_lactate_threshold",
        "get_scheduled_workouts",
    ):
        assert expected in names
