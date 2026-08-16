"""`graphcanon verify` must agree with `tools/validate_submission.py`.

Corrupts a clean submission one way at a time and asserts both implementations
reach the same verdict on every variant. This is the only thing that makes the
accelerated verifier trustworthy, so a new assertion in verify.py needs a new
corruption here. Also supplies the scenario 1 coverage-accounting evidence.
"""

from __future__ import annotations

import json

import pytest

from graphcanon.verify import VerificationError, verify

from helpers import run_tool


def _lines(path):
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def _write(path, lines):
    path.write_text("".join(lines), encoding="utf-8")


# --- corruptions -------------------------------------------------------------


def drop_an_assignment(out):
    path = out / "entity_assignments.jsonl"
    _write(path, _lines(path)[1:])


def duplicate_an_assignment(out):
    path = out / "entity_assignments.jsonl"
    lines = _lines(path)
    _write(path, lines + [lines[0]])


def drop_a_fact_assignment(out):
    path = out / "fact_assignments.jsonl"
    _write(path, _lines(path)[1:])


def duplicate_a_fact_assignment(out):
    path = out / "fact_assignments.jsonl"
    lines = _lines(path)
    _write(path, lines + [lines[0]])


def drop_a_canonical_entity(out):
    path = out / "canonical_entities.jsonl"
    _write(path, _lines(path)[1:])


def duplicate_a_member_across_components(out):
    path = out / "canonical_entities.jsonl"
    lines = _lines(path)
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    second["member_candidate_entity_ids"] = sorted(
        set(second["member_candidate_entity_ids"]) | {first["member_candidate_entity_ids"][0]}
    )
    lines[1] = json.dumps(second, sort_keys=True) + "\n"
    _write(path, lines)


def misdeclare_a_scope(out):
    path = out / "canonical_entities.jsonl"
    lines = _lines(path)
    row = json.loads(lines[0])
    row["org_id"] = "org_not_this_one"
    lines[0] = json.dumps(row, sort_keys=True) + "\n"
    _write(path, lines)


def project_a_fact_without_an_edge(out):
    path = out / "fact_assignments.jsonl"
    lines = _lines(path)
    for i, line in enumerate(lines):
        row = json.loads(line)
        if row["disposition"] == "PROJECTED":
            row["canonical_edge_id"] = None
            lines[i] = json.dumps(row, sort_keys=True) + "\n"
            break
    _write(path, lines)


def give_a_dropped_fact_an_edge(out):
    path = out / "fact_assignments.jsonl"
    lines = _lines(path)
    for i, line in enumerate(lines):
        row = json.loads(line)
        if row["disposition"] == "DROPPED_INVALID":
            row["canonical_edge_id"] = "cedge_invented"
            lines[i] = json.dumps(row, sort_keys=True) + "\n"
            break
    _write(path, lines)


def point_an_edge_at_nothing(out):
    path = out / "canonical_edges.jsonl"
    lines = _lines(path)
    row = json.loads(lines[0])
    row["subject_canonical_entity_id"] = "canon_does_not_exist"
    lines[0] = json.dumps(row, sort_keys=True) + "\n"
    _write(path, lines)


def strip_edge_provenance(out):
    path = out / "canonical_edges.jsonl"
    lines = _lines(path)
    row = json.loads(lines[0])
    row["source_candidate_fact_ids"] = []
    lines[0] = json.dumps(row, sort_keys=True) + "\n"
    _write(path, lines)


def leave_one_evidence_id(out):
    path = out / "possible_duplicates.jsonl"
    lines = _lines(path)
    row = json.loads(lines[0])
    row["evidence_candidate_entity_ids"] = row["evidence_candidate_entity_ids"][:1]
    lines[0] = json.dumps(row, sort_keys=True) + "\n"
    _write(path, lines)


def cite_an_unknown_canonical_pair(out):
    path = out / "possible_duplicates.jsonl"
    lines = _lines(path)
    row = json.loads(lines[0])
    row["left_canonical_entity_id"] = "canon_does_not_exist"
    lines[0] = json.dumps(row, sort_keys=True) + "\n"
    _write(path, lines)


def blank_a_reason_code(out):
    path = out / "entity_assignments.jsonl"
    lines = _lines(path)
    row = json.loads(lines[0])
    row["reason_codes"] = []
    lines[0] = json.dumps(row, sort_keys=True) + "\n"
    _write(path, lines)


def invent_a_decision(out):
    path = out / "entity_assignments.jsonl"
    lines = _lines(path)
    row = json.loads(lines[0])
    row["decision"] = "PROBABLY_FINE"
    lines[0] = json.dumps(row, sort_keys=True) + "\n"
    _write(path, lines)


def remove_a_report_key(out):
    path = out / "quality_report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report.pop("coverage")
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def delete_a_required_file(out):
    (out / "canonical_edges.jsonl").unlink()


CORRUPTIONS = [
    drop_an_assignment,
    duplicate_an_assignment,
    drop_a_fact_assignment,
    duplicate_a_fact_assignment,
    drop_a_canonical_entity,
    duplicate_a_member_across_components,
    misdeclare_a_scope,
    project_a_fact_without_an_edge,
    give_a_dropped_fact_an_edge,
    point_an_edge_at_nothing,
    strip_edge_provenance,
    leave_one_evidence_id,
    cite_an_unknown_canonical_pair,
    blank_a_reason_code,
    invent_a_decision,
    remove_a_report_key,
    delete_a_required_file,
]


# --- the equivalence claim ---------------------------------------------------


def test_a_clean_submission_passes_both(mini_input, mini_output):
    supplied = run_tool("validate_submission", str(mini_input), str(mini_output))
    assert supplied.returncode == 0, supplied.stdout + supplied.stderr
    assert json.loads(supplied.stdout)["status"] == "PASS"

    mine = verify(mini_input, mini_output)
    assert mine["status"] == "PASS"

    theirs = json.loads(supplied.stdout)
    for key in theirs:
        assert mine[key] == theirs[key], key


@pytest.mark.parametrize("corrupt", CORRUPTIONS, ids=lambda f: f.__name__)
def test_both_implementations_reject_the_same_corruption(
    corrupt, mini_input, mutable_output
):
    corrupt(mutable_output)

    supplied = run_tool("validate_submission", str(mini_input), str(mutable_output))
    assert supplied.returncode != 0, (
        f"{corrupt.__name__}: the supplied validator accepted a corrupted submission"
    )

    with pytest.raises(VerificationError):
        verify(mini_input, mutable_output)


def test_the_accelerated_verifier_reports_the_same_wording(mini_input, mutable_output):
    """Messages are transcribed, so a reviewer can match them line for line."""
    drop_an_assignment(mutable_output)
    supplied = run_tool("validate_submission", str(mini_input), str(mutable_output))
    with pytest.raises(VerificationError) as caught:
        verify(mini_input, mutable_output)
    assert str(caught.value) in supplied.stderr + supplied.stdout
