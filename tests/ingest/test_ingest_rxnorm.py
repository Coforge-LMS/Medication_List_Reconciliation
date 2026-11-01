"""ingest.rxnorm: cache-first resolution, identity by ingredient, live fallback, cache building."""

import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from contract import MedicationRecord, Reason, Rejection
from data.generators import build_rxnorm_cache as builder
from ingest import rxnorm
from ingest.fhir import RXNORM

REAL_LIVE_CLIENT = rxnorm._live_client

ROSUVASTATIN_SCD = {
    "rxcui": "859751",
    "tty": "SCD",
    "name": "rosuvastatin calcium 20 MG Oral Tablet",
    "status": "Active",
    "ingredients": ["rosuvastatin"],
    "dose_form": "Oral Tablet",
    "salt": None,
}
CRESTOR = {
    "rxcui": "320864",
    "tty": "BN",
    "name": "Crestor",
    "status": "Active",
    "ingredients": ["rosuvastatin"],
    "dose_form": None,
    "salt": None,
}
COMBO = {
    "rxcui": "979471",
    "tty": "SCD",
    "name": "hydrochlorothiazide 25 MG / losartan potassium 100 MG Oral Tablet",
    "status": "Active",
    "ingredients": ["hydrochlorothiazide", "losartan"],
    "dose_form": "Oral Tablet",
    "salt": None,
}
CACHE = {
    "_meta": {},
    "rxcuis": {c["rxcui"]: c for c in (ROSUVASTATIN_SCD, CRESTOR, COMBO)},
    "names": {"crestor": "320864", "known nothing": None},
}


def record(name, normalized=None, code=None, source="pharmacy"):
    """An accepted record, FHIR-coded when code is given."""
    raw = {"medicationCodeableConcept": {"coding": [{"system": RXNORM, "code": code}]}}
    return MedicationRecord(
        patient_id="CASE-TEST",
        source=source,
        source_record_id="1",
        name=name,
        dose_amount=Decimal("10"),
        dose_unit="mg",
        date_recorded=date(2026, 9, 15),
        normalized_name=normalized or name.lower(),
        raw=raw if code else {"medication_name": name},
    )


def rejection(name, normalized=None):
    """A rejected record with a readable name."""
    return Rejection(
        source="pharmacy",
        name=name,
        normalized_name=normalized,
        reasons=[Reason(field="dose_amount", code="unreadable_dosage", message="not a number")],
    )


@pytest.fixture(autouse=True)
def no_live(monkeypatch):
    """Offline unless a test says otherwise: any real client creation fails the test."""
    monkeypatch.delenv("RXNORM_LIVE", raising=False)
    rxnorm._live_found.clear()
    monkeypatch.setattr(rxnorm, "_live_retry_at", 0.0)

    def unexpected():
        """Fail if the live path opens a client."""
        pytest.fail("the live path was used")

    monkeypatch.setattr(rxnorm, "_live_client", unexpected)


def test_brand_and_coded_generic_reach_one_ingredient():
    """A coded generic and a bare brand name get the same identity, keeping their own names."""
    fhir, pharmacy = rxnorm.refine(
        [
            record("rosuvastatin calcium 20 MG Oral Tablet", code="859751", source="fhir"),
            record("Crestor"),
        ],
        CACHE,
    )
    assert fhir.normalized_name == pharmacy.normalized_name == "rosuvastatin"
    assert (fhir.name, pharmacy.name) == ("rosuvastatin calcium 20 MG Oral Tablet", "Crestor")
    assert (fhir.rxcui, pharmacy.rxcui) == ("859751", "320864")


def test_concept_is_kept_on_the_record_for_the_rules():
    """The dose form and salt travel in raw, beside the original data, not replacing it."""
    (refined,) = rxnorm.refine([record("x", code="859751", source="fhir")], CACHE)
    assert refined.raw["rxnorm"]["dose_form"] == "Oral Tablet"
    assert "medicationCodeableConcept" in refined.raw


