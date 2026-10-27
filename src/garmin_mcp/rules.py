"""Training rules: the single source the scheduled tasks read first.

``get_training_rules`` returns ``data/reglas_entrenamiento.md`` (Lander's
calendar, strength templates, weekly review rules and how to encode each
session in the connector) plus the deterministic parts the tasks used to get
wrong: which week (A/B) comes next, its dates and the calendar names.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from garmin_mcp import server as _s

mcp: FastMCP[Any] = vars(_s)["mcp"]

RULES_PATH = Path(__file__).parent / "data" / "reglas_entrenamiento.md"
# Week of Monday 19/10/2026 is a "B" week; weeks alternate from there.
REFERENCE_MONDAY = dt.date(2026, 10, 19)
REFERENCE_LETTER = "B"
DAY_LETTERS = "LMXJVSD"


def week_letter(day: dt.date) -> str:
    """'A' or 'B' for the week that contains ``day``."""
    monday = day - dt.timedelta(days=day.weekday())
    weeks = (monday - REFERENCE_MONDAY).days // 7
    if weeks % 2 == 0:
        return REFERENCE_LETTER
    return "A" if REFERENCE_LETTER == "B" else "B"


def _sessions(letter: str) -> list[list[str]]:
    """Default sessions per weekday (Mon..Sun); distances are the base-week defaults."""
    wednesday = "Pesas Legs 65 min" if letter == "A" else "Pesas Hyrox 55 min"
    return [
        [],
        ["Pesas Pull 65 min"],
        [wednesday],
        ["Pesas Push 65 min"],
        ["Series 5x1000"],
        ["Bici larga 2h30"],
        ["Tirada larga 18 km"],
    ]


def week_plan(day: dt.date) -> dict[str, Any]:
    monday = day - dt.timedelta(days=day.weekday())
    letter = week_letter(monday)
    days = []
    for i, sessions in enumerate(_sessions(letter)):
        date = monday + dt.timedelta(days=i)
        prefix = f"Plan {DAY_LETTERS[i]} {date.strftime('%d/%m')}"
        days.append(
            {
                "date": date.isoformat(),
                "day": DAY_LETTERS[i],
                "names": [f"{prefix} {s}" for s in sessions] or ["Descanso total (no programar)"],
            }
        )
    return {
        "monday": monday.isoformat(),
        "sunday": (monday + dt.timedelta(days=6)).isoformat(),
        "letter": letter,
        "days": days,
    }


@mcp.tool()
async def get_training_rules(date: str | None = None) -> dict[str, Any]:
    """Lander's training rules — read this FIRST in every scheduled task.

    Returns the full rules (weekly calendar, strength templates with starting
    loads, the weekly coach review and how to encode each session with the
    connector's tools) and the computed weeks: ``this_week`` and ``next_week``
    with the A/B letter, the dates and the suggested calendar names (durations
    are defaults; the weekly review may change them).

    Args:
        date: reference day YYYY-MM-DD (default today).
    """
    day = dt.date.fromisoformat(_s._normalise_date(date, _s._today_iso()))
    return {
        "today": day.isoformat(),
        "this_week": week_plan(day),
        "next_week": week_plan(day + dt.timedelta(days=7)),
        "rules": RULES_PATH.read_text(encoding="utf-8"),
    }
