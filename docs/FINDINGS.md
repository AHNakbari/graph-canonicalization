# Findings

The measurements behind every policy decision. [DESIGN_NOTE.md](DESIGN_NOTE.md)
cites this file rather than restating it, and `tests/test_full_dataset.py`
asserts the headline figures so they cannot silently drift. The record of the
shipped run itself (metrics achieved, timings, hashes) is in
[RUN_MANIFEST.md](RUN_MANIFEST.md).

Reproduce sections 1 and 2 with `python -m graphcanon profile --input-dir
data/input`, and sections 3 to 7 with `python -m pytest -m slow`.

## 1. The dataset

`python -m graphcanon profile --input-dir data/input`, 19.7 s:

| | |
|---|---:|
| Entity occurrences | 479,930 |
| Distinct (scope, type, name) keys | 55,445 |
| Repetition ratio | 0.8845 |
| Facts | 293,475 |
| Facts with no entity object | **0** |
| Source documents (ledger rows) | 4,192 |
| Chunks referenced by occurrences | 55,417 |
| Organizations / workspaces | **1 / 1** |
| Occurrences carrying aliases | 41,742 |
| `evidence_text` non-empty | **0** |

Two consequences shape everything below:

* **Every fact has two resolvable endpoints.** No literal-valued objects, no
  nulls. Literal handling is implemented and tested, but on this dataset the
  only reasons a fact can fail to project are self-loops, unresolved endpoints,
  cross-scope endpoints, and missing predicates.
* **Scope isolation is untestable on the real data.** One organization, one
  workspace. The requirement is real and the code enforces it, but the only
  evidence it works comes from fixtures, which is why the `mini` fixture spans
  four documents across three scopes, including two workspaces inside one
  organization.

## 2. Name shape carries the identity evidence

Person names decompose into `Name-XXXXXXXXXX` tokens; other types are a single
`Prefix-XXXXXXXXXXXX` token. Person occurrences by token count:

| Tokens | Occurrences |
|---:|---:|
| 1 | 23,584 |
| 2 | 100,230 |
| 3 | 18,383 |
| 4+ | 1,877 |

A single-token Person name is a bare given name: 708 distinct such names cover
23,584 occurrences, and the most common appears in 1,507 of the 4,192 documents.
It cannot identify a person across documents.

## 3. What the public labels actually encode

All 360 pairs in `data/reference/public_labeled_pairs.jsonl`, joined back to
their occurrences:

| Label | Count | Structure |
|---|---:|---|
| `MERGE` | 120 | Same name, **same source event**, different chunks: 115/120. The other 5 pair *different* names within one event. |
| `POSSIBLE_DUPLICATE` | 120 | **120/120**: `Person`, single-token name, same name, **different source events**. |
| `NO_MERGE` | 120 | **120/120** have different names. |

Three things follow.

**The middle class is one specific population.** Every labeled
`POSSIBLE_DUPLICATE` is a single-token Person name seen in two documents. No
other shape appears in that class.

**Same-name pairs are never labeled `NO_MERGE`.** The negative class is drawn
entirely from different-name pairs, so merging same-name occurrences of a
high-entropy type cannot be punished by these labels.

**`MERGE` pairs were sampled within a document, but their names are not
document-local.** All 120 involve a name that also occurs in other events. The
sampler chose same-event pairs; that is a property of the sampling, not evidence
that cross-document identity was rejected.

The 5 different-name `MERGE` pairs are all `LegalEntity`. Only one is explained
by an alias chain inside the event; the other four have no supporting evidence
anywhere in the fictionalized data. They are an accepted recall ceiling of about
4/120.

## 4. The alias experiment

Aliases look like free identity evidence. They are not. Union-find over
`(scope, type, name)` with single-token Person names confined to their source
event, varying only the alias rule:

| Alias policy | Canonical entities | Macro-F1 | Merge precision | Merge recall |
|---|---:|---:|---:|---:|
| **Ignored (shipped)** | 66,120 | **0.9861** | **1.0000** | 0.9583 |
| Honoured | 60,981 | 0.9615 | 0.9015 | 0.9917 |
| Honoured if ≥2 documents assert it | 63,042 | 0.9779 | 0.9444 | 0.9917 |
| Honoured if ≥5 documents assert it | 64,227 | 0.9806 | 0.9593 | 0.9833 |

The required hidden hard-merge precision is **0.97**. Every alias-honouring
variant sits below it, and the recall it buys is four pairs. Aliases are
therefore recorded in `possible_duplicates.jsonl` and never merged. Reproduce
with `--merge-on-alias`.

## 5. Confirming the resulting graph

Full run under the shipped policy, cross-checked with
`tools/score_public_pairs.py` and `graphcanon verify`. Counts and diagnostics
are in [RUN_MANIFEST.md](RUN_MANIFEST.md). What matters here is why the shape
looks the way it does.

Self-loops are 1,603 facts, 0.55% of the total, so rejecting them still leaves
**100%** of facts either projected or rejected with a reason, against a ≥99%
requirement. Every other rejection reason fires zero times on this dataset,
which follows from §1: every fact has two resolvable endpoints, and there is
only one scope to cross.

Official scorer output on the submitted artifacts:

