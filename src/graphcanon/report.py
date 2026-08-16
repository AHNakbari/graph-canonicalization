"""quality_report.json assembly.

Every rate ships with the counts it came from - the spec requires reproducible
denominators, so nothing here may report a bare ratio.
"""

from __future__ import annotations

import collections
from typing import Any, Iterable

from . import reasons
from .config import Config
from .duplicates import DuplicateEnumerator
from .jsonio import read_jsonl
from .loading import Occurrence
from .projection import DISPOSITION_PROJECTED, Projection
from .resolve import Resolution
from .resources import RunMetrics

REQUIRED_KEYS = (
    "input_counts",
    "output_counts",
    "coverage",
    "safety",
    "components",
    "runtime",
    "configuration_fingerprint",
)

LABELS = ("MERGE", "NO_MERGE", "POSSIBLE_DUPLICATE")


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 6) if denominator else 1.0,
    }


def percentiles(values: list[int]) -> dict[str, int]:
    if not values:
        return {"p50": 0, "p90": 0, "p95": 0, "p99": 0, "max": 0}
    ordered = sorted(values)

    def at(fraction: float) -> int:
        rank = max(1, min(len(ordered), int(-(-len(ordered) * fraction // 1))))
        return ordered[rank - 1]

    return {
        "p50": at(0.50),
        "p90": at(0.90),
        "p95": at(0.95),
        "p99": at(0.99),
        "max": ordered[-1],
    }


def score_labeled_pairs(
    labels_path,
    resolution: Resolution,
    emitted_pairs: set[tuple[str, str]],
) -> dict[str, Any]:
    """Three-class identity metrics against the rows actually written.

    A diagnostic; tools/score_public_pairs.py stays authoritative. The
    prediction rule below must keep matching it exactly, and ``emitted_pairs``
    must keep coming from rows actually written rather than from what the
    policy intended to write.
    """
    assignments = resolution.assignments
    matrix: collections.Counter[tuple[str, str]] = collections.Counter()
    predicted_counts: collections.Counter[str] = collections.Counter()
    confidences: dict[str, list[float]] = {label: [] for label in LABELS}
    missing = 0

    for _line_no, row in read_jsonl(labels_path):
        left = row["left_candidate_entity_id"]
        right = row["right_candidate_entity_id"]
        truth = row["label"]
        pair = (left, right) if left <= right else (right, left)

        if left not in assignments or right not in assignments:
            missing += 1
            predicted = "NO_MERGE"
        elif assignments[left].canonical_entity_id == assignments[right].canonical_entity_id:
            predicted = "MERGE"
            confidences["MERGE"].append(assignments[left].confidence)
        elif pair in emitted_pairs:
            predicted = "POSSIBLE_DUPLICATE"
        else:
            predicted = "NO_MERGE"
        matrix[(truth, predicted)] += 1
        predicted_counts[predicted] += 1

    per_class: dict[str, Any] = {}
    for label in LABELS:
        true_positive = matrix[(label, label)]
        false_positive = sum(matrix[(other, label)] for other in LABELS if other != label)
        false_negative = sum(matrix[(label, other)] for other in LABELS if other != label)
        precision = (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 0.0
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else 0.0
        )
        f1 = (
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        )
        per_class[label] = {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "support": true_positive + false_negative,
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
        }

    macro_f1 = sum(per_class[label]["f1"] for label in LABELS) / len(LABELS)
    return {
        "source": str(labels_path),
        "macro_f1": round(macro_f1, 6),
        "threshold": 0.80,
        "pass": macro_f1 >= 0.80,
        "hard_merge_precision": per_class["MERGE"]["precision"],
        "hard_merge_precision_threshold": 0.97,
        "missing_assignments": missing,
        "per_class": per_class,
        "confusion_matrix": {
            truth: {
                predicted: matrix[(truth, predicted)] for predicted in LABELS
            }
            for truth in LABELS
        },
        "predicted_class_counts": {label: predicted_counts[label] for label in LABELS},
        "predicted_class_confidence": {
            label: _distribution(values) for label, values in confidences.items()
        },
    }


def _determinism(output_files: dict[str, dict[str, Any]]) -> dict[str, Any]:
    # A single run cannot observe two-run agreement, so no rate is asserted
    # here. It publishes the hashes to compare and names where the comparison
    # is actually performed. Claiming 1.0 from one run would be the kind of
    # unmeasured assertion the rest of this report avoids.
    return {
        "deterministic_hash_agreement": {
            "compared_files": sorted(output_files),
            "sha256": {name: meta["sha256"] for name, meta in sorted(output_files.items())},
            "excluded": {
                "quality_report.json": (
                    "records measured wall clock and peak memory, which do not "
                    "repeat and are not part of the canonical result"
                )
            },
            "measured_by": [
                "make determinism",
                "tests/test_pipeline.py::test_two_runs_produce_identical_bytes",
                "tests/test_pipeline.py::test_shuffled_input_produces_identical_output",
            ],
            "note": (
                "One run cannot observe agreement across two runs. The rate "
                "measured by the commands above is recorded in "
                "docs/RUN_MANIFEST.md."
            ),
        }
    }


def _distribution(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "note": "no confidence attaches to this predicted class"}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "mean": round(sum(ordered) / len(ordered), 6),
        "histogram": dict(
            sorted(collections.Counter(f"{v:.2f}" for v in ordered).items())
        ),
    }


def build_report(
    config: Config,
    occurrences: Iterable[Occurrence],
    resolution: Resolution,
    projection: Projection,
    enumerator: DuplicateEnumerator,
    metrics: RunMetrics,
    input_counts: dict[str, int],
    entity_violations: dict[str, int],
    edge_violations: dict[str, int],
    output_files: dict[str, dict[str, Any]],
    identity_quality: dict[str, Any] | None,
) -> dict[str, Any]:
    occurrences = list(occurrences)
    entities = resolution.entities
    edges = projection.edges

    total_occurrences = len(occurrences)
    total_facts = len(projection.assignments)

    members_seen = sum(len(e.member_candidate_entity_ids) for e in entities.values())
    distinct_members = {
        member for e in entities.values() for member in e.member_candidate_entity_ids
    }

    projected = sum(
        1
        for a in projection.assignments.values()
        if a.disposition == DISPOSITION_PROJECTED
    )
    reasoned = sum(
        1
        for a in projection.assignments.values()
        if a.disposition == DISPOSITION_PROJECTED
        or set(a.reason_codes) & reasons.VALID_REJECTION_CODES
    )
    valid_endpoints = sum(
        1
        for e in edges.values()
        if e.subject_canonical_entity_id in entities
        and (e.object_canonical_entity_id is None or e.object_canonical_entity_id in entities)
    )
    with_provenance = sum(
        1 for e in entities.values() if e.source_event_ids and e.chunk_ids
    ) + sum(
        1
        for e in edges.values()
        if e.source_candidate_fact_ids and e.source_event_ids and e.chunk_ids
    )

    sizes = [len(e.member_candidate_entity_ids) for e in entities.values()]
    by_type: collections.Counter[str] = collections.Counter()
    by_scope: collections.Counter[str] = collections.Counter()
    for entity in entities.values():
        by_type[entity.entity_type] += 1
        by_scope[f"{entity.org_id}/{entity.workspace_id}"] += 1

    touched: set[str] = set()
    self_loops = 0
    for edge in edges.values():
        touched.add(edge.subject_canonical_entity_id)
        if edge.object_canonical_entity_id is not None:
            touched.add(edge.object_canonical_entity_id)
            if edge.object_canonical_entity_id == edge.subject_canonical_entity_id:
                self_loops += 1
    isolated = len(entities) - len(touched)

    largest = sorted(
        entities.values(),
        key=lambda e: (-len(e.member_candidate_entity_ids), e.canonical_entity_id),
    )[:20]

    decisions: collections.Counter[str] = collections.Counter()
    assignment_confidence: collections.Counter[str] = collections.Counter()
    reason_counts: collections.Counter[str] = collections.Counter()
    for assignment in resolution.assignments.values():
        decisions[assignment.decision] += 1
        assignment_confidence[f"{assignment.confidence:.2f}"] += 1
        for code in assignment.reason_codes:
            reason_counts[code] += 1

    all_violations = {**entity_violations, **edge_violations}
    report: dict[str, Any] = {
        "algorithm_version": config.describe()["algorithm_version"],
        "configuration_fingerprint": config.fingerprint(),
        "configuration": config.describe()["policy"],
        "input_counts": input_counts,
        "output_counts": {
            "entity_assignments": len(resolution.assignments),
            "canonical_entities": len(entities),
            "canonical_edges": len(edges),
            "fact_assignments": len(projection.assignments),
            "possible_duplicates": (
                int(enumerator.stats.get("pairwise_rows", 0))
                + int(enumerator.stats.get("group_rows", 0))
            ),
            "possible_duplicates_pairwise": enumerator.stats.get("pairwise_rows", 0),
            "possible_duplicates_group_level": enumerator.stats.get("group_rows", 0),
            "facts_projected": projected,
            "facts_rejected": total_facts - projected,
        },
        "coverage": {
            "entity_assignment_coverage": _rate(
                len(resolution.assignments), total_occurrences
            ),
            "canonical_membership_coverage": _rate(
                len(distinct_members), total_occurrences
            ),
            "membership_uniqueness": _rate(members_seen, total_occurrences)
            if members_seen == len(distinct_members)
            else {
                "numerator": len(distinct_members),
                "denominator": total_occurrences,
                "rate": round(len(distinct_members) / total_occurrences, 6),
                "duplicate_memberships": members_seen - len(distinct_members),
            },
            "fact_disposition_coverage": _rate(len(projection.assignments), total_facts),
            "endpoint_validity": _rate(valid_endpoints, len(edges)),
            "reasoned_fact_coverage": _rate(reasoned, total_facts),
            "provenance_coverage": _rate(with_provenance, len(entities) + len(edges)),
        },
        "determinism": _determinism(output_files),
        "safety": {
            "boundary_violations": sum(
                all_violations.get(key, 0)
                for key in (
                    "cross_organization_components",
                    "cross_workspace_components",
                    "cross_type_components",
                )
            ),
            "cross_organization_components": all_violations.get(
                "cross_organization_components", 0
            ),
            "cross_workspace_components": all_violations.get(
                "cross_workspace_components", 0
            ),
            "cross_type_components": all_violations.get("cross_type_components", 0),
            "prohibited_one_token_person_components": all_violations.get(
                "prohibited_one_token_person_components", 0
            ),
            "dangling_edge_endpoints": all_violations.get("edges_with_unknown_subject", 0)
            + all_violations.get("edges_with_unknown_object", 0),
            "facts_on_multiple_edges": all_violations.get("facts_on_multiple_edges", 0),
            "self_loop_edges": self_loops,
            "invariant_violations": dict(sorted(all_violations.items())),
            "invariant_violations_total": sum(all_violations.values()),
            "external_services_used": [],
            "network_access": False,
            "remote_model_calls": 0,
            "estimated_cost_usd": 0.0,
            "notes": (
                "Standard-library Python only: no external model, service, or "
                "network access, so there is no remote failure mode to degrade to."
            ),
        },
        "components": {
            "canonical_entities_by_type": dict(sorted(by_type.items())),
            "canonical_entities_by_scope": dict(sorted(by_scope.items())),
            "size_percentiles": percentiles(sizes),
            "size_percentile_method": "nearest-rank over member counts",
            "largest_components": [
                {
                    "canonical_entity_id": e.canonical_entity_id,
                    "canonical_name": e.canonical_name,
                    "entity_type": e.entity_type,
                    "member_count": len(e.member_candidate_entity_ids),
                    "source_event_count": len(e.source_event_ids),
                    "chunk_count": len(e.chunk_ids),
                }
                for e in largest
            ],
            "isolated_canonical_entities": _rate(isolated, len(entities)),
            "edges": {
                "count": len(edges),
                "consolidation_rate": projection.stats.get("edge_consolidation_rate", 0.0),
                "consolidation_note": (
                    "1 - edges / projected facts; "
                    f"{projected} facts became {len(edges)} edges"
                ),
                "self_loop_rate": _rate(self_loops, len(edges)),
                "orphan_edges": all_violations.get("edges_with_unknown_subject", 0)
                + all_violations.get("edges_with_unknown_object", 0),
                "predicates": len({e.predicate for e in edges.values()}),
            },
            "facts_rejected_by_reason": projection.rejected_by_reason,
            "entity_decisions": dict(sorted(decisions.items())),
            "entity_reason_codes": dict(sorted(reason_counts.items())),
            "assignment_confidence_histogram": dict(sorted(assignment_confidence.items())),
            "unresolved_pairs": {
                **{k: v for k, v in enumerator.stats.items()},
                "confidence_histogram": enumerator.confidence_histogram(),
            },
            "resolution_stats": resolution.stats,
        },
        "runtime": metrics.summary(),
        "outputs": output_files,
    }
    if identity_quality is not None:
        report["identity_quality"] = identity_quality
    return report