def test_code_wins_over_name():
    """The coded RxCUI decides, whatever the display text says."""
    (refined,) = rxnorm.refine([record("Crestor", code="979471", source="fhir")], CACHE)
    assert refined.rxcui == "979471"


def test_name_lookup_ignores_case_and_spacing():
    """The original name is matched lowercased with whitespace collapsed."""
    (refined,) = rxnorm.refine([record("  CRESTOR ", normalized="other")], CACHE)
    assert refined.rxcui == "320864"


def test_alias_based_name_is_the_second_chance():
    """A name with a strength that isn't cached still resolves through its normalized name."""
    (refined,) = rxnorm.refine([record("Crestor 10 mg", normalized="crestor")], CACHE)
    assert refined.rxcui == "320864"


def test_combination_stays_a_different_drug_from_its_parts():
    """Several ingredients join into one key that no single drug can match."""
    (refined,) = rxnorm.refine([record("x", code="979471", source="fhir")], CACHE)
    assert refined.normalized_name == "hydrochlorothiazide / losartan"


def test_unresolved_item_keeps_its_alias_identity():
    """Unknown names and cached negatives come back unchanged."""
    unknown, negative = record("Mystery"), record("known nothing")
    assert rxnorm.refine([unknown, negative], CACHE) == [unknown, negative]


def test_rejection_gets_the_ingredient_identity_only():
    """A rejected brand still matches its generic; Rejection has no rxcui to set."""
    (refined,) = rxnorm.refine([rejection("Crestor", "crestor")], CACHE)
    assert refined.normalized_name == "rosuvastatin" and refined.name == "Crestor"


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("{not json", "not valid JSON"),
        ("[]", "needs _meta, rxcuis and names"),
        ('{"_meta": {}, "rxcuis": {"1": {"ingredients": []}}, "names": {}}', "no ingredients"),
        ('{"_meta": {}, "rxcuis": {}, "names": {"a": "1"}}', "unknown 1"),
    ],
    ids=["json", "shape", "no-ingredients", "dangling-name"],
)
def test_bad_cache_is_refused_with_a_reason(tmp_path, content, reason):
    """Every malformed cache raises a readable error naming the problem."""
    path = tmp_path / "cache.json"
    path.write_text(content)
    with pytest.raises(rxnorm.RxNormCacheError, match=reason):
        rxnorm.load_cache(path)


@pytest.mark.parametrize(
    ("concept", "names", "reason"),
    [
        ({"rxcui": "1", "ingredients": "abc"}, {}, "no ingredients"),
        ({"rxcui": "1", "ingredients": [""]}, {}, "no ingredients"),
        ({"ingredients": ["a"]}, {}, "different rxcui"),
        ({"rxcui": "2", "ingredients": ["a"]}, {}, "different rxcui"),
        ({"rxcui": "1", "ingredients": ["a"]}, {"a": ["1"]}, "points at unknown"),
    ],
    ids=["string", "blank", "no-rxcui", "wrong-rxcui", "list-name"],
)
def test_malformed_concept_is_refused_at_load_not_at_request_time(tmp_path, concept, names, reason):
    """Whatever would fail later during a reconciliation fails at startup instead."""
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"_meta": {}, "rxcuis": {"1": concept}, "names": names}))
    with pytest.raises(rxnorm.RxNormCacheError, match=reason):
        rxnorm.load_cache(path)


def test_non_utf8_cache_is_refused_with_a_reason(tmp_path):
    """Bad bytes are the same readable error, not a UnicodeDecodeError."""
    path = tmp_path / "cache.json"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(rxnorm.RxNormCacheError, match="not UTF-8"):
        rxnorm.load_cache(path)


def test_identity_is_lowercase():
    """RxNorm's own casing (vitamin B12) must not split a drug from a lowercase name."""
    concept = {"rxcui": "1", "ingredients": ["vitamin B12"]}
    cache = {"_meta": {}, "rxcuis": {"1": concept}, "names": {"b12": "1"}}
    (refined,) = rxnorm.refine([record("B12")], cache)
    assert refined.normalized_name == "vitamin b12"


