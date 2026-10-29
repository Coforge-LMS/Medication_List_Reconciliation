# 07 — RxNorm normalization via RxNav (with offline cache)
OWNER: Sarthak Kakkar, to review and finalize (terminology review: Rachit Shah)
_Drafted 2026-10-29 by a research agent; facts verified against the sources listed below._

## Recommendation
- **Plain `httpx` against RxNav REST, JSON (`.json` suffix; default is XML). No wrapper, no key, no UMLS license.**
- **Runtime reads only a committed cache** (`data/rxnorm_cache.json`). Live lookup runs only when `RXNORM_LIVE=1`, with `timeout=3`, no retries; any miss/error falls back to the V1 alias path unchanged. Tests and the demo use the cache only.
- **Build the cache once** (script below, run online by a dev, output reviewed by Rachit, committed). Never auto-accept `approximateTerm`; use it only to suggest candidates a human adds to the build script's manual map.
- **Endpoints to use:** `rxcui.json?name=&search=0|1` (name to RxCUI), `rxcui/{id}/historystatus.json` (one call: TTY, status/remap, ingredients, per-ingredient strength, dose form, SCD of an SBD), `rxcui/{id}/related.json?tty=IN` (PIN to IN), `version.json` (pin). Optional: `/generic.json`, `spellingsuggestions.json`, `approximateTerm.json` (build-time suggestions only).
- **Normalization is a pre-step**, not a rule: it turns each record into a `Norm` (below) and hands it to the V1 identity matcher. Keep the original name on the record; attach `rxnorm: {rxcui, tty, name}` beside it, never overwrite.
- **Matching key (satisfies the hard constraint):**
  - `identity` = `frozenset(ingredient_rxcuis)` (IN rxcuis). BN, PIN (salt) and SBD/SCD all reduce to IN. Combination products (MIN) give a multi-element set.
  - `dosage` = per-ingredient `(value, unit)` + `dose_form_rxcui` (RxNorm dose forms already encode route and release type, e.g. Oral Tablet 317541 vs Extended Release Oral Tablet 316945).
  - Same identity AND equal dosage AND equal dose form: **same drug** (brand = generic).
  - Same identity, different strength: **not equivalent**, report as dose discrepancy (not "missing", not "match").
  - Same identity, different dose form/route/ER-vs-IR: **not equivalent**, report as form discrepancy.
  - Different identity set (including combo vs single ingredient): different drug.
  - A side lacking strength or form (BN-only or IN-only name): take strength from the record's dose/unit fields via the existing V1 comparison; form unknown is "unverified", never "equal".
  - If either side is unresolved: V1 alias matching, tagged `normalized: false`.
- **Show on UI:** NLM requires an attribution line (see Gotchas).

## Rationale
- SBD to SCD (`tradename_of`) keeps strength and dose form, so brand-to-generic collapse is lossless; BN to IN loses them, so those are carried separately. Example: `617318` atorvastatin 20 MG Oral Tablet [Lipitor] is `tradename_of` `617310` atorvastatin 20 MG Oral Tablet.
- Synthea gives RxCUIs directly: its FHIR R4 exporter writes `medicationCodeableConcept` with the RxNorm system URI `http://www.nlm.nih.gov/research/umls/rxnorm` unless the code is SNOMED. Sample module codes: 310798 `Hydrochlorothiazide 25 MG Oral Tablet`, 314076, 308136 `amLODIPine 2.5 MG Oral Tablet`, 979485. All four resolve as active SCDs live. Cache by code, not by display string (Synthea casing differs from RxNorm: `amLODIPine` vs `amlodipine`).
- Pharmacy names are strings, hence the name cache. Name search cannot be trusted with strengths in the string (Gotchas), so look up the name part; compare strength from the dose/unit fields.
- 20 req/s per IP is irrelevant for a one-off build of a few dozen codes; the cache removes the network from the demo.

