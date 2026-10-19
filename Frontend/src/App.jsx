import { useEffect, useState } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { getCurrentUser, getStats, logout } from "./api.js";
import CaseList from "./pages/CaseList.jsx";
import CaseDetail from "./pages/CaseDetail.jsx";
import AuthPage from "./pages/AuthPage.jsx";
import CustomerPortal from "./pages/CustomerPortal.jsx";
import "./App.css";

function Workspace({ user, onLogout }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [statsError, setStatsError] = useState("");
  const [logoutError, setLogoutError] = useState("");
  const isAdmin = user.role === "admin";
  useEffect(() => {
    if (!isAdmin) return;
    getStats().then(setStats).catch((error) => setStatsError(error.message));
  }, [location.pathname, isAdmin]);

  async function signOut() {
    setLogoutError("");
    try { await logout(); onLogout(); navigate("/login", { replace: true }); }
    catch (error) { setLogoutError(`Could not sign out: ${error.message}`); }
  }

  return <div className="app">
    <aside className="sidebar">
      <Link to={isAdmin ? "/" : "/portal"} className="brand"><div className="brand-icon">A</div><div><h2>ArbitrAI</h2><span>Dispute Intelligence</span></div></Link>
      <p className="nav-label">WORKSPACE</p>
      <nav>{isAdmin ? <><Link className={`nav-item ${location.pathname === "/" ? "active" : ""}`} to="/">▦ Dashboard</Link><Link className="nav-item" to="/">＋ Disputes</Link></> : <Link className={`nav-item ${location.pathname === "/portal" ? "active" : ""}`} to="/portal">Your disputes</Link>}</nav>
      <div className="sidebar-bottom"><div className="avatar">{user.display_name.slice(0, 2).toUpperCase()}</div><div><strong>{user.display_name}</strong><span>{isAdmin ? "Administrator" : "Customer"}</span></div><button className="btn logout-button" onClick={signOut}>Log out</button></div>
    </aside>
    <main className="main-content">
      <header className="topbar"><div><p className="eyebrow">WORKSPACE / {isAdmin ? "ADMINISTRATION" : "CUSTOMER PORTAL"}</p><h1>{isAdmin ? "Dispute Dashboard" : "Your booking disputes"}</h1></div><div className="system-status"><span className="status-dot" />{isAdmin ? "Live case management" : "Account secured"}</div></header>
      {logoutError && <p className="error" role="alert">{logoutError}</p>}
      {isAdmin && <section className="stats">
        {[["Total disputes", stats?.total_disputes, "All recorded cases"], ["Pending reviews", stats?.pending_reviews, "Awaiting administrator decision"], ["Resolved cases", stats?.resolved_cases, `Disputed amount: Rs ${Number(stats?.disputed_amount ?? 0).toLocaleString("en-IN")}`]].map(([title, value, note]) => <article className="stat-card" key={title}><span>{title}</span><strong>{value ?? "—"}</strong><small>{statsError ? "Backend statistics unavailable" : note}</small></article>)}
      </section>}
      <Routes>
        {isAdmin ? <>
          <Route path="/" element={<CaseList />} />
          <Route path="/cases/:id" element={<CaseDetail />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </> : <>
          <Route path="/portal" element={<CustomerPortal user={user} />} />
          <Route path="*" element={<Navigate to="/portal" replace />} />
        </>}
      </Routes>
      <footer>ArbitrAI · Booking Dispute Engine<span>AI-assisted case management · No refunds are processed</span></footer>
    </main>
  </div>;
}

function AppRoutes() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);
  useEffect(() => { getCurrentUser().then((result) => setUser(result.user)).catch(() => setUser(null)).finally(() => setChecking(false)); }, []);
  if (checking) return <main className="auth-page"><p className="muted">Checking your session…</p></main>;
  return <Routes>
    <Route path="/login" element={user ? <Navigate to={user.role === "admin" ? "/" : "/portal"} replace /> : <AuthPage mode="login" onAuthenticated={setUser} />} />
    <Route path="/register" element={user ? <Navigate to={user.role === "admin" ? "/" : "/portal"} replace /> : <AuthPage mode="register" onAuthenticated={setUser} />} />
    <Route path="*" element={user ? <Workspace user={user} onLogout={() => setUser(null)} /> : <Navigate to="/login" replace />} />
  </Routes>;
}

export default function App() { return <BrowserRouter><AppRoutes /></BrowserRouter>; }
