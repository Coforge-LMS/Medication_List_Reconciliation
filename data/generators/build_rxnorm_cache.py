"""Build data/rxnorm_cache.json from live RxNav, once, for review and commit.

Run from the repo root: python -m data.generators.build_rxnorm_cache

Covers every RxNorm code on an active FHIR medication and every name in the pharmacy, intake and
alias data, plus the salts and ingredients those concepts name, so a plain "chlorpheniramine
maleate" meets a coded product. It fails loudly on any committed input that is unresolved or
ambiguous unless MANUAL decides it, because a silent gap would come back as a false "missing".
"""

import argparse
import csv
import json
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from ingest.rxnorm import RXNAV_URL, _coded_rxcui, _key, describe, lookup

ROOT = Path(__file__).resolve().parents[2]
PAUSE = 0.1  # seconds between concepts, well under RxNav's limit of 20 requests a second

# Hand decisions: a lowercase name mapped to an RxCUI, or to None for "known to have no match".
MANUAL: dict[str, str | None] = {}


class CacheBuildError(Exception):
    """Some inputs couldn't be resolved, so no cache was written."""


def collect_inputs(root: Path = ROOT) -> tuple[dict[str, str], set[str]]:
    """({rxcui: display} for active FHIR medications, names from pharmacy, intake and aliases)."""
    codes: dict[str, str] = {}
    bundles = [*sorted((root / "data/fhir/synthea").glob("*.json"))]
    bundles += sorted((root / "data/fhir/cases").glob("*.json"))
    bundles += sorted((root / "data/fhir/demo").glob("*.json"))
    for path in bundles:
        for entry in json.loads(path.read_text(encoding="utf-8")).get("entry", []):
            resource = entry.get("resource", {})
            if resource.get("resourceType") != "MedicationRequest":
                continue
            code = _coded_rxcui(resource)
            if resource.get("status") == "active" and code:
                concept = resource["medicationCodeableConcept"]
                displays = [c.get("display") for c in concept.get("coding", [])]
                codes[code] = concept.get("text") or next(filter(None, displays), "")
    pharmacy = json.loads((root / "data/pharmacy/pharmacy_records.json").read_text("utf-8"))
    names = {row["medication_name"] for row in pharmacy}
    with (root / "data/intake/intake_medications.csv").open(newline="", encoding="utf-8") as f:
        names |= {row["medication_name"] for row in csv.DictReader(f)}
    aliases = json.loads((root / "data/aliases.json").read_text(encoding="utf-8"))
    names |= set(aliases["aliases"]) | set(aliases["aliases"].values())
    return codes, {name for name in names if name and name.strip()}


def build(
    client: httpx.Client,
    codes: dict[str, str],
    names: set[str],
    built: str,
    manual: dict[str, str | None] = MANUAL,
    pause: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Resolve everything into the cache structure, or raise listing all that failed."""
    version = client.get(f"{RXNAV_URL}/version.json")
    version.raise_for_status()
    rxcuis: dict[str, Any] = {}
    cached_names: dict[str, str | None] = {}
    problems: list[str] = []

    def keep(rxcui: str) -> bool:
        """Describe an RxCUI once; False if it lists no ingredient."""
        if rxcui not in rxcuis:
            pause(PAUSE)
            concept = describe(client, rxcui)
            if concept is None:
                return False
            rxcuis[rxcui] = concept
        return True

    for code, display in codes.items():
        if not keep(code):
            problems.append(f"code {code} ({display}) lists no ingredient")
        elif display:
            cached_names[_key(display)] = code
    for key in {_key(name) for name in names} | set(manual):
        if key in manual:
            cached_names[key] = manual[key]
            if manual[key] and not keep(manual[key]):
                problems.append(f"manual {key!r}: {manual[key]} lists no ingredient")
            continue
        pause(PAUSE)
        concept = lookup(client, key)
        if concept is None:
            problems.append(f"name {key!r} is unresolved or ambiguous; decide it in MANUAL")
            continue
        rxcuis.setdefault(concept["rxcui"], concept)
        cached_names[key] = concept["rxcui"]
    named = {n for c in list(rxcuis.values()) for n in [c.get("salt"), *c["ingredients"]] if n}
    for key in sorted({_key(name) for name in named} - set(cached_names)):
        pause(PAUSE)
        concept = lookup(client, key)  # best effort: without it, this name just keeps its alias
        if concept is not None:
            rxcuis.setdefault(concept["rxcui"], concept)
            cached_names[key] = concept["rxcui"]
    if problems:
        raise CacheBuildError("; ".join(sorted(problems)))
    return {
        "_meta": {
            "rxnorm_version": version.json().get("version"),
            "api_version": version.json().get("apiVersion"),
            "built": built,
        },
        "rxcuis": rxcuis,
        "names": cached_names,
    }


def render(cache: dict[str, Any]) -> str:
    """Stable JSON text: sorted keys and indented, so a rebuild reads well as a diff."""
    return json.dumps(cache, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> None:
    """Build the cache from live RxNav and write it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "rxnorm_cache.json")
    args = parser.parse_args(argv)
    codes, names = collect_inputs()
    with httpx.Client(timeout=10) as client:
        cache = build(client, codes, names, built=date.today().isoformat())
    args.out.write_text(render(cache), encoding="utf-8")
    print(f"Wrote {len(cache['rxcuis'])} concepts and {len(cache['names'])} names to {args.out}")


if __name__ == "__main__":
    main()
