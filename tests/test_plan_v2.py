"""Plan format v2: kg by default, warm-up sets, timed/distance sets, supersets on
the watch, generic exercises, cycling workouts and the training-rules tool."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from garmin_mcp import rules, watch_api
from garmin_mcp import server as server_module
from garmin_mcp.models import (
    CyclingWorkoutInput,
    StrengthBlockInput,
    StrengthExerciseInput,
    StrengthWorkoutInput,
)
from garmin_mcp.running_builder import build_cycling_workout
from garmin_mcp.strength_builder import build_strength_workout, lint


def _steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return payload["workoutSegments"][0]["workoutSteps"]


def _legs() -> StrengthWorkoutInput:
    return StrengthWorkoutInput(
        name="Plan X 21/10 Pesas Legs 65 min",
        blocks=[
            StrengthBlockInput(
                sets=3,
                rest_seconds=180,
                warmup={"reps": 8, "weight": 40},
                exercises=[
                    StrengthExerciseInput(
                        name="Barbell Back Squat",
                        reps=8,
                        weight=80,
                        display_name="Sentadilla",
                        note="peso fijo",
                    )
                ],
            ),
            StrengthBlockInput(
                sets=3,
                rest_seconds=180,
                exercises=[
                    StrengthExerciseInput(
                        name="Back Extension", reps=20, weight=20, display_name="Hiperextension"
                    )
                ],
            ),
            StrengthBlockInput(
                sets=3,
                rest_seconds=180,
                exercises=[
                    StrengthExerciseInput(
                        name="Sled Push", seconds=60, weight=110, display_name="Empuje trineo"
                    )
                ],
            ),
            StrengthBlockInput(
                sets=3,
                rest_seconds=180,
                exercises=[
                    StrengthExerciseInput(name="Toes To Bar", reps=15, display_name="Pies a barra"),
                    StrengthExerciseInput(name="Crunch", reps=12, display_name="Abdominal corto"),
                ],
            ),
        ],
    )


def test_spec_maps_rules_exercises_in_kg() -> None:
    spec, infos, warnings = server_module._spec_from_input(_legs())
    assert warnings == [] and lint(spec) == []
    by_query = {i.query: (i.category, i.exercise_name) for i in infos}
    assert by_query["Back Extension"] == ("HYPEREXTENSION", "HYPEREXTENSION")
    assert by_query["Sled Push"] == ("SLED", "PUSH")
    steps = _steps(build_strength_workout(spec))
    warm, warm_rest, squat_group = steps[0], steps[1], steps[2]
    assert warm["stepType"]["stepTypeKey"] == "warmup"
    assert warm["exerciseName"] == "BARBELL_BACK_SQUAT" and warm["weightValue"] == 40.0
    assert warm["weightUnit"]["unitKey"] == "kilogram"
    assert warm["description"] == "Sentadilla - Calentamiento"
    assert warm_rest["endConditionValue"] == 180.0
    squat = squat_group["workoutSteps"][0]
    assert squat["description"] == "Sentadilla - peso fijo"
    hyper = steps[3]["workoutSteps"][0]
    assert hyper["category"] == "HYPEREXTENSION" and hyper["exerciseName"] is None
    sled = steps[4]["workoutSteps"][0]
    assert sled["endCondition"]["conditionTypeKey"] == "time"
    assert sled["endConditionValue"] == 60.0 and sled["weightValue"] == 110.0
    superset = steps[5]["workoutSteps"]
    assert [s["stepType"]["stepTypeKey"] for s in superset] == ["interval", "interval", "rest"]


def test_lint_flags_pounds_blocks_and_lap_rest() -> None:
    blocks = [
        StrengthBlockInput(sets=3, exercises=[StrengthExerciseInput(name="Crunch", reps=12)])
        for _ in range(7)
    ]
    blocks[0].exercises[0].weight = 10
    blocks[0].exercises[0].weight_unit = "lb"
    spec, _infos, _w = server_module._spec_from_input(
        StrengthWorkoutInput(name="x", blocks=blocks, include_warmup=True)
    )
    text = " | ".join(lint(spec))
    assert "7 blocks" in text and "pounds" in text and "lap button" in text
    assert "include_warmup" in text


def test_distance_set_and_single_set_rest() -> None:
    workout = StrengthWorkoutInput(
        name="Plan X 21/10 Pesas Hyrox 55 min",
        blocks=[
            StrengthBlockInput(
                sets=1,
                rest_seconds=60,
                exercises=[StrengthExerciseInput(name="Treadmill", seconds=600)],
            ),
            StrengthBlockInput(
                sets=3,
                rest_seconds=120,
                exercises=[
                    StrengthExerciseInput(name="Treadmill", meters=1000),
                    StrengthExerciseInput(name="SkiErg", meters=500),
                    StrengthExerciseInput(name="Wall Balls", reps=30, weight=6),
                ],
            ),
        ],
    )
    spec, _infos, warnings = server_module._spec_from_input(workout)
    assert warnings == []
    steps = _steps(build_strength_workout(spec))
    assert steps[0]["endConditionValue"] == 600.0 and steps[1]["stepType"]["stepTypeKey"] == "rest"
    run = steps[2]["workoutSteps"][0]
    assert run["endCondition"]["conditionTypeKey"] == "distance"
    assert run["endConditionValue"] == 1000.0

    blocks = watch_api.strength_blocks(build_strength_workout(spec))
    assert blocks[0] == {
        "s": 1,
        "rest": 60,
        "x": [{"n": "Cinta", "c": "RUN_INDOOR", "e": "TREADMILL", "sec": 600}],
    }
    assert blocks[1]["s"] == 3 and blocks[1]["rest"] == 120
    assert [x.get("m") for x in blocks[1]["x"]] == [1000, 500, None]
    assert blocks[1]["x"][1]["n"] == "SkiErg" and blocks[1]["x"][1]["e"] == "CHOP"


def test_watch_blocks_keep_supersets_and_warmup() -> None:
    spec, _i, _w = server_module._spec_from_input(_legs())
    blocks = watch_api.strength_blocks(build_strength_workout(spec))
    assert blocks[0] == {
        "s": 1,
        "rest": 180,
        "wu": 1,
        "x": [{"n": "Sentadilla", "c": "SQUAT", "e": "BARBELL_BACK_SQUAT", "r": 8, "w": 40.0}],
    }
    hyper = blocks[2]["x"][0]
    assert hyper == {
        "n": "Hiperextension",
        "c": "HYPEREXTENSION",
        "e": "HYPEREXTENSION",
        "r": 20,
        "w": 20.0,
    }
    assert blocks[3]["x"][0] == {
        "n": "Empuje trineo",
        "c": "SLED",
        "e": "PUSH",
        "sec": 60,
        "w": 110.0,
    }
    assert [x["n"] for x in blocks[4]["x"]] == ["Pies a barra", "Abdominal corto"]
    assert blocks[4]["s"] == 3 and blocks[4]["rest"] == 180


def test_timed_set_logged_with_duration_not_reps() -> None:
    sets = watch_api._validate_sets(
        [
            {"c": "SLED", "e": "PUSH", "sec": 60, "d": 61, "w": 110},
            {"c": "HYPEREXTENSION", "e": "HYPEREXTENSION", "r": 20, "w": 20, "d": 50},
            {"c": "ROW", "e": "INDOOR_ROW", "m": 500, "d": 105},
        ]
    )
    payload = watch_api.build_exercise_sets(sets)
    assert payload[0]["repetitionCount"] is None and payload[0]["duration"] == 61.0
    assert payload[0]["weight"] == 110000.0
    assert payload[1]["exercises"][0] == {
        "category": "HYPEREXTENSION",
        "name": None,
        "probability": 100.0,
    }
    desc = watch_api.build_description(sets).splitlines()
    assert desc[0] == "Empuje trineo: 110x61s"
    assert desc[1] == "Hiperextension: 20x20"
    assert desc[2] == "Remo ergometro: 500m 1:45"
    assert "Volumen total: 400 kg" in desc[3]


def test_rating_validation() -> None:
    assert watch_api._validate_rating({"feel": 75, "rpe": 7}) == (75, 70)
    assert watch_api._validate_rating({"feel": 60, "rpe": 11}) == (None, None)
    assert watch_api._validate_rating({}) == (None, None)


def test_cycling_workout_uses_cycling_sport_and_hr_target() -> None:
    ride = CyclingWorkoutInput(
        name="Plan S 24/10 Bici larga 2h30",
        steps=[
            {"type": "warmup", "duration_seconds": 600},
            {"type": "active", "duration_seconds": 8100, "hr_min_bpm": 119, "hr_max_bpm": 139},
        ],
    )
    payload = build_cycling_workout(ride)
    assert payload["sportType"]["sportTypeKey"] == "cycling"
    main = payload["workoutSegments"][0]["workoutSteps"][1]
    assert main["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert (main["targetValueOne"], main["targetValueTwo"]) == (119.0, 139.0)
    paced = CyclingWorkoutInput(
        name="x",
        steps=[
            {
                "type": "active",
                "duration_seconds": 60,
                "pace_min_per_km": "4:00",
                "pace_max_per_km": "4:30",
            }
        ],
    )
    with pytest.raises(ValueError, match="heart-rate"):
        build_cycling_workout(paced)


def test_week_letters_alternate_from_reference() -> None:
    assert rules.week_letter(dt.date(2026, 10, 19)) == "B"
    assert rules.week_letter(dt.date(2026, 10, 25)) == "B"
    assert rules.week_letter(dt.date(2026, 10, 26)) == "A"
    assert rules.week_letter(dt.date(2026, 10, 14)) == "A"
    plan = rules.week_plan(dt.date(2026, 10, 21))
    assert plan["days"][0]["names"] == ["Descanso total (no programar)"]
    assert plan["days"][2]["names"] == ["Plan X 21/10 Pesas Hyrox 55 min"]
    # Tuesday is Pull only: no run after the gym (Lander, 27/10/2026)
    assert plan["days"][1]["names"] == ["Plan M 20/10 Pesas Pull 65 min"]


@pytest.mark.asyncio
async def test_get_training_rules_returns_rules_and_next_week() -> None:
    out = await rules.get_training_rules("2026-10-18")
    assert out["next_week"]["letter"] == "B" and out["next_week"]["monday"] == "2026-10-19"
    assert "Hiperextensión con disco de 20 kg" in out["rules"]
    assert "SIN aducción" in out["rules"]
