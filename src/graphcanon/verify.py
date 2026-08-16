"""Accelerated equivalent of tools/validate_submission.py.

`tools/validate_submission.py` is authoritative and vendored unchanged; this is
a transcription of it with one expression hoisted out of two loops (see
docs/FINDINGS.md §7).

**Every assertion below is a line-for-line transcription of that file, in the
same order, failing on the same conditions.** Changing an assertion here
without changing it there breaks the equivalence that
tests/test_verify_equivalence.py exists to hold, and makes this module's PASS
meaningless.
"""

from __future__ import annotations

import collections
import re
from pathlib import Path
from typing import Any, Iterator

from .jsonio import read_jsonl

REQUIRED_OUTPUTS = (
    "entity_assignments.jsonl",
    "canonical_entities.jsonl",
    "possible_duplicates.jsonl",
    "fact_assignments.jsonl",
    "canonical_edges.jsonl",
    "quality_report.json",
)
ENTITY_DECISIONS = {"NEW_CANONICAL", "MERGED", "POSSIBLE_DUPLICATE"}
FACT_DISPOSITIONS = {"PROJECTED", "DROPPED_INVALID"}
CORROBORATING_CODES = {"VERIFIED_IDENTIFIER", "SOURCE_LOCAL_ALIAS", "VERIFIED_CONTACT"}
REPORT_KEYS = {
    "input_counts",
    "output_counts",
    "coverage",
    "safety",
    "components",
    "runtime",
    "configuration_fingerprint",
}
TOKEN_RE = re.compile(r"[\w]+(?:[-'][\w]+)*", re.UNICODE)


class VerificationError(Exception):
    """A failed acceptance assertion, carrying the validator's own wording."""


def _fail(message: str) -> None:
    raise VerificationError(message)


def _rows(path: Path) -> Iterator[tuple[int, dict]]:
    return read_jsonl(path)


