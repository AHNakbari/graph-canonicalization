# Run manifest

The record of the full run whose artifacts are in `submission/output/`.
Regenerate with:

```bash
python -m graphcanon run --input-dir data/input --output-dir submission/output
```

Configuration fingerprint
`6161ca43e0903e55bb4b8ed10f0a7513c2a5f8587bd1bedc0cd1829a3f31f9dd`
(algorithm version 1.0.0). Any change to the resolution policy changes this
value, so a reviewer can always tell which policy produced a given set of
artifacts.

Artifact rows, sizes and SHA-256 hashes are listed in
[submission/README.md](../submission/README.md), together with why they are not
committed.

## Environment

| | |
|---|---|
| Platform | Windows-11-10.0.26200-SP0 |
| Processor | Intel64 Family 6 Model 186 Stepping 3, GenuineIntel |
| Python | CPython 3.13.2 |
| Wall clock | 105.351 s |
| Peak memory | 577.3 MiB (`windows_peak_working_set`) |

| Stage | Seconds |
|---|---:|
| load | 17.575 |
| resolve | 10.039 |
| verify_entities | 1.993 |
| project | 6.107 |
| verify_edges | 1.620 |
| write | 61.672 |

Write dominates because it enumerates and serialises 8.07 M unresolved-pair
rows; every other stage is linear. See [DESIGN_NOTE.md](DESIGN_NOTE.md),
"Complexity and scale".

Two notes on the wall clock. It is dominated by writing the 2.21 GB
`possible_duplicates.jsonl`, so it moves with disk state: three consecutive runs
on this machine took 105 s, 111 s and 124 s, and all three produced byte
identical JSONL. The same applies to the verification timings below, which are
dominated by reading that file. And the figure recorded inside
`quality_report.json` is taken while the report is still being assembled, so the
true end to end time printed by the CLI is a few seconds higher.

## Required metrics

| Metric | Required | Achieved |
|---|---:|---:|
| Entity assignment coverage | 1.0000 | 1.0000 (479,930/479,930) |
| Canonical membership coverage | 1.0000 | 1.0000 (479,930/479,930) |
| Membership uniqueness | 1.0000 | 1.0000 |
| Fact disposition coverage | 1.0000 | 1.0000 (293,475/293,475) |
| Endpoint validity | 1.0000 | 1.0000 (81,715/81,715) |
| Reasoned fact coverage | ≥ 0.9900 | 1.0000 (293,475/293,475) |
| Provenance coverage | 1.0000 | 1.0000 (147,835/147,835) |
| Boundary violations | 0 | 0 |
| Deterministic hash agreement | 1.0000 | 1.0000 (five JSONL artifacts) |
| Public macro-F1 | ≥ 0.80 | **0.9861** |
| Hard-merge precision | ≥ 0.97 | **1.0000** |

Per class: MERGE P 1.0000 / R 0.9583, NO_MERGE P 0.9600 / R 1.0000,
POSSIBLE_DUPLICATE P 1.0000 / R 1.0000. Missing assignments: 0.

## Graph shape

| | |
|---|---:|
| Canonical entities | 66,120 |
| Canonical edges | 81,715 |
| Facts projected | 291,872 |
| Facts rejected | 1,603 (`SELF_LOOP_AFTER_CANONICALIZATION` 1,603) |
| Edge consolidation rate | 0.7200 |
| Self-loop edges | 0 |
| Isolated canonical entities | 20,017 (30.27%) |
| Component size p50 / p90 / p95 / p99 / max | 1 / 8 / 16 / 75 / 22,486 |
| Unresolved pairs (all enumerated) | 8,060,924 pairwise + 5,705 group-level |
| Invariant violations | 0 |

Canonical entities by type: LegalNorm 15,338, Person 13,508, LegalProvision
11,733, Document 7,678, Topic 4,454, LegalEntity 3,954, DateRef 2,378,
LegalRole 1,754, Matter 1,603, Money 1,414, Place 906, Department 795,
LegalClaim 605.

The largest components are not merge failures. `organization-cce385fdfb84`
(22,486 occurrences across 2,485 documents) is the corpus's own client
organization; the largest `Person` component is a full two-token name appearing
in 2,562 documents. Both are what a legal document set should look like. A run
where the largest component was a `Person` spanning every document would be an
alarm even with all invariants green.

## External services

None. No model, no network, no paid API, so no call volume, no retry or failure
counts, and no cost to report. Asserted mechanically by
`tests/test_no_external_dependencies.py`.

## Verification performed

| Check | Result |
|---|---|
| `tools/validate_inputs.py` | PASS |
| `tools/validate_fictionalization.py` | PASS |
| `python -m graphcanon verify` | PASS in 57 s |
| `tools/score_public_pairs.py` | macro-F1 0.9861, pass, 49 s |
| `python -m pytest` | 174 passed |
| Determinism (`make determinism`) | five JSONL artifacts byte-identical across runs |

`tools/validate_submission.py` makes the same assertions as `graphcanon verify`
but rescans the input entity set once per canonical entity and once per
unresolved pair, which does not complete on artifacts of this size; the
measurement and the one-line fix are in [FINDINGS.md](FINDINGS.md) §7.
