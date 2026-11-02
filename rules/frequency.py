"""Frequency mismatch rule and the deterministic normalizer it compares with.

Stored text maps to QD, BID, TID, QID, QOD, QW, PRN or "n/D" (n doses a day) through an exact table:
nothing is guessed, and anything else is unknown. As-needed and unknown frequencies aren't
comparable, partly because Synthea marks some scheduled medications as needed.
"""

import re
from fractions import Fraction
from typing import ClassVar

from contract import Finding, MedicationRecord, ReconciliationInput
from rules.base import (
    SOURCE_LABELS,
    ReconciliationRule,
    all_names,
    by_name,
    differing_concept,
    participating,
    sentence,
    with_product_differences,
)

PRN = "PRN"

_PHRASES: dict[str, tuple[str, ...]] = {
    "QD": (
        "qd",
        "daily",
        "once daily",
        "once a day",
        "every day",
        "qam",
        "qpm",
        "am",
        "pm",
        "every morning",
        "every evening",
        "qhs",
        "bed",
        "at bedtime",
        "nightly",
        "every night",
    ),
    "BID": ("bid", "twice daily", "twice a day"),
    "TID": ("tid", "three times daily", "three times a day"),
    "QID": ("qid", "four times daily", "four times a day"),
    "QOD": ("qod", "every other day"),
    "QW": ("qw", "wk", "weekly", "once weekly", "once a week"),
    PRN: ("prn", "as needed", "take as needed"),
}
_BY_PHRASE = {phrase: code for code, phrases in _PHRASES.items() for phrase in phrases}

_PER_DAY = {
    Fraction(1): "QD",
    Fraction(2): "BID",
    Fraction(3): "TID",
    Fraction(4): "QID",
    Fraction(1, 2): "QOD",
    Fraction(1, 7): "QW",
}
_DAYS_PER_UNIT = {"h": Fraction(1, 24), "d": Fraction(1), "wk": Fraction(7)}
_HOURLY = re.compile(r"(?:q|every )(\d+)(?:h| hours?)")
_REPEAT = re.compile(r"(\d+)/(\d+(?:\.\d+)?)(h|d|wk)")

PLAIN_TEXT: dict[str, str] = {
    "QD": "once daily",
    "BID": "twice daily",
    "TID": "three times daily",
    "QID": "four times daily",
    "QOD": "every other day",
    "QW": "once weekly",
    PRN: "as needed",
}


def normalize_frequency(text: str | None) -> str | None:
    """The canonical code for stored frequency text, or None when it can't be read for certain."""
    if not text:
        return None
    lowered = " ".join(text.lower().split())
    if repeat := _REPEAT.fullmatch(lowered):
        count, period, unit = repeat.groups()
        return _from_per_day(Fraction(count), Fraction(period) * _DAYS_PER_UNIT[unit])
    key = lowered.replace(".", "")
    if key in _BY_PHRASE:
        return _BY_PHRASE[key]
    if key.endswith(" prn"):
        return PRN  # as needed decides, whatever schedule comes with it
    if hourly := _HOURLY.fullmatch(lowered):  # not key: removing dots would change the number
        return _from_per_day(Fraction(24), Fraction(hourly.group(1)))
    return None


def _from_per_day(doses: Fraction, days: Fraction) -> str | None:
    """A code from a rate: a named one, else "n/D" for whole doses a day, else None."""
    if not days or not doses:
        return None
    per_day = doses / days
    if per_day in _PER_DAY:
        return _PER_DAY[per_day]
    return f"{per_day}/D" if per_day.denominator == 1 else None


def plain_text(code: str) -> str:
    """Plain wording for a code ("once daily"), since abbreviations like QD are easy to misread."""
    if code in PLAIN_TEXT:
        return PLAIN_TEXT[code]
    return f"{code.removesuffix('/D')} times daily"


def _scheduled(records: list[MedicationRecord]) -> list[str]:
    """Distinct codes that state a schedule, sorted; as-needed and unknown add nothing."""
    codes = {normalize_frequency(r.frequency) for r in records} - {None, PRN}
    return sorted(codes)


def _not_compared(records: list[MedicationRecord]) -> list[str]:
    """What these records state that has no schedule to compare, in first-seen order.

    Stored wording is kept when it says more than "as needed" does, as "BID PRN" does.
    """
    stated: dict[str, str] = {}  # keyed by lowercase, so case variants appear once
    for record in records:
        text = " ".join((record.frequency or "").split())
        code = normalize_frequency(text)
        if code == PRN and _BY_PHRASE.get(text.lower().replace(".", "")) == PRN:
            stated.setdefault(PLAIN_TEXT[PRN], PLAIN_TEXT[PRN])
        elif text and code in (PRN, None):
            stated.setdefault(text.lower(), text)
    return list(stated.values())


def _value(records: list[MedicationRecord], found: list[str]) -> str | None:
    """What one source says, in plain wording, with anything not compared marked as such."""
    parts = [plain_text(code) for code in found]
    parts += [f"{text} (not compared)" for text in _not_compared(records)]
    return ", ".join(parts) or None


class FrequencyMismatchRule(ReconciliationRule):
    """A name whose scheduled frequencies differ between 2+ sources; one finding per name.

    A source with no scheduled frequency for the name isn't compared, so as-needed or unknown
    never counts as a difference, but what it says still appears in its value, marked as not
    compared, so it can't be mistaken for saying nothing. No source is treated as the right one.

    Matching by ingredient can group different products, which may rightly have different
    schedules, so the summary leads with any form or salt difference.
    """

    discrepancy_type: ClassVar[str] = "frequency_mismatch"

    def evaluate(self, data: ReconciliationInput) -> list[Finding]:
        """Flag names whose sources state different schedules, comparing codes, not wording."""
        groups = {source: by_name(records) for source, records in participating(data).items()}
        findings = []
        for name in all_names(groups):
            present = {source: g[name] for source, g in groups.items() if name in g}
            codes = {source: _scheduled(group) for source, group in present.items()}
            compared = {source: found for source, found in codes.items() if found}
            if len({tuple(found) for found in compared.values()}) < 2:
                continue
            values = {
                source: ", ".join(map(plain_text, found)) for source, found in compared.items()
            }
            # Only compared sources: a note about another source wouldn't explain this difference.
            sources = {source: present[source] for source in compared}
            forms = differing_concept(sources, "dose_form")
            salts = differing_concept(sources, "salt")
            findings.append(
                Finding(
                    discrepancy_type=self.discrepancy_type,
                    medication=name,
                    summary=with_product_differences(
                        sentence(
                            "; ".join(
                                f"{SOURCE_LABELS[source]} frequency {value}"
                                for source, value in values.items()
                            )
                            + "."
                        ),
                        forms,
                        salts,
                    ),
                    **{
                        f"{source}_value": _value(group, codes[source])
                        for source, group in present.items()
                    },
                    details={
                        **{f"{source}_codes": found for source, found in compared.items()},
                        "not_compared": [source for source in present if source not in compared],
                        **({"different_form": forms} if forms else {}),
                        **({"different_salt": salts} if salts else {}),
                    },
                )
            )
        return findings