def verify(input_dir: Path, output_dir: Path) -> dict[str, Any]:
    import json

    missing = [n for n in REQUIRED_OUTPUTS if not (output_dir / n).is_file()]
    if missing:
        _fail(f"missing output files: {missing}")

    event_scope: dict[str, tuple[str, str]] = {}
    for _, row in _rows(input_dir / "source_ledger.jsonl"):
        event_scope[row["source_event_id"]] = (row["org_id"], row["workspace_id"])

    input_entities: dict[str, dict] = {}
    for line_no, row in _rows(input_dir / "candidate_entities.jsonl"):
        entity_id = row["candidate_entity_id"]
        if entity_id in input_entities:
            _fail(f"candidate_entities.jsonl:{line_no}: duplicate ID")
        org, workspace = event_scope[row["source_event_id"]]
        input_entities[entity_id] = {
            "type": row["type"],
            "org": org,
            "workspace": workspace,
            "source": row["source_event_id"],
            "chunk": row["chunk_id"],
            "normalized_name": row.get("normalized_name") or row.get("name", ""),
        }
    # The hoist: the supplied validator rebuilds this set inside two loops.
    # This single line is the only intended difference between the two files.
    input_entity_ids = set(input_entities)

    input_fact_ids: set[str] = set()
    for line_no, row in _rows(input_dir / "candidate_facts.jsonl"):
        fact_id = row["candidate_fact_id"]
        if fact_id in input_fact_ids:
            _fail(f"candidate_facts.jsonl:{line_no}: duplicate ID")
        input_fact_ids.add(fact_id)

    assignments: dict[str, dict] = {}
    for line_no, row in _rows(output_dir / "entity_assignments.jsonl"):
        entity_id = row.get("candidate_entity_id")
        if entity_id not in input_entities or entity_id in assignments:
            _fail(f"entity_assignments.jsonl:{line_no}: unknown/duplicate candidate_entity_id")
        if row.get("decision") not in ENTITY_DECISIONS:
            _fail(f"entity_assignments.jsonl:{line_no}: invalid decision")
        if not row.get("canonical_entity_id") or not row.get("reason_codes"):
            _fail(f"entity_assignments.jsonl:{line_no}: missing canonical ID or reason codes")
        assignments[entity_id] = row
    if set(assignments) != input_entity_ids:
        _fail(
            "entity assignment coverage mismatch: "
            f"missing={len(input_entity_ids - set(assignments))}"
        )

    canonical_ids: set[str] = set()
    member_seen: set[str] = set()
    one_token_person_violations = 0
    for line_no, row in _rows(output_dir / "canonical_entities.jsonl"):
        canonical_id = row.get("canonical_entity_id")
        members = row.get("member_candidate_entity_ids") or []
        if not canonical_id or canonical_id in canonical_ids or not members:
            _fail(f"canonical_entities.jsonl:{line_no}: missing/duplicate ID or empty members")
        canonical_ids.add(canonical_id)
        member_set = set(members)
        if len(members) != len(member_set):
            _fail(f"canonical_entities.jsonl:{line_no}: duplicate member")
        if member_set - input_entity_ids:
            _fail(f"canonical_entities.jsonl:{line_no}: unknown members")
        if member_set & member_seen:
            _fail(f"canonical_entities.jsonl:{line_no}: members appear in multiple components")
        member_seen |= member_set
        scopes = {
            (
                input_entities[m]["org"],
                input_entities[m]["workspace"],
                input_entities[m]["type"],
            )
            for m in members
        }
        if len(scopes) != 1:
            _fail(f"canonical_entities.jsonl:{line_no}: component crosses org/workspace/type")
        scope = next(iter(scopes))
        if (
            row.get("org_id") != scope[0]
            or row.get("workspace_id") != scope[1]
            or row.get("entity_type") != scope[2]
        ):
            _fail(f"canonical_entities.jsonl:{line_no}: declared scope/type mismatch")
        for member in members:
            if assignments[member]["canonical_entity_id"] != canonical_id:
                _fail(f"canonical_entities.jsonl:{line_no}: assignment/member mismatch")
        if scope[2].casefold() == "person" and len(members) > 1:
            all_one_token = all(
                len(TOKEN_RE.findall(input_entities[m]["normalized_name"])) == 1
                for m in members
            )
            multiple_sources = len({input_entities[m]["source"] for m in members}) > 1
            if all_one_token and multiple_sources:
                codes: set[str] = set()
                for m in members:
                    codes |= set(assignments[m].get("reason_codes") or [])
                if not (codes & CORROBORATING_CODES):
                    one_token_person_violations += 1
    if member_seen != input_entity_ids:
        _fail(
            "canonical membership coverage mismatch: "
            f"missing={len(input_entity_ids - member_seen)}"
        )
    if {row["canonical_entity_id"] for row in assignments.values()} != canonical_ids:
        _fail("assignments reference missing or unused canonical entities")
    if one_token_person_violations:
        _fail(f"prohibited one-token Person components: {one_token_person_violations}")

    possible_duplicate_rows = 0
    for line_no, row in _rows(output_dir / "possible_duplicates.jsonl"):
        possible_duplicate_rows += 1
        left = row.get("left_canonical_entity_id")
        right = row.get("right_canonical_entity_id")
        if left not in canonical_ids or right not in canonical_ids or left == right:
            _fail(f"possible_duplicates.jsonl:{line_no}: invalid canonical pair")
        evidence = set(row.get("evidence_candidate_entity_ids") or [])
        if len(evidence) < 2 or evidence - input_entity_ids:
            _fail(f"possible_duplicates.jsonl:{line_no}: invalid evidence IDs")

    fact_assignments: dict[str, dict] = {}
    projected_to_edge: dict[str, set[str]] = collections.defaultdict(set)
    for line_no, row in _rows(output_dir / "fact_assignments.jsonl"):
        fact_id = row.get("candidate_fact_id")
        if fact_id not in input_fact_ids or fact_id in fact_assignments:
            _fail(f"fact_assignments.jsonl:{line_no}: unknown/duplicate fact")
        disposition = row.get("disposition")
        if disposition not in FACT_DISPOSITIONS or not row.get("reason_codes"):
            _fail(f"fact_assignments.jsonl:{line_no}: invalid disposition/reasons")
        edge_id = row.get("canonical_edge_id")
        if disposition == "PROJECTED":
            if not edge_id:
                _fail(f"fact_assignments.jsonl:{line_no}: projected fact missing edge ID")
            projected_to_edge[edge_id].add(fact_id)
        elif edge_id is not None:
            _fail(f"fact_assignments.jsonl:{line_no}: dropped fact must have null edge ID")
        fact_assignments[fact_id] = row
    if set(fact_assignments) != input_fact_ids:
        _fail(
            "fact assignment coverage mismatch: "
            f"missing={len(input_fact_ids - set(fact_assignments))}"
        )

    edge_ids: set[str] = set()
    edge_fact_ids: set[str] = set()
    for line_no, row in _rows(output_dir / "canonical_edges.jsonl"):
        edge_id = row.get("canonical_edge_id")
        if not edge_id or edge_id in edge_ids:
            _fail(f"canonical_edges.jsonl:{line_no}: missing/duplicate edge ID")
        edge_ids.add(edge_id)
        if row.get("subject_canonical_entity_id") not in canonical_ids:
            _fail(f"canonical_edges.jsonl:{line_no}: unknown subject canonical ID")
        obj = row.get("object_canonical_entity_id")
        if obj is not None and obj not in canonical_ids:
            _fail(f"canonical_edges.jsonl:{line_no}: unknown object canonical ID")
        if obj is None and "object_value" not in row:
            _fail(f"canonical_edges.jsonl:{line_no}: missing object endpoint/value")
        source_facts = set(row.get("source_candidate_fact_ids") or [])
        if not source_facts or source_facts - input_fact_ids:
            _fail(f"canonical_edges.jsonl:{line_no}: invalid source facts")
        if edge_fact_ids & source_facts:
            _fail(f"canonical_edges.jsonl:{line_no}: fact appears on multiple edges")
        edge_fact_ids |= source_facts
        if projected_to_edge.get(edge_id, set()) != source_facts:
            _fail(f"canonical_edges.jsonl:{line_no}: fact assignment/edge provenance mismatch")
    if set(projected_to_edge) != edge_ids:
        _fail("projected assignments reference missing or unused edges")

    report = json.loads((output_dir / "quality_report.json").read_text(encoding="utf-8"))
    if REPORT_KEYS - set(report):
        _fail(f"quality_report.json: missing keys {sorted(REPORT_KEYS - set(report))}")

    return {
        "status": "PASS",
        "entity_assignments": len(assignments),
        "canonical_entities": len(canonical_ids),
        "fact_assignments": len(fact_assignments),
        "canonical_edges": len(edge_ids),
        "dropped_facts": sum(
            1
            for row in fact_assignments.values()
            if row["disposition"] == "DROPPED_INVALID"
        ),
        "possible_duplicates": possible_duplicate_rows,
    }
