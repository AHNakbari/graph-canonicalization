"""The quality report."""

from __future__ import annotations

import json

import pytest

from graphcanon.report import REQUIRED_KEYS, percentiles


@pytest.fixture(scope="module")
def report(mini_output):
    return json.loads((mini_output / "quality_report.json").read_text(encoding="utf-8"))


def test_the_validator_required_keys_are_present(report):
    assert not set(REQUIRED_KEYS) - set(report)


def test_every_coverage_rate_ships_with_its_counts(report):
    for name, block in report["coverage"].items():
        assert "numerator" in block, name
        assert "denominator" in block, name
        assert "rate" in block, name


def test_the_mandated_coverage_metrics_are_all_perfect(report):
    coverage = report["coverage"]
    for name in (
        "entity_assignment_coverage",
        "canonical_membership_coverage",
        "membership_uniqueness",
        "fact_disposition_coverage",
        "endpoint_validity",
        "provenance_coverage",
    ):
        assert coverage[name]["rate"] == 1.0, name
    assert coverage["reasoned_fact_coverage"]["rate"] >= 0.99


def test_graph_diagnostics_required_by_the_metrics_document(report):
    components = report["components"]
    for key in (
        "canonical_entities_by_type",
        "canonical_entities_by_scope",
        "size_percentiles",
        "largest_components",
        "isolated_canonical_entities",
        "edges",
        "facts_rejected_by_reason",
        "unresolved_pairs",
    ):
        assert key in components, key
    for key in ("p50", "p90", "p95", "p99", "max"):
        assert key in components["size_percentiles"], key
    for key in ("count", "consolidation_rate", "self_loop_rate", "orphan_edges"):
        assert key in components["edges"], key
    assert len(components["largest_components"]) <= 20


def test_operational_metrics_are_recorded(report):
    runtime = report["runtime"]
    assert runtime["wall_clock_seconds"] >= 0
    assert runtime["stage_seconds"]
    assert runtime["machine"]["python_version"]
    assert "peak_memory_source" in runtime


def test_output_hashes_are_recorded_for_every_artifact(report):
    outputs = report["outputs"]
    assert len(outputs) == 5  # the JSONL artifacts; the report cannot hash itself
    for name, block in outputs.items():
        assert len(block["sha256"]) == 64, name
        assert block["bytes"] > 0, name
        assert block["rows"] >= 0, name


def test_deterministic_hash_agreement_is_reported(report):
    block = report["determinism"]["deterministic_hash_agreement"]
    assert len(block["compared_files"]) == 5
    assert set(block["sha256"]) == set(report["outputs"])
    for digest in block["sha256"].values():
        assert len(digest) == 64
    assert "quality_report.json" in block["excluded"]
    assert block["measured_by"]


def test_the_configuration_is_reproducible_from_the_report(report):
    assert len(report["configuration_fingerprint"]) == 64
    policy = report["configuration"]
    assert policy["one_token_person_scope"] == "source_event"
    assert policy["merge_on_alias"] is False


def test_rejected_facts_are_broken_down_by_reason(report):
    assert report["components"]["facts_rejected_by_reason"] == {
        "CROSS_SCOPE_ENDPOINTS": 1,
        "SELF_LOOP_AFTER_CANONICALIZATION": 1,
    }


# --- percentiles -------------------------------------------------------------


def test_percentiles_use_nearest_rank():
    values = list(range(1, 101))  # 1..100
    result = percentiles(values)
    assert result["p50"] == 50
    assert result["p90"] == 90
    assert result["p99"] == 99
    assert result["max"] == 100


def test_percentiles_handle_degenerate_input():
    assert percentiles([]) == {"p50": 0, "p90": 0, "p95": 0, "p99": 0, "max": 0}
    assert percentiles([7])["p50"] == 7
    assert percentiles([7])["max"] == 7


def test_percentiles_ignore_input_order():
    import random

    values = [random.randint(1, 500) for _ in range(1000)]
    shuffled = values[:]
    random.shuffle(shuffled)
    assert percentiles(values) == percentiles(shuffled)