def test_missing_cache_names_the_path(tmp_path):
    """A missing file is named in the error."""
    with pytest.raises(rxnorm.RxNormCacheError, match="nope.json"):
        rxnorm.load_cache(tmp_path / "nope.json")


@pytest.mark.parametrize(
    ("name", "drug"),
    [
        ("Metoprolol Tartrate 25 mg", "metoprolol tartrate"),
        ("Metoprolol Tartrate 25 mg tab", "metoprolol tartrate"),
        ("metformin hydrochloride 1000 MG Oral Tablet", "metformin hydrochloride"),
        ("Metformin ER", "metformin"),
        ("24 HR metoprolol succinate 100 MG Extended Release Oral Tablet", "metoprolol succinate"),
        ("atorvastatin 20 MG Oral Tablet [Lipitor]", "atorvastatin"),
    ],
)
def test_drug_name_drops_strength_brand_tag_and_product_words(name, drug):
    """What's left of free text is the drug, salt included."""
    assert rxnorm._drug_name(name) == drug


SALTED = {
    "rxcui": "203191",
    "tty": "PIN",
    "name": "metoprolol tartrate",
    "status": "Active",
    "ingredients": ["metoprolol"],
    "dose_form": None,
    "salt": "metoprolol tartrate",
}
PLAIN = {**SALTED, "rxcui": "6918", "tty": "IN", "name": "metoprolol", "salt": None}
FORMS = {
    "_meta": {},
    "rxcuis": {
        "203191": SALTED,
        "6918": PLAIN,
        "860975": {**PLAIN, "rxcui": "860975", "dose_form": "Extended Release Oral Tablet"},
        "861007": {**PLAIN, "rxcui": "861007", "dose_form": "Oral Tablet"},
    },
    "names": {"metoprolol tartrate": "203191", "metoprolol": "6918"},
}


def test_salt_survives_a_strength_in_the_name_even_when_aliases_drop_it():
    """The alias says plain metoprolol, but the name's own salt decides first."""
    (refined,) = rxnorm.refine(
        [record("Metoprolol Tartrate 25 mg", normalized="metoprolol")], FORMS
    )
    assert refined.raw["rxnorm"]["salt"] == "metoprolol tartrate"
    assert refined.normalized_name == "metoprolol"


@pytest.mark.parametrize(
    ("name", "form"),
    [
        ("metoprolol 25 MG Oral Tablet", "Oral Tablet"),
        ("metoprolol 25 MG Extended Release Oral Tablet", "Extended Release Oral Tablet"),
        ("Metoprolol ER", "Extended Release"),
        ("metoprolol xr 25 mg", "Extended Release"),
        ("Metoprolol", None),
        ("Metoprolol 25 mg tablet", None),
    ],
)
def test_form_is_read_from_the_name_when_the_concept_has_none(name, form):
    """A stated form is kept, and a name that states none stays unknown."""
    (refined,) = rxnorm.refine([record(name, normalized="metoprolol")], FORMS)
    assert refined.raw["rxnorm"]["dose_form"] == form


def test_form_in_the_name_does_not_replace_the_concepts_own():
    """A coded product's RxNorm form wins over whatever the display says."""
    (refined,) = rxnorm.refine(
        [record("metoprolol Oral Tablet", code="860975", source="fhir")], FORMS
    )
    assert refined.raw["rxnorm"]["dose_form"] == "Extended Release Oral Tablet"


def test_stated_form_does_not_leak_into_the_shared_cache():
    """One record's stated form must not change the concept the next record gets."""
    rxnorm.refine([record("Metoprolol ER")], FORMS)
    assert FORMS["rxcuis"]["6918"]["dose_form"] is None


def test_source_code_is_saved_even_when_the_concept_comes_from_the_name():
    """An uncached code stays the record's rxcui, so a saved row never contradicts its source."""
    (refined,) = rxnorm.refine([record("Crestor", code="9999999", source="fhir")], CACHE)
    assert refined.rxcui == "9999999" and refined.normalized_name == "rosuvastatin"
    assert refined.raw["rxnorm"]["rxcui"] == "320864"


