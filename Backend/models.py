import re
from datetime import date as DateValue, time as TimeValue
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

Outcome = Literal["full_refund", "partial_refund", "no_refund", "manual_review"]
IssueCategory = Literal[
    "missing_amenity",
    "misleading_listing",
    "access_failure",
    "cancellation",
    "property_damage",
    "noise",
]


# ---------- AI output contract (Gemini must return exactly this) ----------
class Fact(BaseModel):
    fact: str
    source: str  # e.g. "booking data", "listing", "evidence", "admitted by owner"


class Allegation(BaseModel):
    claim: str
    made_by: Literal["customer", "owner"]


class Unknown(BaseModel):
    question: str
    why_it_matters: str
    critical: bool  # True only if the outcome cannot be decided without the answer


class PolicyRef(BaseModel):
    clause_id: str  # e.g. "P1"
    relevance: str


class AIAnalysis(BaseModel):
    model_config = {"extra": "forbid"}
    issue_categories: list[IssueCategory]
    verified_facts: list[Fact]
    allegations: list[Allegation]
    owner_allegations: list[str] = Field(default_factory=list)
    unknowns: list[Unknown]
    policy_references: list[PolicyRef]
    recommendation: Outcome
    refund_percent: Optional[int] = Field(ge=0, le=100)  # 0-100 for refund outcomes, null for manual_review
    explanation: str = Field(min_length=1)
    confidence: Literal["low", "medium", "high"]
    evidence_gaps: list[str]


# ---------- API request bodies ----------
class BookingIn(BaseModel):
    amount: float = Field(gt=0, allow_inf_nan=False)
    date: str = Field(min_length=10, max_length=10)
    time: str = Field(min_length=5, max_length=8)
    space_type: str = Field(min_length=1, max_length=100)
    cancelled_minutes_before: Optional[int] = Field(default=None, ge=0)

    @field_validator("date")
    @classmethod
    def validate_booking_date(cls, value: str) -> str:
        try:
            parsed = DateValue.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("date must use YYYY-MM-DD format") from exc
        if parsed.isoformat() != value:
            raise ValueError("date must use YYYY-MM-DD format")
        return value

    @field_validator("time")
    @classmethod
    def validate_booking_time(cls, value: str) -> str:
        if not re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", value):
            raise ValueError("time must use HH:MM or HH:MM:SS format")
        try:
            TimeValue.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("time is not valid") from exc
        return value


class CaseCreate(BaseModel):
    model_config = {"extra": "forbid"}
    customer: str = Field(min_length=1, max_length=100)
    booking: BookingIn
    listing_id: str
    complaint: str = Field(min_length=5, max_length=10000)
    owner_response: str = Field(default="", max_length=10000)
    evidence: list[str] = Field(default_factory=list, max_length=50)


class DecisionIn(BaseModel):
    model_config = {"extra": "forbid"}
    action: Literal["approve", "reject", "modify"]
    final_outcome: Optional[Outcome] = None  # required for reject / modify
    final_percent: Optional[int] = Field(default=None, ge=0, le=100)  # validated against policy in route
    admin_notes: str = Field(min_length=1, max_length=5000)
    # Identity comes from the authenticated administrator session. This optional
    # legacy input is ignored by the decision endpoint.
    reviewer: Optional[str] = None

    @model_validator(mode="after")
    def validate_final_outcome(self):
        if self.action == "modify" and self.final_outcome is None:
            raise ValueError("final_outcome is required when modifying a proposal")
        if self.action != "modify" and (self.final_outcome is not None or self.final_percent is not None):
            raise ValueError("final outcome fields are only valid when modifying a proposal")
        if self.action == "modify" and self.final_outcome == "partial_refund" and self.final_percent is None:
            raise ValueError("final_percent is required when modifying to a partial refund")
        if self.action == "modify" and self.final_outcome != "partial_refund" and self.final_percent is not None:
            raise ValueError("final_percent is only valid when modifying to a partial refund")
        return self


class EvidenceVerifyIn(BaseModel):
    model_config = {"extra": "forbid"}
    reference: str = Field(min_length=1, max_length=500)
    evidence_type: Literal["ticket", "photo", "log", "timestamped_record", "audio", "video"]
    claim: str = Field(min_length=1, max_length=2000)
    evidence_timestamp: Optional[str] = Field(default=None, max_length=100)

    @field_validator("evidence_timestamp")
    @classmethod
    def validate_evidence_timestamp(cls, value):
        if value is not None:
            try:
                DateValue.fromisoformat(value[:10])
                from datetime import datetime
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("evidence_timestamp must be an ISO timestamp") from exc
        return value


class CredentialsIn(BaseModel):
    model_config = {"extra": "forbid"}
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=72)


class RegistrationIn(CredentialsIn):
    display_name: str = Field(min_length=1, max_length=100)
