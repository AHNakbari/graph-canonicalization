"""Name shape analysis."""

from __future__ import annotations

import re

# Must stay byte-identical to TOKEN_RE in tools/validate_submission.py: this
# regex decides token counts, and the validator rejects multi-source Person
# components whose members all count as one token. An internal hyphen does not
# split, so "quill-fa1308d761" is one token and "quill-fa1308d761 orin-9ac6abe97a"
# is two.
TOKEN_RE = re.compile(r"[\w]+(?:[-'][\w]+)*", re.UNICODE)

PERSON_TYPE = "Person"


def tokens(name: str) -> list[str]:
    return TOKEN_RE.findall(name or "")


def token_count(name: str) -> int:
    return len(tokens(name))


def normalized_name(row: dict) -> str:
    # Same fallback order as tools/validate_submission.py, so our name and its
    # name cannot drift apart.
    return row.get("normalized_name") or row.get("name") or ""


def is_person(entity_type: str) -> bool:
    return (entity_type or "").casefold() == PERSON_TYPE.casefold()


def is_one_token_person(entity_type: str, name: str) -> bool:
    return is_person(entity_type) and token_count(name) == 1
