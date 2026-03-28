import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Identity(Base):
    __tablename__ = "identities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    call_sign: Mapped[str | None] = mapped_column(String(60))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sessions: Mapped[list["Session"]] = relationship(back_populates="identity")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    git_remote: Mapped[str | None] = mapped_column(String(500), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    aliases: Mapped[list["ProjectAlias"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    sessions: Mapped[list["Session"]] = relationship(back_populates="project")


class ProjectAlias(Base):
    __tablename__ = "project_aliases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)

    project: Mapped["Project"] = relationship(back_populates="aliases")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    identity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identities.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    parent_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sessions.id"))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    msg_count: Mapped[int] = mapped_column(Integer, default=0)

    identity: Mapped["Identity"] = relationship(back_populates="sessions")
    project: Mapped["Project"] = relationship(back_populates="sessions")
    messages: Mapped[list["Message"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    children: Mapped[list["Session"]] = relationship(back_populates="parent", foreign_keys="Session.parent_session_id")
    parent: Mapped["Session | None"] = relationship(back_populates="children", remote_side="Session.id")

    __table_args__ = (
        UniqueConstraint("identity_id", "file_path", name="uq_session_identity_file"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[str | None] = mapped_column(String(50))
    tool_name: Mapped[str | None] = mapped_column(String(100))
    tool_input_summary: Mapped[str | None] = mapped_column(String(500))
    has_hard_input: Mapped[bool] = mapped_column(Boolean, default=False)
    hard_question: Mapped[str | None] = mapped_column(Text)

    session: Mapped["Session"] = relationship(back_populates="messages")

    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_message_session_seq"),
    )


class SyncOffset(Base):
    __tablename__ = "sync_offsets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    identity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identities.id"), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    offset: Mapped[int] = mapped_column(Integer, default=0)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("identity_id", "file_path", name="uq_sync_identity_file"),
    )
