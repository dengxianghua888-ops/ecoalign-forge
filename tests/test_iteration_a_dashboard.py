"""Persisted provenance, historical data and truthful dashboard loading."""

import json

import pytest

from ecoalign_forge.schemas.execution import ExecutionMode
from ecoalign_forge.storage.dashboard_bridge import DashboardBridge
from ecoalign_forge.storage.metrics import MetricsCollector


def test_sources_are_separate_and_legacy_is_unknown(tmp_path):
    for mode in (ExecutionMode.LIVE, ExecutionMode.DEMO, ExecutionMode.MOCK):
        mc = MetricsCollector(execution_mode=mode)
        mc.run_id = f"run-{mode}"
        mc.save(tmp_path / mode / "metrics.json")
    legacy = {"decision_counts": {"T0_Block": 100}, "severity_scores": [1.0] * 100}
    (tmp_path / "metrics.json").write_text(json.dumps(legacy))
    live = DashboardBridge(tmp_path, "live").get_latest_snapshot()
    demo = DashboardBridge(tmp_path, "demo").get_latest_snapshot()
    unknown = DashboardBridge(tmp_path, "unknown").get_latest_snapshot()
    assert live.total_cases == 0 and live.run_id == "run-live"
    assert demo.execution_mode == "demo" and demo.is_demo
    assert unknown.execution_mode == "unknown" and unknown.total_cases == 100
    assert json.loads((tmp_path / "metrics.json").read_text()) == legacy


def test_bad_or_wrong_mode_file_never_becomes_demo(tmp_path):
    path = tmp_path / "live" / "metrics.json"
    path.parent.mkdir()
    path.write_text("{bad")
    with pytest.raises(ValueError):
        DashboardBridge(tmp_path, "live").get_latest_snapshot()
    MetricsCollector(execution_mode="demo").save(path)
    with pytest.raises(ValueError, match="mode"):
        DashboardBridge(tmp_path, "live").get_latest_snapshot()


def test_empty_selected_source_stays_empty(tmp_path):
    snapshot = DashboardBridge(tmp_path, "live").get_latest_snapshot()
    assert snapshot.total_cases == 0
    assert snapshot.execution_mode == "live"
    assert not snapshot.is_demo
    assert snapshot.pipeline_runs == snapshot.timeline_data == []
    assert snapshot.avg_pair_quality_heuristic is None


@pytest.mark.parametrize("record", [[], None, 3])
def test_malformed_run_record_is_a_read_error(tmp_path, record):
    MetricsCollector(execution_mode="live").save(tmp_path / "live" / "metrics.json")
    (tmp_path / "live" / "runs.jsonl").write_text(json.dumps(record) + "\n")
    with pytest.raises(ValueError, match="Run record"):
        DashboardBridge(tmp_path, "live").get_latest_snapshot()


def test_review_rates_roundtrip_and_empty_denominator(tmp_path):
    mc = MetricsCollector(execution_mode="mock")
    mc.review_stats = {"consistency_rate": None, "correction_rate": None, "total_failed": 2}
    mc.save(tmp_path / "mock" / "metrics.json")
    snap = DashboardBridge(tmp_path, "mock").get_latest_snapshot()
    assert snap.review_consistency_rate is None
    assert snap.review_correction_rate is None
    assert snap.review_failed == 2
    mc.review_stats.update(consistency_rate=0.75, correction_rate=0.25)
    mc.save(tmp_path / "mock" / "metrics.json")
    snap = DashboardBridge(tmp_path, "mock").get_latest_snapshot()
    assert snap.review_consistency_rate == 0.75
    assert snap.review_correction_rate == 0.25
