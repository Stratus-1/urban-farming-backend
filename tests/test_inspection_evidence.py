from app.services.inspection_evidence import inspection_evidence_gaps


def test_explicit_not_applicable_with_reason_and_required_capture_is_complete() -> None:
    items = [
        {
            "id": "crop-health",
            "category": "Crop health",
            "item_name": "Crop health",
            "requires_photo": True,
            "result": "na",
            "comment": "No crops planted yet",
        }
    ]
    photos = [{"checklist_item_id": None, "photo_type": "crop_close_up"}]

    assert inspection_evidence_gaps(items, photos) == ([], [])


def test_not_applicable_without_reason_remains_incomplete() -> None:
    items = [
        {
            "id": "crop-health",
            "category": "Crop health",
            "item_name": "Crop health",
            "requires_photo": True,
            "result": "na",
            "comment": "  ",
        }
    ]
    photos = [{"checklist_item_id": None, "photo_type": "crop_close_up"}]

    assert inspection_evidence_gaps(items, photos) == (["Crop health"], [])


def test_optional_extra_does_not_satisfy_required_photo_type() -> None:
    items = [
        {
            "id": "crop-health",
            "category": "Crop health",
            "item_name": "Crop health",
            "requires_photo": True,
            "result": "pass",
        }
    ]
    photos = [{"checklist_item_id": None, "photo_type": "extra"}]

    assert inspection_evidence_gaps(items, photos) == ([], ["Crop health"])
