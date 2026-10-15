"""Build Garmin strength-workout JSON from a structured spec.

The vendored ``garminconnect`` library has no strength model, so we hand-build
the payload that ``upload_workout(dict)`` POSTs to ``/workout-service/workout``.
Every magic number here is documented in ``docs/strength_workout_schema.md`` and
was captured from real workouts on the account owner's watch.

Design choices for v1 (an RPE / auto-regulated program with no prescribed loads):
* Weight is optional and **omitted** when absent — the lifter logs actual load
  per set on the watch (also dodges the known lb↔kg display bug).
* Reps use the native ``reps`` end condition (id 10) — confirmed working via JSON.
* "Sets" are a repeat group; a **superset** is >1 exercise inside one group.
* Rest ends on ``lap.button`` (user-controlled), matching the captured workouts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --- Garmin enum constants (see docs/strength_workout_schema.md) --------------
_SPORT_STRENGTH = {"sportTypeId": 5, "sportTypeKey": "strength_training", "displayOrder": 5}

_STEP_WARMUP = {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1}
_STEP_INTERVAL = {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3}
_STEP_REST = {"stepTypeId": 5, "stepTypeKey": "rest", "displayOrder": 5}
_STEP_REPEAT = {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6}

_END_LAP = {
    "conditionTypeId": 1,
    "conditionTypeKey": "lap.button",
    "displayOrder": 1,
    "displayable": True,
}
_END_TIME = {
    "conditionTypeId": 2,
    "conditionTypeKey": "time",
    "displayOrder": 2,
    "displayable": True,
}
_END_DISTANCE = {
    "conditionTypeId": 3,
    "conditionTypeKey": "distance",
    "displayOrder": 3,
    "displayable": True,
}
_END_ITER = {
    "conditionTypeId": 7,
    "conditionTypeKey": "iterations",
    "displayOrder": 7,
    "displayable": False,
}
_END_REPS = {
    "conditionTypeId": 10,
    "conditionTypeKey": "reps",
    "displayOrder": 10,
    "displayable": True,
}

_TARGET_NONE = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
_UNIT_POUND = {"unitId": 9, "unitKey": "pound", "factor": 453.59237}
_UNIT_KILOGRAM = {"unitId": 8, "unitKey": "kilogram", "factor": 1000.0}
_UNIT_METER = {"unitId": 1, "unitKey": "meter", "factor": 100.0}

# Lint threshold for previews (house rule: at most 6 blocks per session).
MAX_BLOCKS = 6

# Accepted spellings for the two units, normalised to Garmin's canonical key.
# Without this, any value that is not exactly "kilogram" (e.g. "kg") silently
# falls through to pounds — a ~2.2x load mis-record on the write path.
_WEIGHT_UNIT_ALIASES: dict[str, str] = {
    "pound": "pound",
    "pounds": "pound",
    "lb": "pound",
    "lbs": "pound",
    "kilogram": "kilogram",
    "kilograms": "kilogram",
    "kilo": "kilogram",
    "kilos": "kilogram",
    "kg": "kilogram",
    "kgs": "kilogram",
}


def normalize_weight_unit(unit: str) -> str:
    """Canonicalise a weight unit to 'pound' or 'kilogram'; raise on unknown."""
    key = unit.strip().lower()
    try:
        return _WEIGHT_UNIT_ALIASES[key]
    except KeyError:
        raise ValueError(
            f"weight_unit {unit!r} is not recognised; use 'pound'/'lb' or 'kilogram'/'kg'."
        ) from None


@dataclass
class SetSpec:
    """One exercise performed inside a block.

    Exactly one end condition: ``reps`` (native reps), ``seconds`` (a timed set,
    e.g. a 60 s sled push; the watch counts down) or ``meters`` (a distance
    set, e.g. 500 m on the rower). ``weight``/``weight_unit`` are optional and
    combine with any of them; omitted from the payload when ``weight`` is None.
    """

    category: str
    exercise_name: str
    reps: int | None = None
    seconds: int | None = None
    meters: float | None = None
    weight: float | None = None
    weight_unit: str = "kilogram"  # "pound" | "kilogram"
    label: str | None = None  # human-readable, for the preview summary
    note: str | None = None  # -> step description (after display_name)
    # Name shown on the watch (e.g. Spanish "Hiperextension"); it leads the step
    # description so the Pesas app and Garmin Connect both show it.
    display_name: str | None = None

    def __post_init__(self) -> None:
        # Normalise here so both the payload (_weight_unit_obj) and the preview
        # (summarize) agree, and an unknown unit fails loud rather than silently
        # becoming pounds, regardless of who built the SetSpec.
        self.weight_unit = normalize_weight_unit(self.weight_unit)
        given = [x for x in (self.reps, self.seconds, self.meters) if x is not None]
        if len(given) != 1:
            raise ValueError(
                f"{self.label or self.exercise_name}: give exactly one of reps, seconds or meters"
            )

    @property
    def description(self) -> str | None:
        if self.display_name and self.note:
            if self.note.lower().startswith(self.display_name.lower()):
                return self.note
            return f"{self.display_name} - {self.note}"
        return self.display_name or self.note


@dataclass
class BlockSpec:
    """A repeat group: ``sets`` rounds of ``exercises`` (>1 = superset), then rest.

    ``warmup`` is one lighter set of the block's first exercise, done before
    the working sets and followed by the same rest.
    """

    sets: int
    exercises: list[SetSpec]
    rest_after_set: bool = True  # add a rest step inside the group
    # Rest length. None -> the rest ends on the lap button (user-controlled);
    # a number -> a timed countdown the watch vibrates at, like a gym app timer.
    rest_seconds: int | None = None
    warmup: SetSpec | None = None


@dataclass
class StrengthWorkoutSpec:
    name: str
    blocks: list[BlockSpec]
    include_warmup: bool = False
    notes: str | None = None  # written to the workout description


@dataclass
class _Counter:
    value: int = 0

    def next(self) -> int:
        self.value += 1
        return self.value


def _weight_unit_obj(unit: str) -> dict[str, Any]:
    return _UNIT_KILOGRAM if unit == "kilogram" else _UNIT_POUND


def _interval_step(
    s: SetSpec, order: int, step_type: dict[str, Any] = _STEP_INTERVAL
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": step_type,
        "targetType": _TARGET_NONE,
        "category": s.category,
        # A bare category (e.g. HYPEREXTENSION/HYPEREXTENSION) is Garmin's generic
        # exercise: it is stored with no exerciseName, so don't send one.
        "exerciseName": None if s.exercise_name == s.category else s.exercise_name,
    }
    if s.reps is not None:
        step["endCondition"], step["endConditionValue"] = _END_REPS, float(s.reps)
    elif s.seconds is not None:
        step["endCondition"], step["endConditionValue"] = _END_TIME, float(s.seconds)
    else:
        step["endCondition"], step["endConditionValue"] = _END_DISTANCE, float(s.meters or 0)
        step["preferredEndConditionUnit"] = _UNIT_METER
    description = s.description
    if description:
        step["description"] = description
    if s.weight is not None:
        step["weightValue"] = float(s.weight)
        step["weightUnit"] = _weight_unit_obj(s.weight_unit)
    return step


def _rest_step(order: int, seconds: int | None = None) -> dict[str, Any]:
    timed = seconds is not None and seconds > 0
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": _STEP_REST,
        "endCondition": _END_TIME if timed else _END_LAP,
        "endConditionValue": float(seconds) if timed and seconds is not None else 0.0,
        "targetType": _TARGET_NONE,
    }


def _warmup_step(order: int) -> dict[str, Any]:
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": _STEP_WARMUP,
        "endCondition": _END_LAP,
        "endConditionValue": 0.0,
        "targetType": _TARGET_NONE,
    }


def build_strength_workout(spec: StrengthWorkoutSpec) -> dict[str, Any]:
    """Return the Garmin Connect JSON payload for a strength workout."""
    if not spec.blocks:
        raise ValueError("workout has no blocks")

    counter = _Counter()
    steps: list[dict[str, Any]] = []

    if spec.include_warmup:
        steps.append(_warmup_step(counter.next()))

    for block in spec.blocks:
        if block.sets < 1:
            raise ValueError("a block needs at least 1 set")
        if not block.exercises:
            raise ValueError("a block needs at least 1 exercise")

        if block.warmup is not None:
            steps.append(_interval_step(block.warmup, counter.next(), _STEP_WARMUP))
            if block.rest_seconds:
                steps.append(_rest_step(counter.next(), block.rest_seconds))

        if block.sets == 1:
            # Single set: emit the exercise step(s) inline, no repeat wrapper,
            # then the timed rest so the countdown still runs before the next block.
            for s in block.exercises:
                steps.append(_interval_step(s, counter.next()))
            if block.rest_after_set and block.rest_seconds:
                steps.append(_rest_step(counter.next(), block.rest_seconds))
            continue

        group_order = counter.next()
        children: list[dict[str, Any]] = [
            _interval_step(s, counter.next()) for s in block.exercises
        ]
        if block.rest_after_set:
            children.append(_rest_step(counter.next(), block.rest_seconds))
        steps.append(
            {
                "type": "RepeatGroupDTO",
                "stepOrder": group_order,
                "stepType": _STEP_REPEAT,
                "numberOfIterations": block.sets,
                "endCondition": _END_ITER,
                "endConditionValue": float(block.sets),
                "smartRepeat": False,
                "skipLastRestStep": False,
                "workoutSteps": children,
            }
        )

    payload: dict[str, Any] = {
        "workoutName": spec.name,
        "sportType": _SPORT_STRENGTH,
        "estimatedDurationInSecs": 0,
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": _SPORT_STRENGTH,
                "workoutSteps": steps,
            }
        ],
    }
    if spec.notes:
        payload["description"] = spec.notes
    return payload


def _target(s: SetSpec) -> str:
    if s.reps is not None:
        return f" {s.reps} reps"
    if s.seconds is not None:
        return f" {s.seconds}s"
    return f" {s.meters:g}m"


def _set_label(s: SetSpec) -> str:
    unit = "kg" if s.weight_unit == "kilogram" else "lb"
    weight = f" @ {s.weight:g}{unit}" if s.weight is not None else ""
    shown = f" [{s.display_name}]" if s.display_name else ""
    return (s.label or s.exercise_name) + shown + _target(s) + weight


def summarize(spec: StrengthWorkoutSpec) -> str:
    """Human-readable one-block-per-line summary for previews."""
    lines = [f"# {spec.name}"]
    if spec.include_warmup:
        lines.append("  warmup (press lap to start)")
    for block in spec.blocks:
        if block.warmup is not None:
            lines.append(f"  1x warmup {_set_label(block.warmup)}")
        names = " + ".join(_set_label(s) for s in block.exercises)
        tag = "superset" if len(block.exercises) > 1 else "exercise"
        rest = ""
        if block.rest_after_set:
            rest = f", rest {block.rest_seconds}s" if block.rest_seconds else ", rest: lap"
        lines.append(f"  {block.sets}x {names}   ({tag}{rest})")
    if spec.notes:
        lines.append(f"  notes: {spec.notes}")
    return "\n".join(lines)


def lint(spec: StrengthWorkoutSpec) -> list[str]:
    """Rule checks shown as preview warnings (they do not block the create)."""
    out: list[str] = []
    if len(spec.blocks) > MAX_BLOCKS:
        out.append(f"{len(spec.blocks)} blocks: the limit is {MAX_BLOCKS}")
    if spec.include_warmup:
        out.append("include_warmup adds a lap-button step; use a block 'warmup' set instead")
    for i, block in enumerate(spec.blocks, 1):
        if block.rest_after_set and not block.rest_seconds:
            out.append(f"block {i}: no rest_seconds, rest ends on the lap button (no countdown)")
        sets = list(block.exercises) + ([block.warmup] if block.warmup else [])
        for st in sets:
            if st.weight is not None and st.weight_unit != "kilogram":
                out.append(f"block {i}: '{st.label or st.exercise_name}' weight is in pounds")
    return out
