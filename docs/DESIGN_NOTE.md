# Design note

**Result.** 479,930 occurrences and 293,475 facts become 66,120 canonical
entities and 81,715 edges, in 105 seconds and 577 MiB. Zero invariant violations,
100% coverage on every required metric, public macro F1 **0.9861**, hard merge
precision **1.0000**.

Measurements are in [FINDINGS.md](FINDINGS.md), the run in
[RUN_MANIFEST.md](RUN_MANIFEST.md). `tests/test_full_dataset.py` asserts these
figures, so this file cannot drift away from the code.

## 1. When are two occurrences the same entity?

The data is fictionalized. Every real word was replaced by a stable token that
keeps repetition but carries no meaning. So edit distance, embeddings and
nickname tables are not just useless here. They are misleading. Any similarity
left between two tokens comes from the scrubbing, not from the source text. A
fuzzy matcher would be measuring the fictionalizer. What survives is exact
repetition, the type, the provenance, and the shape of a name. So identity is
built on shape.

| Shape | Example | What it means |
|---|---|---|
| One long random token | `organization-9593a10ac8d8` | An identifier. Same token means same entity. |
| A name with two or more tokens | `quill-fa1308d761 orin-9ac6abe97a` | A full personal name. Strong enough to travel between documents. |
| One short name token | `quill-fa1308d761` | A bare given name. It identifies someone inside one document only. |

The third row is the whole problem. 23,584 occurrences use one of only 708 bare
given names. The most common appears in 1,507 of the 4,192 documents. Two
documents both saying "Quill" is not evidence. It is a coincidence.

**The rule.** Two occurrences are the same entity when they share a normalized
name inside one (organization, workspace, entity type) scope. Bare given names
have one extra condition: they must also come from the same document.

Three separate things support that condition. `tools/validate_submission.py`
already rejects a Person component whose members are all bare given names and
which spans several documents. All 120 public `POSSIBLE_DUPLICATE` labels have
exactly this shape, and nothing else does. And the name frequency alone makes it
true.

## 2. Evidence I trusted, discounted and rejected

**Trusted.** Exact name equality inside a scope and type. The organization and
workspace from the ledger. The document as a boundary. The token shape of a name.

One trap is worth naming. An entity row has `org_id` but no `workspace_id`. The
workspace is only reachable by joining `source_event_id` against
`source_ledger.jsonl`. A loader that trusts the entity row alone loses one of the
three isolation boundaries and never notices, because this dataset has only one
workspace. So the loader does the join, checks the declared organization against
the ledger, and stops the run if they disagree.

**Discounted.** Extraction confidence. It sets edge confidence and appears in
diagnostics, but nothing is ever dropped for being low confidence. The
thresholds exist only for sensitivity analysis and default to zero.

**Rejected.** Aliases as merge evidence. This is the one place where the obvious
move is wrong, and measurement settled it. Using aliases drops merge precision
from 1.0000 to 0.9015. Softer versions, needing two or five documents to agree,
still land under the 0.97 floor. All of that buys four extra pairs of recall.
See [FINDINGS.md](FINDINGS.md) §4.

So aliases are written into `possible_duplicates.jsonl` as open questions and
never acted on. The `--merge-on-alias` flag stays so the comparison can be
repeated, not because it is a supported mode. Also rejected: `evidence_text`,
empty on all 479,930 rows, and string similarity, for the reason in §1.

## 3. False merges against missed merges

These two mistakes are not equal, and the thresholds say so: hard merge
precision must reach 0.97, while overall macro F1 only needs 0.78. The real
reason is worse than the scoring. A false merge is silent and it spreads: joining two entities also joins every edge on them, so the graph gains
facts nobody stated, and nothing downstream can see it, because the provenance
looks perfect. It just points at two different real things. A missed merge is
visible and fixable: both entities stay, both are correct, and the open question
is written down for a later pass or a person to settle.

So the design leans hard towards missed merges and pays for it in
`possible_duplicates.jsonl`. Merge precision is 1.0000 and merge recall is
0.9583. The five missed merges are pairs with different names in one document,
whose only link lived in text the fictionalization removed. Four cannot be
recovered at any threshold. I would rather report that ceiling than close it
with a rule I cannot justify.

