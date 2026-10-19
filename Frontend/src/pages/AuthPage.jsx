import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { login, register } from "../api.js";
import "../App.css";

export default function AuthPage({ mode, onAuthenticated }) {
  const isRegister = mode === "register";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = isRegister
        ? await register({ email, password, display_name: displayName })
        : await login({ email, password });
      onAuthenticated(result.user);
      navigate(result.user.role === "admin" ? "/" : "/portal", { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <main className="auth-page">
    <Link to="/" className="brand auth-brand"><div className="brand-icon">A</div><div><h2>ArbitrAI</h2><span>Dispute Intelligence</span></div></Link>
    <form className="card auth-card" onSubmit={submit}>
      <p className="eyebrow">CUSTOMER PORTAL</p>
      <h1>{isRegister ? "Create your account" : "Welcome back"}</h1>
      <p className="muted">{isRegister ? "Submit and track your booking disputes." : "Sign in to continue to your disputes."}</p>
      {isRegister && <label>Your name<input autoComplete="name" required maxLength={100} value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label>}
      <label>Email<input type="email" autoComplete="email" required maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} /></label>
      <label>Password<input type="password" autoComplete={isRegister ? "new-password" : "current-password"} required minLength={isRegister ? 12 : 1} maxLength={72} value={password} onChange={(event) => setPassword(event.target.value)} />{isRegister && <small>Use at least 12 characters.</small>}</label>
      {error && <p className="error" role="alert">{error}</p>}
      <button className="btn primary" disabled={busy}>{busy ? "Please wait…" : isRegister ? "Create customer account" : "Sign in"}</button>
      <p className="auth-switch">{isRegister ? "Already registered?" : "New to ArbitrAI?"} <Link to={isRegister ? "/login" : "/register"}>{isRegister ? "Sign in" : "Create an account"}</Link></p>
    </form>
  </main>;
}
