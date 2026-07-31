from types import SimpleNamespace

import eagle.jora_final_today100 as final


def test_receptionist_requires_hospitality_context() -> None:
    assert final.strict_industry(
        "Receptionist",
        "Answer phones, enter invoices and support a sheetmetal workshop.",
    ) == "Other/Unverified"
    assert final.strict_industry(
        "Night Security Officer & Receptionist",
        "Maintain safety of a hostel and support hospitality guests overnight.",
    ) == "Tourism/Hospitality"


def test_direct_mining_and_construction_roles_remain_specified() -> None:
    assert final.strict_industry("Drillers Offsider", "Exploration field role") == "Mining"
    assert final.strict_industry("Construction Labourer", "Civil site duties") == "Construction"


def test_hard_gate_terms_cover_whv_blockers() -> None:
    final._install_hard_gates()
    assert "australian citizenship" in final.today100.HARD_MISMATCH_TERMS
    assert "hr license" in final.today100.LICENCE_REQUIRED_TERMS
    assert "driver's license" in final.today100.LICENCE_REQUIRED_TERMS


def test_mining_field_role_uses_general_labour_cv() -> None:
    record = SimpleNamespace(
        opportunity="Drillers Offsider",
        industry="Mining",
        role_family="operations_admin",
    )
    assert final._cv_cluster(record) == "CV_GENERAL_LABOUR"


def test_construction_site_admin_keeps_operations_cv() -> None:
    record = SimpleNamespace(
        opportunity="Construction Site Administrator",
        industry="Construction",
        role_family="operations_admin",
    )
    assert final._cv_cluster(record) == "CV_OPERATIONS_ADMIN"
