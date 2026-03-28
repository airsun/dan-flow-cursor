from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import (
    generate_token, hash_token, get_current_identity, require_admin,
)
from ..database import get_db
from ..models import Identity, SyncOffset
from ..services.callsign import generate_callsign_suggestions

router = APIRouter(prefix="/api", tags=["identities"])


class SetupRequest(BaseModel):
    name: str


class CreateIdentityRequest(BaseModel):
    name: str


class CallSignRequest(BaseModel):
    call_sign: str


@router.get("/setup-status")
async def setup_status(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(func.count(Identity.id)))
    count = result.scalar() or 0
    return {"initialized": count > 0}


@router.post("/setup")
async def setup(req: SetupRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(func.count(Identity.id)))
    if (result.scalar() or 0) > 0:
        raise HTTPException(400, "Already initialized")

    name = req.name.strip()
    if not name:
        raise HTTPException(400, "Name required")

    token = generate_token()
    identity = Identity(
        name=name,
        token_hash=hash_token(token),
        is_admin=True,
        enabled=True,
    )
    db.add(identity)
    await db.commit()
    await db.refresh(identity)

    suggestions = await generate_callsign_suggestions(name)

    return {
        "token": token,
        "identity": {
            "id": str(identity.id),
            "name": identity.name,
            "isAdmin": True,
        },
        "callSignSuggestions": suggestions,
    }


@router.post("/identities")
async def create_identity(
    req: CreateIdentityRequest,
    admin: Identity = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "Name required")

    existing = await db.execute(
        select(Identity).where(func.lower(Identity.name) == name.lower())
    )
    if existing.scalar_one_or_none():
        suggestions = [f"{name}-{i}" for i in range(2, 5)]
        raise HTTPException(409, detail={"message": "Name taken", "suggestions": suggestions})

    token = generate_token()
    identity = Identity(
        name=name,
        token_hash=hash_token(token),
        is_admin=False,
        enabled=True,
    )
    db.add(identity)
    await db.commit()
    await db.refresh(identity)

    suggestions = await generate_callsign_suggestions(name)

    return {
        "token": token,
        "identity": {
            "id": str(identity.id),
            "name": identity.name,
            "isAdmin": False,
        },
        "callSignSuggestions": suggestions,
    }


@router.post("/identities/{identity_id}/callsign")
async def set_callsign(
    identity_id: str,
    req: CallSignRequest,
    current: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Identity).where(Identity.id == identity_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Identity not found")

    if str(target.id) != str(current.id) and not current.is_admin:
        raise HTTPException(403, "Can only set own call sign")

    target.call_sign = req.call_sign[:60]
    await db.commit()
    return {"ok": True}


@router.post("/identities/{identity_id}/disable")
async def disable_identity(
    identity_id: str,
    admin: Identity = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if str(admin.id) == identity_id:
        raise HTTPException(400, "Cannot disable self")

    result = await db.execute(select(Identity).where(Identity.id == identity_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Identity not found")

    target.enabled = False
    await db.commit()
    return {"ok": True}


@router.post("/identities/{identity_id}/enable")
async def enable_identity(
    identity_id: str,
    admin: Identity = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Identity).where(Identity.id == identity_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Identity not found")

    target.enabled = True
    await db.commit()
    return {"ok": True}


@router.get("/identities")
async def list_identities(
    admin: Identity = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Identity).order_by(Identity.created_at))
    identities = result.scalars().all()

    items = []
    for ident in identities:
        sync_result = await db.execute(
            select(func.count(SyncOffset.id), func.max(SyncOffset.synced_at))
            .where(SyncOffset.identity_id == ident.id)
        )
        row = sync_result.one()
        items.append({
            "id": str(ident.id),
            "name": ident.name,
            "callSign": ident.call_sign,
            "isAdmin": ident.is_admin,
            "enabled": ident.enabled,
            "createdAt": ident.created_at.isoformat() if ident.created_at else None,
            "filesTracked": row[0] or 0,
            "lastSyncTime": row[1].isoformat() if row[1] else None,
        })
    return items
