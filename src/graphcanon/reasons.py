"""The reason-code vocabulary."""

from __future__ import annotations

# --- entity assignment -------------------------------------------------------

EXACT_NAME_IN_SCOPE = "EXACT_NAME_IN_SCOPE"
SINGLETON_NAME = "SINGLETON_NAME"
ONE_TOKEN_PERSON_SOURCE_SCOPED = "ONE_TOKEN_PERSON_SOURCE_SCOPED"
ONE_TOKEN_PERSON_UNRESOLVED_CROSS_SOURCE = "ONE_TOKEN_PERSON_UNRESOLVED_CROSS_SOURCE"

# tools/validate_submission.py treats these three as licensing a cross-source
# merge of otherwise-prohibited one-token Person components. Emitting one
# without evidence actually present in the input would silence the graders' own
# check, so they are only ever attached to a real corroborating assertion.
SOURCE_LOCAL_ALIAS = "SOURCE_LOCAL_ALIAS"
VERIFIED_IDENTIFIER = "VERIFIED_IDENTIFIER"
VERIFIED_CONTACT = "VERIFIED_CONTACT"

CORROBORATING_CODES = frozenset(
    {SOURCE_LOCAL_ALIAS, VERIFIED_IDENTIFIER, VERIFIED_CONTACT}
)

# --- possible duplicates -----------------------------------------------------

ONE_TOKEN_PERSON_CROSS_SOURCE = "ONE_TOKEN_PERSON_CROSS_SOURCE"
ALIAS_ASSERTED_UNCORROBORATED = "ALIAS_ASSERTED_UNCORROBORATED"
GROUP_LEVEL_AMBIGUITY = "GROUP_LEVEL_AMBIGUITY"

# --- fact disposition --------------------------------------------------------

ENDPOINTS_RESOLVED = "ENDPOINTS_RESOLVED"
SELF_LOOP_AFTER_CANONICALIZATION = "SELF_LOOP_AFTER_CANONICALIZATION"
UNRESOLVED_SUBJECT = "UNRESOLVED_SUBJECT"
UNRESOLVED_OBJECT = "UNRESOLVED_OBJECT"
CROSS_SCOPE_ENDPOINTS = "CROSS_SCOPE_ENDPOINTS"
MISSING_PREDICATE = "MISSING_PREDICATE"

ENTITY_CODES = frozenset(
    {
        EXACT_NAME_IN_SCOPE,
        SINGLETON_NAME,
        ONE_TOKEN_PERSON_SOURCE_SCOPED,
        ONE_TOKEN_PERSON_UNRESOLVED_CROSS_SOURCE,
        SOURCE_LOCAL_ALIAS,
        VERIFIED_IDENTIFIER,
        VERIFIED_CONTACT,
    }
)

DUPLICATE_CODES = frozenset(
    {
        ONE_TOKEN_PERSON_CROSS_SOURCE,
        ALIAS_ASSERTED_UNCORROBORATED,
        GROUP_LEVEL_AMBIGUITY,
    }
)

FACT_CODES = frozenset(
    {
        ENDPOINTS_RESOLVED,
        SELF_LOOP_AFTER_CANONICALIZATION,
        UNRESOLVED_SUBJECT,
        UNRESOLVED_OBJECT,
        CROSS_SCOPE_ENDPOINTS,
        MISSING_PREDICATE,
    }
)

# Counted as an explicit rejection by the "reasoned fact coverage" metric, which
# must stay >= 0.99. A new drop path that is not listed here silently lowers it.
VALID_REJECTION_CODES = frozenset(
    {
        SELF_LOOP_AFTER_CANONICALIZATION,
        UNRESOLVED_SUBJECT,
        UNRESOLVED_OBJECT,
        CROSS_SCOPE_ENDPOINTS,
        MISSING_PREDICATE,
    }
)
