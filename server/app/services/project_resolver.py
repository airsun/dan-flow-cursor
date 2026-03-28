"""Multi-tier project identity resolution (Design D7)."""

from __future__ import annotations

import re

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Project, ProjectAlias


def _name_from_git_remote(remote: str) -> str:
    m = re.search(r"[/:]([^/]+?)(?:\.git)?$", remote)
    return m.group(1) if m else remote


async def resolve_project(
    git_remote: str | None,
    project_hint: str | None,
    source: str,
    db: AsyncSession,
) -> Project:
    if git_remote:
        result = await db.execute(
            select(Project).where(Project.git_remote == git_remote)
        )
        project = result.scalar_one_or_none()
        if project:
            return project

        name = _name_from_git_remote(git_remote)
        project = Project(canonical_name=name, git_remote=git_remote)
        db.add(project)
        await db.flush()
        return project

    if project_hint:
        result = await db.execute(
            select(Project).where(
                func.lower(Project.canonical_name) == project_hint.lower()
            )
        )
        project = result.scalar_one_or_none()
        if project:
            return project

        result = await db.execute(
            select(ProjectAlias).where(ProjectAlias.source == source)
        )
        aliases = result.scalars().all()
        for alias in aliases:
            if _glob_match(alias.pattern, project_hint):
                proj_result = await db.execute(
                    select(Project).where(Project.id == alias.project_id)
                )
                project = proj_result.scalar_one_or_none()
                if project:
                    return project

    fallback_name = project_hint or "unknown"
    project = Project(canonical_name=fallback_name)
    db.add(project)
    await db.flush()
    return project


def _glob_match(pattern: str, text: str) -> bool:
    regex = re.escape(pattern).replace(r"\*", ".*")
    return bool(re.fullmatch(regex, text, re.IGNORECASE))
