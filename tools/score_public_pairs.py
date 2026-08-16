#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

LABELS = ('MERGE', 'NO_MERGE', 'POSSIBLE_DUPLICATE')


def load_jsonl(path):
    with path.open('r', encoding='utf-8') as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('labels', type=Path)
    parser.add_argument('output_dir', type=Path)
    args = parser.parse_args()

    assignments = {}
    for row in load_jsonl(args.output_dir / 'entity_assignments.jsonl'):
        assignments[row['candidate_entity_id']] = row['canonical_entity_id']

    possible = set()
    for row in load_jsonl(args.output_dir / 'possible_duplicates.jsonl'):
        evidence = sorted(set(row.get('evidence_candidate_entity_ids') or []))
        if len(evidence) == 2:
            possible.add(tuple(evidence))

    matrix = collections.Counter()
    missing = 0
    for row in load_jsonl(args.labels):
        left = row['left_candidate_entity_id']
        right = row['right_candidate_entity_id']
        truth = row['label']
        if left not in assignments or right not in assignments:
            missing += 1
            predicted = 'NO_MERGE'
        elif assignments[left] == assignments[right]:
            predicted = 'MERGE'
        elif tuple(sorted((left, right))) in possible:
            predicted = 'POSSIBLE_DUPLICATE'
        else:
            predicted = 'NO_MERGE'
        matrix[(truth, predicted)] += 1

    metrics = {}
    for label in LABELS:
        tp = matrix[(label, label)]
        fp = sum(matrix[(other, label)] for other in LABELS if other != label)
        fn = sum(matrix[(label, other)] for other in LABELS if other != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metrics[label] = {'precision': precision, 'recall': recall, 'f1': f1, 'support': tp + fn}
    macro_f1 = sum(metrics[label]['f1'] for label in LABELS) / len(LABELS)
    result = {'macro_f1': macro_f1, 'threshold': 0.80, 'pass': macro_f1 >= 0.80, 'missing_assignments': missing, 'per_class': metrics}
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result['pass'] else 1)


if __name__ == '__main__':
    main()
