import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getCase, analyzeCase, submitDecision, verifyEvidence, getDraftMessages } from "../api.js";
import AIPanel from "../components/AIPanel.jsx";
import { OUTCOME_LABEL } from "../outcomeLabels.js";
import DecisionControls from "../components/DecisionControls.jsx";

export default function CaseDetail() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState("");
  const [verification, setVerification] = useState({});
  const [drafts, setDrafts] = useState(null);

  const load = useCallback(async () => {
    try {
      setData(await getCase(id));
    } catch (e) {
      setError(e.message);
    }
  }, [id]);

  useEffect(() => {
    let active = true;
    getCase(id).then((result) => { if (active) setData(result); })
      .catch((e) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [id]);

  async function runAnalysis() {
    setAnalyzing(true);
    setError("");
    try {
      await analyzeCase(id);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleDecision(payload) {
    setError("");
    await submitDecision(id, payload);
    await load();
  }

  async function handleVerification(reference) {
    setError("");
    try { await verifyEvidence(id, { reference, ...verification[reference] }); await load(); }
    catch (e) { setError(e.message); }
  }

  async function loadDrafts() {
    setError("");
    try { setDrafts(await getDraftMessages(id)); } catch (e) { setError(e.message); }
  }

  if (!data || data.case.id !== id) return error ? <div><p className="error" role="alert">Could not load this case: {error}</p><button className="btn" onClick={load}>Retry</button></div> : <p className="muted">Loading case…</p>;

  const { case: c, listing, analysis, decision } = data;
  const finalized = c.status === "Finalized";

  return (
    <>
      <Link to="/">&larr; All disputes</Link>
      <div className="row between">
        <h2>{c.id}: {c.customer}</h2>
        <span className={`badge status-${c.status.replace(" ", "")}`}>{c.status}</span>
      </div>

      <div className="grid2">
        {/* LEFT: booking facts + listing promises */}
        <section className="card">
          <h3>Booking facts</h3>
          <dl className="facts">
            <dt>Amount paid</dt><dd>Rs {c.booking.amount.toLocaleString("en-IN")}</dd>
            <dt>Date / time</dt><dd>{c.booking.date} at {c.booking.time}</dd>
            <dt>Space type</dt><dd>{c.booking.space_type}</dd>
            <dt>Cancelled</dt>
            <dd>
              {c.booking.cancelled_minutes_before != null
                ? `${c.booking.cancelled_minutes_before} minutes before start`
                : "No"}
            </dd>
          </dl>
          <h3>Listing promises: {listing.title}</h3>
          <ul>{listing.promises.map((p) => <li key={p}>{p}</li>)}</ul>
        </section>

        {/* RIGHT: statements + evidence */}
        <section className="card">
          <h3>Customer complaint</h3>
          <p className="quote customer">{c.complaint}</p>
          <h3>Owner statement</h3>
          <p className="quote owner">{c.owner_response || "No response provided."}</p>
          <h3>Submitted evidence</h3>
          {c.evidence.length ? (
            <ul>{c.evidence.map((e) => {
              const verified = (c.verified_evidence || []).some((item) => item.reference === e && item.verification_status === "verified");
              return <li key={e}>{e}{verified ? <p className="muted">Verified</p> : !finalized && <form onSubmit={(event) => { event.preventDefault(); handleVerification(e); }}>
                <label>Type <select required value={verification[e]?.evidence_type || ""} onChange={(event) => setVerification({ ...verification, [e]: { ...verification[e], evidence_type: event.target.value } })}><option value="">Select type</option>{["ticket", "photo", "log", "timestamped_record", "audio", "video"].map((type) => <option key={type}>{type}</option>)}</select></label>
                <label>What does it verify? <input required value={verification[e]?.claim || ""} onChange={(event) => setVerification({ ...verification, [e]: { ...verification[e], claim: event.target.value } })} /></label>
                <label>Evidence timestamp (optional) <input type="datetime-local" value={verification[e]?.evidence_timestamp || ""} onChange={(event) => setVerification({ ...verification, [e]: { ...verification[e], evidence_timestamp: event.target.value ? new Date(event.target.value).toISOString() : undefined } })} /></label>
                <button className="btn" type="submit">Mark verified</button>
              </form>}</li>;
            })}</ul>
          ) : (
            <p className="muted">No evidence submitted.</p>
          )}
        </section>
      </div>

      {error && <p className="error">{error}</p>}

      <section className="card">
        <div className="row between">
          <h3>AI investigation</h3>
          {!finalized && analysis && (
            <button className="btn primary" onClick={runAnalysis} disabled={analyzing}>
              {analyzing ? "Analyzing..." : "Re-run analysis"}
            </button>
          )}
        </div>
        {analysis ? <AIPanel analysis={analysis} listing={listing} booking={c.booking} evidence={c.evidence} /> : (
          <div><p className="muted">{analyzing ? "Contacting Gemini and validating policy…" : error ? "Analysis is ready to retry." : "Not analyzed yet. Start an investigation."}</p><button className="btn primary" onClick={runAnalysis} disabled={analyzing}>{analyzing ? "Analyzing..." : error ? "Retry analysis" : "Analyze with AI"}</button></div>
        )}
      </section>

      {analysis && !finalized && (
        <DecisionControls analysis={analysis} pendingManualReview={decision?.decision_status === "pending_manual_review"} onSubmit={handleDecision} />
      )}
      {analysis?.recommendation === "manual_review" && <section className="card"><h3>Manual investigation required</h3><p>Review the evidence gaps above. Then reject or modify the proposal and record your reason. Approval is unavailable for cases requiring manual review.</p></section>}

      {decision && decision.decision_status !== "finalized" && (
        <section className="card">
          <h3>Manual investigation in progress</h3>
          <p>The AI proposal was rejected for further review. This case has not been finally resolved.</p>
          <p><b>{decision.reviewer || "Administrator"}</b> recorded: {decision.reason || decision.admin_notes}</p>
          <p className="muted">AI proposal retained: {OUTCOME_LABEL[decision.ai_recommendation]}. Recorded {decision.decided_at}.</p>
        </section>
      )}

      {decision?.decision_status === "finalized" && (
        <section className="card final">
          <h3>Final decision (simulated)</h3>
          <p>
            <b>{decision.reviewer || "Administrator"}</b> recorded <b>{decision.action}</b>.
            Final outcome: <b>{OUTCOME_LABEL[decision.final_outcome]}</b>
            {decision.final_percent != null && ` (${decision.final_percent}%)`}
          </p>
          <p className="muted">AI had proposed: {OUTCOME_LABEL[decision.ai_recommendation]}</p>
          {decision.admin_notes && <p>Notes: {decision.admin_notes}</p>}
          <p className="muted">Recorded {decision.finalized_at || decision.decided_at}. No real refund was processed.</p>
          <button className="btn" onClick={loadDrafts}>Generate draft messages</button>
          {drafts && <div><p><b>Draft, not sent · Customer</b> <button className="btn" onClick={() => navigator.clipboard.writeText(drafts.customer)}>Copy</button></p><p>{drafts.customer}</p><p><b>Draft, not sent · Owner</b> <button className="btn" onClick={() => navigator.clipboard.writeText(drafts.owner)}>Copy</button></p><p>{drafts.owner}</p></div>}
        </section>
      )}
    </>
  );
}
