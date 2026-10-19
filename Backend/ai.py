import json
import importlib
import logging
import os
import random
import time
import uuid

from pydantic import ValidationError

import guardrails
from models import AIAnalysis

logger = logging.getLogger("disputes.provider")
MAX_ATTEMPTS = 3
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class ProviderFailure(Exception):
    def __init__(self, category, message, *, retryable=False, status_code=None, request_id=None, attempts=1):
        super().__init__(message)
        self.category, self.retryable, self.status_code = category, retryable, status_code
        self.request_id, self.attempts = request_id, attempts

    def public_message(self):
        return f"{self.category}: {self.args[0]} (request {self.request_id}, attempts {self.attempts})"


def build_prompt(case, listing):
    return f"""POLICY\n{guardrails.load_policy_text()}\nLISTING\n{json.dumps(listing, ensure_ascii=False)}\nBOOKING\n{json.dumps(case['booking'], ensure_ascii=False)}\nCUSTOMER ALLEGATION\n{case['complaint']}\nOWNER RESPONSE\n{case.get('owner_response') or '(none)'}\nEVIDENCE REFERENCES (not inspected; filenames/descriptions are not proof)\n{json.dumps(case.get('evidence', []), ensure_ascii=False)}\nReturn structured JSON. Separate verified facts, customer allegations, owner allegations and unknowns. Only specific owner admissions can verify admitted facts. Explain the supporting policy rule and relevance for each policy reference. Use manual_review when outcome-critical facts lack evidence."""


def response_json_schema():
    """Small inline schema for Gemini's documented JSON Schema subset."""
    string = {"type": "string"}

    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

    fact = obj({"fact": string, "source": string})
    allegation = obj({"claim": string, "made_by": {"type": "string", "enum": ["customer", "owner"]}})
    unknown = obj({"question": string, "why_it_matters": string, "critical": {"type": "boolean"}})
    policy_ref = obj({"clause_id": string, "relevance": string})
    return obj({
        "issue_categories": {"type": "array", "items": {"type": "string", "enum": ["missing_amenity", "misleading_listing", "access_failure", "cancellation", "property_damage", "noise"]}},
        "verified_facts": {"type": "array", "items": fact},
        "allegations": {"type": "array", "items": allegation},
        "owner_allegations": {"type": "array", "items": string},
        "unknowns": {"type": "array", "items": unknown},
        "policy_references": {"type": "array", "items": policy_ref},
        "recommendation": {"type": "string", "enum": ["full_refund", "partial_refund", "no_refund", "manual_review"]},
        "refund_percent": {"type": ["integer", "null"], "minimum": 0, "maximum": 100},
        "explanation": string,
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "evidence_gaps": {"type": "array", "items": string},
    })


def _safe_provider_diagnostic(exc: Exception, api_key: str) -> str:
    message = getattr(exc, "message", None)
    if not isinstance(message, str) or not message.strip():
        return ""
    return message.replace(api_key, "[redacted]").replace("\n", " ").strip()[:500]


def _metadata(exc):
    status = getattr(exc, "code", None)
    headers = getattr(getattr(exc, "response", None), "headers", {}) or {}
    req_id = headers.get("x-goog-request-id") or headers.get("x-request-id")
    if status in (401, 403): return "authentication", status, req_id
    if status == 429: return "quota_or_rate_limit", status, req_id
    if status in RETRYABLE_STATUS: return "provider_transient", status, req_id
    if status in (400, 404): return "configuration_or_request", status, req_id
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)): return "network", None, req_id
    return "provider_error", status, req_id


def analyze_case(case, listing):
    request_id, start = str(uuid.uuid4()), time.monotonic()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    key = os.getenv("GEMINI_API_KEY", "").strip()
    attempts = 0
    try:
        if not key: raise ProviderFailure("configuration", "GEMINI_API_KEY is missing; set it in Backend/.env", request_id=request_id)
        if not model: raise ProviderFailure("configuration", "GEMINI_MODEL is empty", request_id=request_id)
        genai = importlib.import_module("google.genai")
        types = importlib.import_module("google.genai.types")
        client = genai.Client(api_key=key)
        config = types.GenerateContentConfig(
            system_instruction="You investigate coworking disputes and propose outcomes only. Do not treat evidence filenames/descriptions as proof. Owner admission verifies only the admitted fact. Unverified claims remain allegations. Cite actual policy rules and recommend manual_review when critical facts are unresolved.",
            temperature=0, response_mime_type="application/json", response_json_schema=response_json_schema())
        prompt = build_prompt(case, listing)
        while attempts < MAX_ATTEMPTS:
            attempts += 1
            try:
                response = client.models.generate_content(model=model, contents=prompt, config=config)
                analysis = AIAnalysis.model_validate_json(response.text or "")
                if not analysis.issue_categories or not analysis.explanation.strip():
                    raise ValueError("Missing issue categories or explanation")
                return analysis
            except (ValidationError, ValueError) as exc:
                if attempts < MAX_ATTEMPTS:
                    prompt += "\nReturn valid JSON matching the required schema."
                    continue
                raise ProviderFailure("malformed_output", "Gemini returned invalid structured analysis", request_id=request_id, attempts=attempts) from exc
            except Exception as exc:
                category, status, provider_req_id = _metadata(exc)
                if category in {"network", "provider_transient", "quota_or_rate_limit"} and attempts < MAX_ATTEMPTS:
                    time.sleep(min(0.2 * (2 ** (attempts - 1)) + random.random() * 0.1, 1.0))
                    continue
                text = {
                    "authentication": "Gemini rejected the API key; verify or rotate GEMINI_API_KEY",
                    "quota_or_rate_limit": "Gemini quota/rate limit reached; wait and retry",
                    "configuration_or_request": f"Gemini rejected model '{model}' or request; verify GEMINI_MODEL and API access",
                    "provider_transient": "Gemini service is temporarily unavailable",
                    "network": "Cannot reach Gemini; check backend network connectivity",
                }.get(category, f"Gemini request failed ({type(exc).__name__})")
                if category == "configuration_or_request":
                    diagnostic = _safe_provider_diagnostic(exc, key)
                    if diagnostic:
                        text = f"{text}. Provider detail: {diagnostic}"
                raise ProviderFailure(category, text, retryable=category in {"network", "provider_transient", "quota_or_rate_limit"},
                                      status_code=status, request_id=provider_req_id or request_id, attempts=attempts) from exc
    except ProviderFailure:
        raise
    except Exception as exc:
        logger.error("provider_setup_failure request_id=%s exception_type=%s", request_id, type(exc).__name__)
        raise ProviderFailure("configuration_or_network", f"Could not configure Gemini client ({type(exc).__name__})", request_id=request_id, attempts=attempts or 1) from exc
    finally:
        logger.info("provider_complete request_id=%s model=%s duration_ms=%d retry_count=%d", request_id, model,
                    int((time.monotonic() - start) * 1000), max(attempts - 1, 0))
