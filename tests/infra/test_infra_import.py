import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# infra/ is not a package, so load the script by path.
_spec = importlib.util.spec_from_file_location("import_fhir", REPO / "infra" / "import_fhir.py")
import_fhir = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(import_fhir)


def test_ordered_bundles_loads_hospital_practitioner_patients_then_cases(tmp_path):
    names = [
        "synthea/Zed_Last_1.json",
        "synthea/practitionerInformation123.json",
        "synthea/Abe_First_2.json",
        "synthea/hospitalInformation123.json",
        "synthea/notes.txt",
        "cases/medrec-cases.json",
    ]
    for name in names:
        (tmp_path / name).parent.mkdir(exist_ok=True)
        (tmp_path / name).write_text("{}")

    got = [str(p.relative_to(tmp_path)) for p in import_fhir.ordered_bundles(tmp_path)]

    assert got == [
        "synthea/hospitalInformation123.json",
        "synthea/practitionerInformation123.json",
        "synthea/Abe_First_2.json",
        "synthea/Zed_Last_1.json",
        "cases/medrec-cases.json",
    ]


def test_ordered_bundles_empty_dir(tmp_path):
    assert import_fhir.ordered_bundles(tmp_path) == []


def test_committed_data_order():
    got = import_fhir.ordered_bundles(REPO / "data" / "fhir")
    assert len(got) == 13  # 1 hospital + 1 practitioner + 10 patients + 1 case bundle
    assert got[0].name.startswith("hospitalInformation")
    assert got[1].name.startswith("practitionerInformation")
    assert got[-1].name == "medrec-cases.json"
