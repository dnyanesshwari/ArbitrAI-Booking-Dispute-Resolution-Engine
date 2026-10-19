export const OUTCOME_LABEL = {
  full_refund: "Full refund",
  partial_refund: "Partial refund",
  no_refund: "No refund",
  manual_review: "Manual investigation",
};

export default function AIPanel({ analysis: a, listing, booking, evidence = [] }) {
  return (
    <div>
      <div className="banner pending">
        {a.status}: nothing is final until an admin decides.
      </div>

      {a.guardrail_notes?.length > 0 && (
        <div className="banner warn">
          {a.guardrail_notes.map((n) => <div key={n}>{n}</div>)}
        </div>
      )}

      <div className="proposal">
        <div>
          <span className="muted">Proposed outcome</span>
          <h2>
            {OUTCOME_LABEL[a.recommendation]}
            {a.refund_percent != null && ` (${a.refund_percent}%)`}
          </h2>
        </div>
        <span className={`badge conf-${a.confidence}`}>Confidence: {a.confidence}</span>
      </div>

      <p><b>Issues detected:</b>{" "}
        {a.issue_categories.map((i) => (
          <span key={i} className="badge issue">{i.replaceAll("_", " ")}</span>
        ))}
      </p>

      <p>{a.explanation}</p>

      <section className="box">
        <h4>Evidence comparison</h4>
        <p><b>Listing promises:</b> {(listing?.promises ?? []).join(" / ") || "None recorded"}</p>
        <p><b>Booking record:</b> {booking?.space_type}, Rs {Number(booking?.amount ?? 0).toLocaleString("en-IN")} on {booking?.date} at {booking?.time}{booking?.cancelled_minutes_before != null ? ` / cancelled ${booking.cancelled_minutes_before} minutes before` : ""}</p>
        <p><b>Submitted evidence:</b> {evidence.length ? evidence.join(" / ") : "None submitted"}</p>
      </section>

      <div className="grid2">
        <div className="box facts-box">
          <h4>Verified facts</h4>
          {a.verified_facts.length === 0 && <p className="muted">None</p>}
          <ul>
            {a.verified_facts.map((f, i) => (
              <li key={i}>{f.fact} <em>({f.source})</em></li>
            ))}
          </ul>
        </div>
        <div className="box allegations-box">
          <h4>Customer allegations</h4>
          {a.allegations.filter((x) => x.made_by === "customer").length === 0 && <p className="muted">None</p>}
          <ul>
            {a.allegations.filter((x) => x.made_by === "customer").map((x, i) => (
              <li key={i}>{x.claim}</li>
            ))}
          </ul>
        </div>
        <div className="box allegations-box">
          <h4>Owner allegations</h4>
          {(a.owner_allegations ?? a.allegations.filter((x) => x.made_by === "owner").map((x) => x.claim)).length === 0 && <p className="muted">None</p>}
          <ul>{(a.owner_allegations ?? a.allegations.filter((x) => x.made_by === "owner").map((x) => x.claim)).map((claim, i) => <li key={i}>{claim}</li>)}</ul>
        </div>
        <div className="box unknowns-box">
          <h4>Unknowns</h4>
          {a.unknowns.length === 0 && <p className="muted">None</p>}
          <ul>
            {a.unknowns.map((u, i) => (
              <li key={i}>
                {u.critical && <b className="crit">[CRITICAL] </b>}
                {u.question} <em>{u.why_it_matters}</em>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <h4>Policy references</h4>
      {a.policy_references.length === 0 && <p className="muted">No policy cited — manual review required.</p>}
      <ul>
        {a.policy_references.map((p) => (
          <li key={p.clause_id}><b>{p.clause_id}</b> : {p.rule}<br /><span>{p.relevance}</span></li>
        ))}
      </ul>

      <h4>Evidence gaps</h4>
      {a.evidence_gaps.length === 0 ? (
        <p className="muted">None</p>
      ) : (
        <ul>{a.evidence_gaps.map((g, i) => <li key={i}>{g}</li>)}</ul>
      )}
    </div>
  );
}
