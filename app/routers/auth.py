from fastapi import APIRouter

from app.core.security import CurrentUserDep

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
async def me(user: CurrentUserDep) -> dict:
    return {"id": str(user.id), "email": user.email, "roles": sorted(user.roles)}
