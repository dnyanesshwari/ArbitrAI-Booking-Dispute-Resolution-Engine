import { useEffect, useState } from "react";
import { createCase, getCases, getListings } from "../api.js";

const initial = { listing_id: "", amount: "", date: "", time: "", complaint: "", owner_response: "", evidence: "" };

export default function CustomerPortal({ user }) {
  const [cases, setCases] = useState([]);
  const [listings, setListings] = useState([]);
  const [form, setForm] = useState(initial);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    setLoading(true);
    try {
      const [ownCases, availableListings] = await Promise.all([getCases(), getListings()]);
      setCases(ownCases);
      setListings(availableListings);
      setError("");
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  function set(key) { return (event) => setForm((current) => ({ ...current, [key]: event.target.value })); }
  async function submit(event) {
    event.preventDefault();
    const listing = listings.find((item) => item.id === form.listing_id);
    if (!listing) { setError("Choose a listing."); return; }
    setSaving(true); setError(""); setNotice("");
    try {
      const result = await createCase({
        customer: user.display_name,
        listing_id: listing.id,
        booking: { amount: Number(form.amount), date: form.date, time: form.time, space_type: listing.space_type, cancelled_minutes_before: null },
        complaint: form.complaint, owner_response: form.owner_response,
        evidence: form.evidence.split("\n").map((item) => item.trim()).filter(Boolean),
      });
      if (result.duplicate) setNotice(`This looks like an existing dispute (${result.id}); it was not added again.`);
      else { setForm(initial); setNotice(`Dispute ${result.id} was submitted.`); }
      await load();
    } catch (err) { setError(err.message); }
    finally { setSaving(false); }
  }

  return <>
    <div className="row between"><div><h2>Your disputes</h2><p className="muted">Submit a dispute and track its review status here.</p></div></div>
    <form className="card form" onSubmit={submit}>
      <h3>Submit a dispute</h3>
      <div className="grid2">
        <label>Listing<select required value={form.listing_id} onChange={set("listing_id")}><option value="">Select a listing…</option>{listings.map((listing) => <option key={listing.id} value={listing.id}>{listing.title}</option>)}</select></label>
        <label>Amount paid (Rs)<input required type="number" min="1" step="0.01" value={form.amount} onChange={set("amount")} /></label>
        <label>Booking date<input required type="date" value={form.date} onChange={set("date")} /></label>
        <label>Start time<input required type="time" value={form.time} onChange={set("time")} /></label>
      </div>
      <label>What happened?<textarea required minLength={5} rows="3" value={form.complaint} onChange={set("complaint")} /></label>
      <label>Owner response, if available<textarea rows="2" value={form.owner_response} onChange={set("owner_response")} /></label>
      <label>Evidence references (one per line)<textarea rows="2" value={form.evidence} onChange={set("evidence")} /></label>
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="success" role="status">{notice}</p>}
      <button className="btn primary" disabled={saving || loading}>{saving ? "Submitting…" : "Submit dispute"}</button>
    </form>

    <section className="card customer-cases">
      <div className="row between"><h3>Case status</h3><button className="btn" onClick={load} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button></div>
      {loading ? <p className="muted">Loading your disputes…</p> : cases.length === 0 ? <p className="muted">You have not submitted any disputes yet.</p> : <div className="customer-case-list">{cases.map((item) => <article key={item.id} className="customer-case">
        <div className="row between"><strong>{item.id} · {item.listing_title}</strong><span className={`badge ${item.status === "Finalized" ? "status-Finalized" : "status-New"}`}>{item.status}</span></div>
        <p className="muted">Amount in dispute: Rs {Number(item.amount).toLocaleString("en-IN")}</p>
        {item.final_outcome && <p>Final outcome: <strong>{item.final_outcome.replaceAll("_", " ")}</strong></p>}
      </article>)}</div>}
    </section>
  </>;
}
