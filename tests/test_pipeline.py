"""End-to-end: determinism, order independence, atomicity, schema conformance."""

from __future__ import annotations

import json
import random
import shutil

import pytest

from graphcanon.config import Config
from graphcanon.jsonio import sha256_file
from graphcanon.pipeline import JSONL_OUTPUTS, OUTPUT_FILES, run

from helpers import read_jsonl

jsonschema = pytest.importorskip("jsonschema")

SCHEMA_FOR = {
    "entity_assignments.jsonl": "entity_assignment.schema.json",
    "canonical_entities.jsonl": "canonical_entity.schema.json",
    "possible_duplicates.jsonl": "possible_duplicate.schema.json",
    "fact_assignments.jsonl": "fact_assignment.schema.json",
    "canonical_edges.jsonl": "canonical_edge.schema.json",
}


# --- artifacts ---------------------------------------------------------------


def test_all_six_artifacts_are_written(mini_output):
    for name in OUTPUT_FILES:
        assert (mini_output / name).is_file(), name


def test_no_staging_directory_survives(mini_output):
    assert not (mini_output / ".staging").exists()


@pytest.mark.parametrize("name", sorted(SCHEMA_FOR))
def test_rows_validate_against_the_supplied_schema(name, mini_output, repo_root):
    schema = json.loads(
        (repo_root / "schemas" / SCHEMA_FOR[name]).read_text(encoding="utf-8")
    )
    validator = jsonschema.Draft202012Validator(schema)
    rows = read_jsonl(mini_output / name)
    assert rows, name
    for row in rows:
        errors = sorted(validator.iter_errors(row), key=lambda e: e.path)
        assert not errors, f"{name}: {errors[0].message}"


def test_the_report_validates_against_its_schema(mini_output, repo_root):
    schema = json.loads(
        (repo_root / "schemas" / "quality_report.schema.json").read_text(encoding="utf-8")
    )
    report = json.loads((mini_output / "quality_report.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(report)


# --- determinism (scenario 7) ------------------------------------------------


def test_two_runs_produce_identical_bytes(mini_input, tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    run(Config(input_dir=mini_input, output_dir=first))
    run(Config(input_dir=mini_input, output_dir=second))
    for name in JSONL_OUTPUTS:
        assert sha256_file(first / name) == sha256_file(second / name), name


def test_the_report_differs_only_in_measured_runtime(mini_input, tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    run(Config(input_dir=mini_input, output_dir=first))
    run(Config(input_dir=mini_input, output_dir=second))
    left = json.loads((first / "quality_report.json").read_text(encoding="utf-8"))
    right = json.loads((second / "quality_report.json").read_text(encoding="utf-8"))
    for report in (left, right):
        report.pop("runtime")
        report["outputs"].pop("possible_duplicates.jsonl", None)
    assert left == right


# --- input-order robustness (scenario 8) -------------------------------------


def _shuffled_copy(source, target, seed):
    target.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    for path in source.iterdir():
        if path.suffix != ".jsonl":
            continue
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        rng.shuffle(lines)
        (target / path.name).write_text("".join(lines), encoding="utf-8")
    return target


def test_shuffled_input_produces_identical_output(mini_input, tmp_path):
    """Canonical IDs are content-addressed, so this is equality, not re-sorting."""
    baseline = tmp_path / "baseline"
    run(Config(input_dir=mini_input, output_dir=baseline))

    for seed in (1, 2, 3, 17):
        shuffled_input = _shuffled_copy(mini_input, tmp_path / f"in{seed}", seed)
        shuffled_output = tmp_path / f"out{seed}"
        run(Config(input_dir=shuffled_input, output_dir=shuffled_output))
        for name in JSONL_OUTPUTS:
            assert sha256_file(baseline / name) == sha256_file(shuffled_output / name), (
                f"seed {seed} changed {name}"
            )


# --- atomicity ---------------------------------------------------------------


def test_a_failed_run_leaves_the_previous_artifacts_intact(mini_input, tmp_path, monkeypatch):
    output = tmp_path / "out"
    run(Config(input_dir=mini_input, output_dir=output))
    before = {name: sha256_file(output / name) for name in OUTPUT_FILES}

    import graphcanon.pipeline as pipeline

    def explode(*_args, **_kwargs):
        raise RuntimeError("simulated failure during write")

    monkeypatch.setattr(pipeline, "_write_outputs", explode)
    with pytest.raises(RuntimeError):
        run(Config(input_dir=mini_input, output_dir=output))

    after = {name: sha256_file(output / name) for name in OUTPUT_FILES}
    assert before == after
    assert not (output / ".staging").exists()


# --- coverage accounting on the real contract --------------------------------


def test_counts_line_up_with_the_input(mini_input, mini_output):
    report = json.loads((mini_output / "quality_report.json").read_text(encoding="utf-8"))
    assert report["input_counts"]["candidate_entities"] == 13
    assert report["input_counts"]["candidate_facts"] == 6
    assert report["output_counts"]["entity_assignments"] == 13
    assert report["output_counts"]["fact_assignments"] == 6
    assert len(read_jsonl(mini_output / "entity_assignments.jsonl")) == 13
    assert len(read_jsonl(mini_output / "fact_assignments.jsonl")) == 6


def test_identity_quality_is_skipped_without_labels(mini_input, tmp_path):
    result = run(Config(input_dir=mini_input, output_dir=tmp_path / "out"), labels_path=None)
    assert result.identity_quality is None


def test_a_run_reports_its_own_invariant_violations(mini_output):
    report = json.loads((mini_output / "quality_report.json").read_text(encoding="utf-8"))
    assert report["safety"]["invariant_violations"] == {}
    assert report["safety"]["invariant_violations_total"] == 0
    assert report["safety"]["boundary_violations"] == 0
