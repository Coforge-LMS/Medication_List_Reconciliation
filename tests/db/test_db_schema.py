from sqlalchemy import Text, inspect

from db.models import Base


def columns(insp, table):
    return {c["name"]: c for c in insp.get_columns(table)}


def test_seven_tables(db):
    assert set(inspect(db).get_table_names()) == {t.name for t in Base.metadata.sorted_tables}
    assert len(Base.metadata.sorted_tables) == 7


def test_v2_and_intake_columns_are_nullable(db):
    insp = inspect(db)
    nullable = {
        "medication_record": ("rxcui", "normalized_name", "frequency"),
        "patient": ("fhir_base_url", "fhir_patient_id", "fetched_at"),
        "reconciliation_run": ("intake_interview_id",),
        "finding": ("intake_value", "fhir_value", "pharmacy_value"),
    }
    for table, names in nullable.items():
        cols = columns(insp, table)
        assert all(cols[name]["nullable"] for name in names), table


def test_discrepancy_type_is_plain_text_without_check(db):
    insp = inspect(db)
    assert isinstance(columns(insp, "finding")["discrepancy_type"]["type"], Text)
    assert insp.get_check_constraints("finding") == []


def test_unique_keys(db):
    insp = inspect(db)

    def uniques(table):
        return [u["column_names"] for u in insp.get_unique_constraints(table)]

    assert ["identifier"] in uniques("patient")
    assert ["interview_ref"] in uniques("intake_interview")
    assert ["interview_id", "record_id"] in uniques("intake_medication")
