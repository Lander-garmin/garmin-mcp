"""Tests for the watch app API (garmin_mcp.watch_api)."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from typing import Any

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Route

from garmin_mcp import server as server_module
from garmin_mcp import watch_api
from garmin_mcp.garmin_client import GarminClientError
from garmin_mcp.strength_builder import (
    BlockSpec,
    SetSpec,
    StrengthWorkoutSpec,
    build_strength_workout,
)
from tests.test_tools import FakeGarminClient

SECRET = "x" * 48


def _workout() -> dict[str, Any]:
    bench = SetSpec(
        category="BENCH_PRESS",
        exercise_name="BARBELL_BENCH_PRESS",
        reps=8,
        weight=80,
        weight_unit="kg",
        note="Objetivo: 82,5 kg",
    )
    raise_ = SetSpec(
        category="LATERAL_RAISE",
        exercise_name="DUMBBELL_LATERAL_RAISE",
        reps=15,
        weight=30,
        weight_unit="lb",
    )
    plank = SetSpec(category="PLANK", exercise_name="PLANK", seconds=45)
    spec = StrengthWorkoutSpec(
        name="Plan X 30/09 Pesas Push 70 min",
        blocks=[
            BlockSpec(sets=4, exercises=[bench], rest_seconds=120),
            BlockSpec(sets=3, exercises=[raise_]),
            BlockSpec(sets=1, exercises=[plank]),
        ],
    )
    payload = build_strength_workout(spec)
    payload["workoutId"] = 555
    return payload


def test_flatten_strength_workout() -> None:
    ex = watch_api.flatten_strength_workout(_workout())
    assert [e["e"] for e in ex] == ["BARBELL_BENCH_PRESS", "DUMBBELL_LATERAL_RAISE", "PLANK"]
    bench, lateral, plank = ex
    assert bench == {
        "n": "Barbell Bench Press",
        "c": "BENCH_PRESS",
        "e": "BARBELL_BENCH_PRESS",
        "s": 4,
        "rest": 120,
        "r": 8,
        "w": 80.0,
        "note": "Objetivo: 82,5 kg",
    }
    assert lateral["s"] == 3 and lateral["rest"] == 0 and lateral["w"] == 13.5  # 30 lb
    assert plank["s"] == 1 and plank["sec"] == 45 and "r" not in plank


def test_watch_key_is_derived_and_stable() -> None:
    k1 = watch_api.watch_key(SECRET)
    assert k1 == watch_api.watch_key(SECRET) and len(k1) == 32
    assert k1 != watch_api.watch_key("y" * 48)
    assert watch_api.watch_key("") == ""


def test_description_and_sets_payload() -> None:
    sets = [
        {
            "c": "BENCH_PRESS",
            "e": "BARBELL_BENCH_PRESS",
            "r": 8,
            "w": 80.0,
            "t": 1759240000,
            "d": 40,
        },
        {
            "c": "BENCH_PRESS",
            "e": "BARBELL_BENCH_PRESS",
            "r": 7,
            "w": 82.5,
            "t": 1759240200,
            "d": 42,
        },
        {"c": "PLANK", "e": "PLANK", "r": 0, "d": 45},
    ]
    desc = watch_api.build_description(sets)
    assert desc.splitlines()[0] == "Barbell Bench Press: 80x8, 82.5x7"
    assert desc.splitlines()[1] == "Plank: 0"
    assert "Volumen total: 1.218 kg" in desc
    payload = watch_api.build_exercise_sets(sets)
    assert payload[0]["exercises"][0] == {
        "category": "BENCH_PRESS",
        "name": "BARBELL_BENCH_PRESS",
        "probability": 100.0,
    }
    assert payload[0]["weight"] == 80000.0 and payload[0]["repetitionCount"] == 8
    assert payload[0]["startTime"] == "2025-09-30T13:46:40.0"
    assert "weight" not in payload[2]


def _app() -> Starlette:
    return Starlette(
        routes=[
            Route("/watch/today", watch_api.watch_today, methods=["GET"]),
            Route("/watch/log", watch_api.watch_log, methods=["POST"]),
        ]
    )


@pytest.fixture
def keyed(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(server_module, "JWT_SECRET", SECRET)
    watch_api._logs.clear()
    return watch_api.watch_key(SECRET)


@pytest.mark.asyncio
async def test_today_requires_key_and_returns_strength(keyed: str) -> None:
    today = "2026-09-30"
    fake = FakeGarminClient(
        {
            "get_scheduled_workouts": {
                "calendarItems": [
                    {"itemType": "activity", "date": today, "id": 1},
                    {"itemType": "workout", "date": today, "workoutId": 999, "title": "Run"},
                    {"itemType": "workout", "date": today, "workoutId": 555, "title": "Push"},
                ]
            },
            "get_workout_by_id": lambda wid: (
                _workout() if wid == 555 else {"sportType": {"sportTypeKey": "running"}}
            ),
        }
    )
    server_module.set_garmin_client_for_testing(fake)
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        assert (await http.get("/watch/today")).status_code == 401
        assert (await http.get("/watch/today", params={"k": "nope"})).status_code == 401
        r = await http.get("/watch/today", params={"k": keyed, "date": today})
    assert r.status_code == 200
    body = r.json()
    assert body["name"].startswith("Plan X 30/09 Pesas Push")
    assert body["id"] == "555" and len(body["ex"]) == 3
    assert len(json.dumps(body)) < 2000  # small enough for the watch


@pytest.mark.asyncio
async def test_today_without_strength_says_none(keyed: str) -> None:
    fake = FakeGarminClient({"get_scheduled_workouts": {"calendarItems": []}})
    server_module.set_garmin_client_for_testing(fake)
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        r = await http.get(
            "/watch/today", headers={"X-Watch-Key": keyed}, params={"date": "2026-09-29"}
        )
    assert r.json() == {"ok": True, "date": "2026-09-29", "none": True}


@pytest.mark.asyncio
async def test_log_is_applied_to_matching_activity(
    keyed: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    start = int(dt.datetime(2026, 9, 30, 15, 30, tzinfo=dt.UTC).timestamp())
    calls: list[tuple[Any, ...]] = []
    acts = [
        {
            "activityId": 11,
            "startTimeGMT": "2026-09-30 08:00:00",
            "activityType": {"typeKey": "running"},
        },
        {
            "activityId": 22,
            "startTimeGMT": "2026-09-30 15:31:10",
            "activityType": {"typeKey": "strength_training"},
        },
    ]
    fake = FakeGarminClient(
        {
            "get_activities_by_date": acts,
            "update_strength_activity": lambda *a: calls.append(a) or {"ok": True},
        }
    )
    server_module.set_garmin_client_for_testing(fake)
    monkeypatch.setattr(watch_api, "APPLY_RETRY_SECONDS", 0)
    body = {
        "start": start,
        "dur": 3600,
        "name": "Pesas Push",
        "sets": [
            {
                "c": "BENCH_PRESS",
                "e": "BARBELL_BENCH_PRESS",
                "r": 8,
                "w": 80,
                "t": start + 300,
                "d": 40,
            }
        ],
    }
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        bad = await http.post("/watch/log", params={"k": keyed}, content=b'{"start":1,"sets":[]}')
        assert bad.status_code == 400
        r = await http.post("/watch/log", params={"k": keyed}, content=json.dumps(body))
        again = await http.post("/watch/log", params={"k": keyed}, content=json.dumps(body))
    assert r.status_code == 200 and r.json()["ok"]
    assert again.json()["dup"] is True and again.json()["id"] == r.json()["id"]
    assert len(watch_api._logs) == 1
    for _ in range(50):
        await asyncio.sleep(0.01)
        if watch_api._logs[r.json()["id"]]["status"] == "applied":
            break
    record = watch_api._logs[r.json()["id"]]
    assert record["status"] == "applied" and record["activity_id"] == "22"
    aid, sets, title, desc = calls[0]
    assert aid == 22 and title == "Pesas Push" and sets[0]["weight"] == 80000.0
    assert desc.startswith("Barbell Bench Press: 80x8")
    logs = await watch_api.get_watch_strength_logs()
    assert logs["logs"][0]["id"] == r.json()["id"]


@pytest.mark.asyncio
async def test_apply_falls_back_to_description_when_sets_rejected(keyed: str) -> None:
    start = int(dt.datetime(2026, 9, 30, 15, 30, tzinfo=dt.UTC).timestamp())
    calls: list[tuple[Any, ...]] = []

    def update(aid: Any, sets: Any, title: Any, desc: Any) -> Any:
        calls.append((aid, sets, title, desc))
        if sets:
            raise GarminClientError("400 bad exerciseSets")
        return {"ok": True}

    fake = FakeGarminClient(
        {
            "get_activities_by_date": [
                {
                    "activityId": 22,
                    "startTimeGMT": "2026-09-30 15:30:30",
                    "activityType": {"typeKey": "strength_training"},
                }
            ],
            "update_strength_activity": update,
        }
    )
    server_module.set_garmin_client_for_testing(fake)
    watch_api._logs["abc"] = {
        "id": "abc",
        "received": 0,
        "start": start,
        "name": "Pesas",
        "sets": [{"c": "BENCH_PRESS", "e": "BARBELL_BENCH_PRESS", "r": 8, "w": 80.0}],
        "status": "queued",
    }
    await watch_api.apply_log("abc", retry_seconds=0)
    rec = watch_api._logs["abc"]
    assert rec["status"] == "partial" and "400" in rec["sets_error"]
    assert calls[-1][1] == [] and calls[-1][3].startswith("Barbell Bench Press")


def test_watch_routes_registered() -> None:
    paths = {getattr(r, "path", None) for r in server_module.mcp._custom_starlette_routes}
    assert {"/watch/today", "/watch/log"} <= paths


def test_match_window_is_tight() -> None:
    start = int(dt.datetime(2026, 9, 30, 15, 30, tzinfo=dt.UTC).timestamp())
    near = {
        "activityId": 1,
        "startTimeGMT": "2026-09-30 15:31:30",
        "activityType": {"typeKey": "strength_training"},
    }
    far = {
        "activityId": 2,
        "startTimeGMT": "2026-09-30 15:40:00",
        "activityType": {"typeKey": "strength_training"},
    }
    assert watch_api._find_activity([far, near], start) == near
    assert watch_api._find_activity([far], start) is None