## 4. How uncertainty is represented

**On the row.** `decision` is `POSSIBLE_DUPLICATE` whenever an occurrence has an
open question about its identity, and reason codes say why. The doubt is visible
from the assignment row itself, not only from another file.

**As pairs.** `possible_duplicates.jsonl` states every open question: 8,060,924
pairs of bare given names, plus 5,705 group rows for aliases. They are pairwise
because that is how the question is really asked, and because the supplied
scorer only reads rows with exactly two evidence IDs, so a group row answers
nothing at all. This is what makes the file 2.21 GB. The cost and the alternatives are
in [submission/README.md](../submission/README.md).

**As a number.** Pair confidence falls as a name gets more common:
`1 / (1 + log2(documents carrying the name))`. A name in two documents gets 0.50,
the most common given name gets 0.09. That is an ordering, not a probability, and
[confidence.py](../src/graphcanon/confidence.py) says so plainly. 360 labeled
pairs is far too few to calibrate anything, and a number that looks calibrated
but is not would be worse than an honest ranking. Assignment confidence is
equally narrow: it answers only whether an occurrence belongs in the component it
was put in.

## 5. Testing quality without ground truth

There are two questions here, and only one of them can be answered.

**Is the graph broken?** Fully testable, and this is where the effort went. The
key choice is that the checker rebuilds the answer from the finished artifacts.
`resolve.verify_invariants` and `projection.verify_invariants` never read the
builder's own bookkeeping. If they did, a bug in the builder could hide itself.
They run on every execution, including the full dataset, and the run exits with
a failure code if anything fires.

Three layers sit on top:

* **Small inputs with known answers.** `tests/fixtures/mini` is 13 occurrences
  and 6 facts, and every row exists to break one rule if that rule is wrong. It
  passes `tools/validate_inputs.py`, so it is a real input package and not a
  convenient fake. Because the real data has one organization and one workspace,
  this fixture is the only place the isolation rules are ever tested.
* **Our checker against their checker.** `tests/test_verify_equivalence.py`
  breaks a good submission in 17 different ways and checks that `graphcanon
  verify` and `tools/validate_submission.py` give the same verdict every time.
  Without this, the fast checker would just be a claim.
* **Reading the shape.** The report lists the twenty largest components. The
  biggest has 22,486 members and is the client organization of the corpus, which
  is correct. If the biggest were ever a Person appearing in every document, that
  would be an alarm even with all invariants green.

**Is the graph right?** This cannot be answered here, and I want to be clear
about it. Passing every invariant proves the graph is consistent. It does not
prove the merges match reality. The only ground truth is 360 labeled pairs, out
of a space of billions, so they are used as a check and never as a target. The
moment you tune against them they stop measuring anything, and there is no second
set to catch you.

## 6. Before production

**This is not a production system, and it should not be mistaken for one.** It is
a batch job that reads a fixed snapshot, decides everything from scratch, and
writes files. It scores well. That is a different thing from being ready. What
follows is not polish. These are missing parts.

**There is nowhere to put a human decision.** This is the biggest gap. When a
person says "these two really are the same", or "you got this wrong", there is no
place to record it, and the next run throws the answer away and repeats the
mistake. Production needs a decision store that is separate from the algorithm,
survives every rerun, and always beats the automatic rule. Without it the system
cannot be corrected and cannot improve.

**Identity is not stable over time.** IDs are hashes of content, so new documents
do not renumber unrelated entities. Merging is the problem. If two entities later
turn out to be one, the joined entity gets a new ID, and every system holding the
old IDs points at nothing. Production needs supersede records so an old ID keeps
working and redirects. An ID that silently disappears is a data loss bug for
everyone downstream.

**Nothing handles change.** Documents get corrected, retracted and extracted
again. This code assumes the input never changes. There is no update path, no
delete path, and no way to withdraw facts from a document that was pulled.

**Merging people is a privacy action, not just a data action.** Joining two
Person entities joins two real people's records, so a wrong merge exposes one
person's information under another's identity. Production needs an audit trail
for every merge, access control on the result, and a real answer for erasure
requests. Deleting a person is not deleting a row. It means pulling one member
out of a component and rebuilding everything that touched it.