@pytest.mark.parametrize(
    "coding",
    [
        {"system": "http://snomed.info/sct", "code": "320864"},
        {"system": RXNORM, "code": "not-a-code"},
        {"system": RXNORM, "code": "1\n2"},
        {"system": RXNORM},
    ],
    ids=["other-system", "not-digits", "newline", "no-code"],
)
def test_only_a_numeric_rxnorm_code_counts(coding):
    """Another terminology's code, or a malformed one, is never taken as an RxCUI."""
    raw = {"medicationCodeableConcept": {"coding": [coding]}}
    assert rxnorm._coded_rxcui(raw) is None


def _rxnav(handler):
    """Have the live path talk to a MockTransport."""
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return lambda: client


def _history(tty, name, ingredients=(), status="Active", dose_form=None, boss=None):
    """A historystatus.json response body."""
    features = {}
    if dose_form:
        features["doseFormConcept"] = [{"doseFormName": dose_form}]
    if boss:
        features["ingredientAndStrength"] = [{"bossName": boss}]
    return {
        "rxcuiStatusHistory": {
            "metaData": {"status": status},
            "attributes": {"tty": tty, "name": name},
            "derivedConcepts": {"ingredientConcept": [{"ingredientName": i} for i in ingredients]},
            "definitionalFeatures": features,
        }
    }


def test_live_answers_a_cache_miss_only_with_the_flag(monkeypatch):
    """RXNORM_LIVE=1 asks RxNav once for an unknown name, and remembers the answer."""
    calls = []

    def handler(request):
        """Answer a name search, then its concept."""
        calls.append(request.url.path)
        if request.url.path.endswith("/rxcui.json"):
            return httpx.Response(200, json={"idGroup": {"rxnormId": ["5640"]}})
        return httpx.Response(200, json=_history("IN", "ibuprofen"))

    monkeypatch.setattr(rxnorm, "_live_client", _rxnav(handler))
    monkeypatch.setenv("RXNORM_LIVE", "1")
    first, second = rxnorm.refine([record("Ibuprofen"), record("Ibuprofen")], CACHE)
    assert first.normalized_name == second.normalized_name == "ibuprofen"
    assert len(calls) == 2


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectTimeout("too slow"),
        httpx.ConnectError("no route"),
    ],
    ids=["timeout", "unreachable"],
)
def test_live_network_failure_falls_back_to_the_alias_identity(monkeypatch, failure):
    """A network problem leaves the record as it was, and isn't remembered as a no-match."""

    def handler(request):
        """Fail the request."""
        raise failure

    monkeypatch.setattr(rxnorm, "_live_client", _rxnav(handler))
    monkeypatch.setenv("RXNORM_LIVE", "1")
    item = record("Ibuprofen")
    assert rxnorm.refine([item], CACHE) == [item]
    assert rxnorm._live_found == {}


def test_live_http_error_falls_back(monkeypatch):
    """A server error from RxNav is also just unresolved."""
    monkeypatch.setattr(rxnorm, "_live_client", _rxnav(lambda r: httpx.Response(500)))
    monkeypatch.setenv("RXNORM_LIVE", "1")
    item = record("Ibuprofen")
    assert rxnorm.refine([item], CACHE) == [item]


@pytest.mark.parametrize("value", ["0", "true", "yes", ""])
def test_only_the_value_1_enables_live(monkeypatch, value):
    """Anything else stays offline; the autouse fixture fails the test if a client opens."""
    monkeypatch.setenv("RXNORM_LIVE", value)
    item = record("Ibuprofen")
    assert rxnorm.refine([item], CACHE) == [item]


