"""Evidence tiers for assignments and unresolved pairs.

These are **ordinal tiers, not calibrated probabilities**, and nothing
downstream may treat them as probabilities: 360 public pairs is far too little
to calibrate against. Assignment confidence answers only "does this occurrence
belong to the component it was placed in" - never "should this component merge
with another", which is priced separately in possible_duplicates.jsonl.
"""

from __future__ import annotations

import math

SINGLETON = 1.0
EXACT_NAME = 0.99
SOURCE_LOCAL = 0.95
ALIAS_MERGE = 0.60
ALIAS_UNRESOLVED = 0.40

_MIN_PAIR_CONFIDENCE = 0.05
_MAX_PAIR_CONFIDENCE = 0.50


def one_token_person_pair(event_count: int) -> float:
    # 1 / (1 + log2(documents carrying the name)): 0.50 for a name in two
    # documents, 0.09 for the corpus's commonest given name. Monotone in name
    # breadth, which is the only property the report's ranking relies on.
    if event_count < 2:
        return _MAX_PAIR_CONFIDENCE
    value = 1.0 / (1.0 + math.log2(event_count))
    return round(min(_MAX_PAIR_CONFIDENCE, max(_MIN_PAIR_CONFIDENCE, value)), 4)
