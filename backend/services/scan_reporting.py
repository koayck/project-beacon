from __future__ import annotations


def format_sweep_levels(levels: list[float]) -> str:
    return ", ".join(f"{level:g}" for level in levels)


def format_sweep_findings(survivor_count: int) -> str:
    if survivor_count <= 0:
        return "No heat signatures detected."
    return f"{survivor_count} heat signature(s) detected."


def build_sweep_scan_report(
    asset_id: str,
    building: dict,
    levels: list[float],
    flood_level: float,
    waypoint_count: int,
    survivor_count: int,
    battery: float,
    sensor_summary: str,
) -> str:
    return (
        f"SWEEP SCAN COMPLETE — {asset_id}\n"
        f"  Building  : X=({building['min_x']:.1f} to {building['max_x']:.1f}), "
        f"Z=({building['min_z']:.1f} to {building['max_z']:.1f})\n"
        f"  Levels    : {format_sweep_levels(levels)} "
        f"(above flood level {flood_level:.1f}m)\n"
        f"  Waypoints : {waypoint_count}\n"
        f"  Findings  : {format_sweep_findings(survivor_count)}\n"
        f"  Battery   : {battery:.1f}% remaining\n"
        f"  Sensor    : {sensor_summary}"
    )
