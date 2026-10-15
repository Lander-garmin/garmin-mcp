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
import unicodedata
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
# Coach note for the Trainer widget: {"date": "YYYY-MM-DD", "text": "..."}.
_note: dict[str, str] = {}
NOTE_MAX = 40
# Longer coach messages readable inside the Trainer widget (START on the watch).
# kind -> {"date": "YYYY-MM-DD", "text": "..."}; "week" stays valid for 7 days.
_messages: dict[str, dict[str, str]] = {}
MESSAGE_KINDS = {"morning": 600, "evening": 600, "week": 900}
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


# Spanish names for the watch when the plan note does not carry one. Keyed by
# exerciseName, or by category for Garmin's generic (category-only) exercises.
_ES_NAMES: dict[str, str] = {
    "BARBELL_BENCH_PRESS": "Press banca",
    "SEATED_DUMBBELL_SHOULDER_PRESS": "Press hombro manc.",
    "WEIGHT_PLATE_FRONT_RAISE": "Elev. frontal disco",
    "CABLE_CROSSOVER": "Cruce de poleas",
    "TRICEPS_PRESSDOWN": "Triceps polea",
    "DUMBBELL_LATERAL_RAISE": "Elev. laterales",
    "FACE_PULL": "Face pull",
    "CHIN_UP": "Dominada",
    "BENT_OVER_ROW_WITH_BARBELL": "Remo con barra",
    "BARBELL_ROW": "Remo con barra",
    "STRAIGHT_ARM_PULLDOWN": "Jalon brazos rectos",
    "HYPEREXTENSION": "Hiperextension",
    "DUMBBELL_HAMMER_CURL": "Curl martillo",
    "TOES_TO_BAR": "Pies a barra",
    "CRUNCH": "Abdominal corto",
    "BARBELL_BACK_SQUAT": "Sentadilla",
    "WALKING_DUMBBELL_LUNGE": "Zancadas manc.",
    "SEATED_CALF_RAISE": "Gemelo sentado",
    "WEIGHTED_SEATED_CALF_RAISE": "Gemelo sentado",
    "STANDING_HIP_ABDUCTION": "Abduccion cadera",
    "PUSH": "Empuje trineo",
    "TREADMILL": "Cinta",
    "INDOOR_ROW": "Remo ergometro",
    "CHOP": "SkiErg",
    "WALL_BALL": "Wall balls",
}
NAME_MAX = 22
_NOTE_SEPARATORS = (
    " - ",
    " " + chr(0x2014) + " ",
    " " + chr(0x2013) + " ",
)  # hyphen, em dash, en dash


def _ascii(text: str) -> str:
    """Watch fonts draw ASCII only: fold accents, drop the rest."""
    flat = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(flat.split())


def display_name(step: dict[str, Any]) -> str:
    """Name for the watch: the note's lead ('Hiperextension - 3x20'), else Spanish, else enum."""
    note = str(step.get("description") or "").strip()
    head = note
    for sep in _NOTE_SEPARATORS:
        head = head.split(sep, 1)[0]
    head = _ascii(head)
    # A lead before ' - ' is the name ('Hiperextension - 3x20'). A note with no
    # separator only counts if it reads like a name (no numbers, e.g. not
    # 'Objetivo: 82,5 kg').
    named = head != _ascii(note) or not any(ch.isdigit() for ch in head)
    if named and head and len(head) <= NAME_MAX and head.lower() != "calentamiento":
        return head
    key = step.get("exerciseName") or step.get("category") or ""
    return _ascii(
        _ES_NAMES.get(str(key)) or _pretty(step.get("exerciseName") or step.get("category"))
    )[:NAME_MAX]


def _kg(step: dict[str, Any]) -> float | None:
    value = step.get("weightValue")
    if value is None:
        return None
    unit = (step.get("weightUnit") or {}).get("unitKey", "kilogram")
    kg = float(value) * (0.45359237 if unit == "pound" else 1.0)
    return round(kg * 2) / 2  # nearest 0.5 kg


def _target(step: dict[str, Any], entry: dict[str, Any]) -> None:
    cond = (step.get("endCondition") or {}).get("conditionTypeKey")
    value = step.get("endConditionValue")
    if cond == "reps" and value:
        entry["r"] = int(value)
    elif cond == "time" and value:
        entry["sec"] = int(value)
    elif cond == "distance" and value:
        entry["m"] = round(float(value))


