from backend.services.simulation_store import SimulationStore


def test_parse_scan_targets_extracts_buildings_from_coords() -> None:
    known_buildings = [
        {"id": 4, "cx": -23.0, "cz": -28.0},
        {"id": 7, "cx": -15.0, "cz": -20.0},
    ]
    prompt = (
        "scan for survivors in each of the following buildings: "
        "building-4 at (-23.0, 0, -28.0); building-7 at (-15.0, 0, -20.0)."
    )

    parsed = SimulationStore.parse_scan_targets(prompt, known_buildings)

    assert parsed.has_scan_intent is True
    assert parsed.building_ids == [4, 7]


def test_parse_scan_targets_non_scan_prompt() -> None:
    known_buildings = [{"id": 1, "cx": 0.0, "cz": 0.0}]

    parsed = SimulationStore.parse_scan_targets("move fleet to base", known_buildings)

    assert parsed.has_scan_intent is False
    assert parsed.building_ids == []
