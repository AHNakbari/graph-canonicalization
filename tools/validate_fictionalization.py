#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path


FILES = (
    "candidate_entities.jsonl",
    "candidate_facts.jsonl",
    "extraction_artifacts.jsonl",
    "source_ledger.jsonl",
)
TOKEN_RE = re.compile(r"[\w]+(?:[-'][\w]+)*", re.UNICODE)
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
URL_RE = re.compile(r"(?i)\bhttps?://[^\s\]\[<>{}\"']+")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
FICTION_PHONE_RE = re.compile(r"(?<!\w)\+1-202-555-\d{4}(?!\w)")
UUID_RE = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
DATEISH_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T\s].*)?$")
PSEUDONYM_RE = re.compile(r"(?i)\b[a-z]+-[0-9a-f]{10,12}\b")
DATE_VALUE_RE = re.compile(r"(?i)\bDate-20\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d)\b")
AMOUNT_VALUE_RE = re.compile(r"(?i)\bAmount-USD-\d+(?:\.\d{2})?\b")

SAFE_TOKENS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "between", "by", "can", "case",
    "client", "company", "contact", "contract", "court", "date", "department", "document", "email",
    "entity", "event", "example", "fact", "fiction", "for", "from", "group", "has", "have", "html",
    "http", "https", "in", "inc", "incorporated", "is", "it", "item", "its", "json", "law", "legal",
    "limited", "llc", "llp", "ltd", "matter", "of", "on", "or", "organization", "party", "pdf", "person",
    "project", "reference", "report", "resource", "section", "service", "source", "system", "team", "the",
    "their", "this", "to", "txt", "type", "under", "valid", "version", "was", "were", "with", "workspace",
    "doc", "docx", "xls", "xlsx", "csv", "rtf", "xml", "null", "none", "true", "false",
}
TECHNICAL_FIELDS = {
    "type", "entity_type", "predicate", "source_system", "source_role", "schema_version", "ontology_version",
    "chunking_strategy", "semantic_segment_kind", "source_offset_reason", "authority_level", "authorship_kind",
    "relation_kind", "decision", "decision_source", "adjudication_kind", "component_coherence_status",
    "abstraction_layer", "source_ref",
}
TYPE_PREFIXES = {
    "DateRef": "Date", "Department": "Department", "Document": "Document", "LegalClaim": "Claim",
    "LegalEntity": "Organization", "LegalNorm": "Norm", "LegalProvision": "Provision", "LegalRole": "Role",
    "Matter": "Matter", "Money": "Amount", "Topic": "Topic",
}
EXPECTED_TYPES = set(TYPE_PREFIXES) | {"Person", "Place"}


def semantic_name_matches(value: str, entity_type: str) -> bool:
    if entity_type in {"Person", "Place"}:
        named_form = r"[A-Za-z]+-[0-9A-F]{10}(?: [A-Za-z]+-[0-9A-F]{10})*"
        generic_form = re.escape(entity_type) + r"-[0-9A-F]{12}"
        return bool(re.fullmatch(rf"(?:{named_form}|{generic_form})", value))
    if entity_type == "DateRef":
        return bool(re.fullmatch(r"Date-20\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d)", value))
    if entity_type == "Money":
        return bool(re.fullmatch(r"Amount-USD-\d+\.\d{2}", value))
    prefix = TYPE_PREFIXES.get(entity_type)
    return bool(prefix and re.fullmatch(re.escape(prefix) + r"-[0-9A-F]{12}", value))


def should_scan(key: str, value: str) -> bool:
    folded = key.casefold()
    if folded in TECHNICAL_FIELDS or folded.endswith("_id") or folded.endswith("_hash"):
        return False
    if (folded.endswith("_at") or folded == "reference_time") and (DATEISH_RE.match(value) or value.casefold() in {"null", "none"}):
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Verify that candidate-facing text uses only approved fictional forms.")
    parser.add_argument("input_dir", type=Path)
    args = parser.parse_args()
    counts = collections.Counter()
    sample_hashes = []

    def scan_text(value: str):
        counts["text_values_scanned"] += 1
        counts["uuid_hits"] += len(UUID_RE.findall(value))
        counts["nonfiction_email_hits"] += sum(not email.casefold().endswith("@fiction.example") for email in EMAIL_RE.findall(value))
        counts["nonfiction_url_hits"] += sum(".example/" not in url.casefold() for url in URL_RE.findall(value))

        phone_scan = DATE_VALUE_RE.sub("", value)
        phone_scan = AMOUNT_VALUE_RE.sub("", phone_scan)
        phone_scan = PSEUDONYM_RE.sub("", phone_scan)
        phone_scan = FICTION_PHONE_RE.sub("", phone_scan)
        counts["nonfiction_phone_hits"] += len(PHONE_RE.findall(phone_scan))

        lexical = URL_RE.sub("", value)
        lexical = EMAIL_RE.sub("", lexical)
        lexical = FICTION_PHONE_RE.sub("", lexical)
        lexical = DATE_VALUE_RE.sub("", lexical)
        lexical = AMOUNT_VALUE_RE.sub("", lexical)
        lexical = PSEUDONYM_RE.sub("", lexical)
        for token in TOKEN_RE.findall(lexical):
            if token.casefold() not in SAFE_TOKENS:
                counts["unapproved_lexical_token_hits"] += 1
                if len(sample_hashes) < 10:
                    import hashlib
                    sample_hashes.append(hashlib.sha256(token.casefold().encode("utf-8")).hexdigest()[:12])

    def visit(value, key=""):
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, child_key)
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str) and should_scan(key, value):
            scan_text(value)

    for name in FILES:
        path = args.input_dir / name
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    counts["rows_scanned"] += 1
                    row = json.loads(line)
                    if name == "candidate_entities.jsonl":
                        entity_type = row.get("type")
                        if entity_type not in EXPECTED_TYPES:
                            counts["unexpected_entity_types"] += 1
                        elif not semantic_name_matches(row.get("name") or "", entity_type):
                            counts["type_semantic_name_failures"] += 1
                        if row.get("normalized_name") != (row.get("name") or "").casefold():
                            counts["normalized_name_mismatches"] += 1
                        for alias in row.get("aliases") or []:
                            if entity_type not in EXPECTED_TYPES or not semantic_name_matches(alias, entity_type):
                                counts["type_semantic_alias_failures"] += 1
                    visit(row)

    failures = {key: counts[key] for key in (
        "uuid_hits", "nonfiction_email_hits", "nonfiction_url_hits", "nonfiction_phone_hits",
        "unapproved_lexical_token_hits", "unexpected_entity_types", "type_semantic_name_failures",
        "type_semantic_alias_failures", "normalized_name_mismatches",
    )}
    status = "PASS" if not any(failures.values()) else "FAIL"
    result = {"status": status, **failures, "rows_scanned": counts["rows_scanned"], "text_values_scanned": counts["text_values_scanned"], "sample_hashes": sample_hashes}
    print(json.dumps(result, indent=2, sort_keys=True))
    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
