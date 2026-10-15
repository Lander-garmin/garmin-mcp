"""Post-activity rating (feel / RPE) exposed on activity reads."""

from __future__ import annotations

from typing import Any

import pytest

from garmin_mcp import extra_tools
from garmin_mcp import server as server_module
from tests.test_tools import FakeGarminClient

RATED = {
    "activityName": "Series 4x1000",
    "activityTypeDTO": {"typeKey": "running"},
    "summaryDTO": {"duration": 2377.0, "directWorkoutFeel": 100, "directWorkoutRpe": 30},
}


@pytest.fixture(autouse=True)
async def _reset_state() -> Any:
    await server_module.get_cache_for_testing().clear()
    server_module.set_garmin_client_for_testing(None)
    yield
    server_module.set_garmin_client_for_testing(None)


def test_rating_from_summary_maps_garmin_scales() -> None:
    r = server_module._rating_from_summary(RATED)
    assert r == {"feel": "Muy bien", "feel_raw": 100, "rpe": 3}
    assert server_module._rating_from_summary({"summaryDTO": {"directWorkoutFeel": 50}}) == {
        "feel": "Normal",
        "feel_raw": 50,
    }
    assert server_module._rating_from_summary({"summaryDTO": {}}) == {}
    assert server_module._rating_from_summary(None) == {}


@pytest.mark.asyncio
async def test_activity_details_include_feel_and_rpe() -> None:
    fake = FakeGarminClient(
        {
            "get_activity": RATED,
            "get_activity_splits": {"lapDTOs": []},
            "get_activity_hr_in_timezones": [],
        }
    )
    server_module.set_garmin_client_for_testing(fake)
    detail = await server_module.get_activity_details("24666070902")
    assert detail.feel == "Muy bien" and detail.feel_raw == 100 and detail.rpe == 3


@pytest.mark.asyncio
async def test_activities_by_date_adds_rating_and_drops_noise() -> None:
    acts = [
        {"activityId": 1, "activityName": "Rodaje", "userRoles": ["X"] * 30},
        {"activityId": 2, "activityName": "Pesas"},
    ]

    def activity(aid: str) -> dict[str, Any]:
        return RATED if aid == "1" else {"summaryDTO": {}}

    fake = FakeGarminClient({"get_activities_by_date": acts, "get_activity": activity})
    server_module.set_garmin_client_for_testing(fake)
    result = await extra_tools.get_activities_by_date("2026-10-09", "2026-10-14")
    first, second = result.data
    assert first["feel"] == "Muy bien" and first["rpe"] == 3 and "userRoles" not in first
    assert "feel" not in second
    off = await extra_tools.get_activities_by_date(
        "2026-10-09", "2026-10-14", include_feedback=False
    )
    assert "feel" not in off.data[0]
