"""Resolve medications to RxNorm ingredients from a committed cache; live RxNav only on request.

Matching is by ingredient, so a brand, a salt and a generic meet. Strength and dose form are not
part of identity: the dosage rule compares them, so a difference is reported and never merged.
Set RXNORM_LIVE=1 to ask RxNav about what the cache doesn't hold (3-second timeout, no retries).
Anything unresolved keeps its alias-based identity.
"""

import json
import os
import re
import time
from collections.abc import Iterable
from functools import cache as memoize
from pathlib import Path
from typing import Any

import httpx

from contract import MedicationRecord, Rejection
from ingest.checks import BRACKETED, KNOWN_UNITS, strength_pattern
from ingest.fhir import RXNORM

RXNAV_URL = "https://rxnav.nlm.nih.gov/REST"
LIVE_TIMEOUT = 3.0
LIVE_COOLDOWN = 60.0  # seconds to stop asking after a failure, so each record doesn't wait again
DEFAULT_CACHE = Path(__file__).resolve().parents[1] / "data" / "rxnorm_cache.json"

# Words that describe the product, not the drug, dropped to find the drug name in free text.
PRODUCT_WORDS = frozenset(
    "oral tablet tab capsule cap extended delayed release er xr xl sr film coated chewable "
    "disintegrating sublingual solution suspension".split()
)
RELEASE_WORDS = frozenset({"er", "xr", "xl", "sr"})
EXTENDED_RELEASE = "Extended Release"
# RxNorm's names for forms a free-text name may state; the cache adds any others it holds.
STATED_FORMS = (
    "Oral Tablet",
    "Oral Capsule",
    "Oral Solution",
    "Oral Suspension",
    "Extended Release Oral Tablet",
    "Extended Release Oral Capsule",
    "Delayed Release Oral Tablet",
    "Delayed Release Oral Capsule",
    "Chewable Tablet",
    "Disintegrating Oral Tablet",
    "Sublingual Tablet",
)
PLAIN_ORAL_FORMS = frozenset({"Oral Tablet", "Oral Capsule"})
FORM_WORDINGS = {"chewable oral tablet": "Chewable Tablet"}  # common wording RxNorm doesn't use

_STRENGTH = strength_pattern(KNOWN_UNITS, re.IGNORECASE)
_TOKEN = re.compile(r"[^\W_]+")

Concept = dict[str, Any]

_live_found: dict[str, Concept | None] = {}  # successful live answers, including "no match"
_live_retry_at = 0.0  # time.monotonic() value before which live RxNav isn't asked again


class RxNormCacheError(Exception):
    """The RxNorm cache file is missing, isn't valid JSON, or has the wrong shape."""


