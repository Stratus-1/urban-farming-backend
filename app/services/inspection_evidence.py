from collections.abc import Iterable, Mapping
from typing import Any

PHOTO_TYPES_BY_REQUIRED_CHECK: dict[str, set[str]] = {
    "garden condition": {"full_garden_view"},
    "crop health": {"crop_close_up"},
    "irrigation status": {"irrigation"},
    "pest and disease": {"problem_area"},
}


def inspection_evidence_gaps(
    checklist_items: Iterable[Mapping[str, Any]],
    photos: Iterable[Mapping[str, Any]],
) -> tuple[list[str], list[str]]:
    """Return required checklist results and photos that are still missing."""
    photo_rows = list(photos)
    linked_item_ids = {str(photo.get("checklist_item_id")) for photo in photo_rows}
    photo_types = {str(photo.get("photo_type")) for photo in photo_rows}
    missing_results: list[str] = []
    missing_photos: list[str] = []

    for item in checklist_items:
        if item.get("requires_photo") is not True:
            continue

        label = str(item.get("item_name") or item.get("category") or "Checklist item")
        item_id = item.get("id")
        result = item.get("result")
        comment = str(item.get("comment") or "").strip()
        if result is None or (result == "na" and not comment):
            missing_results.append(label)

        category = str(item.get("category") or "").casefold()
        required_photo_types = PHOTO_TYPES_BY_REQUIRED_CHECK.get(category, set())
        has_linked_photo = item_id is not None and str(item_id) in linked_item_ids
        has_matching_capture = bool(required_photo_types & photo_types)
        if not has_linked_photo and not has_matching_capture:
            missing_photos.append(label)

    return missing_results, missing_photos
