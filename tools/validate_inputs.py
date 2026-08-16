#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def rows(path: Path):
    with path.open('r', encoding='utf-8') as handle:
        for line_no, line in enumerate(handle, 1):
            if line.strip():
                try:
                    yield line_no, json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SystemExit(f'{path.name}:{line_no}: invalid JSON: {exc}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input_dir', type=Path)
    args = parser.parse_args()
    root = args.input_dir
    required = ['candidate_entities.jsonl','candidate_facts.jsonl','extraction_artifacts.jsonl','source_ledger.jsonl']
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise SystemExit(f'missing input files: {missing}')

    ledger = {}
    for line_no, row in rows(root / 'source_ledger.jsonl'):
        event = row.get('source_event_id')
        if not event or event in ledger:
            raise SystemExit(f'source_ledger.jsonl:{line_no}: missing/duplicate source_event_id')
        ledger[event] = (row.get('org_id'), row.get('workspace_id'))

    chunks = {}
    artifact_rows = 0
    for line_no, row in rows(root / 'extraction_artifacts.jsonl'):
        artifact_rows += 1
        event = row.get('source_event_id')
        if event not in ledger:
            raise SystemExit(f'extraction_artifacts.jsonl:{line_no}: unknown source_event_id')
        for chunk in row.get('chunks') or []:
            chunk_id = chunk.get('chunk_id')
            if not chunk_id or chunk_id in chunks:
                raise SystemExit(f'extraction_artifacts.jsonl:{line_no}: missing/duplicate chunk_id')
            if chunk.get('source_event_id') != event:
                raise SystemExit(f'extraction_artifacts.jsonl:{line_no}: chunk/source event mismatch')
            chunks[chunk_id] = event

    entities = {}
    for line_no, row in rows(root / 'candidate_entities.jsonl'):
        entity_id = row.get('candidate_entity_id')
        if not entity_id or entity_id in entities:
            raise SystemExit(f'candidate_entities.jsonl:{line_no}: missing/duplicate candidate_entity_id')
        event = row.get('source_event_id')
        chunk = row.get('chunk_id')
        if event not in ledger or chunk not in chunks or chunks[chunk] != event:
            raise SystemExit(f'candidate_entities.jsonl:{line_no}: broken event/chunk lineage')
        if ledger[event][0] != row.get('org_id'):
            raise SystemExit(f'candidate_entities.jsonl:{line_no}: org mismatch')
        entities[entity_id] = True

    fact_count = 0
    for line_no, row in rows(root / 'candidate_facts.jsonl'):
        fact_count += 1
        event = row.get('source_event_id')
        chunk = row.get('chunk_id')
        if event not in ledger or chunk not in chunks or chunks[chunk] != event:
            raise SystemExit(f'candidate_facts.jsonl:{line_no}: broken event/chunk lineage')
        if row.get('subject_candidate_id') not in entities:
            raise SystemExit(f'candidate_facts.jsonl:{line_no}: unknown subject_candidate_id')
        obj = row.get('object_candidate_id')
        if obj is not None and obj not in entities:
            raise SystemExit(f'candidate_facts.jsonl:{line_no}: unknown object_candidate_id')

    print(json.dumps({
        'status': 'PASS', 'candidate_entities': len(entities), 'candidate_facts': fact_count,
        'source_ledger_rows': len(ledger), 'extraction_artifacts': artifact_rows, 'chunks': len(chunks),
    }, indent=2))


if __name__ == '__main__':
    main()