def _exercise(step: dict[str, Any], sets: int, rest: int) -> dict[str, Any]:
    """v1 entry (one per exercise), kept for app builds older than the block format."""
    category = step.get("category") or "UNKNOWN"
    entry: dict[str, Any] = {
        "n": display_name(step),
        "c": category,
        # Garmin's generic exercises have no exerciseName; send the category so
        # the app always has a non-empty id to log against.
        "e": step.get("exerciseName") or category,
        "s": max(1, int(sets)),
        "rest": int(rest),
    }
    _target(step, entry)
    kg = _kg(step)
    if kg is not None:
        entry["w"] = kg
    note = step.get("description")
    if note:
        entry["note"] = str(note)[:48]
    return entry


def _block_exercise(step: dict[str, Any]) -> dict[str, Any]:
    category = step.get("category") or "UNKNOWN"
    entry: dict[str, Any] = {
        "n": display_name(step),
        "c": category,
        "e": step.get("exerciseName") or category,
    }
    _target(step, entry)
    kg = _kg(step)
    if kg is not None:
        entry["w"] = kg
    return entry


def _rest_seconds(step: dict[str, Any]) -> int:
    cond = (step.get("endCondition") or {}).get("conditionTypeKey")
    if cond == "time":
        return int(step.get("endConditionValue") or 0)
    return 0


def _kind(step: dict[str, Any]) -> str:
    if step.get("type") == "RepeatGroupDTO":
        return "repeat"
    return str((step.get("stepType") or {}).get("stepTypeKey") or "")


def strength_blocks(workout: dict[str, Any]) -> list[dict[str, Any]]:
    """Garmin strength workout -> blocks the watch walks round by round.

    A block is ``{"s": sets, "rest": seconds, "x": [exercises]}``; with more
    than one exercise it is a superset: the app does x[0], x[1], ... then rests,
    ``s`` times. A warm-up set comes as its own one-set block with ``"wu": 1``.
    A top-level timed rest after a single step belongs to that step's block.
    """
    blocks: list[dict[str, Any]] = []
    for segment in workout.get("workoutSegments") or []:
        for step in segment.get("workoutSteps") or []:
            kind = _kind(step)
            if kind in ("repeat",):
                children = step.get("workoutSteps") or []
                rest = 0
                exercises = []
                for child in children:
                    ck = _kind(child)
                    if ck == "rest":
                        rest = _rest_seconds(child)
                    elif ck in ("interval", "active", "warmup") and child.get("category"):
                        exercises.append(_block_exercise(child))
                if exercises:
                    sets = int(step.get("numberOfIterations") or step.get("endConditionValue") or 1)
                    blocks.append({"s": max(1, sets), "rest": rest, "x": exercises})
            elif kind in ("interval", "active", "warmup") and step.get("category"):
                block: dict[str, Any] = {"s": 1, "rest": 0, "x": [_block_exercise(step)]}
                if kind == "warmup":
                    block["wu"] = 1
                blocks.append(block)
            elif kind == "rest" and blocks and not blocks[-1]["rest"]:
                blocks[-1]["rest"] = _rest_seconds(step)
    return blocks


def flatten_strength_workout(workout: dict[str, Any]) -> list[dict[str, Any]]:
    """v1 format: one entry per exercise (supersets are walked one exercise at a time)."""
    out: list[dict[str, Any]] = []
    for block in strength_blocks(workout):
        for ex in block["x"]:
            entry = {k: v for k, v in ex.items()}
            entry["s"], entry["rest"] = block["s"], block["rest"]
            out.append(entry)
    return out


def _is_strength(workout: dict[str, Any]) -> bool:
    return (workout.get("sportType") or {}).get("sportTypeKey") == "strength_training"


async def todays_strength_workout(date: str, version: int = 1) -> dict[str, Any]:
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
            body: dict[str, Any] = {
                "ok": True,
                "date": date,
                "id": str(item["workoutId"]),
                "name": name[:40],
            }
            if version >= 2:
                body["b"] = strength_blocks(workout)
            else:
                body["ex"] = flatten_strength_workout(workout)
            return body
    return {"ok": True, "date": date, "none": True}


# ---------------------------------------------------------------------------
# Applying a performed session to the Garmin activity
# ---------------------------------------------------------------------------


