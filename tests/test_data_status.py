"""Bugs of 20/10/2026: sync times, briefing sleep date, sleep stages, daily summary
sections and ok / empty / error states for every Garmin call."""

from __future__ import annotations

from typing import Any

import pytest

from garmin_mcp import extra_tools
from garmin_mcp import server as server_module
from garmin_mcp.garmin_client import GarminClientError, error_note, http_status_of
from tests.test_tools import FakeGarminClient


@pytest.fixture(autouse=True)
async def _reset_state() -> Any:
    await server_module.get_cache_for_testing().clear()
    server_module.set_garmin_client_for_testing(None)
    yield
    server_module.set_garmin_client_for_testing(None)


# Real shapes captured from the account on 20/10/2026 (values trimmed).
SLEEP_20 = {
    "dailySleepDTO": {
        "calendarDate": "2026-10-20",
        "sleepTimeSeconds": 31680,
        "deepSleepSeconds": 3900,
        "lightSleepSeconds": 15240,
        "remSleepSeconds": 12540,
        "awakeSleepSeconds": 0,
        "sleepStartTimestampLocal": 1792447860000,  # 22:11 local
        "sleepEndTimestampLocal": 1792479540000,  # 06:59 local
        "deviceRemCapable": True,
    }
}
SUMMARY_20 = {
    "calendarDate": "2026-10-20",
    "sleepingSeconds": 25140,
    "lastSyncTimestampGMT": "2026-10-20T07:47:15.692",
    "wellnessStartTimeGmt": "2026-10-19T22:00:00.0",
    "wellnessStartTimeLocal": "2026-10-20T00:00:00.0",
    "restingHeartRate": None,
    "totalSteps": 708,
}
RHR_EMPTY = {
    "allMetrics": {
        "metricsMap": {"WELLNESS_RESTING_HEART_RATE": [{"value": None, "calendarDate": "x"}]}
    }
}
HR_EMPTY = {
    "calendarDate": "2026-10-20",
    "startTimestampGMT": "2026-10-19T22:00:00.0",
    "startTimestampLocal": "2026-10-20T00:00:00.0",
    "restingHeartRate": None,
    "heartRateValues": None,
}


class _HTTPError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(f"{code} Client Error")
        self.response = type("R", (), {"status_code": code})()


def test_http_status_from_chain_and_message() -> None:
    try:
        try:
            raise _HTTPError(429)
        except _HTTPError as inner:
            raise GarminClientError("Garmin call 'get_rhr_day' raised HTTPError") from inner
    except GarminClientError as exc:
        assert http_status_of(exc) == 429
        assert error_note(exc).startswith("Garmin call failed (HTTP 429): Garmin call")
    assert http_status_of(GarminClientError("boom 503 Service Unavailable")) == 503
    assert "no HTTP status" in error_note(GarminClientError("timeout"))


# --- Bug 3 ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sleep_has_bed_and_wake_times_and_contrast() -> None:
    fake = FakeGarminClient({"get_sleep_data": SLEEP_20, "get_user_summary": SUMMARY_20})
    server_module.set_garmin_client_for_testing(fake)
    s = await server_module.get_sleep("2026-10-20")
    assert s.status == "ok"
    assert (s.sleep_start_local, s.sleep_end_local) == (
        "2026-10-19T22:11:00",
        "2026-10-20T06:59:00",
    )
    assert (s.rem_sleep_seconds, s.awake_seconds) == (12540, 0)
    assert s.requested_date == s.garmin_calendar_date == "2026-10-20"
    # 31680 vs 25140 s: more than 15 min apart -> contrast field + explanation
    assert s.summary_sleeping_seconds == 25140
    assert s.note is not None and "-109 min" in s.note


def test_missing_stages_are_null_and_provisional_rem_is_flagged() -> None:
    raw = {
        "dailySleepDTO": {
            "calendarDate": "2026-10-20",
            "sleepTimeSeconds": 19260,
            "deepSleepSeconds": 6900,
            "lightSleepSeconds": 12360,
            "remSleepSeconds": 0,
            "deviceRemCapable": True,
        }
    }
    s = server_module._parse_sleep(raw, "2026-10-20")
    assert s.awake_seconds is None  # key absent -> null, not 0
    assert s.rem_sleep_seconds == 0
    assert s.note is not None and "awake" in s.note and "provisional" in s.note


def test_sleep_of_another_day_is_named() -> None:
    raw = {"dailySleepDTO": {"calendarDate": "2026-10-19", "sleepTimeSeconds": 100}}
    s = server_module._parse_sleep(raw, "2026-10-20")
    assert s.garmin_calendar_date == "2026-10-19" and s.requested_date == "2026-10-20"
    assert s.note is not None and "sleep of 2026-10-19, not 2026-10-20" in s.note