def test_live_uses_the_drug_name_when_the_name_as_given_finds_nothing(monkeypatch):
    """ "Tylenol 500 mg" isn't an RxNorm name, but "tylenol" is."""
    asked = []

    def handler(request):
        """Only the bare brand exists."""
        if request.url.path.endswith("/rxcui.json"):
            asked.append(request.url.params["name"])
            ids = ["202433"] if request.url.params["name"] == "tylenol" else []
            return httpx.Response(200, json={"idGroup": {"rxnormId": ids}})
        return httpx.Response(200, json=_history("BN", "Tylenol", ["acetaminophen"]))

    monkeypatch.setattr(rxnorm, "_live_client", _rxnav(handler))
    monkeypatch.setenv("RXNORM_LIVE", "1")
    (refined,) = rxnorm.refine([record("Tylenol 500 mg")], CACHE)
    assert refined.normalized_name == "acetaminophen"
    assert asked == ["tylenol 500 mg", "tylenol"]


def test_live_tries_the_name_when_a_code_gives_no_concept(monkeypatch):
    """A remapped code lists no ingredient, so the record's name gets its chance."""

    def handler(request):
        """The code is empty; the name resolves."""
        if request.url.path.endswith("/rxcui.json"):
            return httpx.Response(200, json={"idGroup": {"rxnormId": ["5640"]}})
        if "/105048/" in request.url.path:
            return httpx.Response(200, json=_history("SCD", "old"))
        return httpx.Response(200, json=_history("IN", "ibuprofen"))

    monkeypatch.setattr(rxnorm, "_live_client", _rxnav(handler))
    monkeypatch.setenv("RXNORM_LIVE", "1")
    (refined,) = rxnorm.refine([record("Ibuprofen", code="105048", source="fhir")], CACHE)
    assert refined.normalized_name == "ibuprofen" and refined.rxcui == "105048"


@pytest.mark.parametrize(
    "body",
    [
        [],
        "text",
        {"rxcuiStatusHistory": []},
        {"idGroup": []},
    ],
    ids=["list", "string", "history-list", "idgroup-list"],
)
def test_unexpected_rxnav_body_falls_back_instead_of_crashing(monkeypatch, body):
    """A 200 in an odd shape is unresolved; it must never fail the reconciliation."""
    monkeypatch.setattr(rxnorm, "_live_client", _rxnav(lambda r: httpx.Response(200, json=body)))
    monkeypatch.setenv("RXNORM_LIVE", "1")
    item = record("Ibuprofen", code="5640", source="fhir")
    assert rxnorm.refine([item], CACHE) == [item]


def test_dead_rxnav_costs_one_attempt_for_many_records(monkeypatch):
    """After a failure, later records skip the network, so a page doesn't wait 3 seconds each."""
    attempts = []

    def handler(request):
        """Fail every request."""
        attempts.append(request.url)
        raise httpx.ConnectTimeout("too slow")

    monkeypatch.setattr(
        rxnorm,
        "_live_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setenv("RXNORM_LIVE", "1")
    items = [record(name) for name in ("Ibuprofen", "Naproxen", "Aspirin", "Digoxin")]
    assert rxnorm.refine(items, CACHE) == items
    assert len(attempts) == 1


def test_live_is_tried_again_after_the_cooldown(monkeypatch):
    """RxNav coming back is noticed once the pause ends."""
    now = [1000.0]
    monkeypatch.setattr(rxnorm.time, "monotonic", lambda: now[0])
    healthy = [False]

    def handler(request):
        """Fail until healthy, then resolve."""
        if not healthy[0]:
            raise httpx.ConnectError("no route")
        if request.url.path.endswith("/rxcui.json"):
            return httpx.Response(200, json={"idGroup": {"rxnormId": ["5640"]}})
        return httpx.Response(200, json=_history("IN", "ibuprofen"))

    monkeypatch.setattr(
        rxnorm,
        "_live_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setenv("RXNORM_LIVE", "1")
    item = record("Ibuprofen")
    assert rxnorm.refine([item], CACHE) == [item]
    healthy[0] = True
    assert rxnorm.refine([item], CACHE) == [item]  # still pausing
    now[0] += rxnorm.LIVE_COOLDOWN + 1
    (refined,) = rxnorm.refine([item], CACHE)
    assert refined.normalized_name == "ibuprofen"


def test_live_client_is_bounded_to_three_seconds():
    """The real live client has a short timeout, so RxNav can't hold up a reconciliation."""
    with REAL_LIVE_CLIENT() as client:
        assert client.timeout == httpx.Timeout(3.0)


def test_ambiguous_name_is_not_guessed():
    """Several matches return nothing, rather than picking one."""
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"idGroup": {"rxnormId": ["1", "2"]}})
        )
    )
    assert rxnorm.lookup(client, "metformin") is None


