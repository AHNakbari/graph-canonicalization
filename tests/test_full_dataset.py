"""Required scenario 10: scale evidence on the real dataset.

Asserts the figures quoted in docs/RUN_MANIFEST.md and docs/FINDINGS.md. A
policy change is meant to fail these - it is what stops those documents from
drifting away from the code - so update them together, never separately.
Marked `slow`; skipped when the handout data is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphcanon.config import Config
from graphcanon.pipeline import run
from graphcanon.verify import verify

DATA = Path(__file__).resolve().parents[1] / "data" / "input"
LABELS = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "reference"
    / "public_labeled_pairs.jsonl"
)

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not (DATA / "candidate_entities.jsonl").is_file(),
        reason="handout data not present; see README for how to place it",
    ),
]


@pytest.fixture(scope="module")
def full_run(tmp_path_factory):
    output = tmp_path_factory.mktemp("full")
    result = run(Config(input_dir=DATA, output_dir=output), labels_path=LABELS)
    report = json.loads((output / "quality_report.json").read_text(encoding="utf-8"))
    return result, report, output


def test_the_whole_dataset_is_accounted_for(full_run):
    _result, report, _out = full_run
    assert report["input_counts"]["candidate_entities"] == 479_930
    assert report["input_counts"]["candidate_facts"] == 293_475
    assert report["output_counts"]["entity_assignments"] == 479_930
    assert report["output_counts"]["fact_assignments"] == 293_475


def test_no_invariant_is_violated_at_scale(full_run):
    result, report, _out = full_run
    assert result.violations == {}
    assert report["safety"]["invariant_violations_total"] == 0
    assert report["safety"]["boundary_violations"] == 0
    assert report["safety"]["prohibited_one_token_person_components"] == 0


def test_coverage_targets_are_met(full_run):
    _result, report, _out = full_run
    coverage = report["coverage"]
    assert coverage["entity_assignment_coverage"]["rate"] == 1.0
    assert coverage["canonical_membership_coverage"]["rate"] == 1.0
    assert coverage["membership_uniqueness"]["rate"] == 1.0
    assert coverage["fact_disposition_coverage"]["rate"] == 1.0
    assert coverage["endpoint_validity"]["rate"] == 1.0
    assert coverage["provenance_coverage"]["rate"] == 1.0
    assert coverage["reasoned_fact_coverage"]["rate"] == 1.0


def test_the_graph_matches_the_documented_shape(full_run):
    _result, report, _out = full_run
    assert report["output_counts"]["canonical_entities"] == 66_120
    assert report["output_counts"]["canonical_edges"] == 81_715
    assert report["output_counts"]["facts_projected"] == 291_872
    assert report["components"]["facts_rejected_by_reason"] == {
        "SELF_LOOP_AFTER_CANONICALIZATION": 1_603
    }


def test_identity_quality_clears_every_threshold(full_run):
    _result, report, _out = full_run
    quality = report["identity_quality"]
    assert quality["macro_f1"] >= 0.80, "public macro-F1 target"
    assert quality["macro_f1"] == pytest.approx(0.9861, abs=5e-4)
    assert quality["hard_merge_precision"] >= 0.97
    assert quality["hard_merge_precision"] == 1.0
    assert quality["per_class"]["POSSIBLE_DUPLICATE"]["recall"] == 1.0
    assert quality["missing_assignments"] == 0


def test_the_submission_passes_the_acceptance_assertions(full_run):
    _result, _report, output = full_run
    assert verify(DATA, output)["status"] == "PASS"


def test_runtime_and_peak_memory_are_recorded(full_run):
    _result, report, _out = full_run
    runtime = report["runtime"]
    assert 0 < runtime["wall_clock_seconds"] < 900, "full run should stay minutes, not hours"
    assert runtime["peak_memory_bytes"], "peak memory must be measured, not guessed"
    assert runtime["peak_memory_mib"] < 4096, "must fit comfortably in a laptop"
    assert set(runtime["stage_seconds"]) >= {"load", "resolve", "project", "write"}
