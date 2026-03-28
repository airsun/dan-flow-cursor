from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..auth import get_current_identity
from ..database import get_db
from ..models import Identity, Session, Message, Project
from ..services.state_engine import compute_session_state

router = APIRouter(prefix="/api", tags=["sessions"])


@router.get("/sessions")
async def list_sessions(
    identity_filter: str | None = Query(None, alias="identity"),
    current: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Session)
        .where(Session.parent_session_id.is_(None))
        .options(
            selectinload(Session.identity),
            selectinload(Session.project),
            selectinload(Session.children).selectinload(Session.identity),
        )
    )

    if identity_filter:
        query = query.join(Session.identity).where(
            func.lower(Identity.name) == identity_filter.lower()
        )

    result = await db.execute(query)
    sessions = result.scalars().unique().all()

    items = []
    for sess in sessions:
        msgs = await _get_messages_summary(sess.id, db)
        state_info = compute_session_state(msgs, sess.last_updated)

        children_items = []
        for child in sess.children:
            child_msgs = await _get_messages_summary(child.id, db)
            child_state = compute_session_state(child_msgs, child.last_updated)
            children_items.append({
                "id": str(child.id),
                "key": child.file_path,
                "source": child.source,
                "state": child_state["state"],
                "snippet": child_state["snippet"],
                "inputType": child_state["inputType"],
                "msgCount": child.msg_count,
                "ageSec": _age_sec(child.last_updated),
                "turns": sum(1 for m in child_msgs if m.get("role") == "user"),
                "lastModified": child.last_updated.timestamp() if child.last_updated else 0,
            })

        active = _age_sec(sess.last_updated) < 600

        items.append({
            "id": str(sess.id),
            "key": sess.file_path,
            "source": sess.source,
            "project": sess.project.canonical_name if sess.project else "unknown",
            "turns": sum(1 for m in msgs if m.get("role") == "user"),
            "msgCount": sess.msg_count,
            "active": active,
            "lastModified": sess.last_updated.timestamp() if sess.last_updated else 0,
            "ageSec": _age_sec(sess.last_updated),
            "state": state_info["state"],
            "snippet": state_info["snippet"],
            "phase": state_info["phase"],
            "inputType": state_info["inputType"],
            "identity": {
                "name": sess.identity.name,
                "callSign": sess.identity.call_sign,
            } if sess.identity else None,
            "children": sorted(children_items, key=lambda x: -x["lastModified"]),
            "subCount": len(children_items),
        })

    items.sort(key=lambda x: (not x["active"], -x["lastModified"]))
    return items


@router.get("/session/{session_id}")
async def get_session(
    session_id: str,
    current: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Session)
        .where(Session.id == session_id)
        .options(selectinload(Session.identity), selectinload(Session.project))
    )
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(404, "Session not found")

    msg_result = await db.execute(
        select(Message)
        .where(Message.session_id == sess.id)
        .order_by(Message.seq)
    )
    messages = msg_result.scalars().all()

    return {
        "id": str(sess.id),
        "source": sess.source,
        "project": sess.project.canonical_name if sess.project else "unknown",
        "identity": {
            "name": sess.identity.name,
            "callSign": sess.identity.call_sign,
        } if sess.identity else None,
        "messages": [
            {
                "role": m.role,
                "text": m.content,
                "ts": m.timestamp,
                "tool_name": m.tool_name,
                "has_hard_input": m.has_hard_input,
                "hard_question": m.hard_question,
            }
            for m in messages
        ],
    }


@router.get("/projects")
async def list_projects(
    current: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).options(selectinload(Project.sessions).selectinload(Session.identity))
    )
    projects = result.scalars().unique().all()

    items = []
    for proj in projects:
        if not proj.sessions:
            continue

        identity_map: dict[str, dict] = {}
        active_count = 0
        last_activity = 0.0

        for sess in proj.sessions:
            if sess.parent_session_id:
                continue
            ts = sess.last_updated.timestamp() if sess.last_updated else 0
            if ts > last_activity:
                last_activity = ts
            if _age_sec(sess.last_updated) < 600:
                active_count += 1
            if sess.identity:
                iname = sess.identity.name
                if iname not in identity_map:
                    identity_map[iname] = {
                        "name": iname,
                        "callSign": sess.identity.call_sign,
                        "sessions": 0,
                    }
                identity_map[iname]["sessions"] += 1

        main_count = sum(1 for s in proj.sessions if not s.parent_session_id)
        items.append({
            "name": proj.canonical_name,
            "gitRemote": proj.git_remote,
            "sessionCount": main_count,
            "activeCount": active_count,
            "lastActivity": last_activity,
            "identities": list(identity_map.values()),
        })

    items.sort(key=lambda x: -x["lastActivity"])
    return items


@router.post("/dismiss/{session_key:path}")
async def dismiss_session(
    session_key: str,
    current: Identity = Depends(get_current_identity),
):
    return {"ok": True}


async def _get_messages_summary(session_id, db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Message.role, Message.content, Message.has_hard_input)
        .where(Message.session_id == session_id)
        .order_by(Message.seq)
    )
    return [{"role": r[0], "text": r[1], "has_hard_input": r[2]} for r in result.all()]


def _age_sec(dt) -> int:
    if dt is None:
        return 999999
    import time
    return int(time.time() - dt.timestamp())
