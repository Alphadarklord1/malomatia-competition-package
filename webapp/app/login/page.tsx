"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { useAuth } from "../../components/auth-provider";
import { login } from "../../lib/api";

export default function LoginPage() {
  const router = useRouter();
  const { ready, user, signIn } = useAuth();
  const [username, setUsername] = useState("supervisor_demo");
  const [password, setPassword] = useState("Supervisor@123");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (ready && user) {
      router.replace("/dashboard");
    }
  }, [ready, router, user]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const authUser = await login(username, password);
      signIn(authUser);
      router.replace("/dashboard");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <form className="login-card" onSubmit={onSubmit}>
        <div>
          <div className="eyebrow" style={{ color: "#5f6b76" }}>Malomatia</div>
          <h1>Core Ops MVP Login</h1>
          <p className="muted">Use a seeded local account to access the FastAPI-backed product slice.</p>
        </div>
        <div className="form-grid">
          <label className="field">
            <span>Username</span>
            <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} />
          </label>
          <label className="field">
            <span>Password</span>
            <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
        </div>
        {error ? <div className="error-text">{error}</div> : null}
        <button className="primary-button" type="submit" disabled={loading}>
          {loading ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </main>
  );
}
