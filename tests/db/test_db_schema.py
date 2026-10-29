from sqlalchemy import Text, inspect


def columns(insp, table):
    return {c["name"]: c for c in insp.get_columns(table)}


def test_v2_columns_are_nullable(db):
    meds = columns(inspect(db), "medication_record")
    assert all(meds[name]["nullable"] for name in ("rxcui", "normalized_name", "frequency"))


def test_discrepancy_type_is_plain_text_without_check(db):
    insp = inspect(db)
    assert isinstance(columns(insp, "finding")["discrepancy_type"]["type"], Text)
    assert insp.get_check_constraints("finding") == []


def test_patient_identifier_is_unique(db):
    uniques = inspect(db).get_unique_constraints("patient")
    assert ["identifier"] in [u["column_names"] for u in uniques]
