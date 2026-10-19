"""Shared types between modules. Change only with the orchestrator's agreement."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Gender = Literal["female", "male", "unspecified"]
Seniority = Literal["junior", "mid", "senior", "lead"]


class MemberProfile(BaseModel):
    """Public roster facts an attacker (e.g. the manager) is assumed to know."""

    member_id: str
    display_name: str  # e.g. "มิ้น"
    full_name: str = ""  # e.g. "มินตรา ใจดี"
    nicknames: list[str] = []
    role: str = ""  # e.g. "Junior Backend Developer"
    gender: Gender = "unspecified"
    seniority: Seniority = "mid"
    style_samples: list[str] = []  # past messages the manager has seen from this person


class StructuredFeedback(BaseModel):
    situation: str  # สถานการณ์
    impact: str  # ผลกระทบ
    request: str  # สิ่งที่ขอ / ข้อเสนอ


class AttackerGuess(BaseModel):
    round: int
    guessed_member_id: str | None
    confidence: float  # 0..1
    guessed_gender: Gender | None = None
    guessed_seniority: Seniority | None = None
    reason: str = ""
    identified: bool  # True when the guess hits the real author with enough confidence


class PipelineStep(BaseModel):
    """One visible step for the demo trace. Never contains the original text after step 1."""

    step: int  # 1..6
    name: str
    output: str
    notes: list[str] = []


class PipelineResult(BaseModel):
    ok: bool  # False when the attacker still identifies the author after max rounds
    final_text: str = ""  # neutral rewritten text
    structured: StructuredFeedback | None = None
    theme_slug: str = ""  # e.g. "friday-urgent-work"
    theme_label: str = ""  # e.g. "งานด่วนเย็นวันศุกร์"
    attacker_rounds: list[AttackerGuess] = []
    steps: list[PipelineStep] = []
    reason_blocked: str = ""


class MetadataEvent(BaseModel):
    """Normalized SDLC metadata. Identities are hashed at ingest."""

    type: Literal[
        "pr_opened", "pr_review_requested", "pr_reviewed", "pr_merged", "pr_labeled",
        "ticket_status", "ticket_reopened", "task_assigned", "commit", "leave", "sprint_ended",
    ]
    actor_hash: str
    target_hash: str | None = None
    timestamp: datetime
    status: str = ""
    ref: str = ""  # "PR #123", "TICKET-42", "Sprint 14"
    meta: dict = Field(default_factory=dict)


SignalKind = Literal["pr_stale", "ticket_blocked", "friday_urgent", "late_night", "review_concentration", "sprint_end"]


class Signal(BaseModel):
    kind: SignalKind
    affected_hash: str  # the person the agent privately messages
    target_hash: str | None = None  # e.g. the reviewer to nudge
    ref: str = ""
    detected_at: datetime
    evidence: dict = Field(default_factory=dict)
    judge_ok: bool = True
    judge_reason: str = ""