```
macro_f1                     0.9861   (threshold 0.80, pass)
MERGE                 P 1.0000  R 0.9583  F1 0.9787
NO_MERGE              P 0.9600  R 1.0000  F1 0.9796
POSSIBLE_DUPLICATE    P 1.0000  R 1.0000  F1 1.0000
missing_assignments   0
```

The five missed merges are the different-name pairs from §3. Four of them are
unrecoverable from the visible data at any threshold.

## 6. Sizing the unresolved-pair file

`tools/score_public_pairs.py` only counts a `possible_duplicates` row whose
`evidence_candidate_entity_ids` holds **exactly two** IDs, and it matches on the
specific occurrence pair. An unresolved pair is scored only if that exact pair
of `cent_` IDs is present, so a group-level row is a non-answer to a pairwise
question.

Full enumeration of single-token Person cross-document pairs is 8,060,924 rows
(2.21 GB). Before accepting that, three things were tested.

**Is there a signal that would let a smaller, smarter selection work?** No. The
120 labeled pairs were compared against 400 randomly drawn same-name
cross-document pairs on shared relations, fact participation, and name
frequency. They are statistically indistinguishable:

| | Labeled PD | Random baseline |
|---|---:|---:|
| Share a (predicate, endpoint) relation | 6.7% | 8.0% |
| Both endpoints appear in facts | 28.3% | 29.0% |
| Median documents carrying the name | 91 | 77 |

**How are the labels distributed?** By *occurrence*, not by pair. The commonest
name holds 63% of all pairs but drew only 11.7% of the labels, against 13.6% of
occurrences. That makes each row of a small group far more valuable than each
row of a large one, so a budget should take whole groups in descending
occurrences-per-pair order, which is what `_group_plan` does. A uniform
per-group cap was implemented first and is strictly worse.

**What does a budget actually cost?** Coverage measured against the 120 public
labels, with macro-F1 derived from the confusion structure:

| Budget | Rows | Size | PD covered | Macro-F1 |
|---:|---:|---:|---:|---:|
| 5,000 | 4,941 | 1 MB | 10/120 | 0.603 |
| 50,000 | 49,298 | 14 MB | 30/120 | 0.698 |
| 250,000 | 248,893 | 68 MB | 53/120 | 0.787 |
| 500,000 | 488,061 | 134 MB | 63/120 | 0.821 |
| 1,000,000 | 976,890 | 268 MB | 77/120 | 0.865 |
| **none (shipped)** | **8,060,924** | **2.21 GB** | **120/120** | **0.9861** |

Clearing the 0.80 target needs roughly 450,000 rows. Everything below that fails
an explicit acceptance criterion, so full enumeration ships. The operational
consequences of that choice are in
[submission/README.md](../submission/README.md).

## 7. A scaling defect in `tools/validate_submission.py`

The supplied validator rebuilds a 479,930-element set inside two loops:

```python
# line 89, once per canonical entity
unknown = set(members) - set(input_entities)

# line 125, once per unresolved-pair row
if len(set(evidence)) < 2 or set(evidence) - set(input_entities):
```

`set(input_entities)` is re-evaluated on every iteration. Measured at **61.6 ms**
per iteration on the reference machine, so the tool costs about
`(canonical_entities + possible_duplicate_rows) × 61.6 ms` regardless of what the
submission contains. That is a best case: repeated trials on the same machine
ranged from 61 ms to 72 ms, so the projections below are lower bounds.

| Submission | Iterations | Projected runtime |
|---|---:|---:|
| Any valid one, with an *empty* possible_duplicates | 66,120 | ~68 min |
| 500,000 unresolved pairs | 566,120 | ~9.7 h |
| These artifacts | 8,132,749 | **~139 h** |

Note the first row: the tool already needs over an hour on *any* correct
submission of this dataset, before a single unresolved pair exists. The problem
is not the size of this submission; the size only scales an existing defect.

To be precise about what was and was not measured end to end: the 61.6 ms figure
is measured directly, by reproducing the loop body against a 479,930-entry dict.
The runtimes in the table are extrapolations from it. No complete run of the
unpatched tool on these artifacts was carried out, for the obvious reason. What
*was* run to completion is the transcribed checker below.

**The fix is one line, twice.** Hoist the set above the loops:

```python
input_entity_id_set = set(input_entities)   # once, after input_entities is built
...
unknown = set(members) - input_entity_id_set
...
if len(set(evidence)) < 2 or set(evidence) - input_entity_id_set:
```

`src/graphcanon/verify.py` is that same checker, transcribed
assertion-for-assertion with the hoist applied. It verifies the full submission
in **57 seconds** and returns `PASS`. `tests/test_verify_equivalence.py` corrupts
a clean submission seventeen distinct ways (dropped assignment, duplicated
assignment, member in two components, misdeclared scope, projected fact with no
edge, dropped fact with an edge, dangling endpoint, stripped provenance, single
evidence ID, missing report key, and more) and asserts both implementations
agree on every one, so the speed-up costs no strictness.

The vendored `tools/` copy is left untouched: it is the graders' artifact, and
patching it in place would be exactly the kind of silent divergence the rest of
this submission is built to avoid.
