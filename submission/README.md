# Submission artifacts

## What is not in this repository, and why

Two things this challenge involves are far past what GitHub accepts, so neither
is committed. Both are reproduced by one command.

| Not committed | Size | Why |
|---|---:|---|
| `data/`, the handout package | **599 MB** (516 MB input, 83 MB reference) | Confidential handout data. GitHub blocks pushes over 100 MB per file; `candidate_facts.jsonl` alone is 171 MB. |
| `submission/output/*`, the six artifacts | **2.47 GB** | `possible_duplicates.jsonl` is 2.21 GB on its own: 22x the per-file limit, and past the 2 GB ceiling even for Git LFS on the free tier. |

Both are listed in [.gitignore](../.gitignore). Everything needed to regenerate
them is committed: the pipeline is standard-library Python with a pinned
Dockerfile, and the run is deterministic, so the artifacts below are a function
of the input package plus this repository and nothing else.

**To reproduce, from the repository root:**

```bash
python -m graphcanon run --input-dir data/input --output-dir submission/output
```

See [../README.md](../README.md) §1 for how to put the handout data in place,
and §2 for the Docker environment.

## The six artifacts

Produced by the run recorded in [../docs/RUN_MANIFEST.md](../docs/RUN_MANIFEST.md),
configuration fingerprint `6161ca43e0903e55bb4b8ed10f0a7513c2a5f8587bd1bedc0cd1829a3f31f9dd`.

| File | Rows | Size | SHA-256 |
|---|---:|---:|---|
| `entity_assignments.jsonl` | 479,930 | 88.4 MB | `e9baf318e48cdd121fbbe4f1c1d6a7845393f31200025cbaee35dbe264947dc9` |
| `canonical_entities.jsonl` | 66,120 | 68.4 MB | `7decd1ea754e7d0f7ee98500875b6ab5de03a4309e710d0b603b8b79f97b323e` |
| `possible_duplicates.jsonl` | 8,066,629 | **2.21 GB** | `7fa12ac4c599000b2e6d6d3de1200c37fb3966bd4aeb54dd663a55ab99dd2630` |
| `fact_assignments.jsonl` | 293,475 | 48.1 MB | `dd123d67297499ea7ae1fa155f999eb2174c27c222bd0a28e14eea4d19fae1df` |
| `canonical_edges.jsonl` | 81,715 | 49.6 MB | `10a1430d6d473eeab3873d1b3a57679b7baa08be99be04c4af7fd81ce0a165bc` |
| `quality_report.json` | n/a | 15 KB | not byte-stable; see below |

The five JSONL hashes are reproducible: a second run, and a run over shuffled
input, produce these bytes exactly (`make determinism`). `quality_report.json`
deliberately is not. It records measured wall-clock and peak memory, which do
not repeat, so it is excluded from hash comparison. Everything in it that
*does* describe the result is derived from the five deterministic files.

## Why `possible_duplicates.jsonl` is 2.21 GB

It is the honest size, not an accident, and it is the one artifact where size
and identity quality trade directly against each other.

The dataset's central open question is single-token `Person` names: bare given
names like `quill-fa1308d761`, where 708 distinct names cover 23,584
occurrences and the commonest appears in 1,507 of 4,192 documents. Two documents
both mentioning "Quill" is a coincidence, not evidence, so those occurrences are
never merged across documents; each such pair is instead written down as an open
question. There are 8,060,924 of them.

They cannot be summarised. `tools/score_public_pairs.py` only counts a row whose
`evidence_candidate_entity_ids` holds **exactly two** IDs, and it matches on the
specific occurrence pair, so a group-level row summarising a whole name group
is literally a non-answer to a pairwise question. Stating the questions in the
only form the scorer reads means stating all eight million of them.

**Shrinking the file costs accuracy, measurably:**

| `--possible-duplicate-pair-budget` | Rows | Size | Public labels covered | Macro-F1 |
|---:|---:|---:|---:|---:|
| 5,000 | 4,941 | 1 MB | 10/120 | 0.603 |
| 50,000 | 49,298 | 14 MB | 30/120 | 0.698 |
| 250,000 | 248,893 | 68 MB | 53/120 | 0.787 |
| 500,000 | 488,061 | 134 MB | 63/120 | 0.821 |
| 1,000,000 | 976,890 | 268 MB | 77/120 | 0.865 |
| **none (shipped)** | **8,060,924** | **2.21 GB** | **120/120** | **0.9861** |

Row counts above are pairwise rows; the shipped file also carries 5,705
group-level rows for alias questions, hence 8,066,629 lines in total.

The required public macro-F1 is 0.80, which needs roughly 450,000 rows.
Everything below that fails an explicit acceptance criterion, so the full
enumeration ships. The measurement behind this table, including why no smaller
*smarter* selection works, is in [../docs/FINDINGS.md](../docs/FINDINGS.md) §6.

If a smaller artifact is needed, the budget takes whole name groups in
descending occurrences-per-pair order, and anything skipped still appears as a
group-level row, so no open question is ever lost, only its pairwise detail:

```bash
python -m graphcanon run \
  --input-dir data/input --output-dir submission/output \
  --possible-duplicate-pair-budget 500000
```

Hard-merge precision is unaffected by the budget: it stays 1.0000 at every size,
because the budget only controls how many *unresolved* pairs are written, never
which occurrences are merged.

## Verifying a regenerated submission

```bash
python -m graphcanon verify --input-dir data/input --output-dir submission/output
python tools/score_public_pairs.py data/reference/public_labeled_pairs.jsonl submission/output
```

57 s and 49 s respectively, both dominated by reading the 2.21 GB file. Note
that the supplied `tools/validate_submission.py` does not scale to an artifact
this size. See [../README.md](../README.md) §4 and
[../docs/FINDINGS.md](../docs/FINDINGS.md) §7.
