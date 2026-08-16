# Graph canonicalization

Turns 479,930 raw entity occurrences and 293,475 extracted facts into a
canonical graph: one identity per real thing, every relationship rewired onto
those identities, and every merge, non-merge, and rejection recorded with a
reason.

Python 3.11+, **standard library only**. No network, no external models, no
paid services.

| Document | What it covers |
|---|---|
| [docs/DESIGN_NOTE.md](docs/DESIGN_NOTE.md) | The submitted design note: interpretation, decisions, tradeoffs, failure modes |
| [docs/FINDINGS.md](docs/FINDINGS.md) | Every measurement behind those decisions |
| [docs/RUN_MANIFEST.md](docs/RUN_MANIFEST.md) | The recorded full run: metrics achieved, timings, artifact hashes |
| [submission/README.md](submission/README.md) | The six artifacts, their sizes, and why they are not in git |

---

## 1. Full run

One command produces all six required artifacts:

```bash
python -m graphcanon run --input-dir data/input --output-dir submission/output
```

It reads the four input files and writes the six artifacts, printing row counts,
runtime, peak memory, output SHA-256 hashes, the configuration fingerprint, and
any invariant violation. **A run that breaks an invariant exits non-zero**, so it
can be chained safely.

Measured on the reference machine: **105 s, 577 MiB**. Full results are in
[docs/RUN_MANIFEST.md](docs/RUN_MANIFEST.md).

### Getting the data in place

The handout data is not committed (599 MB). Point `--input-dir` at it, or place
it at `data/input/` so every command here works verbatim:

```bash
# from the challenge package root
cp -r data graph-canonicalization/data
```

## 2. Reproducible environment

The pipeline has **zero runtime dependencies**; `requirements-dev.txt` pins the
two test-only packages exactly, and the image pins the interpreter.

```bash
docker build -t graphcanon .
docker run --rm \
  -v "$PWD/data:/app/data:ro" \
  -v "$PWD/submission/output:/app/submission/output" \
  graphcanon
```

The image is `python:3.13.2-slim-bookworm` with `PYTHONHASHSEED=0`; the default
command is the full run above. Without Docker:

```bash
pip install -r requirements-dev.txt   # pytest==8.3.4, jsonschema==4.23.0
pip install -e .                      # optional; otherwise set PYTHONPATH=src
```

## 3. Tests

```bash
python -m pytest                  # 174 tests, incl. the full-dataset run
```

Each of the ten scenarios the specification requires maps to named tests:

| # | Required scenario | Where |
|---:|---|---|
| 1 | Coverage accounting; missing/duplicate assignments fail | `test_verify_equivalence.py` (dropped, duplicated and double-counted assignment corruptions), `test_resolve.py::test_members_partition_the_input` |
| 2 | Scope isolation across organizations and workspaces | `test_resolve.py::test_organization_isolation`, `::test_workspace_isolation`, `test_loading.py` |
| 3 | Type isolation | `test_resolve.py::test_type_isolation` |
| 4 | Uncertain identity represented, never discarded | `test_resolve.py::test_unresolved_persons_are_flagged_on_the_assignment`, `test_duplicates.py::test_a_truncated_group_still_states_its_open_question` |
| 5 | Dangling endpoint rejected with a reason | `test_projection.py::test_no_dangling_edge_survives_a_rejection`, `::test_an_unresolved_endpoint_is_rejected_not_invented` |
| 6 | Provenance retained through consolidation | `test_projection.py::test_consolidation_keeps_every_contributing_reference`, `test_resolve.py::test_components_retain_every_contributing_reference` |
| 7 | Determinism across two runs | `test_pipeline.py::test_two_runs_produce_identical_bytes` |
| 8 | Input-order robustness | `test_pipeline.py::test_shuffled_input_produces_identical_output`, `test_unionfind.py::test_components_are_independent_of_union_order` |
| 9 | Documented behaviour when an optional dependency is unavailable | `test_no_external_dependencies.py` |
| 10 | Scale evidence with recorded runtime and memory | `test_full_dataset.py` (marked `slow`) |

## 4. Acceptance

```bash
make accept
```

runs, in order:

```bash
python tools/validate_inputs.py data/input
python tools/validate_fictionalization.py data/input
python -m graphcanon run    --input-dir data/input --output-dir submission/output
python -m graphcanon verify --input-dir data/input --output-dir submission/output
python tools/score_public_pairs.py data/reference/public_labeled_pairs.jsonl submission/output
```

`tools/` and `schemas/` are the challenge package's own copies, vendored
unchanged.

`python -m graphcanon verify` is `tools/validate_submission.py` transcribed
assertion-for-assertion with one expression hoisted out of two loops. The
supplied tool rebuilds a 479,930-element set on every iteration, which costs it
over an hour on *any* correct submission of this dataset before a single
unresolved pair exists; the verifier checks the full submission in 57 s and
returns `PASS`. The measurement, the one-line fix, and the reason the vendored
copy is left untouched are in [docs/FINDINGS.md](docs/FINDINGS.md) §7.
`make accept-strict` runs the supplied tool instead, for anyone who wants it.

## 5. Other commands

```bash
python -m graphcanon profile --input-dir data/input   # summarise the input
python -m graphcanon config                           # show the resolved policy
make determinism                                      # two runs, compare hashes
```

## 6. Output ordering

Deterministic and content-addressed: two runs, and runs over shuffled input,
produce byte-identical artifacts. Canonical IDs are hashes of identity-bearing
content, so these orders are stable across runs, not merely re-sortable
afterwards.

| File | Order |
|---|---|
| `entity_assignments.jsonl` | `candidate_entity_id` ascending |
| `canonical_entities.jsonl` | `canonical_entity_id` ascending |
| `fact_assignments.jsonl` | `candidate_fact_id` ascending |
| `canonical_edges.jsonl` | `canonical_edge_id` ascending |
| `possible_duplicates.jsonl` | pairwise rows by (org, workspace, normalized name, left source event, right source event, left candidate id, right candidate id), then group-level rows by (left canonical id, right canonical id, evidence) |

`quality_report.json` is excluded from hash comparison: it records measured
runtime, which does not repeat and is not part of the canonical result.

## 7. Layout

```
src/graphcanon/
  cli.py          command line
  pipeline.py     stage orchestration, staged writes, ordering
  loading.py      input parsing, scope join, string interning
  naming.py       name-shape rules
  unionfind.py    order-independent components
  ids.py          content-addressed canonical IDs
  resolve.py      occurrences -> canonical entities (+ invariant re-derivation)
  duplicates.py   unresolved identity pairs, budgeting
  projection.py   facts -> canonical edges (+ invariant re-derivation)
  report.py       quality_report.json
  verify.py       accelerated equivalent of the acceptance validator
  confidence.py   evidence tiers, and what they do not claim
  config.py       policy + fingerprint
  resources.py    runtime and peak-memory measurement
tests/fixtures/mini/   13 occurrences, 6 facts, one per rule
```
