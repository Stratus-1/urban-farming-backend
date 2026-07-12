from app.schemas.inspections import InspectionAssessment, InspectionAssessmentResult


def score_assessment(payload: InspectionAssessment) -> InspectionAssessmentResult:
    sunlight = (
        30
        if payload.sunlight_hours >= 6
        else 22
        if payload.sunlight_hours >= 4
        else 10
        if payload.sunlight_hours >= 2
        else 0
    )
    water = {"reliable": 25, "limited": 12, "none": 0}[payload.water_access]
    space = (
        20
        if payload.usable_space_m2 >= 10
        else 15
        if payload.usable_space_m2 >= 5
        else 8
        if payload.usable_space_m2 >= 2
        else 3
    )
    installation_fit = 10 if payload.installation_types else 0
    risk_penalty = min(
        15,
        sum({"low": 2, "medium": 5, "high": 10}[risk.severity] for risk in payload.risks),
    )
    safety = 15 - risk_penalty
    breakdown = {
        "sunlight": sunlight,
        "water": water,
        "usable_space": space,
        "installation_fit": installation_fit,
        "safety": safety,
    }
    total = sum(breakdown.values())
    band = "suitable" if total >= 75 else "conditional" if total >= 55 else "not_suitable"
    return InspectionAssessmentResult(
        **payload.model_dump(),
        suitability_score=total,
        score_breakdown=breakdown,
        suitability_band=band,
    )
