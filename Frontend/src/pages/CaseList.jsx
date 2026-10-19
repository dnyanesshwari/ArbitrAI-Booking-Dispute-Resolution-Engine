import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getCases, getListings, createCase } from "../api.js";

const EMPTY_FORM = {
  customer: "",
  listing_id: "",
  amount: "",
  date: "",
  time: "",
  cancelled_minutes_before: "",
  complaint: "",
  owner_response: "",
  evidence: "",
};

function IntakeForm({ listings, onCreated, onCancel }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    const listing = listings.find((l) => l.id === form.listing_id);
    if (!listing) return setError("Please choose a listing");
    setSaving(true);
    try {
      const created = await createCase({
        customer: form.customer,
        listing_id: form.listing_id,
        booking: {
          amount: Number(form.amount),
          date: form.date,
          time: form.time,
          space_type: listing.space_type,
          cancelled_minutes_before: form.cancelled_minutes_before
            ? Number(form.cancelled_minutes_before)
            : null,
        },
        complaint: form.complaint,
        owner_response: form.owner_response,
        evidence: form.evidence.split("\n").map((s) => s.trim()).filter(Boolean),
      });
      if (created.duplicate) {
        setError(`Duplicate detected: existing case ${created.id} was kept; no case was added.`);
        return;
      }
      onCreated(created);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="card form" onSubmit={handleSubmit}>
      <h3>New dispute intake</h3>
      <div className="grid2">
        <label>Customer name
          <input required value={form.customer} onChange={set("customer")} />
        </label>
        <label>Listing
          <select required value={form.listing_id} onChange={set("listing_id")}>
            <option value="">Select...</option>
            {listings.map((l) => (
              <option key={l.id} value={l.id}>{l.title}</option>
            ))}
          </select>
        </label>
        <label>Amount paid (Rs)
          <input required type="number" min="1" value={form.amount} onChange={set("amount")} />
        </label>
        <label>Booking date
          <input required type="date" value={form.date} onChange={set("date")} />
        </label>
        <label>Start time
          <input required type="time" value={form.time} onChange={set("time")} />
        </label>
        <label>Cancelled how many minutes before? (optional)
          <input type="number" min="0" value={form.cancelled_minutes_before}
                 onChange={set("cancelled_minutes_before")} />
        </label>
      </div>
      <label>Customer complaint
        <textarea required rows="3" value={form.complaint} onChange={set("complaint")} />
      </label>
      <label>Owner response (optional)
        <textarea rows="2" value={form.owner_response} onChange={set("owner_response")} />
      </label>
      <label>Evidence references (optional, one per line)
        <textarea rows="2" value={form.evidence} onChange={set("evidence")} />
      </label>
      {error && <p className="error">{error}</p>}
      <div className="row">
        <button className="btn primary" disabled={saving}>
          {saving ? "Saving..." : "Create case"}
        </button>
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

export default function CaseList() {
  const [cases, setCases] = useState([]);
  const [listings, setListings] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  async function load() {
    try {
      setCases(await getCases());
      setListings(await getListings());
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => { load(); }, []);
  const filteredCases = cases.filter((c) => {
    const matchesText = `${c.id} ${c.customer} ${c.listing_title}`.toLowerCase().includes(query.toLowerCase());
    return matchesText && (statusFilter === "all" || c.status === statusFilter);
  });

  return (
    <>
      <div className="row between">
        <h2>Disputes</h2>
        <button className="btn primary" onClick={() => setShowForm(true)}>+ New dispute</button>
      </div>
      <div className="toolbar"><input aria-label="Search disputes" placeholder="Search case, customer or listing" value={query} onChange={(e) => setQuery(e.target.value)} /><select aria-label="Filter by status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}><option value="all">All statuses</option><option>New</option><option>AI Analyzed</option><option>Finalized</option></select></div>
      {error && <p className="error">Could not load cases: {error}. Is the backend running?</p>}
      {showForm && (
        <IntakeForm
          listings={listings}
          onCancel={() => setShowForm(false)}
          onCreated={() => { setShowForm(false); load(); }}
        />
      )}
      <table className="table">
        <thead>
          <tr>
            <th>Case</th><th>Customer</th><th>Space</th><th>Amount</th>
            <th>Issues (AI)</th><th>Status</th>
          </tr>
        </thead>
        <tbody>
          {filteredCases.map((c) => (
            <tr key={c.id}>
              <td><Link to={`/cases/${c.id}`}>{c.id}</Link></td>
              <td>{c.customer}</td>
              <td>{c.listing_title}</td>
              <td>Rs {c.amount.toLocaleString("en-IN")}</td>
              <td>{c.issues.length ? c.issues.join(", ").replaceAll("_", " ") : "-"}</td>
              <td><span className={`badge status-${c.status.replace(" ", "")}`}>{c.status}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
