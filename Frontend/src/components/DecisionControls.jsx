import { useState } from "react";
import { OUTCOME_LABEL } from "../outcomeLabels.js";

export default function DecisionControls({ analysis, onSubmit, pendingManualReview = false }) {
  const [action, setAction] = useState(analysis.recommendation === "manual_review" ? "reject" : "approve");
  const [outcome, setOutcome] = useState(analysis.recommendation);
  const [percent, setPercent] = useState(analysis.refund_percent ?? 30);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selectedAction = pendingManualReview ? "modify" : (analysis.recommendation === "manual_review" && action === "approve" ? "reject" : action);

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const payload = { action: selectedAction, admin_notes: notes };
    if (selectedAction === "modify") {
      payload.final_outcome = outcome;
      if (outcome === "partial_refund") payload.final_percent = Number(percent);
    }
    try { await onSubmit(payload); } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h3>Admin decision</h3>
      <div className="banner pending">Simulated: no real refund will be processed.</div>

      <div className="row">
        {["approve", "reject", "modify"].map((a) => (
          <label key={a} className="radio">
            <input type="radio" name="action" checked={selectedAction === a} disabled={busy || (a === "approve" && (pendingManualReview || analysis.recommendation === "manual_review")) || (a === "reject" && pendingManualReview)} onChange={() => setAction(a)} />
            {a === "approve" ? "Approve AI proposal" : a === "reject" ? pendingManualReview ? "Already in manual investigation" : "Reject proposal (manual investigation)" : pendingManualReview ? "Record final outcome after investigation" : "Modify outcome"}
          </label>
        ))}
      </div>

      {selectedAction === "modify" && (
        <div className="grid2">
          <label>Final outcome
            <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              {Object.entries(OUTCOME_LABEL).map(([k, v]) => (
                <option key={k} value={k} disabled={pendingManualReview && k === "manual_review"}>{v}</option>
              ))}
            </select>
          </label>
          {outcome === "partial_refund" && (
            <label>Refund percent (policy allows 30 or 50)
              <select value={percent} onChange={(e) => setPercent(e.target.value)}><option value={30}>30%</option><option value={50}>50%</option></select>
            </label>
          )}
        </div>
      )}

      <p className="muted">Your signed-in administrator account will be recorded as the reviewer. A final outcome is required for modify.</p>
      <label>Decision reason
        <textarea required rows="2" value={notes} onChange={(e) => setNotes(e.target.value)}
                  placeholder="Reason for your decision" />
      </label>

      {error && <p className="error">{error}</p>}

      <button className="btn primary" disabled={busy}>
        {busy ? "Saving..." : selectedAction === "reject" || (selectedAction === "modify" && outcome === "manual_review") ? "Send to manual investigation" : "Save final decision (simulated)"}
      </button>
    </form>
  );
}
