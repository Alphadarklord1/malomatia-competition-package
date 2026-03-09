"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { useAuth } from "../../components/auth-provider";
import { useI18n } from "../../components/i18n-provider";
import { buildAuthUser, login, register, verifyMfa } from "../../lib/api";

export default function LoginPage() {
  const router = useRouter();
  const { ready, user, signIn } = useAuth();
  const { text } = useI18n();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("supervisor_demo");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("Supervisor@123");
  const [enableMfa, setEnableMfa] = useState(false);
  const [pendingToken, setPendingToken] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [registerResult, setRegisterResult] = useState<{ message: string; secret?: string | null; uri?: string | null } | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (ready && user) {
      router.replace("/dashboard");
    }
  }, [ready, router, user]);

  async function handleLogin(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const result = await login(username, password);
      if (result.mfa_required && result.pending_token) {
        setPendingToken(result.pending_token);
        return;
      }
      if (!result.access_token) {
        throw new Error(result.message || "Login failed");
      }
      const authUser = await buildAuthUser(result.access_token);
      signIn(authUser);
      router.replace("/dashboard");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleVerifyMfa(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const result = await verifyMfa(pendingToken, mfaCode);
      if (!result.access_token) {
        throw new Error(result.message || "Verification failed");
      }
      const authUser = await buildAuthUser(result.access_token);
      signIn(authUser);
      router.replace("/dashboard");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Verification failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleRegister(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setRegisterResult(null);
    try {
      const result = await register(username, displayName, password, enableMfa);
      setRegisterResult({ message: result.message, secret: result.mfa_secret, uri: result.provisioning_uri });
      setMode("login");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Registration failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <div className="login-card">
        <div>
          <div className="eyebrow" style={{ color: "#5f6b76" }}>Malomatia</div>
          <h1>{text("Core Ops MVP Access", "الوصول إلى المنتج التشغيلي")}</h1>
          <p className="muted">{text("Local JWT login, pending-approval signup, and optional TOTP verification.", "تسجيل دخول محلي مع موافقة المشرف وخيار التحقق الثنائي.")}</p>
        </div>

        <div className="actions">
          <button className={mode === "login" ? "primary-button" : "secondary-button"} type="button" onClick={() => setMode("login")}>{text("Sign in", "تسجيل الدخول")}</button>
          <button className={mode === "register" ? "primary-button" : "secondary-button"} type="button" onClick={() => setMode("register")}>{text("Create account", "إنشاء حساب")}</button>
        </div>

        {!pendingToken ? (
          mode === "login" ? (
            <form className="form-grid" onSubmit={handleLogin}>
              <label className="field">
                <span>{text("Username", "اسم المستخدم")}</span>
                <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} />
              </label>
              <label className="field">
                <span>{text("Password", "كلمة المرور")}</span>
                <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
              </label>
              <button className="primary-button" type="submit" disabled={loading}>{loading ? text("Signing in...", "جارٍ تسجيل الدخول...") : text("Sign in", "تسجيل الدخول")}</button>
            </form>
          ) : (
            <form className="form-grid" onSubmit={handleRegister}>
              <label className="field">
                <span>{text("Display name", "الاسم المعروض")}</span>
                <input className="input" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
              </label>
              <label className="field">
                <span>{text("Username", "اسم المستخدم")}</span>
                <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} />
              </label>
              <label className="field">
                <span>{text("Password", "كلمة المرور")}</span>
                <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
              </label>
              <label className="checkbox-field">
                <span>{text("Enable two-step verification", "تفعيل التحقق بخطوتين")}</span>
                <input type="checkbox" checked={enableMfa} onChange={(e) => setEnableMfa(e.target.checked)} />
              </label>
              <button className="primary-button" type="submit" disabled={loading}>{loading ? text("Creating...", "جارٍ الإنشاء...") : text("Create account", "إنشاء حساب")}</button>
            </form>
          )
        ) : (
          <form className="form-grid" onSubmit={handleVerifyMfa}>
            <label className="field">
              <span>{text("Verification code", "رمز التحقق")}</span>
              <input className="input" value={mfaCode} onChange={(e) => setMfaCode(e.target.value)} maxLength={6} />
            </label>
            <div className="actions">
              <button className="primary-button" type="submit" disabled={loading}>{loading ? text("Verifying...", "جارٍ التحقق...") : text("Verify code", "تحقق من الرمز")}</button>
              <button className="secondary-button" type="button" onClick={() => { setPendingToken(""); setMfaCode(""); }}>{text("Back", "رجوع")}</button>
            </div>
          </form>
        )}

        {registerResult ? (
          <div className="panel inset-panel">
            <strong>{text("Registration submitted", "تم إرسال التسجيل")}</strong>
            <p className="muted">{registerResult.message}</p>
            {registerResult.secret ? <p className="muted">{text("MFA secret", "سر التحقق الثنائي")}: <code>{registerResult.secret}</code></p> : null}
            {registerResult.uri ? <p className="muted">{text("Provisioning URI", "رابط التهيئة")}: <code>{registerResult.uri}</code></p> : null}
          </div>
        ) : null}
        {error ? <div className="error-text">{error}</div> : null}
      </div>
    </main>
  );
}
