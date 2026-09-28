"""Narrow extensions to ``garminconnect.Garmin``.

``garminconnect`` can read an activity's exercise sets but cannot write them.
Garmin Connect's own web editor saves them with a PUT to
``/activity-service/activity/{id}/exerciseSets`` and renames an activity with a
PUT to ``/activity-service/activity/{id}``. We expose exactly one combined
write, ``update_strength_activity``, used to finish a strength session recorded
by the watch app: it attaches the performed sets and sets title/description.

Nothing else about an activity (type, time, HR, GPS) can be changed through it.
"""

from __future__ import annotations

from typing import Any

from garminconnect import Garmin


class ExtendedGarmin(Garmin):  # type: ignore[misc]
    def update_strength_activity(
        self,
        activity_id: int | str,
        exercise_sets: list[dict[str, Any]],
        title: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Attach exercise sets to a strength activity and set its title/description."""
        aid = int(activity_id)
        if aid <= 0:
            raise ValueError("activity_id must be positive")
        base = f"{self.garmin_connect_activity}/{aid}"
        result: dict[str, Any] = {"activity_id": aid}
        if exercise_sets:
            payload = {"activityId": aid, "exerciseSets": exercise_sets}
            self.client.put("connectapi", f"{base}/exerciseSets", json=payload, api=True)
            result["exercise_sets"] = len(exercise_sets)
        meta: dict[str, Any] = {"activityId": aid}
        if title:
            meta["activityName"] = title[:120]
        if description:
            meta["description"] = description[:2000]
        if len(meta) > 1:
            self.client.put("connectapi", base, json=meta, api=True)
            result["renamed"] = bool(title)
            result["described"] = bool(description)
        return result
