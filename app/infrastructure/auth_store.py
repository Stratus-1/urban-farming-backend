"""User credential and refresh-token storage for AUTH_MODE=native.

Works against the auth schema created by database/cloud_sql/0000_supabase_compatibility.sql.
Inserting into auth.users fires the replayed handle_new_user() trigger where present;
ensure_provisioned() covers databases bootstrapped without it.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.errors import AppError

REFRESH_TOKENS_DDL = """
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.refresh_tokens (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS refresh_tokens_user_id_idx ON auth.refresh_tokens (user_id);
"""


class NativeAuthStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def ensure_schema(self) -> None:
        async with self.engine.begin() as connection:
            for statement in REFRESH_TOKENS_DDL.strip().split(";"):
                if statement.strip():
                    await connection.execute(text(statement))

    async def create_user(
        self,
        *,
        email: str,
        password_hash: str | None,
        user_metadata: dict[str, Any],
        app_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        statement = text(
            """
            INSERT INTO auth.users (
              id, email, encrypted_password, raw_app_meta_data, raw_user_meta_data,
              email_confirmed_at, created_at, updated_at
            ) VALUES (
              :id, :email, :password_hash, :app_metadata, :user_metadata, now(), now(), now()
            )
            RETURNING id, email, raw_user_meta_data, created_at
            """
        )
        try:
            async with self.engine.begin() as connection:
                row = (
                    await connection.execute(
                        statement,
                        {
                            "id": uuid4(),
                            "email": email.lower(),
                            "password_hash": password_hash,
                            "app_metadata": app_metadata or {},
                            "user_metadata": user_metadata,
                        },
                    )
                ).mappings().one()
        except IntegrityError as error:
            raise AppError(
                409, "email_exists", "An account with this email already exists"
            ) from error
        return dict(row)

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        statement = text(
            """
            SELECT id, email, encrypted_password, raw_user_meta_data, created_at
            FROM auth.users WHERE lower(email) = :email
            """
        )
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(statement, {"email": email.lower()})
            ).mappings().first()
        return dict(row) if row else None

    async def get_user_by_id(self, user_id: UUID) -> dict[str, Any] | None:
        statement = text(
            """
            SELECT id, email, encrypted_password, raw_user_meta_data, created_at
            FROM auth.users WHERE id = :user_id
            """
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(statement, {"user_id": user_id})).mappings().first()
        return dict(row) if row else None

    async def set_password(self, user_id: UUID, password_hash: str) -> None:
        statement = text(
            "UPDATE auth.users SET encrypted_password = :password_hash, updated_at = now() "
            "WHERE id = :user_id"
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                statement, {"password_hash": password_hash, "user_id": user_id}
            )

    async def touch_last_sign_in(self, user_id: UUID) -> None:
        statement = text(
            "UPDATE auth.users SET last_sign_in_at = now(), updated_at = now() WHERE id = :user_id"
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement, {"user_id": user_id})

    async def user_roles(self, user_id: UUID) -> list[str]:
        statement = text("SELECT role FROM public.user_roles WHERE user_id = :user_id")
        async with self.engine.connect() as connection:
            rows = (await connection.execute(statement, {"user_id": user_id})).scalars().all()
        return sorted({str(role) for role in rows})

    async def ensure_provisioned(
        self, user_id: UUID, *, full_name: str | None, role: str
    ) -> None:
        """Idempotent counterpart of the handle_new_user() trigger."""
        statements: list[tuple[str, dict[str, Any]]] = [
            (
                "INSERT INTO public.profiles (id, full_name) VALUES (:user_id, :full_name) "
                "ON CONFLICT (id) DO NOTHING",
                {"user_id": user_id, "full_name": full_name},
            ),
            (
                "INSERT INTO public.user_roles (user_id, role) "
                "VALUES (:user_id, CAST(:role AS app_role)) ON CONFLICT DO NOTHING",
                {"user_id": user_id, "role": role},
            ),
            (
                "INSERT INTO public.grower_stats (user_id) VALUES (:user_id) "
                "ON CONFLICT (user_id) DO NOTHING",
                {"user_id": user_id},
            ),
            (
                "INSERT INTO public.user_settings (user_id) VALUES (:user_id) "
                "ON CONFLICT (user_id) DO NOTHING",
                {"user_id": user_id},
            ),
        ]
        async with self.engine.begin() as connection:
            for statement, bound in statements:
                await connection.execute(text(statement), bound)
            if role == "inspector":
                await connection.execute(
                    text(
                        "INSERT INTO public.inspectors (user_id, name) "
                        "VALUES (:user_id, COALESCE(:full_name, 'Inspector')) "
                        "ON CONFLICT (user_id) DO NOTHING"
                    ),
                    {"user_id": user_id, "full_name": full_name},
                )

    async def store_refresh_token(
        self, token_id: UUID, user_id: UUID, expires_at: datetime
    ) -> None:
        statement = text(
            "INSERT INTO auth.refresh_tokens (id, user_id, expires_at) "
            "VALUES (:token_id, :user_id, :expires_at)"
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                statement, {"token_id": token_id, "user_id": user_id, "expires_at": expires_at}
            )

    async def is_refresh_token_active(self, token_id: UUID) -> bool:
        statement = text(
            "SELECT 1 FROM auth.refresh_tokens "
            "WHERE id = :token_id AND revoked_at IS NULL AND expires_at > :now"
        )
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    statement, {"token_id": token_id, "now": datetime.now(UTC)}
                )
            ).first()
        return row is not None

    async def revoke_refresh_token(self, token_id: UUID) -> None:
        statement = text(
            "UPDATE auth.refresh_tokens SET revoked_at = now() "
            "WHERE id = :token_id AND revoked_at IS NULL"
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement, {"token_id": token_id})

    async def revoke_all_refresh_tokens(self, user_id: UUID) -> None:
        statement = text(
            "UPDATE auth.refresh_tokens SET revoked_at = now() "
            "WHERE user_id = :user_id AND revoked_at IS NULL"
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement, {"user_id": user_id})
