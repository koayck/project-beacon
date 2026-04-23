from datetime import datetime, timezone

from backend.services.mission_runs import MissionRunAccumulator


def test_accumulator_initial_state() -> None:
    acc = MissionRunAccumulator(asset_id="BEACON-01", prompt="scan area", simulation_id="sim-1")
    assert acc.asset_id == "BEACON-01"
    assert acc.prompt == "scan area"
    assert acc.simulation_id == "sim-1"
    assert acc.tool_call_count == 0
    assert acc.survivors_detected == 0
    assert acc.survivors_rescued == 0


def test_record_tool_call_increments_count() -> None:
    acc = MissionRunAccumulator(asset_id="FLEET", prompt="test", simulation_id=None)
    acc.record_tool_call()
    acc.record_tool_call()
    assert acc.tool_call_count == 2


def test_record_detections_dedupes_by_rounded_key() -> None:
    acc = MissionRunAccumulator(asset_id="FLEET", prompt="test", simulation_id=None)
    acc.record_detections([{"x": 1.0, "y": 0.0, "z": 2.0}, {"x": 1.0001, "y": 0.0, "z": 2.0}])
    acc.record_detections([{"x": 5.0, "y": 0.0, "z": 5.0}])
    assert acc.survivors_detected == 2


def test_record_detections_ignores_invalid_entries() -> None:
    acc = MissionRunAccumulator(asset_id="FLEET", prompt="test", simulation_id=None)
    acc.record_detections([{"x": 1.0, "y": 0.0}, {"x": None, "y": 0, "z": 0}, "nonsense"])
    assert acc.survivors_detected == 0


def test_record_deliveries_dedupes_by_survivor_key() -> None:
    acc = MissionRunAccumulator(asset_id="FLEET", prompt="test", simulation_id=None)
    acc.record_deliveries([
        {"asset_id": "BEACON-01", "survivor": {"x": 1.0, "y": 0.0, "z": 2.0},
         "drop_point": {"x": 1.1, "y": 0.0, "z": 2.1}},
        {"asset_id": "BEACON-02", "survivor": {"x": 1.0, "y": 0.0, "z": 2.0},
         "drop_point": {"x": 1.2, "y": 0.0, "z": 2.2}},
    ])
    assert acc.survivors_rescued == 1


def test_build_success_populates_fields() -> None:
    acc = MissionRunAccumulator(asset_id="BEACON-01", prompt="scan", simulation_id="sim-1")
    acc.record_tool_call()
    acc.record_detections([{"x": 0.0, "y": 0.0, "z": 0.0}])
    run = acc.build(status="success", ttft_ms=250, final_text="Report complete.")
    assert run.status == "success"
    assert run.ttft_ms == 250
    assert run.tool_call_count == 1
    assert run.survivors_detected == 1
    assert run.result_summary == "Report complete."
    assert run.duration_ms is not None and run.duration_ms >= 0
    assert run.ended_at is not None


def test_build_truncates_result_summary_to_500_chars() -> None:
    acc = MissionRunAccumulator(asset_id="FLEET", prompt="test", simulation_id=None)
    long_text = "x" * 1000
    run = acc.build(status="success", ttft_ms=None, final_text=long_text)
    assert run.result_summary is not None
    assert len(run.result_summary) == 500


def test_build_failed_populates_error_message() -> None:
    acc = MissionRunAccumulator(asset_id="FLEET", prompt="test", simulation_id=None)
    run = acc.build(status="failed", ttft_ms=None, final_text="", error="boom")
    assert run.status == "failed"
    assert run.error_message == "boom"


def test_build_clamps_negative_duration() -> None:
    acc = MissionRunAccumulator(asset_id="FLEET", prompt="test", simulation_id=None)
    acc.started_at = datetime.now(timezone.utc).replace(year=9999)  # future start
    run = acc.build(status="success", ttft_ms=None, final_text="")
    assert run.duration_ms == 0
