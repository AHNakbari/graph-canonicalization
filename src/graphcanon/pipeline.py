"""Run orchestration. Output ordering is documented in README.md."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, NamedTuple

from .config import Config
from .duplicates import DuplicateEnumerator
from .jsonio import JsonlWriter, file_size, sha256_file, write_json
from .loading import check_inputs, count_chunks, iter_facts, iter_occurrences, load_scopes
from .projection import project
from .projection import verify_invariants as verify_edges
from .report import build_report, score_labeled_pairs
from .resolve import resolve
from .resolve import verify_invariants as verify_entities
from .resources import RunMetrics

JSONL_OUTPUTS = (
    "entity_assignments.jsonl",
    "canonical_entities.jsonl",
    "possible_duplicates.jsonl",
    "fact_assignments.jsonl",
    "canonical_edges.jsonl",
)
REPORT_FILE = "quality_report.json"
OUTPUT_FILES = JSONL_OUTPUTS + (REPORT_FILE,)
STAGING_DIR = ".staging"


class RunResult(NamedTuple):
    output_dir: Path
    counts: dict[str, int]
    hashes: dict[str, str]
    runtime: dict[str, Any]
    identity_quality: dict[str, Any] | None
    violations: dict[str, int]


def run(config: Config, labels_path: Path | None = None) -> RunResult:
    metrics = RunMetrics.start()

    with metrics.stage("load"):
        check_inputs(config.input_dir)
        scopes = load_scopes(config.input_dir)
        occurrences = list(iter_occurrences(config.input_dir, scopes))
        facts = list(iter_facts(config.input_dir))
        input_counts = {
            "candidate_entities": len(occurrences),
            "candidate_facts": len(facts),
            "source_ledger_rows": len(scopes),
            "chunks": count_chunks(config.input_dir),
            "distinct_source_events_referenced": len(
                {occ.source_event_id for occ in occurrences}
            ),
        }

    with metrics.stage("resolve"):
        resolution = resolve(occurrences, config)

    with metrics.stage("verify_entities"):
        entity_violations = verify_entities(resolution, occurrences)

    with metrics.stage("project"):
        projection = project(facts, resolution, config)
    del facts

    with metrics.stage("verify_edges"):
        edge_violations = verify_edges(projection, resolution)

    enumerator = DuplicateEnumerator(resolution, config)
    if labels_path is not None and labels_path.is_file():
        enumerator.watch = _labeled_pairs(labels_path)

    # Everything is written to staging and moved into place only once every
    # stage has succeeded. A half-written output directory is the one failure
    # mode that could pass a structural check while being wrong.
    staging = config.output_dir / STAGING_DIR
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    try:
        with metrics.stage("write"):
            counts = _write_outputs(staging, resolution, projection, enumerator)

        with metrics.stage("report"):
            output_files = {
                name: {
                    "rows": counts[name],
                    "bytes": file_size(staging / name),
                    "sha256": sha256_file(staging / name),
                }
                for name in JSONL_OUTPUTS
            }
            identity_quality = None
            if labels_path is not None and labels_path.is_file():
                identity_quality = score_labeled_pairs(
                    labels_path, resolution, enumerator.emitted_watch_pairs()
                )
            report = build_report(
                config=config,
                occurrences=occurrences,
                resolution=resolution,
                projection=projection,
                enumerator=enumerator,
                metrics=metrics,
                input_counts=input_counts,
                entity_violations=entity_violations,
                edge_violations=edge_violations,
                output_files=output_files,
                identity_quality=identity_quality,
            )
            write_json(staging / REPORT_FILE, report)

        _promote(staging, config.output_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    hashes = {name: sha256_file(config.output_dir / name) for name in OUTPUT_FILES}
    return RunResult(
        output_dir=config.output_dir,
        counts=counts,
        hashes=hashes,
        runtime=metrics.summary(),
        identity_quality=identity_quality,
        violations={**entity_violations, **edge_violations},
    )


def _labeled_pairs(path: Path) -> set[tuple[str, str]]:
    from .jsonio import read_jsonl

    pairs: set[tuple[str, str]] = set()
    for _line_no, row in read_jsonl(path):
        left = row.get("left_candidate_entity_id")
        right = row.get("right_candidate_entity_id")
        if left and right:
            pairs.add((left, right) if left <= right else (right, left))
    return pairs


def _write_outputs(
    directory: Path,
    resolution,
    projection,
    enumerator: DuplicateEnumerator,
) -> dict[str, int]:
    counts: dict[str, int] = {}

    with JsonlWriter(directory / "entity_assignments.jsonl") as writer:
        for entity_id in sorted(resolution.assignments):
            assignment = resolution.assignments[entity_id]
            writer.write(
                {
                    "candidate_entity_id": assignment.candidate_entity_id,
                    "canonical_entity_id": assignment.canonical_entity_id,
                    "decision": assignment.decision,
                    "confidence": assignment.confidence,
                    "reason_codes": list(assignment.reason_codes),
                }
            )
        counts["entity_assignments.jsonl"] = writer.count

    with JsonlWriter(directory / "canonical_entities.jsonl") as writer:
        for canonical_id in sorted(resolution.entities):
            entity = resolution.entities[canonical_id]
            writer.write(
                {
                    "canonical_entity_id": entity.canonical_entity_id,
                    "canonical_name": entity.canonical_name,
                    "entity_type": entity.entity_type,
                    "org_id": entity.org_id,
                    "workspace_id": entity.workspace_id,
                    "aliases": list(entity.aliases),
                    "member_candidate_entity_ids": list(entity.member_candidate_entity_ids),
                    "source_event_ids": list(entity.source_event_ids),
                    "chunk_ids": list(entity.chunk_ids),
                    "component_quality": entity.component_quality,
                }
            )
        counts["canonical_entities.jsonl"] = writer.count

    with JsonlWriter(directory / "possible_duplicates.jsonl") as writer:
        for line in enumerator.lines():
            writer.write_raw(line)
        counts["possible_duplicates.jsonl"] = writer.count

    with JsonlWriter(directory / "fact_assignments.jsonl") as writer:
        for fact_id in sorted(projection.assignments):
            writer.write(projection.assignments[fact_id].as_row())
        counts["fact_assignments.jsonl"] = writer.count

    with JsonlWriter(directory / "canonical_edges.jsonl") as writer:
        for edge_id in sorted(projection.edges):
            writer.write(projection.edges[edge_id].as_row())
        counts["canonical_edges.jsonl"] = writer.count

    return counts


def _promote(staging: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in OUTPUT_FILES:
        source = staging / name
        if source.is_file():
            os.replace(source, destination / name)
