import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guardrails
import main
import ai
import storage
from google.genai.errors import ClientError, ServerError
from models import AIAnalysis, Fact


class ProviderErrorWithSecret(Exception):
    message = "Credential secret-test-key rejected"


def analysis_for(issue, recommendation, percent, *, refs=None, unknowns=None, confidence="high"):
    return AIAnalysis(
        issue_categories=[issue], verified_facts=[], allegations=[], unknowns=unknowns or [],
        policy_references=refs or [], recommendation=recommendation,
        refund_percent=percent, explanation="Scenario test", confidence=confidence,
        evidence_gaps=[],
    )


class DisputeScenarioTests(unittest.TestCase):
    def setUp(self):
        self.sleep_patcher = patch("ai.time.sleep")
        self.sleep_patcher.start()
        self.original_data_path = Path(main.storage.DATA_PATH)
        self.original = Path(storage.DATA_TEMPLATE_PATH).read_text(encoding="utf-8-sig")
        self.temp_data_dir = tempfile.TemporaryDirectory()
        main.storage.DATA_PATH = Path(self.temp_data_dir.name) / "data.json"
        self.fixture = json.loads(self.original)
        self.fixture["cases"] = [case for case in self.fixture["cases"] if case["id"] in {"C-1001", "C-1002", "C-1003", "C-1004", "C-1005"}]
        self.fixture["analyses"] = {key: value for key, value in self.fixture["analyses"].items() if key in {"C-1001", "C-1002", "C-1003", "C-1004", "C-1005"}}
        self.fixture["decisions"] = {}
        self.fixture.pop("decision_history", None)
        self.fixture["users"] = []
        self.fixture["sessions"] = {}
        main.storage.DATA_PATH.write_text(json.dumps(self.fixture), encoding="utf-8")
        self.client = TestClient(main.app)
        main.auth.provision_admin("admin@example.test", "correct-horse-battery", "Test Admin")
        login = self.client.post("/api/auth/login", json={"email": "admin@example.test", "password": "correct-horse-battery"})
        self.assertEqual(login.status_code, 200)

    def tearDown(self):
        self.sleep_patcher.stop()
        main.storage.DATA_PATH = self.original_data_path
        self.temp_data_dir.cleanup()


    def test_dispute_fixtures_are_the_five_supplied_scenarios(self):
        fixture_ids = {case["id"] for case in self.fixture["cases"]}
        self.assertEqual(fixture_ids, {"C-1001", "C-1002", "C-1003", "C-1004", "C-1005"})

    def test_admin_verifies_submitted_evidence_and_audits_it(self):
        case_id = "C-1001"
        payload = {"reference": self.fixture["cases"][0]["evidence"][0], "evidence_type": "ticket", "claim": "Projector failed during the booking."}
        response = self.client.post(f"/api/cases/{case_id}/evidence/verify", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["verified_by"], "Test Admin")
        stored = main.storage.get_case(main.storage.load(), case_id)
        self.assertEqual(stored["verified_evidence"][0]["verification_status"], "verified")
        self.assertEqual(stored["audit_history"][-1]["event"], "evidence_verified")
        self.assertEqual(self.client.post(f"/api/cases/{case_id}/evidence/verify", json={**payload, "reference": "other"}).status_code, 400)

    def test_modify_refund_uses_case_facts_not_ai_citations(self):
        case_id = "C-1003"
        case = main.storage.get_case(main.storage.load(), case_id)
        case["booking"]["cancelled_minutes_before"] = 120
        proposal = analysis_for("cancellation", "no_refund", 0, refs=[])
        result = guardrails.apply_guardrails(proposal, case, self.fixture["listings"][2])
        data = main.storage.load()
        data["cases"][2]["booking"]["cancelled_minutes_before"] = 120
        data["analyses"][case_id] = result
        main.storage.save(data)
        response = self.client.post(f"/api/cases/{case_id}/decision", json={"action": "modify", "final_outcome": "partial_refund", "final_percent": 50, "admin_notes": "P3 supports this cancellation window."})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["final_percent"], 50)

    def test_draft_messages_require_final_decision_and_use_templates(self):
        case_id = "C-1003"
        self.fixture["analyses"][case_id] = guardrails.apply_guardrails(
            analysis_for("cancellation", "no_refund", 0, refs=[{"clause_id": "P3", "relevance": "cancellation"}]),
            self.fixture["cases"][2], self.fixture["listings"][2])
        data = main.storage.load()
        data["analyses"][case_id] = self.fixture["analyses"][case_id]
        main.storage.save(data)
        response = self.client.post(f"/api/cases/{case_id}/draft-messages")
        self.assertEqual(response.status_code, 409)
        final = self.client.post(f"/api/cases/{case_id}/decision", json={"action": "modify", "final_outcome": "no_refund", "admin_notes": "P3 does not support a refund."})
        self.assertEqual(final.status_code, 200)
        drafts = self.client.post(f"/api/cases/{case_id}/draft-messages")
        self.assertEqual(drafts.status_code, 200)
        self.assertIn("no refund", drafts.json()["customer"])
        self.assertIn("P3", drafts.json()["owner"])

    def test_all_supplied_scenarios_and_live_stats(self):
        cases = self.client.get("/api/cases").json()
        self.assertEqual(len(cases), 5)
        self.assertEqual(self.client.get("/api/stats").json(), {
            "total_disputes": 5, "pending_reviews": 5, "resolved_cases": 0,
            "disputed_amount": 10300.0,
        })

        fixtures = json.loads(self.original)
        by_id = {case["id"]: case for case in fixtures["cases"]}
        projector = analysis_for("missing_amenity", "partial_refund", 30, refs=[{"clause_id": "P1", "relevance": "one verified failed amenity"}])
        projector.verified_facts = [Fact(fact="The projector was not working and owner admitted the fault.", source="Owner admission")]
        guarded = guardrails.apply_guardrails(projector, by_id["C-1001"], fixtures["listings"][0])
        self.assertEqual(guarded["refund_percent"], 30)

        access = analysis_for("access_failure", "full_refund", 100, refs=[{"clause_id": "P2", "relevance": "access denied"}])
        self.assertEqual(guardrails.apply_guardrails(access, by_id["C-1002"], fixtures["listings"][1])["recommendation"], "full_refund")

        cancellation = analysis_for("cancellation", "full_refund", 100, refs=[{"clause_id": "P3", "relevance": "cancellation"}])
        cancelled = guardrails.apply_guardrails(cancellation, by_id["C-1003"], fixtures["listings"][2])
        self.assertEqual((cancelled["recommendation"], cancelled["refund_percent"]), ("no_refund", 0))

        damage = analysis_for("property_damage", "no_refund", 0, refs=[{"clause_id": "P4", "relevance": "unsupported damage claim"}])
        self.assertEqual(guardrails.apply_guardrails(damage, by_id["C-1004"], fixtures["listings"][3])["recommendation"], "manual_review")

        noise = analysis_for("noise", "no_refund", 0, refs=[{"clause_id": "P5", "relevance": "open plan listing does not promise quiet"}])
        self.assertEqual(guardrails.apply_guardrails(noise, by_id["C-1005"], fixtures["listings"][4])["recommendation"], "no_refund")

    def test_filename_only_is_not_evidence_and_missing_access_terms_go_manual(self):
        fixture = json.loads(self.original)
        c1 = fixture["cases"][0].copy()
        c1["owner_response"] = "We dispute the projector complaint."
        c1["evidence"] = ["Photo: projector_error_screen.jpg"]
        amenity = analysis_for("missing_amenity", "partial_refund", 30,
                               refs=[{"clause_id": "P1", "relevance": "claimed failure"}])
        checked = guardrails.apply_guardrails(amenity, c1, fixture["listings"][0])
        self.assertEqual(checked["recommendation"], "manual_review")

        not_admitted = dict(c1, evidence=[])
        not_admitted["owner_response"] = "We disagree with the customer's version."
        claimed = analysis_for("missing_amenity", "partial_refund", 30,
                               refs=[{"clause_id": "P1", "relevance": "claimed failure"}])
        claimed.verified_facts = [Fact(fact="Projector failure", source="Submitted evidence references")]
        guarded_claim = guardrails.apply_guardrails(claimed, not_admitted, fixture["listings"][0])
        self.assertEqual(guarded_claim["recommendation"], "manual_review")
        self.assertFalse(any("parking ticket" in fact["fact"].lower() for fact in guarded_claim["verified_facts"]))

        c2 = fixture["cases"][1].copy()
        c2["complaint"] = "I could not enter the reserved cabin."
        c2["owner_response"] = "We are sorry."
        access = analysis_for("access_failure", "full_refund", 100,
                              refs=[{"clause_id": "P2", "relevance": "access"}])
        checked = guardrails.apply_guardrails(access, c2, fixture["listings"][1])
        self.assertEqual(checked["recommendation"], "manual_review")

    def test_noise_policy_overrides_ai_refund_if_listing_does_not_promise_quiet(self):
        fixture = json.loads(self.original)
        noise = analysis_for("noise", "partial_refund", 30,
                             refs=[{"clause_id": "P5", "relevance": "noise complaint"}])
        result = guardrails.apply_guardrails(noise, fixture["cases"][4], fixture["listings"][4])
        self.assertEqual((result["recommendation"], result["refund_percent"]), ("no_refund", 0))

    def test_create_analyze_and_finalize_case(self):
        create = self.client.post("/api/cases", json={
            "customer": "Test Customer", "listing_id": "L1", "booking": {
                "amount": 1000, "date": "2026-10-20", "time": "10:00",
                "space_type": "Meeting room", "cancelled_minutes_before": None,
            }, "complaint": "The projector did not work during my booking.",
            "owner_response": "We confirm the projector fault.", "evidence": ["Ticket #1"],
        })
        self.assertEqual(create.status_code, 201)
        case_id = create.json()["id"]
        self.assertIn(case_id, [row["id"] for row in self.client.get("/api/cases").json()])

        proposed = analysis_for("missing_amenity", "partial_refund", 30, refs=[{"clause_id": "P1", "relevance": "verified amenity failure"}])
        with patch.object(main.ai, "analyze_case", return_value=proposed):
            self.assertEqual(self.client.post(f"/api/cases/{case_id}/analyze").status_code, 200)
        decision = self.client.post(f"/api/cases/{case_id}/decision", json={
            "action": "modify", "final_outcome": "no_refund", "admin_notes": "Evidence was inconclusive.", "reviewer": "A. Reviewer",
        })
        self.assertEqual(decision.status_code, 200)
        self.assertEqual(decision.json()["reviewer"], "Test Admin")
        detail = self.client.get(f"/api/cases/{case_id}").json()
        self.assertEqual(detail["decision"]["final_outcome"], "no_refund")
        self.assertEqual(detail["case"]["status"], "Finalized")
        self.assertEqual(self.client.get("/api/stats").json()["resolved_cases"], 1)

    def test_reject_action_sends_to_manual_review_without_resolving(self):
        case_id = "C-1002"
        proposed = analysis_for("access_failure", "full_refund", 100,
                                refs=[{"clause_id": "P2", "relevance": "access denied"}])
        with patch.object(main.ai, "analyze_case", return_value=proposed):
            self.client.post(f"/api/cases/{case_id}/analyze")
        response = self.client.post(f"/api/cases/{case_id}/decision", json={
            "action": "reject", "admin_notes": "Insufficient proof to grant refund.", "reviewer": "Reviewer"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["final_outcome"], "manual_review")
        self.assertEqual(response.json()["ai_proposal_snapshot"]["recommendation"], "full_refund")
        self.assertEqual(response.json()["decision_status"], "pending_manual_review")
        detail = self.client.get(f"/api/cases/{case_id}").json()
        self.assertEqual(detail["case"]["status"], "Manual Review")
        self.assertEqual(self.client.get("/api/stats").json()["resolved_cases"], 0)
        self.assertEqual(self.client.get("/api/stats").json()["pending_reviews"], 5)
        self.assertEqual(self.client.post(f"/api/cases/{case_id}/decision", json={"action": "approve", "admin_notes": "Attempt bypass"}).status_code, 409)
        self.assertEqual(self.client.post(f"/api/cases/{case_id}/decision", json={"action": "reject", "admin_notes": "Repeat"}).status_code, 409)
        final = self.client.post(f"/api/cases/{case_id}/decision", json={
            "action": "modify", "final_outcome": "no_refund",
            "admin_notes": "Manual review confirmed the records.", "reviewer": "Reviewer"})
        self.assertEqual(final.status_code, 200)
        self.assertEqual(final.json()["decision_status"], "finalized")
        history = main.storage.load()["decision_history"][case_id]
        self.assertEqual([item["decision_status"] for item in history], ["pending_manual_review", "finalized"])

    def test_manual_review_outcome_stays_pending_until_a_final_outcome_is_recorded(self):
        case_id = "C-1004"
        proposal = analysis_for("property_damage", "manual_review", None,
                               refs=[{"clause_id": "P4", "relevance": "Missing damage evidence"}])
        with patch.object(main.ai, "analyze_case", return_value=proposal):
            self.assertEqual(self.client.post(f"/api/cases/{case_id}/analyze").status_code, 200)
        response = self.client.post(f"/api/cases/{case_id}/decision", json={
            "action": "modify", "final_outcome": "manual_review", "admin_notes": "Request manual evidence review."})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["decision_status"], "pending_manual_review")
        self.assertEqual(self.client.get(f"/api/cases/{case_id}").json()["case"]["status"], "Manual Review")
        self.assertEqual(self.client.get("/api/stats").json()["resolved_cases"], 0)
        final = self.client.post(f"/api/cases/{case_id}/decision", json={
            "action": "modify", "final_outcome": "no_refund", "admin_notes": "Investigation did not establish a damage deduction."})
        self.assertEqual(final.status_code, 200)
        self.assertEqual(final.json()["decision_status"], "finalized")

    def test_critical_unknown_after_p3_cannot_be_overwritten_by_cancellation(self):
        case = dict(self.fixture["cases"][2])
        proposal = analysis_for("cancellation", "partial_refund", 50,
                               refs=[{"clause_id": "P3", "relevance": "cancellation"}],
                               unknowns=[{"question": "Was cancellation recorded?", "why_it_matters": "Determines the outcome.", "critical": True}])
        result = guardrails.apply_guardrails(proposal, case, self.fixture["listings"][2])
        self.assertEqual(result["recommendation"], "manual_review")
        self.assertIsNone(result["refund_percent"])

    def test_p3_boundaries_match_supplied_policy(self):
        self.assertEqual(guardrails.p3_expected_percent(24 * 60 + 1), 100)
        self.assertEqual(guardrails.p3_expected_percent(24 * 60), 50)
        self.assertEqual(guardrails.p3_expected_percent(2 * 60), 50)
        self.assertEqual(guardrails.p3_expected_percent(2 * 60 - 1), 0)

    def test_listing_amenity_mention_is_not_failure_evidence(self):
        case = {"complaint": "The room was disappointing.", "owner_response": "We confirmed the booking.", "evidence": [], "booking": {"cancelled_minutes_before": None}}
        proposal = analysis_for("missing_amenity", "partial_refund", 30, refs=[{"clause_id": "P1", "relevance": "projector listed"}])
        proposal.verified_facts = [Fact(fact="The listing promises a projector with HDMI.", source="Listing")]
        result = guardrails.apply_guardrails(proposal, case, self.fixture["listings"][0])
        self.assertEqual(result["recommendation"], "manual_review")

    def test_unrelated_owner_admission_does_not_verify_amenity_failure(self):
        case = {"complaint": "The projector failed and I reported it during the booking.", "owner_response": "We confirmed the booking time, but we dispute the projector complaint.", "evidence": [], "booking": {"cancelled_minutes_before": None}}
        proposal = analysis_for("missing_amenity", "partial_refund", 30, refs=[{"clause_id": "P1", "relevance": "amenity"}])
        result = guardrails.apply_guardrails(proposal, case, self.fixture["listings"][0])
        self.assertEqual(result["recommendation"], "manual_review")

    def test_unrelated_reference_is_not_verified_evidence(self):
        case = {"complaint": "The projector failed and was reported during the booking.", "owner_response": "We disagree.", "evidence": ["ticket #19 about parking validation"], "booking": {"cancelled_minutes_before": None}}
        proposal = analysis_for("missing_amenity", "partial_refund", 30, refs=[{"clause_id": "P1", "relevance": "projector"}])
        proposal.verified_facts = [Fact(fact="Parking ticket #19 exists.", source="Submitted evidence references")]
        result = guardrails.apply_guardrails(proposal, case, self.fixture["listings"][0])
        self.assertEqual(result["recommendation"], "manual_review")
        self.assertFalse(any("parking ticket" in fact["fact"].lower() for fact in result["verified_facts"]))
        self.assertTrue(any("parking ticket" in fact["fact"].lower() for fact in result["ai_asserted_facts"]))

    def test_p1_counts_distinct_verified_amenities_not_evidence_items(self):
        fixture = json.loads(self.original)
        case = dict(fixture["cases"][0], complaint="I reported the issue at the front desk during the booking.",
                    evidence=["ticket-1"], verified_evidence=[{
                        "reference": "ticket-1", "evidence_type": "ticket", "claim": "Projector failed during presentation.",
                        "verification_status": "verified", "verified_by": "admin-1", "verified_at": "2026-10-20T10:00:00+00:00"}])
        proposal = analysis_for("missing_amenity", "partial_refund", 50,
                               refs=[{"clause_id": "P1", "relevance": "One projector failure."}])
        result = guardrails.apply_guardrails(proposal, case, fixture["listings"][0])
        self.assertEqual((result["recommendation"], result["refund_percent"]), ("manual_review", None))
        proposal.refund_percent = 30
        result = guardrails.apply_guardrails(proposal, case, fixture["listings"][0])
        self.assertEqual((result["recommendation"], result["refund_percent"]), ("partial_refund", 30))

    def test_p1_calculates_two_distinct_verified_amenities(self):
        fixture = json.loads(self.original)
        refs = ["projector-ticket", "wifi-log"]
        case = dict(fixture["cases"][0], complaint="I reported both failures during the booking.", owner_response="We disagree.",
                    evidence=refs, verified_evidence=[
                        {"reference": refs[0], "evidence_type": "ticket", "claim": "Projector failed.", "verification_status": "verified", "verified_by": "admin", "verified_at": "2026-10-20T10:00:00+00:00"},
                        {"reference": refs[1], "evidence_type": "log", "claim": "Wi-Fi failed repeatedly.", "verification_status": "verified", "verified_by": "admin", "verified_at": "2026-10-20T10:01:00+00:00"},
                    ])
        proposal = analysis_for("missing_amenity", "partial_refund", 50,
                               refs=[{"clause_id": "P1", "relevance": "Two amenities failed."}])
        result = guardrails.apply_guardrails(proposal, case, fixture["listings"][0])
        self.assertEqual((result["recommendation"], result["refund_percent"]), ("partial_refund", 50))

    def test_invalid_policy_reference_is_removed_and_cannot_support_refund(self):
        case = json.loads(self.original)["cases"][1]
        proposal = analysis_for("access_failure", "full_refund", 100,
                               refs=[{"clause_id": "PX", "relevance": "invented clause"}])
        result = guardrails.apply_guardrails(proposal, case, self.fixture["listings"][1])
        self.assertEqual(result["recommendation"], "manual_review")
        self.assertEqual(result["policy_references"], [])

    def test_unverified_claim_metadata_cannot_satisfy_p4(self):
        fixture = json.loads(self.original)
        case = dict(fixture["cases"][3], evidence=["damage-report.pdf"], verified_evidence=[{
            "reference": "damage-report.pdf", "evidence_type": "log", "claim": "Damage observed.",
            "verification_status": "verified", "verified_by": "admin", "verified_at": "2026-10-20T10:00:00+00:00"}])
        proposal = analysis_for("property_damage", "no_refund", 0,
                               refs=[{"clause_id": "P4", "relevance": "claim"}])
        result = guardrails.apply_guardrails(proposal, case, fixture["listings"][3])
        self.assertEqual(result["recommendation"], "manual_review")

    def test_analysis_requires_complete_schema_and_wrong_percent_becomes_manual(self):
        case_id = "C-1001"
        before = self.client.get(f"/api/cases/{case_id}").json()["analysis"]
        with patch.object(main.ai, "analyze_case", side_effect=ai.ProviderFailure("malformed_output", "Missing required fields", attempts=3)):
            response = self.client.post(f"/api/cases/{case_id}/analyze")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.client.get(f"/api/cases/{case_id}").json()["analysis"], before)

        invalid = analysis_for("missing_amenity", "partial_refund", 80,
                               refs=[{"clause_id": "P1", "relevance": "amenity"}])
        invalid.verified_facts = [Fact(fact="The projector amenity failed; owner admits fault.", source="Owner admission")]
        result = guardrails.apply_guardrails(invalid, self.fixture["cases"][0], self.fixture["listings"][0])
        self.assertEqual(result["recommendation"], "manual_review")
        self.assertIsNone(result["refund_percent"])

    def test_gemini_request_schema_is_inline_and_matches_analysis_fields(self):
        schema = ai.response_json_schema()
        self.assertEqual(schema["type"], "object")
        self.assertNotIn("$defs", json.dumps(schema))
        self.assertNotIn("$ref", json.dumps(schema))
        self.assertEqual(schema["properties"]["refund_percent"]["type"], ["integer", "null"])
        self.assertEqual(set(schema["properties"]), set(AIAnalysis.model_fields))

    def test_provider_request_error_exposes_safe_specific_detail(self):
        class ProviderError(Exception):
            code = 400
            message = "Invalid schema: field response_schema is unsupported"

        detail = ai._safe_provider_diagnostic(ProviderError(), "secret-test-key")
        self.assertEqual(detail, "Invalid schema: field response_schema is unsupported")
        leaked = ai._safe_provider_diagnostic(ProviderErrorWithSecret(), "secret-test-key")
        self.assertNotIn("secret-test-key", leaked)

    def test_unsupported_percentage_is_forced_to_manual_review(self):
        case = json.loads(self.original)["cases"][0]
        invalid = analysis_for("missing_amenity", "partial_refund", 75, refs=[{"clause_id": "P1", "relevance": "unsupported"}])
        invalid.verified_facts = [Fact(fact="Projector amenity failed; owner admitted fault.", source="Owner admission")]
        result = guardrails.apply_guardrails(invalid, case, json.loads(self.original)["listings"][0])
        self.assertEqual(result["recommendation"], "manual_review")
        self.assertIsNone(result["refund_percent"])

    def test_provider_auth_quota_malformed_and_retryable_errors_have_status_and_no_mutation(self):
        with patch.object(main.ai, "analyze_case", side_effect=ai.ProviderFailure("authentication", "Gemini rejected key", request_id="r-auth")):
            response = self.client.post("/api/cases/C-1002/analyze")
        self.assertEqual(response.status_code, 502)
        self.assertIn("authentication", response.json()["detail"])
        self.assertIsNone(self.client.get("/api/cases/C-1002").json()["analysis"])

        with patch.object(main.ai, "analyze_case", side_effect=ai.ProviderFailure("quota_or_rate_limit", "Quota reached", retryable=True, status_code=429, request_id="r-quota", attempts=3)):
            response = self.client.post("/api/cases/C-1002/analyze")
        self.assertEqual(response.status_code, 503)
        self.assertIn("attempts 3", response.json()["detail"])

        with patch.object(main.ai, "analyze_case", side_effect=ai.ProviderFailure("malformed_output", "Invalid JSON", request_id="r-json", attempts=3)):
            response = self.client.post("/api/cases/C-1002/analyze")
        self.assertEqual(response.status_code, 502)

        with patch.object(main.ai, "analyze_case", side_effect=ai.ProviderFailure("network", "Cannot reach Gemini", retryable=True, request_id="r-timeout", attempts=3)):
            response = self.client.post("/api/cases/C-1002/analyze")
        self.assertEqual(response.status_code, 503)
        self.assertIn("network", response.json()["detail"])
        self.assertIsNone(self.client.get("/api/cases/C-1002").json()["analysis"])

    def test_duplicate_case_and_policy_invalid_finalize_leave_data_unchanged(self):
        payload = {"customer": "Duplicate Test", "listing_id": "L1", "booking": {
            "amount": 1234, "date": "2026-10-21", "time": "11:00", "space_type": "Meeting room",
            "cancelled_minutes_before": None}, "complaint": "The listed projector failed during our meeting.",
            "owner_response": "", "evidence": []}
        first = self.client.post("/api/cases", json=payload)
        second = self.client.post("/api/cases", json=payload)
        self.assertEqual(first.status_code, 201)
        self.assertTrue(second.json()["duplicate"])
        self.assertEqual(first.json()["id"], second.json()["id"])

        case_id = first.json()["id"]
        proposed = analysis_for("missing_amenity", "manual_review", None)
        with patch.object(main.ai, "analyze_case", return_value=proposed):
            self.assertEqual(self.client.post(f"/api/cases/{case_id}/analyze").status_code, 200)
        before = self.client.get(f"/api/cases/{case_id}").json()
        invalid = self.client.post(f"/api/cases/{case_id}/decision", json={
            "action": "approve", "admin_notes": "Review", "reviewer": "Reviewer"})
        self.assertEqual(invalid.status_code, 409)
        after = self.client.get(f"/api/cases/{case_id}").json()
        self.assertIsNone(after["decision"])
        self.assertEqual(after["case"]["status"], before["case"]["status"])

    def test_failed_finalization_does_not_overwrite_proposal_and_partial_is_policy_limited(self):
        proposed = analysis_for("missing_amenity", "partial_refund", 30,
                                refs=[{"clause_id": "P1", "relevance": "verified one amenity"}])
        case_id = "C-1001"
        with patch.object(main.ai, "analyze_case", return_value=proposed):
            self.assertEqual(self.client.post(f"/api/cases/{case_id}/analyze").status_code, 200)
        invalid = self.client.post(f"/api/cases/{case_id}/decision", json={
            "action": "modify", "final_outcome": "partial_refund", "final_percent": 75,
            "admin_notes": "Modify", "reviewer": "Reviewer"})
        self.assertEqual(invalid.status_code, 400)
        state = self.client.get(f"/api/cases/{case_id}").json()
        self.assertIsNone(state["decision"])
        self.assertEqual(state["analysis"]["recommendation"], "partial_refund")

    def test_saved_analysis_decision_and_audit_survive_storage_reload(self):
        case_id = "C-1002"
        proposal = analysis_for("access_failure", "full_refund", 100,
                                refs=[{"clause_id": "P2", "relevance": "Owner admitted double booking"}])
        with patch.object(main.ai, "analyze_case", return_value=proposal):
            self.assertEqual(self.client.post(f"/api/cases/{case_id}/analyze").status_code, 200)
        decision = self.client.post(f"/api/cases/{case_id}/decision", json={
            "action": "approve", "admin_notes": "Access was denied.", "reviewer": "Reviewer"})
        self.assertEqual(decision.status_code, 200)
        reloaded = main.storage.load()
        self.assertEqual(reloaded["decisions"][case_id]["ai_proposal_snapshot"]["recommendation"], "full_refund")
        self.assertEqual(len(reloaded["proposal_history"][case_id]), 1)
        self.assertEqual([e["event"] for e in main.storage.get_case(reloaded, case_id)["audit_history"]],
                         ["analysis_completed", "decision_finalized"])

    def test_registration_login_password_hashing_and_public_customer_role(self):
        client = TestClient(main.app)
        registered = client.post("/api/auth/register", json={"email": "owner@example.test", "password": "a-long-password-123", "display_name": "Case Owner", "role": "admin"})
        self.assertEqual(registered.status_code, 422)
        registered = client.post("/api/auth/register", json={"email": "owner@example.test", "password": "a-long-password-123", "display_name": "Case Owner"})
        self.assertEqual(registered.status_code, 201)
        self.assertEqual(registered.json()["user"]["role"], "customer")
        self.assertNotIn("password_hash", registered.json()["user"])
        stored_user = next(user for user in main.storage.load()["users"] if user["email"] == "owner@example.test")
        self.assertNotEqual(stored_user["password_hash"], "a-long-password-123")
        self.assertTrue(stored_user["password_hash"].startswith("$2"))

        invalid = TestClient(main.app).post("/api/auth/login", json={"email": "owner@example.test", "password": "wrong-password"})
        self.assertEqual(invalid.status_code, 401)
        login = client.post("/api/auth/login", json={"email": "owner@example.test", "password": "a-long-password-123"})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(client.get("/api/auth/me").json()["user"]["role"], "customer")

    def test_expired_session_is_rejected(self):
        token = self.client.cookies.get(main.auth.SESSION_COOKIE)
        digest = __import__("hashlib").sha256(token.encode()).hexdigest()
        data = main.storage.load()
        data["sessions"][digest]["expires_at"] = "2000-01-01T00:00:00+00:00"
        main.storage.save(data)
        self.assertEqual(self.client.get("/api/cases").status_code, 401)

    def test_booking_input_rejects_invalid_date_time_and_amount(self):
        payload = {"customer": "Test", "listing_id": "L1", "booking": {"amount": 10, "date": "2026-02-30", "time": "25:61", "space_type": "Meeting room"}, "complaint": "The booking was not usable."}
        self.assertEqual(self.client.post("/api/cases", json=payload).status_code, 422)
        payload["booking"].update({"date": "2026-10-20", "time": "10:00"})
        payload["booking"]["amount"] = float("inf")
        response = self.client.post("/api/cases", content=json.dumps(payload), headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 422)

    def test_customer_to_admin_finalized_workflow_updates_both_views(self):
        customer = TestClient(main.app)
        self.assertEqual(customer.post("/api/auth/register", json={"email": "workflow@example.test", "password": "customer-password-123", "display_name": "Workflow Customer"}).status_code, 201)
        payload = {"customer": "ignored", "listing_id": "L3", "booking": {"amount": 700, "date": "2026-10-20", "time": "10:00", "space_type": "Meeting room", "cancelled_minutes_before": 30}, "complaint": "I cancelled this booking 30 minutes before it started.", "owner_response": "The cancellation was received 30 minutes before start.", "evidence": []}
        created = customer.post("/api/cases", json=payload)
        self.assertEqual(created.status_code, 201)
        case_id = created.json()["id"]
        proposal = analysis_for("cancellation", "full_refund", 100, refs=[{"clause_id": "P3", "relevance": "30 minute cancellation"}])
        with patch.object(main.ai, "analyze_case", return_value=proposal):
            analyzed = self.client.post(f"/api/cases/{case_id}/analyze")
        self.assertEqual(analyzed.status_code, 200)
        self.assertEqual((analyzed.json()["recommendation"], analyzed.json()["refund_percent"]), ("no_refund", 0))
        finalized = self.client.post(f"/api/cases/{case_id}/decision", json={"action": "approve", "admin_notes": "P3 applies to cancellation 30 minutes before the booking."})
        self.assertEqual(finalized.status_code, 200)
        customer_view = customer.get(f"/api/cases/{case_id}").json()
        self.assertEqual(customer_view["case"]["status"], "Finalized")
        self.assertEqual(customer_view["decision"]["final_outcome"], "no_refund")

    def test_unauthorized_customer_ownership_and_admin_permissions(self):
        anonymous = TestClient(main.app)
        self.assertEqual(anonymous.get("/api/cases").status_code, 401)
        self.assertEqual(anonymous.get("/api/listings").status_code, 401)
        self.assertEqual(anonymous.get("/api/stats").status_code, 401)

        first = TestClient(main.app)
        second = TestClient(main.app)
        for client, email in ((first, "first@example.test"), (second, "second@example.test")):
            response = client.post("/api/auth/register", json={"email": email, "password": "customer-password-123", "display_name": email.split("@")[0]})
            self.assertEqual(response.status_code, 201)

        payload = {"customer": "Forged Name", "listing_id": "L1", "booking": {"amount": 500, "date": "2026-10-20", "time": "10:00", "space_type": "Meeting room", "cancelled_minutes_before": None}, "complaint": "The projector failed in the room.", "owner_response": "", "evidence": [], "owner_id": "someone-else"}
        rejected_spoof = first.post("/api/cases", json=payload)
        self.assertEqual(rejected_spoof.status_code, 422)
        payload.pop("owner_id")
        created = first.post("/api/cases", json=payload)
        self.assertEqual(created.status_code, 201)
        case_id = created.json()["id"]
        stored = main.storage.get_case(main.storage.load(), case_id)
        self.assertEqual(stored["customer"], "first")
        self.assertEqual(stored["owner_id"], first.get("/api/auth/me").json()["user"]["id"])

        self.assertEqual([row["id"] for row in first.get("/api/cases").json()], [case_id])
        self.assertEqual(second.get("/api/cases").json(), [])
        self.assertEqual(second.get(f"/api/cases/{case_id}").status_code, 404)
        self.assertNotIn("analysis", first.get(f"/api/cases/{case_id}").json())
        self.assertEqual(first.get("/api/stats").status_code, 403)
        self.assertEqual(first.post(f"/api/cases/{case_id}/analyze").status_code, 403)
        self.assertEqual(first.post(f"/api/cases/{case_id}/decision", json={"action": "reject", "admin_notes": "No", "reviewer": "Spoofed"}).status_code, 403)

        restarted_api = TestClient(main.app)
        restarted_api.cookies.set(main.auth.SESSION_COOKIE, first.cookies.get(main.auth.SESSION_COOKIE))
        self.assertEqual(restarted_api.get("/api/auth/me").json()["user"]["email"], "first@example.test")
        self.assertEqual([row["id"] for row in restarted_api.get("/api/cases").json()], [case_id])

        first.post("/api/auth/logout")
        self.assertEqual(first.get("/api/cases").status_code, 401)

    def test_admin_identity_and_decision_persist_on_reloaded_storage(self):
        case_id = "C-1002"
        proposal = analysis_for("access_failure", "full_refund", 100, refs=[{"clause_id": "P2", "relevance": "Owner admission"}])
        with patch.object(main.ai, "analyze_case", return_value=proposal):
            self.assertEqual(self.client.post(f"/api/cases/{case_id}/analyze").status_code, 200)
        response = self.client.post(f"/api/cases/{case_id}/decision", json={"action": "approve", "admin_notes": "The booking was inaccessible.", "reviewer": "Impersonated Admin"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reviewer"], "Test Admin")
        reloaded = main.storage.load()
        self.assertEqual(reloaded["decisions"][case_id]["final_outcome"], "full_refund")
        self.assertEqual(reloaded["decisions"][case_id]["ai_proposal_snapshot"]["recommendation"], "full_refund")
        duplicate = self.client.post(f"/api/cases/{case_id}/decision", json={"action": "approve", "admin_notes": "Again"})
        self.assertEqual(duplicate.status_code, 400)

    def test_reanalysis_failure_keeps_persisted_valid_proposal_and_history(self):
        case_id = "C-1002"
        original_proposal = analysis_for("access_failure", "full_refund", 100,
                                         refs=[{"clause_id": "P2", "relevance": "owner admission"}])
        with patch.object(main.ai, "analyze_case", return_value=original_proposal):
            self.assertEqual(self.client.post(f"/api/cases/{case_id}/analyze").status_code, 200)
        before = self.client.get(f"/api/cases/{case_id}").json()["analysis"]
        with patch.object(main.ai, "analyze_case", side_effect=ai.ProviderFailure("malformed_output", "Invalid output", attempts=3)):
            response = self.client.post(f"/api/cases/{case_id}/analyze")
        self.assertEqual(response.status_code, 502)
        after = self.client.get(f"/api/cases/{case_id}").json()["analysis"]
        self.assertEqual(after, before)
        self.assertEqual(len(main.storage.load()["proposal_history"][case_id]), 1)


if __name__ == "__main__":
    unittest.main()
