"""HTTP API for the "Pesas" Connect IQ watch app.

The Forerunner 55 has no native strength profile, so it cannot follow a
strength workout from the Garmin calendar. A small Connect IQ app fills the
gap and talks to this server through the phone's Bluetooth link:

* ``GET  /watch/today`` returns today's scheduled strength workout (the one the
  weekly Claude task put in the Garmin calendar), flattened into a compact list
  of exercises the watch can walk through.
* ``POST /watch/log`` receives the sets actually performed (exercise, reps,
  weight, time) when the session is saved. A background task waits until the
  activity shows up in Garmin Connect and attaches the sets, a title and a
  one-line-per-exercise description to it (``update_strength_activity``).

Both endpoints are protected by a watch key derived from ``JWT_SECRET`` with an
HMAC, so no extra secret has to be configured on the host; rotating
``JWT_SECRET`` also rotates the watch key.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from garmin_mcp import server as _s
from garmin_mcp.garmin_client import GarminClientError

# Looked up via vars(): this module is imported from the bottom of server.py,
# and mypy cannot infer attribute types across that import cycle.
mcp: FastMCP[Any] = vars(_s)["mcp"]
log: Any = vars(_s)["log"]

APPLY_RETRY_SECONDS = 120
APPLY_MAX_SECONDS = 3 * 60 * 60
# The app's session start and Garmin's startTimeGMT come from the same watch
# clock, so a real match is within seconds. Keep the window tight so a test log
# (e.g. from the simulator, never uploaded) cannot grab a real session.
MATCH_WINDOW_SECONDS = 3 * 60
MAX_SETS = 120
MAX_LOGS = 30

_logs: dict[str, dict[str, Any]] = {}
_tasks: set[asyncio.Task[None]] = set()


def watch_key(jwt_secret: str | None = None) -> str:
    """The key the watch app must send. Empty when auth is not configured."""
    secret = _s.JWT_SECRET if jwt_secret is None else jwt_secret
    if not secret:
        return ""
    return hmac.new(secret.encode(), b"watch-api", hashlib.sha256).hexdigest()[:32]


def _authorized(request: Request) -> bool:
    expected = watch_key()
    if not expected:
        return False
    given = request.headers.get("x-watch-key") or request.query_params.get("k") or ""
    return hmac.compare_digest(given, expected)


def _deny() -> Response:
    return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)


# ---------------------------------------------------------------------------
# Workout flattening
# ---------------------------------------------------------------------------


def _pretty(enum_name: str | None) -> str:
    if not enum_name:
        return "Ejercicio"
    return enum_name.replace("_", " ").title()


def _kg(step: dict[str, Any]) -> float | None:
    value = step.get("weightValue")
    if value is None:
        return None
    unit = (step.get("weightUnit") or {}).get("unitKey", "kilogram")
    kg = float(value) * (0.45359237 if unit == "pound" else 1.0)
    return round(kg * 2) / 2  # nearest 0.5 kg


def _exercise(step: dict[str, Any], sets: int, rest: int) -> dict[str, Any]:
    cond = (step.get("endCondition") or {}).get("conditionTypeKey")
    value = step.get("endConditionValue")
    entry: dict[str, Any] = {
        "n": _pretty(step.get("exerciseName"))[:22],
        "c": step.get("category") or "UNKNOWN",
        "e": step.get("exerciseName") or "UNKNOWN",
        "s": max(1, int(sets)),
        "rest": int(rest),
    }
    if cond == "reps" and value:
        entry["r"] = int(value)
    elif cond == "time" and value:
        entry["sec"] = int(value)
    kg = _kg(step)
    if kg is not None:
        entry["w"] = kg
    note = step.get("description")
    if note:
        entry["note"] = str(note)[:48]
    return entry


def _rest_seconds(step: dict[str, Any]) -> int:
    cond = (step.get("endCondition") or {}).get("conditionTypeKey")
    if cond == "time":
        return int(step.get("endConditionValue") or 0)
    return 0


def flatten_strength_workout(workout: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn a Garmin strength workout JSON into an ordered exercise list."""
    out: list[dict[str, Any]] = []
    for segment in workout.get("workoutSegments") or []:
        for step in segment.get("workoutSteps") or []:
            kind = (step.get("stepType") or {}).get("stepTypeKey")
            if step.get("type") == "RepeatGroupDTO" or kind == "repeat":
                children = step.get("workoutSteps") or []
                rest = 0
                for child in children:
                    if (child.get("stepType") or {}).get("stepTypeKey") == "rest":
                        rest = _rest_seconds(child)
                sets = int(step.get("numberOfIterations") or step.get("endConditionValue") or 1)
                for child in children:
                    if (child.get("stepType") or {}).get("stepTypeKey") in ("interval", "active"):
                        out.append(_exercise(child, sets, rest))
            elif kind in ("interval", "active") and step.get("exerciseName"):
                out.append(_exercise(step, 1, 0))
    return out


