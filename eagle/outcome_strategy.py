from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

MODEL_VERSION = "EAGLE-OUTCOME-V5-20260731"


def _rows(outcomes: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in outcomes if isinstance(row, Mapping)]


def build_feedback_strategy(
    outcomes: Iterable[Mapping[str, Any]], *, work_rights: str
) -> dict[str, Any]:
    """Turn sanitized recruitment outcomes into operational controls.

    This function deliberately works only with derived codes and coarse role bands.
    It must never require email bodies, addresses, names, document numbers or other PII.
    """

    rows = _rows(outcomes)
    counts = Counter(str(row.get("outcome_code") or "R10") for row in rows)
    role_bands = Counter(str(row.get("role_band") or "UNKNOWN") for row in rows)
    flags = Counter(
        str(flag)
        for row in rows
        for flag in (row.get("risk_flags") or [])
        if str(flag).strip()
    )

    state = str(work_rights or "").strip().lower()
    alerts: list[str] = []
    controls: list[str] = []

    if state != "granted" and (counts.get("R01") or counts.get("R02")):
        alerts.append("WORK_RIGHTS_BLOCKER_ACTIVE")
        controls.append(
            "Do not submit an ATS application that asks for current Australian work rights unless the visa is granted or the employer explicitly accepts the pending status."
        )
    if counts.get("R02"):
        alerts.append("SEEK_PASS_DOCUMENT_REPAIR_REQUIRED")
        controls.append(
            "Complete right-to-work verification fields before relying on SEEK verification badges."
        )
    if counts.get("R03"):
        alerts.append("SCREENING_ANSWER_AUDIT_REQUIRED")
        controls.append(
            "Verify date of birth and every age/work-right screening answer before submission."
        )
    if counts.get("R07"):
        alerts.append("INTERVIEW_CONVERSION_GAP")
        controls.append(
            "Treat the CV as having passed at least one screen and focus the next improvement cycle on interview evidence, availability and local-readiness answers."
        )
    if counts.get("R06"):
        alerts.append("HIGH_COMPETITION_CHANNEL")
        controls.append(
            "Reduce dependence on famous resort mass-applications; prioritise direct employer campaigns, regional seasonal intakes and less visible operational roles."
        )
    if role_bands.get("MANAGERIAL_OR_CREDENTIALLED") or flags.get("LEVEL_OVERREACH"):
        alerts.append("LEVEL_OVERREACH")
        controls.append(
            "Cap stretch applications at 5% until Australian supervisory evidence or a directly matching credential exists."
        )

    # Portfolio weights are an application allocation, not a probability forecast.
    portfolio = {
        "light_duty_specified_work_ops": 45,
        "fast_cash_entry_hospitality_or_processing": 35,
        "career_bridge_operations": 15,
        "stretch_managerial_or_specialist": 5,
    }

    return {
        "model_version": MODEL_VERSION,
        "sample_size": len(rows),
        "outcome_counts": dict(sorted(counts.items())),
        "role_band_counts": dict(sorted(role_bands.items())),
        "risk_flag_counts": dict(sorted(flags.items())),
        "alerts": alerts,
        "controls": controls,
        "application_portfolio_percent": portfolio,
        "calibration_status": (
            "OBSERVATIONAL_ONLY"
            if len(rows) < 30
            else "CLUSTER_CALIBRATION_ALLOWED"
        ),
        "minimum_cluster_sample_before_weight_learning": 10,
    }