def _describe(body):
    """Run describe against a canned response."""
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    return rxnorm.describe(client, "1")


def test_ingredient_is_its_own_ingredient():
    """An IN lists no ingredient concept, because it is one."""
    assert _describe(_history("IN", "acetaminophen"))["ingredients"] == ["acetaminophen"]


def test_obsolete_concept_keeps_its_ingredient_and_status():
    """Dropping an obsolete code would turn a real match into a false missing finding."""
    concept = _describe(_history("SBD", "verapamil [Calan]", ["verapamil"], status="Obsolete"))
    assert concept["ingredients"] == ["verapamil"] and concept["status"] == "Obsolete"


def test_concept_with_no_ingredient_is_none():
    """Nothing to match on means unresolved."""
    assert _describe(_history("SCDF", "something")) is None


@pytest.mark.parametrize(
    ("body", "salt"),
    [
        (_history("PIN", "Metoprolol Succinate", ["metoprolol"]), "metoprolol succinate"),
        (_history("SCD", "x", ["metoprolol"], boss="metoprolol tartrate"), "metoprolol tartrate"),
        (_history("SCD", "rosuvastatin calcium", ["rosuvastatin"], boss="rosuvastatin"), None),
        (_history("SBD", "x", ["losartan", "hctz"], boss="losartan potassium"), None),
        (_history("BN", "Crestor", ["rosuvastatin"]), None),
        (_history("SCD", "x", ["alendronate"], boss="alendronic acid"), None),
        (_history("PIN", "alendronic acid", ["alendronate"]), None),
        (_history("IN", "metoprolol"), None),
    ],
    ids=[
        "pin",
        "scd-with-salt",
        "basis-is-ingredient",
        "combination",
        "brand",
        "free-acid-scd",
        "free-acid-pin",
        "ingredient",
    ],
)
def test_salt_is_only_known_when_a_concept_states_one(body, salt):
    """A strength basis equal to the ingredient says nothing, as for rosuvastatin calcium."""
    assert _describe(body)["salt"] == salt


def _builder_transport(request):
    """A small RxNav: one version, one name, one coded concept and one unknown name."""
    path = request.url.path
    if path.endswith("version.json"):
        return httpx.Response(200, json={"version": "05-Oct-2026", "apiVersion": "3.1.356"})
    if path.endswith("/rxcui.json"):
        ids = ["320864"] if request.url.params["name"] == "crestor" else []
        return httpx.Response(200, json={"idGroup": {"rxnormId": ids}})
    if "320864" in path:
        return httpx.Response(200, json=_history("BN", "Crestor", ["rosuvastatin"]))
    return httpx.Response(200, json=_history("IN", "lisinopril"))


def _build(names, manual=None):
    """Run the cache build against the small RxNav, without pausing."""
    client = httpx.Client(transport=httpx.MockTransport(_builder_transport))
    return builder.build(
        client,
        {"29046": "Lisinopril Oral Tablet"},
        names,
        built="2026-11-01",
        manual=manual or {},
        pause=lambda seconds: None,
    )


def test_committed_cache_covers_every_code_and_name_in_the_data():
    """No committed FHIR code, pharmacy, intake or alias name is left to fall back on aliases."""
    cache = rxnorm.load_cache(rxnorm.DEFAULT_CACHE)
    codes, names = builder.collect_inputs()
    assert len(codes) == 39
    assert not [code for code in codes if code not in cache["rxcuis"]]
    assert not [name for name in names if not cache["names"].get(rxnorm._key(name))]
    assert cache["_meta"]["rxnorm_version"]


