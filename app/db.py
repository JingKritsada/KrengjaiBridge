"""Portable persistence. Feedback deliberately has no relationship to its author."""

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


def uid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def actor_hash(member_id: str, salt: str = "") -> str:
    from app.config import get_settings
    # The public demo salt is only for local fixtures; cloud uses its secret encryption key.
    salt = salt or get_settings().token_enc_key or "kreng-jai-local-demo"
    return hashlib.sha256((salt + member_id).encode()).hexdigest()[:16]


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))


class Member(Base):
    __tablename__ = "members"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(200))
    gender: Mapped[str] = mapped_column(String(20), default="unspecified")
    seniority: Mapped[str] = mapped_column(String(20), default="mid")
    line_user_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    actor_hash: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    opted_in: Mapped[bool] = mapped_column(Boolean, default=True)
    muted_kinds: Mapped[list] = mapped_column(JSON, default=list)

    @property
    def member_id(self):
        return self.id


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    actor_hash: Mapped[str] = mapped_column(String(16), index=True)
    target_hash: Mapped[str | None] = mapped_column(String(16), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(100), default="")
    ref: Mapped[str] = mapped_column(String(200), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class SignalRow(Base):
    __tablename__ = "signals"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    affected_hash: Mapped[str] = mapped_column(String(16))
    target_hash: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ref: Mapped[str] = mapped_column(String(200), default="")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    judge_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    judge_reason: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(30), default="pending")
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True)


class Outreach(Base):
    __tablename__ = "outreach"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), index=True)
    signal_id: Mapped[str | None] = mapped_column(ForeignKey("signals.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(50))
    text: Mapped[str] = mapped_column(Text)
    buttons: Mapped[list] = mapped_column(JSON, default=list)
    channel: Mapped[str] = mapped_column(String(10), default="web")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    response: Mapped[str | None] = mapped_column(String(200), nullable=True)


class FeedbackItem(Base):
    __tablename__ = "feedback_items"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    theme_id: Mapped[str] = mapped_column(ForeignKey("themes.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    structured: Mapped[dict] = mapped_column(JSON)
    attacker_rounds: Mapped[int] = mapped_column(Integer, default=0)


class Theme(Base):
    __tablename__ = "themes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    slug: Mapped[str] = mapped_column(String(100), index=True)
    label: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="open")
    proposal: Mapped[str] = mapped_column(Text, default="")
    manager_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_proposal: Mapped[bool] = mapped_column(Boolean, default=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    followup: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ReplyToken(Base):
    __tablename__ = "reply_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    theme_id: Mapped[str] = mapped_column(ForeignKey("themes.id"), index=True)
    enc_recipient: Mapped[str] = mapped_column(Text)


def make_session_factory(database_url: str):
    url = make_url(database_url)
    options = {}
    if url.get_backend_name() == "sqlite":
        options["connect_args"] = {"check_same_thread": False}
        if not url.database or url.database == ":memory:":
            options["poolclass"] = StaticPool
        else:
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    elif url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    if url.get_backend_name() == "postgresql":
        # Sync DB calls run on the event loop; a blocked lock must fail fast, not freeze every request.
        options["connect_args"] = {"options": "-c lock_timeout=5000 -c statement_timeout=20000"}
    engine = create_engine(url, pool_pre_ping=True, **options)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
