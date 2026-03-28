import hashlib
import secrets

from fastapi import Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .models import Identity


def generate_token() -> str:
    return "df_" + secrets.token_urlsafe(30)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def get_current_identity(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> Identity:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token required")

    token = authorization[7:]
    token_h = hash_token(token)

    result = await db.execute(
        select(Identity).where(Identity.token_hash == token_h)
    )
    identity = result.scalar_one_or_none()

    if identity is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    if not identity.enabled:
        raise HTTPException(status_code=403, detail="Identity disabled")

    return identity


async def require_admin(
    identity: Identity = Depends(get_current_identity),
) -> Identity:
    if not identity.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
    return identity
