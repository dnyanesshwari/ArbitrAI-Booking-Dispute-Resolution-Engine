import hashlib
import json
import logging
import os
import time
from functools import wraps
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import ai
import guardrails
import storage
import auth
from ai import ProviderFailure
from models import CaseCreate, CredentialsIn, DecisionIn, EvidenceVerifyIn, RegistrationIn

logger = logging.getLogger("disputes.api")
app = FastAPI(title="AI Booking Dispute & Resolution Engine")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, exc: RequestValidationError):
    # Excluding raw inputs avoids reflecting sensitive values and non-finite
    # floats (which are not valid JSON) in validation responses.
    detail = [{key: error[key] for key in ("loc", "msg", "type") if key in error}
              for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": detail})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _serialized_write(endpoint):
    @wraps(endpoint)
    def wrapped(*args, **kwargs):
        with storage.write_lock():
            return endpoint(*args, **kwargs)
    return wrapped


def _fingerprint(case: dict) -> str:
    relevant = {key: case.get(key) for key in ("owner_id", "customer", "booking", "listing_id", "complaint", "owner_response", "evidence")}
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(auth.SESSION_COOKIE, token, max_age=auth.SESSION_HOURS * 3600,
                        httponly=True, secure=os.getenv("ARBITRAI_COOKIE_SECURE", "0").lower() in {"1", "true", "yes"},
                        samesite="lax", path="/")


@app.post("/api/auth/register", status_code=201)
def register(body: RegistrationIn, response: Response):
    try:
        user = auth.create_user(body.email, body.password, body.display_name, role="customer")
    except ValueError as exc:
        raise HTTPException(409 if "already exists" in str(exc) else 422, str(exc)) from exc
    token, _ = auth.start_session(user)
    _set_session_cookie(response, token)
    return {"user": auth.public_user(user)}


@app.post("/api/auth/login")
def login(body: CredentialsIn, response: Response):
    user = auth.authenticate(body.email, body.password)
    if not user:
        raise HTTPException(401, "Email or password is incorrect.")
    token, _ = auth.start_session(user)
    _set_session_cookie(response, token)
    return {"user": auth.public_user(user)}


@app.post("/api/auth/logout")
def logout(response: Response, request: Request, user: dict = Depends(auth.current_user)):
    auth.revoke_session(request.cookies.get(auth.SESSION_COOKIE))
    response.delete_cookie(auth.SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(auth.current_user)):
    return {"user": auth.public_user(user)}


@app.get("/api/listings")
def list_listings(user: dict = Depends(auth.current_user)):
    return storage.load()["listings"]


@app.get("/api/cases")
def list_cases(user: dict = Depends(auth.current_user)):
    data = storage.load()
    rows = []
    for c in data["cases"]:
        if user["role"] == "customer" and c.get("owner_id") != user["id"]:
            continue
        analysis = data["analyses"].get(c["id"])
        listing = storage.get_listing(data, c["listing_id"])
        row = {"id": c["id"], "customer": c["customer"], "amount": c["booking"]["amount"],
                     "space_type": c["booking"]["space_type"], "listing_title": listing["title"] if listing else c["listing_id"],
                     "status": c["status"]}
        if user["role"] == "admin":
            row.update({"issues": analysis["issue_categories"] if analysis else [],
                        "recommendation": analysis["recommendation"] if analysis else None})
        decision = data["decisions"].get(c["id"])
        if decision and decision.get("decision_status") == "finalized":
            row["final_outcome"] = decision.get("final_outcome")
        rows.append(row)
    return rows


@app.get("/api/stats")
def get_stats(user: dict = Depends(auth.require_admin)):
    cases = storage.load()["cases"]
    return {"total_disputes": len(cases), "pending_reviews": sum(c["status"] != "Finalized" for c in cases),
            "resolved_cases": sum(c["status"] == "Finalized" for c in cases),
            "disputed_amount": round(sum(c["booking"]["amount"] for c in cases), 2)}


@app.post("/api/cases", status_code=201)
@_serialized_write
def create_case(body: CaseCreate, user: dict = Depends(auth.current_user)):
    data = storage.load()
    if not storage.get_listing(data, body.listing_id):
        raise HTTPException(400, "Unknown listing_id")
    case = body.model_dump()
    submitted_name = body.customer.strip()
    if user["role"] == "customer":
        case["customer"] = user["display_name"]
    else:
        if not submitted_name:
            raise HTTPException(422, "Customer display name is required")
        case["customer"] = submitted_name
    case["owner_id"] = user["id"]
    fingerprint = _fingerprint(case)
    for existing in data["cases"]:
        if existing.get("fingerprint") == fingerprint or _fingerprint(existing) == fingerprint:
            return {**existing, "duplicate": True}
    next_num = max((int(c["id"].split("-")[1]) for c in data["cases"]), default=1000) + 1
    case.update({"id": f"C-{next_num}", "status": "New", "fingerprint": fingerprint,
                 "created_at": _now(),
                 "audit_history": [{"event": "case_created", "at": _now()}]})
    data["cases"].append(case)
    storage.save(data)
    return case


@app.get("/api/cases/{case_id}")
def get_case(case_id: str, user: dict = Depends(auth.current_user)):
    data = storage.load()
    case = storage.get_case(data, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    if user["role"] == "customer":
        if case.get("owner_id") != user["id"]:
            raise HTTPException(404, "Case not found")
        decision = data["decisions"].get(case_id)
        finalized_decision = decision if decision and decision.get("decision_status") == "finalized" else None
        safe_case = {key: case.get(key) for key in ("id", "customer", "booking", "listing_id", "complaint", "status", "created_at")}
        return {"case": safe_case, "decision": ({"final_outcome": finalized_decision.get("final_outcome"),
                "final_percent": finalized_decision.get("final_percent")} if finalized_decision else None)}
    return {"case": case, "listing": storage.get_listing(data, case["listing_id"]),
            "analysis": data["analyses"].get(case_id), "decision": data["decisions"].get(case_id)}


@app.post("/api/cases/{case_id}/evidence/verify")
@_serialized_write
def verify_evidence(case_id: str, body: EvidenceVerifyIn, user: dict = Depends(auth.require_admin)):
    data = storage.load()
    case = storage.get_case(data, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    if case["status"] == "Finalized":
        raise HTTPException(400, "Case is already finalized")
    if body.reference not in case.get("evidence", []):
        raise HTTPException(400, "Reference is not submitted for this case")
    item = {**body.model_dump(), "verified_by": user["display_name"], "verified_at": _now(), "verification_status": "verified"}
    case.setdefault("verified_evidence", []).append(item)
    case.setdefault("audit_history", []).append({"event": "evidence_verified", "at": item["verified_at"], "reference": body.reference, "reviewer": user["display_name"]})
    storage.save(data)
    return item


@app.post("/api/cases/{case_id}/draft-messages")
@_serialized_write
def draft_messages(case_id: str, user: dict = Depends(auth.require_admin)):
    data = storage.load()
    case = storage.get_case(data, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    decision = data["decisions"].get(case_id)
    if case["status"] != "Finalized" or not decision or decision.get("decision_status") != "finalized":
        raise HTTPException(409, "Draft messages are available after the case is finalized")
    outcome = decision["final_outcome"].replace("_", " ")
    percent = decision.get("final_percent")
    amount = f" at {percent}%" if percent is not None else ""
    refs = ", ".join(ref["clause_id"] for ref in data.get("analyses", {}).get(case_id, {}).get("policy_references", [])) or "the recorded case review"
    return {"customer": f"Hello {case['customer']}, your booking dispute has been reviewed. The final outcome is {outcome}{amount}. The decision was recorded under {refs}. No payment has been processed by this demonstration.",
            "owner": f"Hello, the dispute for booking {case_id} has been reviewed. The final outcome is {outcome}{amount}, based on {refs}. No payment has been processed by this demonstration."}


@app.post("/api/cases/{case_id}/analyze")
def analyze(case_id: str, user: dict = Depends(auth.require_admin)):
    data = storage.load()
    case = storage.get_case(data, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    if case["status"] == "Finalized":
        raise HTTPException(400, "Case is already finalized")
    listing = storage.get_listing(data, case["listing_id"])
    started = time.monotonic()
    try:
        raw = ai.analyze_case(case, listing)
    except ProviderFailure as exc:
        logger.warning("analysis_failed case_id=%s category=%s status=%s request_id=%s duration_ms=%d retry_count=%d",
                       case_id, exc.category, exc.status_code, exc.request_id,
                       int((time.monotonic() - started) * 1000), max(exc.attempts - 1, 0))
        status = 503 if exc.retryable or exc.category == "quota_or_rate_limit" else 502
        raise HTTPException(status, exc.public_message()) from exc
    except Exception as exc:
        logger.exception("analysis_internal_error case_id=%s", case_id)
        raise HTTPException(500, "Analysis failed unexpectedly. Check backend logs using the request ID.") from exc

    result = guardrails.apply_guardrails(raw, case, listing)
    result["generated_at"] = _now()
    with storage.write_lock():
        data = storage.load()
        case = storage.get_case(data, case_id)
        if not case:
            raise HTTPException(404, "Case not found")
        if case["status"] == "Finalized":
            raise HTTPException(400, "Case is already finalized")
        data.setdefault("proposal_history", {})
        if case_id in data["analyses"]:
            data["proposal_history"].setdefault(case_id, []).append(data["analyses"][case_id])
        data["proposal_history"].setdefault(case_id, []).append(result)
        data["analyses"][case_id] = result
        case["status"] = "AI Analyzed"
        case.setdefault("audit_history", []).append({"event": "analysis_completed", "at": _now(), "recommendation": result["recommendation"]})
        storage.save(data)
    return result


@app.post("/api/cases/{case_id}/decision")
@_serialized_write
def decide(case_id: str, body: DecisionIn, user: dict = Depends(auth.require_admin)):
    data = storage.load()
    case = storage.get_case(data, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    analysis = data["analyses"].get(case_id)
    if not analysis:
        raise HTTPException(400, "Run the AI analysis before deciding")
    if case["status"] == "Finalized":
        raise HTTPException(400, "Case is already finalized")
    if not body.admin_notes.strip():
        raise HTTPException(422, "Decision reason is required")
    reviewer_name = user["display_name"]
    if case["status"] == "Manual Review" and body.action == "approve":
        raise HTTPException(409, "This proposal is in manual review. Record a modified final outcome after investigation.")
    if case["status"] == "Manual Review" and body.action == "reject":
        raise HTTPException(409, "This case is already pending manual investigation.")
    if body.action == "reject":
        timestamp = _now()
        pending_review = {
            "action": "reject", "final_outcome": "manual_review", "final_percent": None,
            "admin_notes": body.admin_notes.strip(), "reason": body.admin_notes.strip(),
            "reviewer": reviewer_name, "ai_recommendation": analysis["recommendation"],
            "ai_proposal_snapshot": analysis, "simulated": True, "decided_at": timestamp,
            "decision_status": "pending_manual_review",
        }
        data.setdefault("decision_history", {}).setdefault(case_id, []).append(pending_review)
        data["decisions"][case_id] = pending_review
        case["status"] = "Manual Review"
        case.setdefault("audit_history", []).append({"event": "proposal_rejected_manual_review", "at": timestamp, "reviewer": reviewer_name})
        storage.save(data)
        return pending_review
    if body.action == "approve":
        outcome, percent = analysis["recommendation"], analysis["refund_percent"]
        if outcome == "manual_review":
            raise HTTPException(409, "This proposal requires manual investigation; approve is unavailable. Reject or modify it after review.")
    else:
        if not body.final_outcome:
            raise HTTPException(400, "final_outcome is required for modify")
        else:
            outcome, percent = body.final_outcome, body.final_percent
            if outcome == "full_refund":
                percent = 100
            elif outcome == "no_refund":
                percent = 0
            elif outcome == "manual_review":
                if case["status"] == "Manual Review":
                    raise HTTPException(409, "This case is already pending manual investigation.")
                timestamp = _now()
                pending_review = {
                    "action": "modify", "final_outcome": "manual_review", "final_percent": None,
                    "admin_notes": body.admin_notes.strip(), "reason": body.admin_notes.strip(),
                    "reviewer": reviewer_name, "ai_recommendation": analysis["recommendation"],
                    "ai_proposal_snapshot": analysis, "simulated": True, "decided_at": timestamp,
                    "decision_status": "pending_manual_review",
                }
                data.setdefault("decision_history", {}).setdefault(case_id, []).append(pending_review)
                data["decisions"][case_id] = pending_review
                case["status"] = "Manual Review"
                case.setdefault("audit_history", []).append({"event": "manual_review_requested", "at": timestamp, "reviewer": reviewer_name})
                storage.save(data)
                return pending_review
            elif percent not in {30, 50}:
                raise HTTPException(400, "Partial refund must be 30% or 50% under policy. Other percentages are unsupported.")
    if outcome in {"full_refund", "partial_refund"}:
        policy_ids = guardrails.valid_clause_ids()
        issue_categories = set(analysis.get("issue_categories", []))
        listing = storage.get_listing(data, case["listing_id"])
        verified = guardrails._verified_evidence(case)
        amenities = guardrails._admitted_amenities(case, listing) | guardrails._evidenced_amenities(verified, listing)
        minutes = case.get("booking", {}).get("cancelled_minutes_before")
        p3_percent = guardrails.p3_expected_percent(minutes) if minutes is not None else None
        access_text = f"{case.get('complaint', '')} {case.get('owner_response', '')}".lower()
        p2_facts = "access_failure" in issue_categories and any(term in access_text for term in ("nobody offered", "no equivalent", "not offered", "no alternative", "denied access", "locked", "unavailable", "keycard"))
        p3_facts = "cancellation" in issue_categories and p3_percent is not None
        p1_facts = "missing_amenity" in issue_categories and bool(amenities) and bool(re.search(r"report(?:ed|ing)?|during the booking|front desk|ticket", case.get("complaint", ""), re.I))
        supported = ((outcome == "full_refund" and percent == 100 and (("P2" in policy_ids and p2_facts) or ("P3" in policy_ids and p3_facts and p3_percent == 100)))
                     or (outcome == "partial_refund" and percent in {30, 50} and "P1" in policy_ids and p1_facts and percent == (50 if len(amenities) >= 2 else 30))
                     or (outcome == "partial_refund" and percent == 50 and "P3" in policy_ids and p3_facts and p3_percent == 50))
        if not supported:
            raise HTTPException(400, "The final refund outcome is not supported by this case's cited policy.")
    timestamp = _now()
    decision = {"action": body.action, "final_outcome": outcome, "final_percent": percent,
                "admin_notes": body.admin_notes.strip(), "reason": body.admin_notes.strip(),
                "reviewer": reviewer_name, "ai_recommendation": analysis["recommendation"],
                "ai_proposal_snapshot": analysis, "simulated": True, "decided_at": timestamp, "finalized_at": timestamp,
                "decision_status": "finalized"}
    data.setdefault("decision_history", {}).setdefault(case_id, []).append(decision)
    data["decisions"][case_id] = decision
    case["status"] = "Finalized"
    case.setdefault("audit_history", []).append({"event": "decision_finalized", "at": timestamp, "action": body.action, "reviewer": reviewer_name})
    storage.save(data)
    return decision