def test_collect_inputs_includes_alias_keys_values_and_the_demo_bundle():
    """Every alias, on both sides, and the live demo patient's codes are in the build's input."""
    aliases = json.loads((rxnorm.DEFAULT_CACHE.parent / "aliases.json").read_text())["aliases"]
    codes, names = builder.collect_inputs()
    assert set(aliases) | set(aliases.values()) <= names
    assert {"314076", "617310"} <= set(codes)


def test_committed_cache_resolves_offline(monkeypatch):
    """With no network at all and no live flag, brand, salt and generic meet from the file alone."""

    def no_network(*args, **kwargs):
        """Fail if anything tries to open an HTTP client."""
        pytest.fail("tried to use the network")

    monkeypatch.setattr(httpx, "Client", no_network)
    fhir, salt, brand = rxnorm.refine(
        [
            record(
                "rosuvastatin calcium 10 MG Oral Tablet [Crestor]", code="859747", source="fhir"
            ),
            record("Rosuvastatin Calcium"),
            record("Crestor"),
        ]
    )
    assert fhir.normalized_name == salt.normalized_name == brand.normalized_name == "rosuvastatin"
    assert all(item.rxcui for item in (fhir, salt, brand))


def test_committed_cache_keeps_the_obsolete_verapamil_code():
    """FHIR's obsolete Calan code still meets the pharmacy's plain salt name."""
    fhir, pharmacy = rxnorm.refine(
        [
            record(
                "verapamil hydrochloride 80 MG Oral Tablet [Calan]", code="897685", source="fhir"
            ),
            record("Verapamil Hydrochloride"),
        ]
    )
    assert fhir.normalized_name == pharmacy.normalized_name == "verapamil"
    assert fhir.raw["rxnorm"]["status"] == "Obsolete"


def test_build_maps_names_and_displays_to_concepts():
    """Both a looked-up name and a FHIR display resolve; the release is recorded."""
    cache = _build({"Crestor"})
    assert cache["names"] == {"crestor": "320864", "lisinopril oral tablet": "29046"}
    assert set(cache["rxcuis"]) == {"320864", "29046"}
    assert cache["_meta"]["rxnorm_version"] == "05-Oct-2026"


def test_build_adds_the_salts_and_ingredients_its_concepts_name():
    """A concept's own ingredient becomes findable as a plain name, on a best-effort basis."""

    def transport(request):
        """Crestor names rosuvastatin, which RxNav can also resolve; nothing else exists."""
        if request.url.path.endswith("/rxcui.json"):
            ids = {"crestor": ["320864"], "rosuvastatin": ["301542"]}
            return httpx.Response(
                200, json={"idGroup": {"rxnormId": ids.get(request.url.params["name"], [])}}
            )
        return _builder_transport(request)

    client = httpx.Client(transport=httpx.MockTransport(transport))
    cache = builder.build(client, {}, {"Crestor"}, "2026-11-01", {}, lambda seconds: None)
    assert cache["names"]["rosuvastatin"] == "301542"


def test_build_refuses_an_unresolved_name():
    """A silent gap would become a false missing finding, so the build stops and names it."""
    with pytest.raises(builder.CacheBuildError, match="'nosuchdrug' is unresolved"):
        _build({"NoSuchDrug"})


def test_manual_map_decides_what_the_lookup_cannot():
    """A hand decision of None is a cached negative instead of a failure."""
    assert _build({"NoSuchDrug"}, {"nosuchdrug": None})["names"]["nosuchdrug"] is None


def test_build_output_is_stable():
    """The same inputs render byte-identically, whatever the order they were resolved in."""
    first, second = _build({"Crestor"}), _build({"crestor"})
    assert builder.render(first) == builder.render(second)
    assert json.loads(builder.render(first)) == first
