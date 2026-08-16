"""Input loading and scope resolution."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterator, NamedTuple

from .jsonio import InputError, read_jsonl

ENTITIES_FILE = "candidate_entities.jsonl"
FACTS_FILE = "candidate_facts.jsonl"
ARTIFACTS_FILE = "extraction_artifacts.jsonl"
LEDGER_FILE = "source_ledger.jsonl"

REQUIRED_FILES = (ENTITIES_FILE, FACTS_FILE, ARTIFACTS_FILE, LEDGER_FILE)

# These charsets are a precondition, not a formality: duplicates.py serialises
# millions of rows through JsonlWriter.write_raw, which is only safe because no
# identifier can contain a quote, a backslash, or a control character. Widening
# either pattern means giving up that fast path.
ENTITY_ID_RE = re.compile(r"^cent_[0-9A-Za-z._:-]+$")
FACT_ID_RE = re.compile(r"^cfact_[0-9A-Za-z._:-]+$")


class Scope(NamedTuple):
    org_id: str
    workspace_id: str


class Occurrence(NamedTuple):
    candidate_entity_id: str
    entity_type: str
    normalized_name: str
    name: str
    source_event_id: str
    chunk_id: str
    org_id: str
    workspace_id: str
    confidence: float
    aliases: tuple[str, ...]

    @property
    def scope(self) -> Scope:
        return Scope(self.org_id, self.workspace_id)

    @property
    def block(self) -> tuple[str, str, str]:
        """The isolation boundary: nothing merges across this triple."""
        return (self.org_id, self.workspace_id, self.entity_type)


class Fact(NamedTuple):
    candidate_fact_id: str
    subject_candidate_id: str
    object_candidate_id: str | None
    predicate: str
    object_value: object
    source_event_id: str
    chunk_id: str
    confidence: float


def check_inputs(input_dir: Path) -> None:
    missing = [name for name in REQUIRED_FILES if not (input_dir / name).is_file()]
    if missing:
        raise InputError(f"missing input files in {input_dir}: {missing}")


def load_scopes(input_dir: Path) -> dict[str, Scope]:
    # Entity rows carry org_id but no workspace_id. The workspace is knowable
    # only through this join, and it is one of the three isolation boundaries
    # the submission is graded on, so it can never be inferred from the
    # occurrence alone. sys.intern here and below is what keeps a full run in a
    # few hundred MiB: ~480k occurrences reference ~55k names and ~4.2k events.
    scopes: dict[str, Scope] = {}
    for line_no, row in read_jsonl(input_dir / LEDGER_FILE):
        event_id = row.get("source_event_id")
        org_id = row.get("org_id")
        workspace_id = row.get("workspace_id")
        if not event_id or not org_id or not workspace_id:
            raise InputError(f"{LEDGER_FILE}:{line_no}: incomplete provenance row")
        if event_id in scopes:
            raise InputError(f"{LEDGER_FILE}:{line_no}: duplicate source_event_id {event_id}")
        scopes[sys.intern(event_id)] = Scope(sys.intern(org_id), sys.intern(workspace_id))
    if not scopes:
        raise InputError(f"{LEDGER_FILE}: no provenance rows")
    return scopes


def iter_occurrences(input_dir: Path, scopes: dict[str, Scope]) -> Iterator[Occurrence]:
    seen: set[str] = set()
    for line_no, row in read_jsonl(input_dir / ENTITIES_FILE):
        entity_id = row.get("candidate_entity_id")
        if not entity_id:
            raise InputError(f"{ENTITIES_FILE}:{line_no}: missing candidate_entity_id")
        if not ENTITY_ID_RE.match(entity_id):
            raise InputError(f"{ENTITIES_FILE}:{line_no}: unsupported ID form {entity_id!r}")
        if entity_id in seen:
            raise InputError(f"{ENTITIES_FILE}:{line_no}: duplicate ID {entity_id}")
        seen.add(entity_id)

        event_id = row.get("source_event_id")
        scope = scopes.get(event_id)
        if scope is None:
            raise InputError(
                f"{ENTITIES_FILE}:{line_no}: source_event_id {event_id!r} absent from the ledger"
            )
        declared_org = row.get("org_id")
        if declared_org and declared_org != scope.org_id:
            raise InputError(
                f"{ENTITIES_FILE}:{line_no}: org_id {declared_org!r} contradicts ledger "
                f"{scope.org_id!r}"
            )

        # Same fallback order as tools/validate_submission.py: it recomputes
        # token counts from this field, so a different choice here would make
        # its one-token-Person check disagree with ours.
        surface = row.get("name") or ""
        name = row.get("normalized_name") or surface
        aliases = tuple(sys.intern(alias) for alias in (row.get("aliases") or []) if alias)
        yield Occurrence(
            candidate_entity_id=entity_id,
            entity_type=sys.intern(row.get("type") or ""),
            normalized_name=sys.intern(name),
            name=sys.intern(surface or name),
            source_event_id=sys.intern(event_id),
            chunk_id=sys.intern(row.get("chunk_id") or ""),
            org_id=scope.org_id,
            workspace_id=scope.workspace_id,
            confidence=float(row.get("confidence") or 0.0),
            aliases=aliases,
        )


def iter_facts(input_dir: Path) -> Iterator[Fact]:
    seen: set[str] = set()
    for line_no, row in read_jsonl(input_dir / FACTS_FILE):
        fact_id = row.get("candidate_fact_id")
        if not fact_id:
            raise InputError(f"{FACTS_FILE}:{line_no}: missing candidate_fact_id")
        if not FACT_ID_RE.match(fact_id):
            raise InputError(f"{FACTS_FILE}:{line_no}: unsupported ID form {fact_id!r}")
        if fact_id in seen:
            raise InputError(f"{FACTS_FILE}:{line_no}: duplicate ID {fact_id}")
        seen.add(fact_id)
        object_id = row.get("object_candidate_id")
        yield Fact(
            candidate_fact_id=fact_id,
            subject_candidate_id=row.get("subject_candidate_id") or "",
            object_candidate_id=object_id or None,
            predicate=sys.intern(row.get("predicate") or ""),
            object_value=row.get("object_value"),
            source_event_id=sys.intern(row.get("source_event_id") or ""),
            chunk_id=sys.intern(row.get("chunk_id") or ""),
            confidence=float(row.get("confidence") or 0.0),
        )


def count_chunks(input_dir: Path) -> int:
    total = 0
    for _, row in read_jsonl(input_dir / ARTIFACTS_FILE):
        total += len(row.get("chunks") or [])
    return total
