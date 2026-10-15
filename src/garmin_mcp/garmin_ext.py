"""Narrow extensions to ``garminconnect.Garmin``.

``garminconnect`` can read an activity's exercise sets but cannot write them.
Garmin Connect's own web editor saves them with a PUT to
``/activity-service/activity/{id}/exerciseSets`` and renames an activity with a
PUT to ``/activity-service/activity/{id}``. We expose exactly one combined
write, ``update_strength_activity``, used to finish a strength session recorded
by the watch app: it attaches the performed sets, sets title/description and
the post-session rating (feel / RPE) the app asked for.

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
        feel: int | None = None,
        rpe: int | None = None,
    ) -> dict[str, Any]:
        """Attach exercise sets to a strength activity and set its title/description.

        feel (0/25/50/75/100) and rpe (10-100, i.e. RPE x10) are the
        post-activity rating Garmin asks for on native activities; the watch app
        collects them itself and they land in the same summary fields.
        """
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
        rating: dict[str, Any] = {}
        if feel is not None and feel in (0, 25, 50, 75, 100):
            rating["directWorkoutFeel"] = int(feel)
        if rpe is not None and 10 <= int(rpe) <= 100:
            rating["directWorkoutRpe"] = int(rpe)
        if rating:
            meta["summaryDTO"] = rating
        if len(meta) > 1:
            self.client.put("connectapi", base, json=meta, api=True)
            result["renamed"] = bool(title)
            result["described"] = bool(description)
            result["rated"] = bool(rating)
        return result
