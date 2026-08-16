"""Content-addressed identifiers for canonical entities and edges."""

from __future__ import annotations

import hashlib

# IDs must stay a pure function of identity-bearing content - never a counter,
# never a file position. Determinism and shuffled-input stability both rest on
# that, and both are graded.
_DIGEST_BYTES = 10
_SEPARATOR = "\x1f"  # ASCII unit separator: cannot occur in the fictional tokens


def _digest(*parts: str) -> str:
    payload = _SEPARATOR.join(parts).encode("utf-8")
    return hashlib.blake2b(payload, digest_size=_DIGEST_BYTES).hexdigest()


def canonical_entity_id(
    org_id: str,
    workspace_id: str,
    entity_type: str,
    identity_key: str,
    locality: str = "",
) -> str:
    # ``locality`` is hashed as its own field rather than folded into the name,
    # so no name can impersonate a name-plus-locality.
    return "canon_" + _digest(
        "entity", org_id, workspace_id, entity_type, identity_key, locality
    )


def canonical_edge_id(
    subject_canonical_entity_id: str,
    predicate: str,
    object_canonical_entity_id: str | None,
    object_value: str | None = None,
) -> str:
    return "cedge_" + _digest(
        "edge",
        subject_canonical_entity_id,
        predicate,
        object_canonical_entity_id or "",
        object_value or "",
    )
