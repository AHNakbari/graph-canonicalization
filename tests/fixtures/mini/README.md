# `mini` fixture

Thirteen occurrences and six facts, hand-built so that each one exists to make a
specific rule fail if it is broken. It passes `tools/validate_inputs.py`, so it
is a legal input package, not a convenient fake.

## Scopes

| Event | Org | Workspace |
|---|---|---|
| `event_alpha` | `org_alpha` | `ws_alpha` |
| `event_beta` | `org_alpha` | `ws_alpha` |
| `event_gamma` | `org_beta` | `ws_beta` |
| `event_delta` | `org_alpha` | `ws_delta` |

`event_delta` shares an organization with alpha/beta but not a workspace, so
workspace isolation is testable independently of organization isolation. The
workspace is only reachable through the ledger - the entity rows never state it.

## What each occurrence is for

| ID | Type | Name | Purpose |
|---|---|---|---|
| `cent_p001`, `cent_p002` | Person | `quill-aaaaaaaaaa` | Single-token name, same event, different chunks. **Must merge** |
| `cent_p003` | Person | `quill-aaaaaaaaaa` | Same single-token name, different event. **Must not merge**, becomes a possible duplicate |
| `cent_p004`, `cent_p005` | Person | `quill-aaaaaaaaaa orin-bbbbbbbbbb` | Multi-token name across events. **Must merge** |
| `cent_e001`, `cent_e002` | LegalEntity | `organization-cccccccccccc` | Same scope, different events. **Must merge** |
| `cent_e003` | LegalEntity | `organization-cccccccccccc` | Different org *and* workspace. **Must not merge** |
| `cent_e004` | LegalEntity | `organization-cccccccccccc` | Same org, different workspace. **Must not merge** |
| `cent_t001`, `cent_t002` | Topic / Document | `topic-dddddddddddd` | Identical name, different type. **Must not merge** |
| `cent_a001` | LegalEntity | `organization-eeeeeeeeeeee` | Asserts `Organization-CCCCCCCCCCCC` as an alias. **Must not merge** under the default policy, must surface as an unresolved pair |
| `cent_pl001` | Place | `riverbend-ffffffffff` | Endpoint for the `org_beta` edge |

Note that `cent_p001`/`cent_p002` and `cent_p004`/`cent_p005` are deliberately
*different* canonical entities that share a given name: a correct run must not
collapse the bare `quill-aaaaaaaaaa` into the full `quill-aaaaaaaaaa
orin-bbbbbbbbbb`.

## What each fact is for

| ID | Purpose |
|---|---|
| `cfact_f001`, `cfact_f002` | Two facts, one canonical edge. Consolidation must keep both chunk references |
| `cfact_f003` | Same predicate, different canonical subject. Must stay a separate edge |
| `cfact_f004` | Both endpoints canonicalize to one entity. Self-loop, **rejected with a reason** |
| `cfact_f005` | Edge entirely inside `org_beta` |
| `cfact_f006` | Endpoints in different organizations. **Rejected**, never a dangling edge |
