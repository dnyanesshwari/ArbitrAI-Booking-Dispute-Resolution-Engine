from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator

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
    amount: float = Field(gt=0)
    date: str
    time: str
    space_type: str
    cancelled_minutes_before: Optional[int] = None


class CaseCreate(BaseModel):
    model_config = {"extra": "forbid"}
    customer: str = Field(min_length=1)
    booking: BookingIn
    listing_id: str
    complaint: str = Field(min_length=5)
    owner_response: str = ""
    evidence: list[str] = Field(default_factory=list)


class DecisionIn(BaseModel):
    model_config = {"extra": "forbid"}
    action: Literal["approve", "reject", "modify"]
    final_outcome: Optional[Outcome] = None  # required for reject / modify
    final_percent: Optional[int] = Field(default=None, ge=0, le=100)  # validated against policy in route
    admin_notes: str = Field(min_length=1)
    # Identity comes from the authenticated administrator session. This optional
    # legacy input is ignored by the decision endpoint.
    reviewer: Optional[str] = None

    @model_validator(mode="after")
    def validate_final_outcome(self):
        if self.action == "modify" and self.final_outcome is None:
            raise ValueError("final_outcome is required when modifying a proposal")
        if self.action != "modify" and self.final_percent is not None:
            raise ValueError("final_percent is only valid when modifying a partial refund")
        return self


class CredentialsIn(BaseModel):
    model_config = {"extra": "forbid"}
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=72)


class RegistrationIn(CredentialsIn):
    display_name: str = Field(min_length=1, max_length=100)