def load_cache(path: str | Path) -> dict[str, Any]:
    """Read and check the cache: names point at known concepts, concepts have ingredients."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RxNormCacheError(f"cannot read RxNorm cache {path}: {exc.strerror}") from exc
    except UnicodeDecodeError as exc:
        raise RxNormCacheError(f"RxNorm cache {path} is not UTF-8 text") from exc
    try:
        cache = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RxNormCacheError(
            f"RxNorm cache {path} is not valid JSON: {exc.msg} at line {exc.lineno}"
        ) from exc
    if not isinstance(cache, dict) or not all(
        isinstance(cache.get(key), dict) for key in ("_meta", "rxcuis", "names")
    ):
        raise RxNormCacheError(f"RxNorm cache {path} needs _meta, rxcuis and names objects")
    for rxcui, concept in cache["rxcuis"].items():
        if not isinstance(concept, dict) or not _is_ingredient_list(concept.get("ingredients")):
            raise RxNormCacheError(f"RxNorm cache {path}: {rxcui} has no ingredients")
        if concept.get("rxcui") != rxcui:
            raise RxNormCacheError(f"RxNorm cache {path}: {rxcui} has a different rxcui inside")
        for field in ("dose_form", "salt"):
            if not isinstance(concept.get(field), str | None):
                raise RxNormCacheError(f"RxNorm cache {path}: {rxcui} has a bad {field}")
    for name, rxcui in cache["names"].items():
        if rxcui is not None and (not isinstance(rxcui, str) or rxcui not in cache["rxcuis"]):
            raise RxNormCacheError(f"RxNorm cache {path}: {name!r} points at unknown {rxcui}")
    return cache


def _is_ingredient_list(value: Any) -> bool:
    """A non-empty list of names; a bare string would otherwise split into letters."""
    return isinstance(value, list) and bool(value) and all(isinstance(v, str) and v for v in value)


@memoize
def _cache_at(path: Path) -> dict[str, Any]:
    """Load one cache file once."""
    return load_cache(path)


def default_cache() -> dict[str, Any]:
    """The cache at RXNORM_CACHE (default data/rxnorm_cache.json)."""
    return _cache_at(Path(os.environ.get("RXNORM_CACHE") or DEFAULT_CACHE))


def describe(client: httpx.Client, rxcui: str) -> Concept | None:
    """One concept from RxNav, or None if it lists no ingredient.

    An obsolete concept is kept with its status: it still names its ingredient, and dropping it
    would turn a match into a false "missing".
    """
    response = client.get(f"{RXNAV_URL}/rxcui/{rxcui}/historystatus.json")
    response.raise_for_status()
    history = response.json()["rxcuiStatusHistory"]
    attributes = history.get("attributes") or {}
    tty = attributes.get("tty")
    derived = history.get("derivedConcepts") or {}
    features = history.get("definitionalFeatures") or {}
    if tty == "IN":
        ingredients = [attributes.get("name")]
    else:
        ingredients = [i["ingredientName"] for i in derived.get("ingredientConcept") or []]
    if not all(ingredients) or not ingredients:
        return None
    forms = features.get("doseFormConcept") or [{}]
    return {
        "rxcui": rxcui,
        "tty": tty,
        "name": attributes.get("name"),
        "status": (history.get("metaData") or {}).get("status"),
        "ingredients": sorted(ingredients),
        "dose_form": forms[0].get("doseFormName"),
        "salt": _salt(tty, attributes.get("name"), ingredients, features),
    }


def _salt(tty: str | None, name: str | None, ingredients: list[str], features: dict) -> str | None:
    """The named salt of a single-ingredient concept, or None when it doesn't state one.

    RxNorm's strength basis is sometimes just the ingredient even when the display names a salt
    (rosuvastatin calcium), so a basis equal to the ingredient says nothing about the salt.
    """
    if len(ingredients) != 1:
        return None
    if tty == "PIN":
        candidate = name
    else:
        strengths = features.get("ingredientAndStrength") or [{}]
        candidate = strengths[0].get("bossName")
    candidate = (candidate or "").lower()
    if not candidate or candidate == ingredients[0].lower() or candidate.endswith(" acid"):
        return None  # a free acid such as alendronic acid is the drug itself, not a named salt
    return candidate


def lookup(client: httpx.Client, name: str) -> Concept | None:
    """A name's concept by exact match; several matches are ambiguous and are never guessed."""
    response = client.get(f"{RXNAV_URL}/rxcui.json", params={"name": name, "search": 0})
    response.raise_for_status()
    ids = (response.json().get("idGroup") or {}).get("rxnormId") or []
    return describe(client, ids[0]) if len(ids) == 1 else None


def refine[Item: (MedicationRecord, Rejection)](
    items: Iterable[Item], cache: dict[str, Any] | None = None
) -> list[Item]:
    """Set the ingredient as normalized_name, and rxcui on records; original names are untouched.

    Records also carry the concept in raw["rxnorm"], which is how the dosage rule learns the dose
    form and salt. Items that don't resolve are returned unchanged, keeping their alias identity.
    """
    cache = default_cache() if cache is None else cache
    result: list[Item] = []
    for item in items:
        concept = _resolve(item, cache)
        if concept is None:
            result.append(item)
            continue
        update: dict[str, Any] = {"normalized_name": _identity(concept)}
        if isinstance(item, MedicationRecord):
            # A code the source stated is kept even when the concept was found by name instead.
            update["rxcui"] = _coded_rxcui(item.raw) or concept["rxcui"]
            update["raw"] = {**item.raw, "rxnorm": _with_stated_form(concept, item.name, cache)}
        result.append(item.model_copy(update=update))
    return result


def _identity(concept: Concept) -> str:
    """The matching key: the ingredient, or all of them, so a combination stays its own drug."""
    return " / ".join(sorted(ingredient.lower() for ingredient in concept["ingredients"]))