def _is_strength(workout: dict[str, Any]) -> bool:
    return (workout.get("sportType") or {}).get("sportTypeKey") == "strength_training"


async def todays_strength_workout(date: str) -> dict[str, Any]:
    client = _s._get_garmin()
    day = dt.date.fromisoformat(date)
    calendar = await client.call("get_scheduled_workouts", day.year, day.month)
    items = (calendar or {}).get("calendarItems") or []
    candidates = [
        i
        for i in items
        if i.get("itemType") == "workout" and i.get("date") == date and i.get("workoutId")
    ]
    for item in candidates:
        workout = await client.call("get_workout_by_id", item["workoutId"])
        if isinstance(workout, dict) and _is_strength(workout):
            name = str(workout.get("workoutName") or item.get("title") or "Pesas")
            return {
                "ok": True,
                "date": date,
                "id": str(item["workoutId"]),
                "name": name[:40],
                "ex": flatten_strength_workout(workout),
            }
    return {"ok": True, "date": date, "none": True}


# ---------------------------------------------------------------------------
# Applying a performed session to the Garmin activity
# ---------------------------------------------------------------------------


def _gmt(epoch: int) -> str:
    return dt.datetime.fromtimestamp(epoch, tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.0")


def build_exercise_sets(sets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Garmin Connect exerciseSets payload (weights in grams, times in GMT)."""
    out: list[dict[str, Any]] = []
    for s in sets:
        entry: dict[str, Any] = {
            "exercises": [{"category": s["c"], "name": s["e"], "probability": 100.0}],
            "setType": "ACTIVE",
            "repetitionCount": int(s.get("r") or 0),
            "duration": float(s.get("d") or 0),
        }
        if s.get("w") is not None:
            entry["weight"] = round(float(s["w"]) * 1000.0, 1)
        if s.get("t"):
            entry["startTime"] = _gmt(int(s["t"]))
        out.append(entry)
    return out


def build_description(sets: list[dict[str, Any]]) -> str:
    """One line per exercise: 'Barbell Bench Press: 80x8, 80x8, 82.5x7'."""
    order: list[str] = []
    per: dict[str, list[str]] = {}
    for s in sets:
        key = _pretty(s.get("e"))
        if key not in per:
            order.append(key)
            per[key] = []
        reps = int(s.get("r") or 0)
        w = s.get("w")
        per[key].append(f"{float(w):g}x{reps}" if w is not None else f"{reps}")
    lines = [f"{k}: {', '.join(per[k])}" for k in order]
    total = sum(float(s.get("w") or 0) * int(s.get("r") or 0) for s in sets)
    lines.append(
        f"Volumen total: {total:,.0f} kg · {len(sets)} series · app Pesas".replace(",", ".")
    )
    return "\n".join(lines)


def _parse_gmt(value: str | None) -> float | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(value, fmt).replace(tzinfo=dt.UTC).timestamp()
        except ValueError:
            continue
    return None


def _find_activity(activities: Any, start: int) -> dict[str, Any] | None:
    best: tuple[float, dict[str, Any]] | None = None
    for act in activities or []:
        if not isinstance(act, dict):
            continue
        ts = _parse_gmt(act.get("startTimeGMT"))
        if ts is None:
            continue
        gap = abs(ts - start)
        if gap > MATCH_WINDOW_SECONDS:
            continue
        type_key = (act.get("activityType") or {}).get("typeKey", "")
        # Prefer the strength activity the app recorded; tie-break on time.
        score = gap + (0 if "strength" in type_key else 3600)
        if best is None or score < best[0]:
            best = (score, act)
    return best[1] if best else None


async def apply_log(log_id: str, retry_seconds: float | None = None) -> None:
    record = _logs[log_id]
    retry = APPLY_RETRY_SECONDS if retry_seconds is None else retry_seconds
    deadline = time.time() + APPLY_MAX_SECONDS
    start = int(record["start"])
    local_day = dt.datetime.fromtimestamp(start).date().isoformat()
    client = _s._get_garmin()
    while True:
        record["attempts"] = record.get("attempts", 0) + 1
        try:
            acts = await client.call("get_activities_by_date", local_day, local_day, None)
            activity = _find_activity(acts, start)
            if activity is not None:
                aid = activity["activityId"]
                title = record.get("name") or "Pesas"
                desc = build_description(record["sets"])
                try:
                    await client.call(
                        "update_strength_activity",
                        aid,
                        build_exercise_sets(record["sets"]),
                        title,
                        desc,
                    )
                    record.update(status="applied", activity_id=str(aid))
                except GarminClientError as exc:
                    # Keep at least the title and the readable summary.
                    record["sets_error"] = str(exc)[:300]
                    await client.call("update_strength_activity", aid, [], title, desc)
                    record.update(status="partial", activity_id=str(aid))
                log.info("watch.log.applied", log_id=log_id, status=record["status"])
                return
            record["status"] = "waiting_for_activity"
        except GarminClientError as exc:
            record.update(status="error_retrying", error=str(exc)[:300])
            log.warning("watch.log.apply_failed", log_id=log_id, error=str(exc)[:200])
        if time.time() > deadline:
            record["status"] = "gave_up"
            return
        await asyncio.sleep(retry)


def _validate_sets(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("sets must be a non-empty list")
    out: list[dict[str, Any]] = []
    for s in raw[:MAX_SETS]:
        if not isinstance(s, dict) or not s.get("c") or not s.get("e"):
            raise ValueError("each set needs c (category) and e (exercise)")
        item: dict[str, Any] = {
            "c": str(s["c"])[:60],
            "e": str(s["e"])[:80],
            "r": max(0, min(int(s.get("r") or 0), 1000)),
            "d": max(0, min(int(s.get("d") or 0), 3600)),
        }
        if s.get("w") is not None:
            item["w"] = max(0.0, min(float(s["w"]), 1000.0))
        if s.get("t"):
            item["t"] = int(s["t"])
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Routes and tool
# ---------------------------------------------------------------------------


@mcp.custom_route("/watch/today", methods=["GET"])  # type: ignore[untyped-decorator]
async def watch_today(request: Request) -> Response:
    if not _authorized(request):
        return _deny()
    date = request.query_params.get("date") or _s._today_iso()
    try:
        dt.date.fromisoformat(date)
        body = await todays_strength_workout(date)
    except ValueError:
        return JSONResponse({"ok": False, "error": "bad date"}, status_code=400)
    except GarminClientError as exc:
        return JSONResponse({"ok": False, "error": str(exc)[:120]}, status_code=502)
    return JSONResponse(body)


@mcp.custom_route("/watch/log", methods=["POST"])  # type: ignore[untyped-decorator]
async def watch_log(request: Request) -> Response:
    if not _authorized(request):
        return _deny()
    try:
        data = json.loads(await request.body())
        sets = _validate_sets(data.get("sets"))
        start = int(data["start"])
    except (ValueError, KeyError, TypeError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)[:120]}, status_code=400)
    # The app re-sends a session it could not confirm (e.g. it was closed while
    # sending). Treat the same start + same number of sets as the same log.
    for existing in _logs.values():
        if existing["start"] == start and len(existing["sets"]) == len(sets):
            return JSONResponse({"ok": True, "id": existing["id"], "sets": len(sets), "dup": True})
    log_id = secrets.token_hex(6)
    _logs[log_id] = {
        "id": log_id,
        "received": int(time.time()),
        "start": start,
        "dur": int(data.get("dur") or 0),
        "name": str(data.get("name") or "Pesas")[:60],
        "sets": sets,
        "status": "queued",
    }
    for old in sorted(_logs, key=lambda k: _logs[k]["received"])[:-MAX_LOGS]:
        _logs.pop(old, None)
    task = asyncio.create_task(apply_log(log_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    log.info("watch.log.received", log_id=log_id, sets=len(sets))
    return JSONResponse({"ok": True, "id": log_id, "sets": len(sets)})


@mcp.tool()
async def get_watch_strength_logs() -> dict[str, Any]:
    """Strength sessions sent by the "Pesas" watch app since the server started.

    Each entry has the performed sets (exercise enum, reps, kg), the matched
    Garmin activity_id and a status: queued, waiting_for_activity, applied
    (sets written to the activity), partial (only title/description written),
    gave_up. Use get_strength_sets(activity_id) for the saved sets afterwards.
    """
    return {
        "logs": sorted(_logs.values(), key=lambda r: r["received"], reverse=True),
        "note": "In-memory: cleared when the server restarts.",
    }
