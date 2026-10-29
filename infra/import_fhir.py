"""Load the committed FHIR bundles into HAPI (stdlib only).

Order: hospital -> practitioner -> Synthea patients -> deliberate cases.
Skips everything if the last case patient (CASE-BRAND) already exists, and exits
non-zero on any failed transaction.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = os.environ.get("HAPI_BASE_URL", "http://localhost:8080/fhir").rstrip("/")
DATA_DIR = Path(
    os.environ.get("FHIR_DATA_DIR", Path(__file__).resolve().parent.parent / "data" / "fhir")
)
MARKER = "urn:medrec:case|CASE-BRAND"
HEADERS = {"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}
READY_TIMEOUT_S = 120


class FhirImportError(Exception):
    pass


def request(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, headers={**HEADERS, **(headers or {})}, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        raise FhirImportError(
            f"{method} {url} -> HTTP {e.code}: {e.read().decode(errors='replace')[:2000]}"
        ) from e
    except urllib.error.URLError as e:
        raise FhirImportError(f"{method} {url} failed: {e.reason}") from e


def wait_for_server():
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        try:
            request("GET", f"{BASE_URL}/metadata?_summary=true")
            return
        except FhirImportError as e:
            if time.monotonic() > deadline:
                raise FhirImportError(f"HAPI not ready after {READY_TIMEOUT_S}s: {e}") from e
            time.sleep(3)


def marker_exists():
    # HAPI reuses cached search results for 60 s; no-cache stops a stale "0" right after an import
    query = urllib.parse.urlencode(
        {"identifier": MARKER, "_summary": "count", "_total": "accurate"}
    )
    url = f"{BASE_URL}/Patient?{query}"
    _, bundle = request("GET", url, headers={"Cache-Control": "no-cache"})
    return bundle.get("total", 0) > 0


def load_order():
    synthea = DATA_DIR / "synthea"
    groups = [
        sorted(synthea.glob("hospitalInformation*.json")),
        sorted(synthea.glob("practitionerInformation*.json")),
        sorted(
            p
            for p in synthea.glob("*.json")
            if not p.name.startswith(("hospitalInformation", "practitionerInformation"))
        ),
        sorted((DATA_DIR / "cases").glob("*.json")),
    ]
    files = [f for g in groups for f in g]
    if not groups[0] or not groups[1] or not groups[2] or not groups[3]:
        raise FhirImportError(f"missing bundle group under {DATA_DIR}")
    return files


def post_bundle(path):
    bundle = json.loads(path.read_text())
    status, resp = request("POST", BASE_URL, bundle)
    entries = resp.get("entry", [])
    bad = [e for e in entries if not str(e.get("response", {}).get("status", "")).startswith("2")]
    if (
        status != 200
        or resp.get("resourceType") != "Bundle"
        or bad
        or len(entries) != len(bundle["entry"])
    ):
        raise FhirImportError(
            f"{path.name}: transaction not fully applied "
            f"(HTTP {status}, {len(bad)} bad of {len(entries)} entries)"
        )
    print(f"ok  {path.name}: {len(entries)} entries")


def main():
    wait_for_server()
    if marker_exists():
        print(f"skip: {MARKER} already present, nothing imported")
        return 0
    for path in load_order():
        post_bundle(path)
    print("import complete")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FhirImportError as e:
        print(f"IMPORT FAILED: {e}", file=sys.stderr)
        sys.exit(1)