def _resolve(item: MedicationRecord | Rejection, cache: dict[str, Any]) -> Concept | None:
    """Coded RxCUI, the name as given, its drug name, the alias-based name, then live RxNav.

    The drug name comes before the alias-based name because aliases can drop a salt:
    "Metoprolol Tartrate 25 mg" must stay tartrate, not become plain metoprolol.
    """
    code = _coded_rxcui(item.raw)
    if code in cache["rxcuis"]:
        return cache["rxcuis"][code]
    given = list(dict.fromkeys(key for key in (_key(item.name), _drug_name(item.name)) if key))
    for key in (*given, _key(item.normalized_name)):
        if cache["names"].get(key):
            return cache["rxcuis"][cache["names"][key]]
    if os.environ.get("RXNORM_LIVE") != "1":
        return None
    return _live(code, given)


def _coded_rxcui(raw: Any) -> str | None:
    """The RxNorm code on a FHIR resource's medicationCodeableConcept, if there is one."""
    concept = raw.get("medicationCodeableConcept") if isinstance(raw, dict) else None
    codings = concept.get("coding") if isinstance(concept, dict) else None
    for coding in codings if isinstance(codings, list) else []:
        if isinstance(coding, dict) and coding.get("system") == RXNORM:
            code = str(coding.get("code") or "")
            if code.isascii() and code.isdigit():
                return code
    return None


def _key(name: str | None) -> str:
    """A cache key: lowercased, with whitespace collapsed."""
    return " ".join(name.lower().split()) if name else ""


def _words(name: str | None) -> list[str]:
    """The lowercase words of a name, without [brand] tags or strengths."""
    return _TOKEN.findall(_STRENGTH.sub(" ", BRACKETED.sub(" ", (name or "").lower())))


def _drug_name(name: str | None) -> str:
    """The drug in free text: "Metoprolol Tartrate 25 mg tab" gives "metoprolol tartrate"."""
    return " ".join(w for w in _words(name) if w not in PRODUCT_WORDS and not w.isdigit())


def _with_stated_form(concept: Concept, name: str, cache: dict[str, Any]) -> Concept:
    """The concept, plus the dose form its record's own name states if RxNorm's concept has none.

    A brand or plain drug name has no form in RxNorm, but "metformin 500 MG Oral Tablet" and
    "Metformin ER" do say something, and that's what the dosage rule compares.
    """
    if concept.get("dose_form"):
        return concept
    stated = _stated_form(name, cache)
    return {**concept, "dose_form": stated} if stated else concept


def _stated_form(name: str, cache: dict[str, Any]) -> str | None:
    """The dose form free text states, combining a release word with a plain oral form.

    "Metformin ER 500 mg Oral Tablet" is an extended release tablet, not a plain one. With no
    route to combine, "Metformin ER" says only "Extended Release", and the rule treats that as
    agreeing with any fuller form it begins.
    """
    text = f" {' '.join(_words(name))} "
    cached = {c["dose_form"] for c in cache["rxcuis"].values() if c.get("dose_form")}
    wordings = {form.lower(): form for form in {*STATED_FORMS, *cached}} | FORM_WORDINGS
    found = [wording for wording in wordings if f" {wording} " in text]
    stated = wordings[max(found, key=len)] if found else None
    if not (RELEASE_WORDS & set(text.split()) or " extended release " in text):
        return stated
    if stated in PLAIN_ORAL_FORMS:
        return f"{EXTENDED_RELEASE} {stated}"
    return stated if stated and stated.startswith(EXTENDED_RELEASE) else EXTENDED_RELEASE


def _live_client() -> httpx.Client:
    """The RxNav client for the optional live path."""
    return httpx.Client(timeout=LIVE_TIMEOUT)


def _live(code: str | None, names: list[str]) -> Concept | None:
    """Ask RxNav about a code, then names, once each.

    A failure isn't remembered as "no match", but it pauses live lookups for LIVE_COOLDOWN, so a
    dead RxNav costs one timeout rather than one for every record on every page.
    """
    global _live_retry_at
    queries = [(f"rxcui:{code}", describe, code)] if code else []
    queries += [(f"name:{name}", lookup, name) for name in names]
    # In order, so a remembered name can't stand in for a code that hasn't been asked about yet.
    while queries and queries[0][0] in _live_found:
        memo = queries.pop(0)[0]
        if _live_found[memo]:
            return _live_found[memo]
    if not queries or time.monotonic() < _live_retry_at:
        return None
    try:
        with _live_client() as client:
            for memo, ask, value in queries:
                if memo not in _live_found:
                    _live_found[memo] = ask(client, value)
                if _live_found[memo]:
                    return _live_found[memo]
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, KeyError, TypeError, AttributeError):
        _live_retry_at = time.monotonic() + LIVE_COOLDOWN
    return None