@pytest.mark.asyncio
async def test_sleep_error_is_reported_not_raised_nor_cached() -> None:
    calls = {"n": 0}

    def failing(*_a: Any) -> Any:
        calls["n"] += 1
        raise GarminClientError("Garmin call 'get_sleep_data' raised HTTPError: 500 Server Error")

    server_module.set_garmin_client_for_testing(FakeGarminClient({"get_sleep_data": failing}))
    s = await server_module.get_sleep("2026-10-20")
    assert s.status == "error" and s.note is not None and "HTTP 500" in s.note
    await server_module.get_sleep("2026-10-20")
    assert calls["n"] == 2


# --- Bug 2 ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_briefing_sleep_uses_the_same_date(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[Any] = []

    async def sleep(date: str | None = None) -> Any:
        asked.append(date)
        return server_module.SleepSummary(date=date or "?", requested_date=date)

    monkeypatch.setattr(server_module, "get_sleep", sleep)
    monkeypatch.setattr(server_module, "_today_iso", lambda: "2026-10-20")
    fake = FakeGarminClient(
        {
            "get_hrv_data": {},
            "get_body_battery": [],
            "get_training_readiness": [],
            "get_training_status": {},
            "get_rhr_day": RHR_EMPTY,
        }
    )
    server_module.set_garmin_client_for_testing(fake)
    brief = await server_module.get_daily_briefing()  # default = today
    assert asked == ["2026-10-20"]
    assert brief.sleep is not None and brief.sleep.requested_date == "2026-10-20"


# --- Bug 5 ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rhr_tells_empty_from_error() -> None:
    def rhr(day: str) -> Any:
        if day == "2026-10-19":
            raise GarminClientError("Garmin call 'get_rhr_day' raised HTTPError: 429 Too Many")
        if day == "2026-10-20":
            return RHR_EMPTY
        return {"allMetrics": {"metricsMap": {"X": [{"value": 44.0}]}}}

    server_module.set_garmin_client_for_testing(FakeGarminClient({"get_rhr_day": rhr}))
    trend = await server_module.get_resting_heart_rate(days=3, end_date="2026-10-20")
    by_day = {d.date: d for d in trend.days}
    assert by_day["2026-10-18"].status == "ok" and by_day["2026-10-18"].rhr_bpm == 44
    assert by_day["2026-10-19"].status == "error" and "HTTP 429" in (
        by_day["2026-10-19"].error or ""
    )
    assert by_day["2026-10-20"].status == "empty" and by_day["2026-10-20"].rhr_bpm is None
    assert trend.note is not None and "no resting HR for 2026-10-20" in trend.note


@pytest.mark.asyncio
async def test_hr_timeline_empty_vs_error() -> None:
    server_module.set_garmin_client_for_testing(FakeGarminClient({"get_heart_rates": HR_EMPTY}))
    empty = await extra_tools.get_heart_rate_timeline("2026-10-20")
    assert empty.status == "empty" and empty.readings_count == 0
    await server_module.get_cache_for_testing().clear()

    def boom(*_a: Any) -> Any:
        raise GarminClientError("Garmin call 'get_heart_rates' raised HTTPError: 403 Forbidden")

    server_module.set_garmin_client_for_testing(FakeGarminClient({"get_heart_rates": boom}))
    failed = await extra_tools.get_heart_rate_timeline("2026-10-20")
    assert failed.status == "error" and failed.note is not None and "HTTP 403" in failed.note


def test_hr_readings_use_garmin_offset_not_server_clock() -> None:
    raw = dict(HR_EMPTY, heartRateValues=[[1792483200000, 60]])  # 08:00 UTC
    tl = extra_tools._parse_heart_rates(raw, "2026-10-20", 10)
    assert tl.last_reading_time == "2026-10-20T10:00:00"


# --- Bug 4 ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_summary_merges_sections_and_names_failures() -> None:
    def stress(*_a: Any) -> Any:
        raise GarminClientError("Garmin call 'get_stress_data' raised HTTPError: 500")

    fake = FakeGarminClient(
        {
            "get_user_summary": SUMMARY_20,
            "get_heart_rates": HR_EMPTY,
            "get_stress_data": stress,
            "get_body_battery": [],
        }
    )
    server_module.set_garmin_client_for_testing(fake)
    out = await extra_tools.get_daily_summary("2026-10-20")
    data = out.data
    assert data["totalSteps"] == 708  # summary keys stay at the top level
    assert data["heart_rate"]["status"] == "empty"
    assert data["body_battery"]["status"] == "empty"
    assert data["stress"] is None and data["sections_unavailable"] == ["stress"]
    assert "HTTP 500" in data["section_errors"]["stress"]
    assert out.note is not None and "heart_rate" in out.note


def test_rhr_deviation_is_none_when_the_last_day_is_empty() -> None:
    from garmin_mcp.models import RestingHeartRateTrend, RHRDay

    days = [RHRDay(date="2026-10-14", rhr_bpm=43), RHRDay(date="2026-10-15", rhr_bpm=44)]
    assert server_module._rhr_deviation(RestingHeartRateTrend(days=days)) == 1.0
    days.append(RHRDay(date="2026-10-20", status="empty"))
    assert server_module._rhr_deviation(RestingHeartRateTrend(days=days)) is None
