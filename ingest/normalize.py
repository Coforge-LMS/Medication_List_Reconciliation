"""Identity matching for V1: build normalized_name from a medication name (TECHNICAL_PLAN §4.3)."""

import re
from collections.abc import Iterable

from contract import AliasConfig, MedicationRecord, Rejection
from ingest.checks import BRACKETED, KNOWN_UNITS, strength_pattern

_STRENGTH = strength_pattern(KNOWN_UNITS, re.IGNORECASE)
_TOKEN = re.compile(r"[^\W_]+")


def normalize_name(name: str, config: AliasConfig) -> str:
    """Lowercase, drop [brand] tags and strengths, tokenize, drop ignored tokens, apply aliases.

    Returns "" when nothing is left (a name made only of strengths and ignored words).
    """
    text = _STRENGTH.sub(" ", BRACKETED.sub(" ", name.lower()))
    ignored = set(config.ignore_tokens)
    tokens = [t for t in _TOKEN.findall(text) if t not in ignored and not t.isdigit()]
    key = " ".join(tokens)
    return config.aliases.get(key, key)


def apply[Item: (MedicationRecord, Rejection)](
    items: Iterable[Item], config: AliasConfig
) -> list[Item]:
    """Set normalized_name on records and on rejections that kept a readable name.

    Rejections are normalized too, so a rejected "Zestril" still matches "lisinopril" and the
    rules can say a counterpart was rejected instead of reporting a plain omission.
    """
    result: list[Item] = []
    for item in items:
        normalized = normalize_name(item.name, config) if item.name else ""
        result.append(item.model_copy(update={"normalized_name": normalized or None}))
    return result
