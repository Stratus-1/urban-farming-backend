from typing import Annotated

import httpx
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app.core.errors import AppError

router = APIRouter(prefix="/geocoding", tags=["geocoding"])


class ReverseGeocodeRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


def normalize_result(item: dict, partial_match: bool = False) -> dict:
    try:
        return {
            "ok": True,
            "source": "openstreetmap",
            "formattedAddress": item["display_name"],
            "lat": float(item["lat"]),
            "lng": float(item["lon"]),
            "placeId": str(item["place_id"]),
            "partialMatch": partial_match,
        }
    except (KeyError, TypeError, ValueError) as error:
        raise AppError(
            502, "invalid_geocoder_response", "The geocoder returned invalid data"
        ) from error


@router.get("/search")
async def search_address(
    request: Request,
    address: Annotated[str, Query(min_length=3, max_length=240)],
    city: Annotated[str | None, Query(max_length=120)] = None,
    country_code: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
) -> dict:
    params = {
        "format": "jsonv2",
        "addressdetails": "1",
        "limit": "3",
        "q": ", ".join(part for part in (address, city) if part),
    }
    if country_code:
        params["countrycodes"] = country_code.lower()
    response = await request.app.state.http.get(
        "https://nominatim.openstreetmap.org/search",
        params=params,
        headers={"User-Agent": request.app.state.settings.geocoding_user_agent},
    )
    if response.status_code in {403, 429}:
        raise AppError(429, "geocoder_rate_limited", "Address lookup is temporarily rate limited")
    try:
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise AppError(502, "geocoder_error", "Address lookup failed") from error
    results = response.json()
    if not results:
        raise AppError(404, "address_not_found", "No matching address was found")
    return normalize_result(results[0])


@router.post("/reverse")
async def reverse_address(payload: ReverseGeocodeRequest, request: Request) -> dict:
    response = await request.app.state.http.get(
        "https://nominatim.openstreetmap.org/reverse",
        params={
            "format": "jsonv2",
            "addressdetails": "1",
            "lat": str(payload.lat),
            "lon": str(payload.lng),
        },
        headers={"User-Agent": request.app.state.settings.geocoding_user_agent},
    )
    if response.status_code == 404:
        raise AppError(404, "address_not_found", "No address was found for these coordinates")
    try:
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise AppError(502, "geocoder_error", "Reverse address lookup failed") from error
    return normalize_result(response.json())
