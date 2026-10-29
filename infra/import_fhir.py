"""One-shot loader: POSTs the Synthea and deliberate-case bundles into HAPI FHIR (B2).

Stdlib only. Env: FHIR_BASE_URL (default http://hapi:8080/fhir), DATA_DIR (default
/data/fhir), WAIT_SECONDS (default 300). Exits 0 when done or already imported, 1 on failure.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("FHIR_BASE_URL", "http://hapi:8080/fhir").rstrip("/")
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data/fhir"))
WAIT_SECONDS = int(os.environ.get("WAIT_SECONDS", "300"))
# The case bundle loads last, so its last patient existing means a previous import completed.
SENTINEL = "Patient?identifier=urn%3Amedrec%3Acase%7CCASE-BRAND&_summary=count"


def ordered_bundles(data_dir: Path) -> list[Path]:
    """Hospital, practitioner, patients (they reference both by search URL), then cases."""
    synthea = sorted(Path(data_dir, "synthea").glob("*.json"))
    hospital = [p for p in synthea if p.name.startswith("hospitalInformation")]
    practitioner = [p for p in synthea if p.name.startswith("practitionerInformation")]
    patients = [p for p in synthea if p not in hospital and p not in practitioner]
    return hospital + practitioner + patients + sorted(Path(data_dir, "cases").glob("*.json"))


def fhir(method: str, path: str = "", body: bytes | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{BASE}/{path}" if path else BASE,
        data=body,
        method=method,
        # no-cache: HAPI reuses identical search results for 60s, hiding a just-finished import.
        headers={
            "Accept": "application/fhir+json",
            "Content-Type": "application/fhir+json",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return resp.status, json.load(resp)


def wait_for_server() -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        try:
            if fhir("GET", "metadata")[0] == 200:
                return
            last = "non-200 status"
        except Exception as exc:  # any failure here just means "not ready yet"
            last = repr(exc)
        if time.monotonic() >= deadline:
            sys.exit(f"FAIL: {BASE}/metadata not ready after {WAIT_SECONDS}s ({last})")
        time.sleep(5)


def post_bundle(path: Path) -> None:
    started = time.monotonic()
    try:
        _, body = fhir("POST", body=path.read_bytes())
    except urllib.error.HTTPError as exc:
        sys.exit(f"FAIL {path}: HTTP {exc.code}: {exc.read().decode(errors='replace')[:2000]}")
    entries = body.get("entry", [])
    for i, entry in enumerate(entries):
        status = entry.get("response", {}).get("status", "")
        if not status.startswith("2"):
            outcome = json.dumps(entry.get("response", {}).get("outcome", {}))[:2000]
            sys.exit(f"FAIL {path}: entry {i} response status {status!r}: {outcome}")
    took = time.monotonic() - started
    print(
        f"OK {path.relative_to(DATA_DIR)}: {body.get('type')} {len(entries)} entries in {took:.1f}s"
    )


def main() -> None:
    bundles = ordered_bundles(DATA_DIR)
    if not bundles:
        sys.exit(f"FAIL: no bundles under {DATA_DIR}/synthea or {DATA_DIR}/cases")
    wait_for_server()
    try:
        if fhir("GET", SENTINEL)[1].get("total", 0) > 0:
            print("already imported (CASE-BRAND exists); nothing to do")
            return
        started = time.monotonic()
        for path in bundles:
            post_bundle(path)
    except urllib.error.URLError as exc:
        sys.exit(f"FAIL: {BASE}: {exc}")
    print(f"imported {len(bundles)} bundles in {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    main()
