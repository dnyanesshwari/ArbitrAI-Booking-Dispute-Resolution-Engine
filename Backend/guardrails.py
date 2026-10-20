import re
from datetime import datetime
from pathlib import Path

from models import AIAnalysis

POLICY_PATH = Path(__file__).parent / "policies.md"
STATUS_TEXT = "AI proposal, pending human review"
POLICY_RULES = {
    "P1": "Amenity failure reported during booking, verified by evidence or owner admission: 30% for one amenity, 50% for two or more.",
    "P2": "Denied access to reserved space with no accepted equivalent: 100% refund.",
    "P3": "Customer cancellation: >24h = 100%, 2-24h = 50%, <2h = 0%.",
    "P4": "Owner damage claim requires photos or timestamped evidence; otherwise manual review.",
    "P5": "Noise refund only when listing promises quiet and noise is evidenced; if promised but unevidenced, manual review.",
    "P6": "Outcome-critical disputed fact without evidence: manual review.",
}


def load_policy_text() -> str:
    return POLICY_PATH.read_text(encoding="utf-8-sig")


def valid_clause_ids() -> set[str]:
    ids = set(re.findall(r"^##\s*(P\d+)", load_policy_text(), flags=re.MULTILINE))
    return ids & POLICY_RULES.keys()


def p3_expected_percent(minutes_before: int) -> int:
    if minutes_before > 24 * 60:
        return 100
    if minutes_before >= 2 * 60:
        return 50
    return 0


def policy_references(analysis: dict) -> list[dict]:
    available = valid_clause_ids()
    return [
        {"clause_id": ref["clause_id"], "rule": POLICY_RULES[ref["clause_id"]],
         "relevance": ref.get("relevance", "")}
        for ref in analysis.get("policy_references", [])
        if ref.get("clause_id") in available and ref.get("clause_id") in POLICY_RULES
    ]


def _verified_evidence(case: dict) -> list[dict]:
    """Only an explicit, structured verifier attestation can establish evidence.

    Intake currently stores evidence references only. Those references, filenames,
    and their prose are never treated as inspected or verified artifacts.
    """
    verified = []
    allowed_types = {"ticket", "photo", "log", "timestamped_record", "audio", "video"}
    for item in case.get("verified_evidence", []):
        if not isinstance(item, dict):
            continue
        evidence_type = str(item.get("evidence_type", "")).strip().lower()
        if (item.get("verification_status") != "verified" or not item.get("verified_by")
                or not item.get("verified_at") or not item.get("claim")
                or evidence_type not in allowed_types
                or item.get("reference") not in case.get("evidence", [])):
            continue
        try:
            datetime.fromisoformat(str(item["verified_at"]).replace("Z", "+00:00"))
            if item.get("evidence_timestamp"):
                datetime.fromisoformat(str(item["evidence_timestamp"]).replace("Z", "+00:00"))
        except ValueError:
            continue
        verified.append(item)
    return verified


def _mentions_promise(text: str, promise: str) -> bool:
    ignored = {"with", "and", "the", "for", "up", "to", "high-speed", "listed", "every"}
    terms = [term for term in re.findall(r"[a-z0-9-]+", promise.lower()) if term not in ignored and len(term) > 1]
    return bool(terms and any(re.search(rf"\b{re.escape(term)}\b", text.lower()) for term in terms))


def _evidenced_amenities(evidence: list[dict], listing: dict | None) -> set[str]:
    eligible = {"ticket", "photo", "log", "timestamped_record"}
    failure = re.compile(r"\b(?:fault|fail(?:ed|ure)?|broken|not working|malfunction(?:ed)?)\b", re.I)
    promises = (listing or {}).get("promises", [])
    return {promise for promise in promises if any(
        item["evidence_type"].lower() in eligible
        and _mentions_promise(item["claim"], promise)
        and failure.search(item["claim"])
        for item in evidence
    )}