**Eight million open questions is an honest answer and a useless workflow.**
Nobody will read that file. It has to become a ranked queue with a person at the
front, and their answers must feed back as `VERIFIED_IDENTIFIER` evidence, which
the validator already expects.

**Nobody would find out if it broke.** There is no monitoring. If the next batch
produced one giant Person component spanning every document, every invariant
would still pass and no alarm would fire. Production needs limits on component
size and growth, and an alert when the shape moves.

**The rule was tuned on fake text.** The bare given name rule comes from this
corpus. On real text the hard parts start: nicknames, initials, titles, OCR
noise, spelling variants, real coreference. None of it could be tried here,
because the fictionalization removed it. The alias decision in §2 should be
measured again on real text, not carried forward.

**Isolation is only proved by fixtures.** One organization, one workspace. The
boundaries this is graded on are never exercised by real data. Before production
I would want a corpus with several real organizations in it, and a fuzzing pass
that mixes scopes on purpose.

## Complexity and scale

| Stage | Complexity |
|---|---|
| Load and scope join | O(n) |
| Resolution | O(n α(n)) over 55,445 keys, not 479,930 occurrences |
| Invariant verification | O(n) |
| Fact projection | O(m) |
| Unresolved pair enumeration and writing | **O(Σ T²), quadratic per name group** |
| Report | O(entities + edges) |

Blocking turns 479,930 occurrences into 55,445 keys before any merging, so the
union find works on a structure ten times smaller than the input. String
interning fits 516 MB of JSON into 577 MiB of memory, because the corpus uses
only about 55,000 distinct names and 4,200 events. Everything except pair
enumeration is linear and streams, and the quadratic part is capped by
`possible_duplicate_pair_budget`. It is the first thing to redesign at scale.

### The method does almost nothing, and that is the point

It is worth saying plainly how little this does. No model. No training. No fuzzy
matching, no threshold tuning, no scoring function. The whole method is exact
string equality inside a scope, plus one rule about bare given names. It is close
to the simplest thing that could possibly work, and it reaches 0.9861 macro F1
with perfect merge precision.

That was deliberate, for three reasons.

**It sets a floor.** There is now a number any cleverer method has to beat. On
its own, a complicated system scoring 0.95 looks impressive. Next to this it
looks like a regression.

**Every decision fits in one sentence.** Any merge can be checked by hand in
seconds. Nothing hides inside a model. For a graph that legal work depends on,
that is worth more than a few points of recall.

**It can grow one step at a time.** Each future rule can be added alone and
measured against this exact baseline, with the configuration fingerprint
recording which policy produced which artifacts. That is a real path into
production. Starting from a large model and then trying to explain its mistakes
is not.

The honest caveat: simple worked here partly because the fictionalization
removed the very signals a smarter method would use. On real text it would not be
enough. It is still the right first step, and the right thing to measure the next
step against.

## The two supplied tools disagree

The scorer rewards pairwise enumeration, and the validator charges a rebuilt
479,930 element set for every row it reads. No artifact can be both maximally
accurate and quick to validate with that tool as written. The measurement is in
[FINDINGS.md](FINDINGS.md) §7.

The submission optimizes for accuracy and makes validity cheap to confirm
another way: full enumeration ships, `graphcanon verify` runs the identical
assertions in under a minute with 17 differential tests proving it agrees, the
one line fix is handed over, and `possible_duplicate_pair_budget` exists for anyone
who must run the tool unpatched. I would rather report a defect in the harness,
measure it, and hand over the fix than quietly ship a weaker graph to work
around it.

## External dependencies

None. Standard library Python only. No model, no service, no network, no paid
API, so there is no call volume, no cost and no remote failure mode.

The criteria ask what happens when an optional external dependency is
unavailable. There is no such dependency, and that is checked by machine rather
than promised: `tests/test_no_external_dependencies.py` checks every import
against `sys.stdlib_module_names` and runs a full pipeline with the socket layer
disabled. If anyone adds an HTTP client later, those tests fail, and the fallback
has to be designed then.
