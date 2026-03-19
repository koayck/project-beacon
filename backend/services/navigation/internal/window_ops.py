from __future__ import annotations

import math


def select_window_waypoint(
    waypoints: list[dict],
    ref_x: float,
    ref_z: float,
    preferred_y: float | None = None,
) -> dict | None:
    if not waypoints:
        return None

    def _score(wp: dict) -> tuple[float, float]:
        y_delta = abs(float(wp["y"]) - preferred_y) if preferred_y is not None else 0.0
        x_delta = float(wp["x"]) - ref_x
        z_delta = float(wp["z"]) - ref_z
        xz_dist = math.sqrt(x_delta * x_delta + z_delta * z_delta)
        return (y_delta, xz_dist)

    return min(waypoints, key=_score)