def _admitted_amenities(case: dict, listing: dict | None) -> set[str]:
    """Find specific listed amenities explicitly admitted as failed by the owner."""
    owner = str(case.get("owner_response", "")).lower()
    promises = listing.get("promises", []) if listing else []
    admissions = set()
    sentences = re.split(r"[.!?;\n]+", owner)
    for promise in promises:
        normalized = promise.lower()
        if not _mentions_promise(owner, normalized):
            continue
        for sentence in sentences:
            if not _mentions_promise(sentence, normalized):
                continue
            if re.search(r"\b(?:not|never|no|deny|denied|disagree|didn't|doesn't|isn't|wasn't)\b", sentence):
                continue
            failure = r"(?:fault|fail(?:ed|ure)?|broken|not working|malfunction(?:ed)?)"
            admission = r"(?:admit(?:s|ted)?|acknowledg(?:e|es|ed)|confirm(?:s|ed)?)"
            explicit_admission = re.search(rf"\b{admission}\b.{{0,45}}\b{failure}\b", sentence) or re.search(rf"\b{failure}\b.{{0,45}}\b{admission}\b", sentence)
            if explicit_admission:
                admissions.add(promise)
                break
    return admissions


def apply_guardrails(analysis: AIAnalysis, case: dict, listing: dict | None = None) -> dict:
    result = analysis.model_dump()
    notes: list[str] = []
    mandatory_manual: list[str] = []
    valid_ids = valid_clause_ids()
    result["policy_references"] = policy_references(result)
    cited = {ref["clause_id"] for ref in result["policy_references"]}
    issue = set(result["issue_categories"])
    verified_evidence = _verified_evidence(case)
    text = f"{case.get('complaint', '')} {case.get('owner_response', '')}".lower()
    admitted_amenities = _admitted_amenities(case, listing)
    evidenced_amenities = _evidenced_amenities(verified_evidence, listing)
    verified_amenities = admitted_amenities | evidenced_amenities

    def require_manual(reason: str) -> None:
        mandatory_manual.append(reason)

    if len(cited) != len(analysis.policy_references):
        notes.append("Unknown or unsupported policy references were removed.")

    # Deterministic P3 calculation happens before final mandatory-review enforcement.
    minutes = case.get("booking", {}).get("cancelled_minutes_before")
    if "cancellation" in issue and "P3" in cited:
        if minutes is None:
            require_manual("the cancellation time is missing (P3).")
        else:
            expected = p3_expected_percent(minutes)
            outcome = "full_refund" if expected == 100 else "no_refund" if expected == 0 else "partial_refund"
            if result["refund_percent"] != expected or result["recommendation"] != outcome:
                notes.append(f"Corrected to P3 policy outcome: {expected}%.")
            result["refund_percent"], result["recommendation"] = expected, outcome

    # Apply deterministic listing-dependent P5 rule before mandatory conditions.
    if "noise" in issue and "P5" in cited:
        quiet_promise = bool(listing and any("quiet" in p.lower() for p in listing.get("promises", [])))
        verified_noise = any(item["evidence_type"].lower() in {"audio", "video", "photo", "log", "timestamped_record"}
                             and "noise" in item["claim"].lower() for item in verified_evidence)
        if quiet_promise and not verified_noise:
            require_manual("noise was promised against but no verified evidence supports the complaint (P5).")
        elif not quiet_promise:
            result["recommendation"], result["refund_percent"] = "no_refund", 0
            notes.append("Applied P5: the listing makes no quiet-environment promise, so no refund is due under this clause.")

    damage_evidence = any(item["evidence_type"].lower() == "photo" or bool(item.get("evidence_timestamp"))
                          for item in verified_evidence)
    if "property_damage" in issue and ("P4" not in cited or not damage_evidence):
        require_manual("property damage deduction requires explicitly verified photos or timestamped evidence (P4).")

    if "access_failure" in issue and "P2" in cited:
        no_equivalent = any(term in text for term in ("nobody offered", "no equivalent", "not offered", "no alternative"))
        accepted_equivalent = "equivalent" in text and "accepted" in text
        admitted_access = bool(re.search(r"\b(?:admit|admitted|confirm|confirmed)\b.{0,50}\b(?:double-book|denied access|locked|unavailable|keycard)\b", case.get("owner_response", "").lower()))
        if not (no_equivalent or accepted_equivalent or admitted_access):
            require_manual("whether equivalent access was offered and accepted remains unknown (P2).")

    if "missing_amenity" in issue:
        reported = bool(re.search(r"report(?:ed|ing)?|during the booking|front desk|ticket", case.get("complaint", "").lower()))
        if "P1" not in cited or not verified_amenities:
            require_manual("a specific amenity failure must be verified by evidence or an owner admission (P1).")
        if not reported:
            require_manual("P1 requires the amenity issue to have been reported during the booking.")
        failure_count = len(verified_amenities)
        if failure_count and "P1" in cited and reported:
            expected = 50 if failure_count >= 2 else 30
            expected_outcome = "partial_refund"
            if result["recommendation"] != expected_outcome or result["refund_percent"] != expected:
                require_manual(f"P1 supports {expected}% for {failure_count} distinct verified amenity failure(s); the AI proposal did not match.")

    if any(unknown.get("critical") for unknown in result["unknowns"]):
        require_manual("a critical unknown remains (P6).")
    if result["confidence"] == "low":
        require_manual("AI confidence is low.")

    pct, rec = result["refund_percent"], result["recommendation"]
    allowed = {"P1": {30, 50}, "P2": {100}, "P3": {0, 50, 100}, "P5": {0}}
    verified_p1 = bool(verified_amenities)
    supporting = {pid for pid in cited if pct in allowed.get(pid, set()) and (
        (pid == "P1" and "missing_amenity" in issue and verified_p1)
        or (pid == "P2" and "access_failure" in issue)
        or (pid == "P3" and "cancellation" in issue)
        or (pid == "P5" and "noise" in issue)
    )}
    if rec != "manual_review":
        if rec == "partial_refund" and (pct not in {30, 50} or not supporting):
            require_manual("partial refund percentage is unsupported by a matching policy rule.")
        elif rec == "full_refund" and (pct != 100 or not supporting):
            require_manual("full refund is unsupported by a matching policy rule.")
        elif rec == "no_refund" and (pct != 0 or not (supporting or ("P5" in cited and "noise" in issue and not (listing and any("quiet" in p.lower() for p in listing.get("promises", [])))))):
            require_manual("no-refund outcome is unsupported by a matching policy rule.")
        elif not cited:
            require_manual("no valid supporting policy clause was cited.")

    # Mandatory review wins after every deterministic correction and policy check.
    if mandatory_manual:
        result["recommendation"], result["refund_percent"] = "manual_review", None
        notes.extend(f"Manual review required: {reason}" for reason in dict.fromkeys(mandatory_manual))

    # Keep submitted references as references. AI facts are not promoted from filenames.
    ai_asserted_facts = result.get("verified_facts", [])
    result["ai_asserted_facts"] = ai_asserted_facts
    booking = case.get("booking", {})
    booking_parts = [f"Rs {booking['amount']}" for key in ("amount",) if booking.get(key) is not None]
    booking_parts.extend(str(booking[key]) for key in ("space_type", "date", "time") if booking.get(key))
    if booking.get("cancelled_minutes_before") is not None:
        booking_parts.append(f"cancelled {booking['cancelled_minutes_before']} minutes before start")
    verified_facts = ([{"fact": "Booking record (as submitted): " + ", ".join(booking_parts) + ".", "source": "Booking record (as submitted)"}]
                      if booking_parts else [])
    verified_facts.extend({"fact": f"The original listing promises: {promise}.", "source": "Original listing"}
                          for promise in (listing or {}).get("promises", []))
    verified_facts.extend({"fact": f"The owner explicitly admitted that the listed amenity failed: {promise}.",
                           "source": "Specific owner admission"} for promise in sorted(admitted_amenities))
    verified_facts.extend({"fact": item["claim"], "source": f"Verified {item['evidence_type']} ({item['verified_by']})"}
                          for item in verified_evidence)
    result["verified_facts"] = verified_facts
    if ai_asserted_facts:
        notes.append("Model-asserted facts are shown separately; verified facts are grounded in stored records or explicit verification.")
    result["verified_owner_admissions"] = sorted(admitted_amenities)
    result["owner_allegations"] = [allegation["claim"] for allegation in result.get("allegations", []) if allegation["made_by"] == "owner"]
    result["evidence_references"] = case.get("evidence", [])
    result["verified_evidence"] = verified_evidence
    result["policy_references"] = [ref for ref in result["policy_references"] if ref["clause_id"] in valid_ids]
    result["guardrail_notes"] = notes
    result["adjusted"] = bool(notes)
    result["status"] = STATUS_TEXT
    return result
