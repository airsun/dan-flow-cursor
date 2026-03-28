import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_identity, require_admin
from ..database import get_db
from ..models import Identity, Session, Message, SyncOffset
from ..services.parser import parse_line
from ..services.project_resolver import resolve_project

router = APIRouter(prefix="/sync", tags=["sync"])
logger = logging.getLogger("danflow.sync")


class HandshakeFile(BaseModel):
    path: str
    size: int
    source: str


class HandshakeRequest(BaseModel):
    files: list[HandshakeFile]


class PushRequest(BaseModel):
    file_path: str
    source: str
    project_hint: str | None = None
    git_remote: str | None = None
    parent_path: str | None = None
    offset: int
    data: str


@router.post("/handshake")
async def handshake(
    req: HandshakeRequest,
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
):
    file_paths = [f.path for f in req.files]
    result = await db.execute(
        select(SyncOffset)
        .where(SyncOffset.identity_id == identity.id)
        .where(SyncOffset.file_path.in_(file_paths))
    )
    known = {so.file_path: so.offset for so in result.scalars().all()}

    offsets = {}
    for f in req.files:
        offsets[f.path] = known.get(f.path, 0)

    return {"offsets": offsets}


@router.post("/push")
async def push(
    req: PushRequest,
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
):
    so_result = await db.execute(
        select(SyncOffset)
        .where(SyncOffset.identity_id == identity.id)
        .where(SyncOffset.file_path == req.file_path)
    )
    sync_offset = so_result.scalar_one_or_none()

    expected = sync_offset.offset if sync_offset else 0
    if req.offset != expected:
        raise HTTPException(409, detail={"message": "Offset mismatch", "serverOffset": expected})

    project = await resolve_project(req.git_remote, req.project_hint, req.source, db)

    sess_result = await db.execute(
        select(Session)
        .where(Session.identity_id == identity.id)
        .where(Session.file_path == req.file_path)
    )
    session = sess_result.scalar_one_or_none()

    if not session:
        session = Session(
            identity_id=identity.id,
            project_id=project.id,
            source=req.source,
            file_path=req.file_path,
            msg_count=0,
        )
        db.add(session)
        await db.flush()

    if req.parent_path:
        parent_result = await db.execute(
            select(Session)
            .where(Session.identity_id == identity.id)
            .where(Session.file_path == req.parent_path)
        )
        parent = parent_result.scalar_one_or_none()
        if parent:
            session.parent_session_id = parent.id

    new_msgs = 0
    current_seq = session.msg_count
    for line in req.data.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = parse_line(line, req.source)
            if parsed:
                current_seq += 1
                msg = Message(
                    session_id=session.id,
                    seq=current_seq,
                    role=parsed["role"],
                    content=parsed["text"],
                    timestamp=parsed.get("ts"),
                    tool_name=parsed.get("tool_name"),
                    tool_input_summary=parsed.get("tool_input_summary"),
                    has_hard_input=parsed.get("has_hard_input", False),
                    hard_question=parsed.get("hard_question"),
                )
                db.add(msg)
                new_msgs += 1
        except (json.JSONDecodeError, KeyError):
            continue

    session.msg_count = current_seq
    new_offset = req.offset + len(req.data.encode("utf-8"))

    if sync_offset:
        sync_offset.offset = new_offset
    else:
        sync_offset = SyncOffset(
            identity_id=identity.id,
            file_path=req.file_path,
            offset=new_offset,
        )
        db.add(sync_offset)

    await db.commit()
    logger.info("Push %s: +%d msgs, offset %d→%d", req.file_path, new_msgs, req.offset, new_offset)

    return {"ack_offset": new_offset, "new_messages": new_msgs}


@router.get("/status")
async def sync_status(
    admin: Identity = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(
            SyncOffset.identity_id,
            func.count(SyncOffset.id).label("files"),
            func.sum(SyncOffset.offset).label("bytes"),
            func.max(SyncOffset.synced_at).label("last_sync"),
        ).group_by(SyncOffset.identity_id)
    )
    rows = result.all()

    stats = []
    for row in rows:
        id_result = await db.execute(
            select(Identity.name, Identity.call_sign)
            .where(Identity.id == row.identity_id)
        )
        id_row = id_result.one_or_none()
        stats.append({
            "identityId": str(row.identity_id),
            "name": id_row[0] if id_row else "unknown",
            "callSign": id_row[1] if id_row else None,
            "filesTracked": row.files,
            "totalBytesSynced": row.bytes or 0,
            "lastSyncTime": row.last_sync.isoformat() if row.last_sync else None,
        })

    return stats