def _gmt(epoch: int) -> str:
    return dt.datetime.fromtimestamp(epoch, tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.0")


def build_exercise_sets(sets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Garmin Connect exerciseSets payload (weights in grams, times in GMT).

    A timed or distance set (sled push 60 s, 500 m row) has no reps: it is
    written with repetitionCount None and its real duration, plus its weight.
    """
    out: list[dict[str, Any]] = []
    for s in sets:
        name = None if s["e"] == s["c"] else s["e"]  # generic exercise: no name
        timed = "sec" in s or "m" in s
        entry: dict[str, Any] = {
            "exercises": [{"category": s["c"], "name": name, "probability": 100.0}],
            "setType": "ACTIVE",
            "repetitionCount": None if timed else int(s.get("r") or 0),
            "duration": float(s.get("d") or 0),
        }
        if s.get("w") is not None:
            entry["weight"] = round(float(s["w"]) * 1000.0, 1)
        if s.get("t"):
            entry["startTime"] = _gmt(int(s["t"]))
        out.append(entry)
    return out


def _mmss(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def _set_text(s: dict[str, Any]) -> str:
    kg = float(s.get("w") or 0)
    weight = f"{kg:g}x" if kg > 0 else ""
    if "m" in s:
        return f"{int(s['m'])}m {_mmss(int(s.get('d') or 0))}" + (f" {kg:g}kg" if kg > 0 else "")
    if "sec" in s:
        return f"{weight}{int(s.get('d') or s['sec'])}s"
    return f"{weight}{int(s.get('r') or 0)}"


def build_description(sets: list[dict[str, Any]], names: dict[str, str] | None = None) -> str:
    """One line per exercise: 'Press banca: 80x8, 80x8, 82.5x7'; 'Empuje trineo: 110x60s'."""
    order: list[str] = []
    per: dict[str, list[str]] = {}
    for s in sets:
        key = (
            (names or {}).get(str(s.get("e")))
            or s.get("n")
            or _ES_NAMES.get(str(s.get("e")))
            or _pretty(s.get("e"))
        )
        if key not in per:
            order.append(key)
            per[key] = []
        per[key].append(_set_text(s))
    lines = [f"{k}: {', '.join(per[k])}" for k in order]
    total = sum(
        float(s.get("w") or 0) * int(s.get("r") or 0)
        for s in sets
        if "sec" not in s and "m" not in s
    )
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
                feel, rpe = record.get("feel"), record.get("rpe")
                try:
                    await client.call(
                        "update_strength_activity",
                        aid,
                        build_exercise_sets(record["sets"]),
                        title,
                        desc,
                        feel,
                        rpe,
                    )
                    record.update(status="applied", activity_id=str(aid))
                except GarminClientError as exc:
                    # Keep at least the title, the readable summary and the rating.
                    record["sets_error"] = str(exc)[:300]
                    await client.call("update_strength_activity", aid, [], title, desc, feel, rpe)
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
            "d": max(0, min(int(s.get("d") or 0), 3600)),
        }
        if s.get("sec") is not None:
            item["sec"] = max(0, min(int(s["sec"]), 3600))
        elif s.get("m") is not None:
            item["m"] = max(0, min(int(s["m"]), 10000))
        else:
            item["r"] = max(0, min(int(s.get("r") or 0), 1000))
        if s.get("w") is not None:
            item["w"] = max(0.0, min(float(s["w"]), 1000.0))
        if s.get("t"):
            item["t"] = int(s["t"])
        if s.get("n"):
            item["n"] = _ascii(str(s["n"]))[:NAME_MAX]
        out.append(item)
    return out


FEEL_VALUES = (0, 25, 50, 75, 100)


def _validate_rating(data: dict[str, Any]) -> tuple[int | None, int | None]:
    """Post-session rating from the app: feel 0/25/50/75/100, RPE 1-10 (Garmin stores x10)."""
    feel = data.get("feel")
    rpe = data.get("rpe")
    feel_v = int(feel) if feel is not None and int(feel) in FEEL_VALUES else None
    rpe_v = int(rpe) * 10 if rpe is not None and 1 <= int(rpe) <= 10 else None
    return feel_v, rpe_v


# ---------------------------------------------------------------------------
# Watch face: today's sessions + coach note
# ---------------------------------------------------------------------------

_PLAN_PREFIX_WORDS = 3  # "Plan", day letter, dd/mm


def session_label(title: str, date: str) -> str:
    """'Plan X 30/09 Gym Push 70 min' -> '17:30 Gym Push 70 min' (usual training hours)."""
    words = title.split()
    if len(words) > _PLAN_PREFIX_WORDS and words[0] == "Plan":
        words = words[_PLAN_PREFIX_WORDS:]
    label = " ".join(words)
    weekend = dt.date.fromisoformat(date).weekday() >= 5
    strength = label.startswith(("Gym", "Pesas"))
    hour = "10:00" if weekend else ("17:30" if strength else "18:30")
    return f"{hour} {label}"[:28]


async def face_data(date: str) -> dict[str, Any]:
    client = _s._get_garmin()
    day = dt.date.fromisoformat(date)
    calendar = await client.call("get_scheduled_workouts", day.year, day.month)
    items = (calendar or {}).get("calendarItems") or []
    labels = [
        session_label(str(i.get("title") or "Entreno"), date)
        for i in items
        if i.get("itemType") == "workout" and i.get("date") == date
    ]
    body: dict[str, Any] = {"ok": True, "date": date, "items": sorted(labels)[:3]}
    if _note.get("date") == date and _note.get("text"):
        body["note"] = _note["text"]
    msgs = current_messages(date)
    if msgs:
        body["msgs"] = msgs
    return body


def watch_text(text: str) -> str:
    """Plain text the watch fonts can draw: no accents or emojis, tidy line breaks."""
    import unicodedata

    lines: list[str] = []
    for raw in text.replace(chr(13), "").split(chr(10)):
        flat = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
        line = " ".join(flat.split())
        if line or (lines and lines[-1]):
            lines.append(line)
    return chr(10).join(lines).strip()


def current_messages(date: str) -> dict[str, str]:
    """Messages to show today: morning/evening of this date, week plan of the last 7 days."""
    out: dict[str, str] = {}
    day = dt.date.fromisoformat(date)
    for kind, msg in _messages.items():
        msg_day = dt.date.fromisoformat(msg["date"])
        if kind == "week":
            if 0 <= (day - msg_day).days < 7:
                out[kind] = msg["text"]
        elif msg_day == day:
            out[kind] = msg["text"]
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
        version = int(request.query_params.get("v") or 1)
        body = await todays_strength_workout(date, version)
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
        feel, rpe = _validate_rating(data)
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
        "feel": feel,
        "rpe": rpe,
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


@mcp.custom_route("/watch/face", methods=["GET"])  # type: ignore[untyped-decorator]
async def watch_face(request: Request) -> Response:
    if not _authorized(request):
        return _deny()
    date = request.query_params.get("date") or _s._today_iso()
    try:
        body = await face_data(dt.date.fromisoformat(date).isoformat())
    except ValueError:
        return JSONResponse({"ok": False, "error": "bad date"}, status_code=400)
    except GarminClientError as exc:
        return JSONResponse({"ok": False, "error": str(exc)[:120]}, status_code=502)
    return JSONResponse(body)


@mcp.tool()
async def set_watch_note(text: str, date: str | None = None) -> dict[str, Any]:
    """Write the one-line coach note shown on the user's "Trainer" watch widget today.

    Keep it short and actionable (max 40 characters, no emojis, no accents), e.g.
    "Dormiste 6 h: hoy rodaje suave" or "11 dias sin pierna: toca Legs".
    The widget refreshes about every 30 minutes while the watch is connected to the phone.

    Args:
        text: The note. Longer text is cut to 40 characters.
        date: YYYY-MM-DD the note is for. Defaults to today.
    """
    day = _s._normalise_date(date, _s._today_iso())
    clean = " ".join(text.split())[:NOTE_MAX]
    _note.clear()
    _note.update({"date": day, "text": clean})
    log.info("watch.note.set", date=day, length=len(clean))
    return {"ok": True, "date": day, "text": clean}


@mcp.tool()
async def set_watch_message(kind: str, text: str, date: str | None = None) -> dict[str, Any]:
    """Save a coach message the user can read on the watch (Trainer widget, START).

    Use it at the end of each scheduled report with a condensed version for a
    small round screen: short lines, no tables, no markdown, no emojis. Accents
    are removed automatically.

    Args:
        kind: "morning" (Buenos dias, max 600 chars), "evening" (Resumen del dia,
            max 600 chars) or "week" (Plan de la semana, max 900 chars; one line per
            day, e.g. "M 30: Rodaje suave 45' Z2"). The week plan stays visible 7 days.
        text: The message. Line breaks are kept; longer text is cut.
        date: YYYY-MM-DD the message is for. Defaults to today.
    """
    if kind not in MESSAGE_KINDS:
        raise ValueError(f"kind must be one of {sorted(MESSAGE_KINDS)}")
    day = _s._normalise_date(date, _s._today_iso())
    clean = watch_text(text)[: MESSAGE_KINDS[kind]]
    _messages[kind] = {"date": day, "text": clean}
    log.info("watch.message.set", kind=kind, date=day, length=len(clean))
    return {"ok": True, "kind": kind, "date": day, "chars": len(clean)}
