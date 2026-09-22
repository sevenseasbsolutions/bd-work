import React, { useState } from "react";
import { api, setToken } from "../api.js";
import { ThemeToggle } from "./ui.jsx";

export default function Login({ onSignedIn }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { token, user } = await api.login(email.trim(), password);
      setToken(token);
      onSignedIn(user);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="gate">
      <form onSubmit={submit} className="enter">
        <span className="brand">MBS</span>
        <div className="field">
          <label htmlFor="email">Email</label>
          <input id="email" type="email" value={email} autoComplete="username"
                 onChange={(e) => setEmail(e.target.value)} required autoFocus />
        </div>
        <div className="field">
          <label htmlFor="password">Password</label>
          <input id="password" type="password" value={password} autoComplete="current-password"
                 onChange={(e) => setPassword(e.target.value)} required />
        </div>
        {error && <p className="small" style={{ color: "var(--bad-text)", margin: 0 }}>{error}</p>}
        <button className="btn primary" disabled={busy} style={{ justifyContent: "center" }}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <div className="row">
          <span className="spacer" />
          <ThemeToggle />
        </div>
      </form>
    </div>
  );
}
