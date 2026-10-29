from app.labels import DISCLAIMER, label_for


def test_known_types_have_labels():
    assert label_for("dosage_mismatch") == "Dosage mismatch"


def test_unknown_type_from_a_newer_release_renders_as_other():
    assert label_for("frequency_mismatch") == "Other (frequency_mismatch)"


def test_disclaimer_never_recommends():
    assert "does not recommend treatment" in DISCLAIMER
