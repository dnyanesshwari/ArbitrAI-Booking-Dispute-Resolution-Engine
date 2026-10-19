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
from fastapi.middleware.cors import CORSMiddleware

import ai
import guardrails
import storage
import auth
from ai import ProviderFailure
from models import CaseCreate, CredentialsIn, DecisionIn, RegistrationIn

logger = logging.getLogger("disputes.api")
app = FastAPI(title="AI Booking Dispute & Resolution Engine")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


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
    case["customer"] = user["display_name"]
    case["owner_id"] = user["id"]
    fingerprint = _fingerprint(case)
    for existing in data["cases"]:
        if existing.get("fingerprint") == fingerprint or _fingerprint(existing) == fingerprint:
            return {**existing, "duplicate": True}
    next_num = max((int(c["id"].split("-")[1]) for c in data["cases"]), default=1000) + 1
    case.update({"id": f"C-{next_num}", "status": "New", "fingerprint": fingerprint,
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
            raise HTTPException(400, "final_outcome is required for reject/modify")
        else:
            outcome, percent = body.final_outcome, body.final_percent
            if outcome == "full_refund":
                percent = 100
            elif outcome == "no_refund":
                percent = 0
            elif outcome == "manual_review":
                percent = None
            elif percent not in {30, 50}:
                raise HTTPException(400, "Partial refund must be 30% or 50% under policy. Other percentages are unsupported.")
    if outcome in {"full_refund", "partial_refund"}:
        issue_categories = set(analysis.get("issue_categories", []))
        cited = {ref.get("clause_id") for ref in analysis.get("policy_references", [])}
        supported = ((outcome == "full_refund" and percent == 100 and (("P2" in cited and "access_failure" in issue_categories) or ("P3" in cited and "cancellation" in issue_categories)))
                     or (outcome == "partial_refund" and percent in {30, 50} and "P1" in cited and "missing_amenity" in issue_categories)
                     or (outcome == "partial_refund" and percent == 50 and "P3" in cited and "cancellation" in issue_categories))
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
