import { useState } from "react";
import { OUTCOME_LABEL } from "./AIPanel.jsx";

export default function DecisionControls({ analysis, onSubmit }) {
  const [action, setAction] = useState("approve");
  const [outcome, setOutcome] = useState(analysis.recommendation);
  const [percent, setPercent] = useState(analysis.refund_percent ?? 30);
  const [notes, setNotes] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const payload = { action, admin_notes: notes, reviewer };
    if (action === "modify") {
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
            <input type="radio" name="action" checked={action === a} onChange={() => setAction(a)} />
            {a === "approve" ? "Approve AI proposal" : a === "reject" ? "Reject proposal (manual investigation)" : "Modify outcome"}
          </label>
        ))}
      </div>

      {action === "modify" && (
        <div className="grid2">
          <label>Final outcome
            <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              {Object.entries(OUTCOME_LABEL).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
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

      <label>Administrator identity
        <input required value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Administrator name" />
      </label>
      <label>Decision reason
        <textarea required rows="2" value={notes} onChange={(e) => setNotes(e.target.value)}
                  placeholder="Reason for your decision" />
      </label>

      {error && <p className="error">{error}</p>}

      <button className="btn primary" disabled={busy}>
        {busy ? "Saving..." : "Finalize decision (simulated)"}
      </button>
    </form>
  );
}
