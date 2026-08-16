#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

REQUIRED = [
    'entity_assignments.jsonl','canonical_entities.jsonl','possible_duplicates.jsonl',
    'fact_assignments.jsonl','canonical_edges.jsonl','quality_report.json',
]
ENTITY_DECISIONS = {'NEW_CANONICAL','MERGED','POSSIBLE_DUPLICATE'}
FACT_DISPOSITIONS = {'PROJECTED','DROPPED_INVALID'}
CORROBORATING_CODES = {'VERIFIED_IDENTIFIER','SOURCE_LOCAL_ALIAS','VERIFIED_CONTACT'}
TOKEN_RE = re.compile(r"[\w]+(?:[-'][\w]+)*", re.UNICODE)


def rows(path: Path):
    with path.open('r', encoding='utf-8') as handle:
        for line_no, line in enumerate(handle, 1):
            if line.strip():
                try:
                    yield line_no, json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SystemExit(f'{path.name}:{line_no}: invalid JSON: {exc}')


def fail(message):
    raise SystemExit(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input_dir', type=Path)
    parser.add_argument('output_dir', type=Path)
    args = parser.parse_args()
    missing = [name for name in REQUIRED if not (args.output_dir / name).is_file()]
    if missing:
        fail(f'missing output files: {missing}')

    event_scope = {}
    for _, row in rows(args.input_dir / 'source_ledger.jsonl'):
        event_scope[row['source_event_id']] = (row['org_id'], row['workspace_id'])

    input_entities = {}
    for line_no, row in rows(args.input_dir / 'candidate_entities.jsonl'):
        entity_id = row['candidate_entity_id']
        if entity_id in input_entities:
            fail(f'candidate_entities.jsonl:{line_no}: duplicate ID')
        org, workspace = event_scope[row['source_event_id']]
        input_entities[entity_id] = {
            'type': row['type'], 'org': org, 'workspace': workspace, 'source': row['source_event_id'],
            'chunk': row['chunk_id'], 'normalized_name': row.get('normalized_name') or row.get('name',''),
        }

    input_facts = {}
    for line_no, row in rows(args.input_dir / 'candidate_facts.jsonl'):
        fact_id = row['candidate_fact_id']
        if fact_id in input_facts:
            fail(f'candidate_facts.jsonl:{line_no}: duplicate ID')
        input_facts[fact_id] = row

    assignments = {}
    for line_no, row in rows(args.output_dir / 'entity_assignments.jsonl'):
        entity_id = row.get('candidate_entity_id')
        if entity_id not in input_entities or entity_id in assignments:
            fail(f'entity_assignments.jsonl:{line_no}: unknown/duplicate candidate_entity_id')
        if row.get('decision') not in ENTITY_DECISIONS:
            fail(f'entity_assignments.jsonl:{line_no}: invalid decision')
        if not row.get('canonical_entity_id') or not row.get('reason_codes'):
            fail(f'entity_assignments.jsonl:{line_no}: missing canonical ID or reason codes')
        assignments[entity_id] = row
    if set(assignments) != set(input_entities):
        fail(f'entity assignment coverage mismatch: missing={len(set(input_entities)-set(assignments))}')

    canonical_ids = set()
    member_seen = set()
    one_token_person_violations = 0
    for line_no, row in rows(args.output_dir / 'canonical_entities.jsonl'):
        canonical_id = row.get('canonical_entity_id')
        members = row.get('member_candidate_entity_ids') or []
        if not canonical_id or canonical_id in canonical_ids or not members:
            fail(f'canonical_entities.jsonl:{line_no}: missing/duplicate ID or empty members')
        canonical_ids.add(canonical_id)
        if len(members) != len(set(members)):
            fail(f'canonical_entities.jsonl:{line_no}: duplicate member')
        unknown = set(members) - set(input_entities)
        if unknown:
            fail(f'canonical_entities.jsonl:{line_no}: unknown members')
        overlap = set(members) & member_seen
        if overlap:
            fail(f'canonical_entities.jsonl:{line_no}: members appear in multiple components')
        member_seen.update(members)
        scopes = {(input_entities[m]['org'], input_entities[m]['workspace'], input_entities[m]['type']) for m in members}
        if len(scopes) != 1:
            fail(f'canonical_entities.jsonl:{line_no}: component crosses org/workspace/type')
        scope = next(iter(scopes))
        if row.get('org_id') != scope[0] or row.get('workspace_id') != scope[1] or row.get('entity_type') != scope[2]:
            fail(f'canonical_entities.jsonl:{line_no}: declared scope/type mismatch')
        for member in members:
            if assignments[member]['canonical_entity_id'] != canonical_id:
                fail(f'canonical_entities.jsonl:{line_no}: assignment/member mismatch')
        if scope[2].casefold() == 'person' and len(members) > 1:
            all_one_token = all(len(TOKEN_RE.findall(input_entities[m]['normalized_name'])) == 1 for m in members)
            multiple_sources = len({input_entities[m]['source'] for m in members}) > 1
            if all_one_token and multiple_sources:
                codes = set().union(*(set(assignments[m].get('reason_codes') or []) for m in members))
                if not (codes & CORROBORATING_CODES):
                    one_token_person_violations += 1
    if member_seen != set(input_entities):
        fail(f'canonical membership coverage mismatch: missing={len(set(input_entities)-member_seen)}')
    if set(row['canonical_entity_id'] for row in assignments.values()) != canonical_ids:
        fail('assignments reference missing or unused canonical entities')
    if one_token_person_violations:
        fail(f'prohibited one-token Person components: {one_token_person_violations}')

    for line_no, row in rows(args.output_dir / 'possible_duplicates.jsonl'):
        left = row.get('left_canonical_entity_id')
        right = row.get('right_canonical_entity_id')
        if left not in canonical_ids or right not in canonical_ids or left == right:
            fail(f'possible_duplicates.jsonl:{line_no}: invalid canonical pair')
        evidence = row.get('evidence_candidate_entity_ids') or []
        if len(set(evidence)) < 2 or set(evidence) - set(input_entities):
            fail(f'possible_duplicates.jsonl:{line_no}: invalid evidence IDs')

    fact_assignments = {}
    projected_to_edge = collections.defaultdict(set)
    for line_no, row in rows(args.output_dir / 'fact_assignments.jsonl'):
        fact_id = row.get('candidate_fact_id')
        if fact_id not in input_facts or fact_id in fact_assignments:
            fail(f'fact_assignments.jsonl:{line_no}: unknown/duplicate fact')
        disposition = row.get('disposition')
        if disposition not in FACT_DISPOSITIONS or not row.get('reason_codes'):
            fail(f'fact_assignments.jsonl:{line_no}: invalid disposition/reasons')
        edge_id = row.get('canonical_edge_id')
        if disposition == 'PROJECTED':
            if not edge_id:
                fail(f'fact_assignments.jsonl:{line_no}: projected fact missing edge ID')
            projected_to_edge[edge_id].add(fact_id)
        elif edge_id is not None:
            fail(f'fact_assignments.jsonl:{line_no}: dropped fact must have null edge ID')
        fact_assignments[fact_id] = row
    if set(fact_assignments) != set(input_facts):
        fail(f'fact assignment coverage mismatch: missing={len(set(input_facts)-set(fact_assignments))}')

    edge_ids = set()
    edge_fact_ids = set()
    for line_no, row in rows(args.output_dir / 'canonical_edges.jsonl'):
        edge_id = row.get('canonical_edge_id')
        if not edge_id or edge_id in edge_ids:
            fail(f'canonical_edges.jsonl:{line_no}: missing/duplicate edge ID')
        edge_ids.add(edge_id)
        if row.get('subject_canonical_entity_id') not in canonical_ids:
            fail(f'canonical_edges.jsonl:{line_no}: unknown subject canonical ID')
        obj = row.get('object_canonical_entity_id')
        if obj is not None and obj not in canonical_ids:
            fail(f'canonical_edges.jsonl:{line_no}: unknown object canonical ID')
        if obj is None and 'object_value' not in row:
            fail(f'canonical_edges.jsonl:{line_no}: missing object endpoint/value')
        source_facts = set(row.get('source_candidate_fact_ids') or [])
        if not source_facts or source_facts - set(input_facts):
            fail(f'canonical_edges.jsonl:{line_no}: invalid source facts')
        if edge_fact_ids & source_facts:
            fail(f'canonical_edges.jsonl:{line_no}: fact appears on multiple edges')
        edge_fact_ids.update(source_facts)
        if projected_to_edge.get(edge_id, set()) != source_facts:
            fail(f'canonical_edges.jsonl:{line_no}: fact assignment/edge provenance mismatch')
    if set(projected_to_edge) != edge_ids:
        fail('projected assignments reference missing or unused edges')

    report = json.loads((args.output_dir / 'quality_report.json').read_text(encoding='utf-8'))
    required_report = {'input_counts','output_counts','coverage','safety','components','runtime','configuration_fingerprint'}
    if required_report - set(report):
        fail(f'quality_report.json: missing keys {sorted(required_report-set(report))}')

    print(json.dumps({
        'status': 'PASS', 'entity_assignments': len(assignments), 'canonical_entities': len(canonical_ids),
        'fact_assignments': len(fact_assignments), 'canonical_edges': len(edge_ids),
        'dropped_facts': sum(1 for row in fact_assignments.values() if row['disposition'] == 'DROPPED_INVALID'),
    }, indent=2))


if __name__ == '__main__':
    main()
