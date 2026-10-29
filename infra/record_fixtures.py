"""Record real HAPI responses for the three case patients into tests/fixtures/hapi/ (stdlib only).

Writes one JSON file per request plus index.json mapping the request path+query
(relative to the FHIR base) to its file, so a MockTransport can serve them by URL.
Run against a populated HAPI: python infra/record_fixtures.py
"""

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = os.environ.get("HAPI_BASE_URL", "http://localhost:8080/fhir").rstrip("/")
OUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "hapi"
CASES = ["CASE-CLEAN", "CASE-MIXED", "CASE-BRAND"]


def get(path):
    req = urllib.request.Request(
        f"{BASE_URL}/{path}",
        headers={"Accept": "application/fhir+json", "Cache-Control": "no-cache"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def main():
    index = {}

    def record(path, filename):
        body = get(path)
        target = OUT_DIR / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(body, indent=2) + "\n")
        index[path] = filename
        return body

    for case in CASES:
        ident = urllib.parse.quote(f"urn:medrec:case|{case}", safe="")
        search = record(f"Patient?identifier={ident}", f"{case}/patient_search.json")
        pid = search["entry"][0]["resource"]["id"]
        record(f"Patient/{pid}", f"{case}/patient_read.json")
        record(
            f"MedicationRequest?patient={pid}&status=active",
            f"{case}/medicationrequest_active.json",
        )

    (OUT_DIR / "index.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    print(f"recorded {len(index)} responses into {OUT_DIR}")


if __name__ == "__main__":
    main()