## Pinned versions
- Observed 2026-10-29 via `version.json`: RxNorm data set `05-Oct-2026` (first-Monday monthly release), API `3.1.356`. Next monthly release is `02-Nov-2026` (after Friday's demo, by the documented first-Monday rule).
- Store both strings in `_meta` of the cache. Weekly Wednesday updates add MTHSPL data on top of the monthly release; whether `version.json` changes weekly is UNVERIFIED.
- Python 3.12, `httpx` (no version pinned by research; use the repo's lock). The snippets below were logic-tested with stdlib `urllib` (httpx not installed in the research shell); on that Mac the python.org build needed `SSL_CERT_FILE=/etc/ssl/cert.pem`. httpx (certifi) was not tested.

## Commands and config snippets
Base `https://rxnav.nlm.nih.gov/REST`. Numbers are strings; empty fields may be `null` or absent.
```
GET /rxcui.json?name=Lipitor&search=1           -> {"idGroup":{"rxnormId":["153165"]}}      (BN)
GET /rxcui.json?name=atorvastatin&search=1      -> {"idGroup":{"rxnormId":["83367"]}}       (IN)
GET /rxcui.json?name=Lipitor%2020%20mg&search=1 -> {"idGroup":{}}     (no match = empty idGroup, HTTP 200)
GET /rxcui.json?name=Lipitor%2020%20mg%20Tab&search=1 -> {"idGroup":{"rxnormId":["617318"]}}   (SBD)
GET /rxcui/153165/properties.json  -> {"properties":{"rxcui":"153165","name":"Lipitor","synonym":"","tty":"BN",...}}
GET /rxcui/617318.json             -> {"idGroup":{"name":"atorvastatin 20 MG Oral Tablet [Lipitor]"}}   (getRxNormName)
GET /rxcui/617318/related.json?rela=tradename_of -> conceptGroup[{"tty":"SCD", conceptProperties:[{"rxcui":"617310",
     "name":"atorvastatin 20 MG Oral Tablet","synonym":"atorvastatin (as atorvastatin calcium) 20 MG Oral Tablet",...}]}]
GET /rxcui/153165/related.json?tty=IN+BN+SCD+SBD -> groups BN 153165, IN 83367, SBD (10/20/40/80 MG: 617314,617318,617320,262095),
     SCD (617312,617310,617311,259255)   # from a BN you get ALL strengths: never pick by BN alone
GET /rxcui/617318/generic.json     -> {"minConceptGroup":{"minConcept":[{"rxcui":"617310","name":"atorvastatin 20 MG Oral Tablet","tty":"SCD"}]}}
GET /rxcui/617318/historystatus.json  (trimmed)
  {"metaData":{"status":"Active",...},"attributes":{"rxcui":"617318","tty":"SBD","isMultipleIngredient":"NO","isBranded":"YES"},
   "definitionalFeatures":{"ingredientAndStrength":[{"baseRxcui":"83367","baseName":"atorvastatin","bossRxcui":"83367",
      "numeratorValue":"20","numeratorUnit":"MG","denominatorValue":"1","denominatorUnit":"EACH"}],
      "doseFormConcept":[{"doseFormRxcui":"317541","doseFormName":"Oral Tablet"}]},
   "derivedConcepts":{"ingredientConcept":[{"ingredientRxcui":"83367","ingredientName":"atorvastatin"}],
      "scdConcept":{"scdConceptRxcui":"617310",...}}}
   # Remapped example (105048): status "Remapped", derivedConcepts.remappedConcept[{remappedRxCui,remappedName,remappedTTY,remappedActive}]
GET /rxcui/85783/related.json?tty=IN+MIN  (BN Zestoretic) -> IN 29046 lisinopril + 5487 hydrochlorothiazide; MIN 214618
GET /rxcui/235743/related.json?tty=IN     (PIN metformin hydrochloride) -> IN 6809 metformin
GET /approximateTerm.json?term=lipitor%2020%20mg&maxEntries=3 -> candidate[{"rxcui":"617318","rxaui":"12877417","score":"13.02",
     "rank":"1","source":"GS"} (no name: restricted source), {"rxcui":"617317","name":"atorvastatin 20 MG [Lipitor]","source":"RXNORM",...}]
GET /spellingsuggestions.json?name=lipitr -> {"suggestionGroup":{"name":null,"suggestionList":{"suggestion":["lipitor"]}}}
GET /version.json -> {"version":"05-Oct-2026","apiVersion":"3.1.356"}
```
Cache schema (`data/rxnorm_cache.json`, committed, sorted keys, pretty-printed for review diffs):
```json
{"_meta": {"rxnorm_version": "05-Oct-2026", "api_version": "3.1.356", "built": "2026-10-29"},
 "names": {"lipitor": {"rxcui": "153165", "tty": "BN", "name": "Lipitor", "ingredient_rxcuis": ["83367"],
                        "ingredient_names": ["atorvastatin"], "strengths": [], "dose_form_rxcui": null, "scd_rxcui": null},
           "lipitor 20 mg": "lipitor",          "unknown drug x": null},
 "rxcuis": {"617310": {"rxcui": "617310", "tty": "SCD", "name": "atorvastatin 20 MG Oral Tablet",
                       "ingredient_rxcuis": ["83367"], "ingredient_names": ["atorvastatin"],
                       "strengths": [{"ingredient_rxcui": "83367", "basis_rxcui": "83367", "value": "20", "unit": "MG"}],
                       "dose_form_rxcui": "317541", "dose_form": "Oral Tablet", "scd_rxcui": "617310"}}}
```
`names` key = `" ".join(name.lower().split())`; a string value is an alias to another key (keeps the file small); `null` is a cached negative. Build and runtime resolve (build script was run against live RxNav and produced the shapes above):
```python
import json, os, re, time, httpx
B = "https://rxnav.nlm.nih.gov/REST"; c = httpx.Client(timeout=5, headers={"Accept": "application/json"})
def get(path, **p):
    time.sleep(0.1)                                   # far below 20 req/s
    r = c.get(f"{B}/{path}", params=p); r.raise_for_status(); return r.json()
def describe(rxcui):                                  # one record per RxCUI; None = not Active, review by hand
    h = get(f"rxcui/{rxcui}/historystatus.json")["rxcuiStatusHistory"]; a, d, f = h["attributes"], h["derivedConcepts"], h["definitionalFeatures"]
    if h["metaData"]["status"] != "Active": return None
    if a["tty"] == "IN": ins = [(rxcui, a["name"])]
    elif a["tty"] == "PIN": ins = [(x["rxcui"], x["name"]) for x in get(f"rxcui/{rxcui}/related.json", tty="IN")["relatedGroup"]["conceptGroup"][0]["conceptProperties"]]
    else: ins = [(x["ingredientRxcui"], x["ingredientName"]) for x in d.get("ingredientConcept", [])]
    df = (f.get("doseFormConcept") or [{}])[0]
    return {"rxcui": rxcui, "tty": a["tty"], "name": a["name"], "ingredient_rxcuis": sorted(i for i, _ in ins), "ingredient_names": [n for _, n in sorted(ins)],
            "strengths": [{"ingredient_rxcui": s["baseRxcui"], "basis_rxcui": s.get("bossRxcui") or None, "value": s["numeratorValue"], "unit": s["numeratorUnit"]} for s in f.get("ingredientAndStrength", [])],
            "dose_form_rxcui": df.get("doseFormRxcui"), "dose_form": df.get("doseFormName"),
            "scd_rxcui": (d.get("scdConcept") or {}).get("scdConceptRxcui") or (rxcui if a["tty"] == "SCD" else None)}
STRIP = re.compile(r"\s+\d[\d.,/]*\s*(mg|mcg|g|ml|iu|units?|%).*$", re.I)   # "Lipitor 20 mg" -> "Lipitor"
def lookup(name):                                     # build-time only
    for q in dict.fromkeys([name, STRIP.sub("", name)]):
        for s in (0, 1):
            ids = get("rxcui.json", name=q, search=s)["idGroup"].get("rxnormId", [])
            if len(ids) == 1: return describe(ids[0])
            if ids: return {"ambiguous": ids}         # hand-review, do not cache a guess
    return None
def resolve(cache, name=None, rxcui=None):            # runtime: cache first, live only if flagged
    hit = cache["rxcuis"].get(rxcui or "") or cache["names"].get(" ".join((name or "").lower().split()))
    while isinstance(hit, str): hit = cache["names"].get(hit)
    if hit or os.getenv("RXNORM_LIVE") != "1": return hit
    try: hit = lookup(name) if name else describe(rxcui)
    except httpx.HTTPError: return None               # None -> V1 alias matching
    return None if hit and "ambiguous" in hit else hit
```
Auth, only if ever needed: header `Authorization: Bearer <UTS key>` (raises limit to 100 req/s; not needed here).

## Gotchas
- **Approximate matching ignores strength and form (false positives).** `approximateTerm` for `lipitor 25 mg` (no such strength) ranked the BN `153165` first; for `lipitor 20 mg ER` it silently dropped `ER` and returned `617318`, the plain 20 mg tablet. Scores are only comparable within one response; no documented threshold. Never use it for identity.
- `maxEntries` is a coarse cap: candidates are atoms (the same RxCUI repeats per source) and ties are not split (8 returned for `maxEntries=3`). Dedupe by `rxcui`. Candidates have no TTY; call `properties`/`historystatus`. `name` is omitted for restricted sources (GS, MMSL) without a UMLS key.
- **Strings with strengths are brittle.** `Lipitor 20 mg` is not found at search 0/1/2, but `Lipitor 20 mg Tab` is (normalization expands abbreviations; the synonym is `Lipitor 20 MG Oral Tablet`). Hence look up the name part. `atorvastatin 20 mg` at search 1 returns SCDC `597966` (ingredient+strength, no form), not the SCD.
- **Name search can return several RxCUIs, including the wrong release type.** `metformin hydrochloride 500 MG Oral Tablet` at search 0 returned `860975` (24 HR Extended Release tablet) and `861007` (plain tablet). Treat >1 hit as ambiguous; the script flags it for hand review.
- **Salts:** `metformin hydrochloride` is PIN `235743`; `metformin` is IN `6809`. Search 1 ignores salt forms and returns both; search 0 returns the PIN only. Map PIN to IN via `related?tty=IN`. Losartan potassium 25 MG tablet: IN `52175` losartan, PIN `203160`; the strength is stated for the salt. Different salts share one IN (metoprolol tartrate `866924` Oral Tablet vs succinate `866427` ER), so the dose-form check, not identity, separates them; `basis_rxcui` keeps the salt for an optional soft warning.
- **Extended release:** ER is a separate dose form (`316945`), and RxNorm adds a quantity factor and qualitative prefixes (`24 HR ...`, `Modified 24 HR ...`, `Osmotic 24 HR ...` have different RxCUIs, same dose form). Compare the `(identity, strengths, dose_form_rxcui)` tuple, not only `scd_rxcui`. `related`/`allrelated` omit `quantified_form_of` links.
- **Retired/remapped RxCUIs:** status values are Active, Obsolete, Remapped, Quantified, NotCurrent; `properties` returns nothing for non-active ids. Remapped ids list successors in `remappedConcept` (105048 maps to 849389 + 849394). Retired ids are never reused. `describe` returns None for non-Active; fix by hand. In-scope SCD/SBD RxCUIs are persistent; out-of-scope ones are transient.
- **Case:** query parameters are case-insensitive (`LIPITOR` = `lipitor` at search 0), but RxNorm display casing differs from Synthea's Tallman casing; lowercase the cache keys. Ingredient order in combo names is alphabetical (`hydrochlorothiazide 12.5 MG / lisinopril 20 MG Oral Tablet`, 197886), so never match combo names by string.
- **Units:** liquids appear as `4 MG/ML` (e.g. 2630760), labels say `20 mg per 5 mL`; unit conversion stays in V1's normalizer.
- **Brand lists are large:** `related?tty=BN+SCD` on IN `83367` also returns Caduet, Atorvaliq and atorvastatin combos; filter by the IN set.
- **Terms:** use is free; no UMLS license needed except RxClass SNOMED CT content (not used). Limit: 20 req/s per IP; NLM suggests caching 12-24 h. Apps must show: "This product uses publicly available data from the U.S. National Library of Medicine (NLM)..." plus the non-endorsement sentence; do not use NLM's name or logo.
- **UNVERIFIED:** commercial-use terms (page is silent); behavior past 20 req/s; whether `version.json` moves with weekly updates; existence of any maintained Python wrapper (search found only `pharmpy`, stale-looking, page not retrievable); full Synthea exporter code body for `mapCodeToCodeableConcept` (only the first 100k chars of `FhirR4.java` were read); RxNav uptime guarantee (observed HTTP 200 on 2026-10-29 only).

## Rejected alternatives
- **`approximateTerm`/`search=9` as the matcher:** ignores strength/ER (shown above); violates the hard constraint.
- **Live-only API at demo time:** network dependency, 20 req/s ceiling, remap drift; rejected for the demo.
- **Matching on SCD/SBD name strings or generic-name text:** casing, order, salt and "24 HR" variation make strings unreliable; use RxCUIs.
- **IN-only equivalence:** would call metoprolol tartrate and succinate ER, or 10 mg and 40 mg, the same drug.
- **Local RxNorm RRF files / RxNav-in-a-Box:** needs UTS account for full release files, big download, and a "custom terminology database" we ruled out.
- **Python wrapper:** none clearly maintained; each endpoint above is one GET returning flat JSON, so `httpx` plus ~40 lines is smaller than a dependency.
- **Manual alias JSON only (V1):** stays as the fallback, but cannot say a strength or form differs and does not scale beyond hand-entered pairs.

## Sources
- [RxNorm API function list](https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html): endpoint names; "no license is needed" statement (fetched 2026-10-29)
- [RxNav Terms of Service](https://lhncbc.nlm.nih.gov/RxNav/TermsofService.html): 20 req/s per IP, optional UTS key to 100 req/s, cache 12-24 h, attribution, one license exception (fetched 2026-10-29)
- [findRxcuiByString](https://lhncbc.nlm.nih.gov/RxNav/APIs/api-RxNorm.findRxcuiByString.html): `search` 0/1/2/9 semantics, JSON strings, empty idGroup (fetched 2026-10-29)
- [getApproximateMatch](https://lhncbc.nlm.nih.gov/RxNav/APIs/api-RxNorm.getApproximateMatch.html): score/rank, maxEntries, restricted-source names (fetched 2026-10-29)
- [getRelatedByType](https://lhncbc.nlm.nih.gov/RxNav/APIs/api-RxNorm.getRelatedByType.html): tty list, response shape, excluded quantified/reformulation links (fetched 2026-10-29)
- [getAllRelatedInfo](https://lhncbc.nlm.nih.gov/RxNav/APIs/api-RxNorm.getAllRelatedInfo.html): allrelated shape and exclusions (fetched 2026-10-29)
- [getRxcuiHistoryStatus](https://lhncbc.nlm.nih.gov/RxNav/APIs/api-RxNorm.getRxcuiHistoryStatus.html): status values, remappedConcept fields (fetched 2026-10-29)
- [getRxConceptProperties](https://lhncbc.nlm.nih.gov/RxNav/APIs/api-RxNorm.getRxConceptProperties.html): properties fields; empty for non-active ids (fetched 2026-10-29)
- [getSpellingSuggestions](https://lhncbc.nlm.nih.gov/RxNav/APIs/api-RxNorm.getSpellingSuggestions.html): RxNorm-only suggestions, not for autocomplete (fetched 2026-10-29)
- [getRxNormVersion](https://lhncbc.nlm.nih.gov/RxNav/APIs/api-RxNorm.getRxNormVersion.html): version.json fields and date format (fetched 2026-10-29)
- [RxNorm term types (appendix 5)](https://www.nlm.nih.gov/research/umls/rxnorm/docs/appendix5.html): IN, PIN, MIN, BN, SCD, SBD, SCDC, SCDF/SBDF, DF definitions (fetched 2026-10-29)
- [RxNorm overview](https://www.nlm.nih.gov/research/umls/rxnorm/overview.html): monthly/weekly releases; UTS account only for full files; has_tradename/tradename_of (fetched 2026-10-29)
- [RxNorm technical documentation](https://www.nlm.nih.gov/research/umls/rxnorm/docs/techdoc.html): SCD/SBD naming, quantity factor, retired RxCUIs never reused, release cadence (fetched 2026-10-29)
- [Synthea FhirR4.java](https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/java/org/mitre/synthea/export/FhirR4.java): medicationRequest uses RxNorm URI unless SNOMED (first 100k chars only; fetched 2026-10-29)
- [Synthea hypertension_medication.json](https://raw.githubusercontent.com/synthetichealth/synthea/master/src/main/resources/modules/medications/hypertension_medication.json): sample RxCUIs and display casing (fetched 2026-10-29)
- Live RxNav calls (curl, HTTP 200, 2026-10-29) under `https://rxnav.nlm.nih.gov/REST/`: every URL and trimmed response in the snippets, plus the false-positive, ambiguity and metoprolol observations
