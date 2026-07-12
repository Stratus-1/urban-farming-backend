from app.schemas.inspections import InspectionAssessment, InspectionRisk
from app.services.inspection_scoring import score_assessment


def test_score_assessment_is_deterministic_and_explainable():
    result = score_assessment(
        InspectionAssessment(
            sunlight_hours=7,
            water_access="reliable",
            usable_space_m2=12,
            installation_types=["raised_bed"],
            measurements={"length_m": 4, "width_m": 3},
            risks=[InspectionRisk(category="access", severity="medium", notes="Narrow gate")],
            recommended_crops=["Spinach"],
            recommended_infrastructure=["Raised bed"],
        )
    )

    assert result.suitability_score == 95
    assert result.suitability_band == "suitable"
    assert result.score_breakdown == {
        "sunlight": 30,
        "water": 25,
        "usable_space": 20,
        "installation_fit": 10,
        "safety": 10,
    }


def test_score_assessment_flags_weak_site():
    result = score_assessment(
        InspectionAssessment(
            sunlight_hours=1,
            water_access="none",
            usable_space_m2=1,
            installation_types=["container"],
            risks=[InspectionRisk(category="security", severity="high", notes="Unsafe")],
        )
    )

    assert result.suitability_score == 18
    assert result.suitability_band == "not_suitable"
