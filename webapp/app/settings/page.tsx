"use client";

import { useEffect, useState } from "react";

import { RequireAuth } from "../../components/require-auth";
import { Sidebar } from "../../components/sidebar";
import { Topbar } from "../../components/topbar";
import { useAuth } from "../../components/auth-provider";
import { useI18n } from "../../components/i18n-provider";
import { createUser, disableUserMfa, fetchUsers, resetUserPassword, setupUserMfa, updateUser } from "../../lib/api";
import type { UserSummary } from "../../lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export default function SettingsPage() {
  const { user } = useAuth();
  const { text } = useI18n();
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [createForm, setCreateForm] = useState({ user_id: "", display_name: "", password: "", role: "operator", status: "pending", enable_mfa: false });
  const [selectedUser, setSelectedUser] = useState("");
  const [passwordReset, setPasswordReset] = useState("NewPassword@123");

  async function loadUsers() {
    if (!user || (user.role !== "supervisor" && user.role !== "auditor")) {
      return;
    }
    const response = await fetchUsers(user.accessToken);
    setUsers(response.items);
  }

  useEffect(() => {
    loadUsers().catch((exc) => setError(exc instanceof Error ? exc.message : "Failed to load settings"));
  }, [user]);

  async function runCreate() {
    if (!user) return;
    setError("");
    setMessage("");
    try {
      await createUser(user.accessToken, createForm);
      setMessage(text("User created", "تم إنشاء المستخدم"));
      setCreateForm({ user_id: "", display_name: "", password: "", role: "operator", status: "pending", enable_mfa: false });
      await loadUsers();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Create user failed");
    }
  }

  async function runExport(path: string, filename: string) {
    if (!user) return;
    const response = await fetch(`${API_BASE_URL}${path}`, { headers: { Authorization: `Bearer ${user.accessToken}` } });
    if (!response.ok) {
      throw new Error(`Export failed (${response.status})`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <RequireAuth>
      <main className="layout">
        <Sidebar />
        <section className="content">
          <Topbar
            title="Settings"
            titleAr="الإعدادات"
            subtitle="Security controls, exports, and supervisor user administration."
            subtitleAr="ضوابط الأمان وعمليات التصدير وإدارة المستخدمين للمشرفين."
          />
          {error ? <div className="error-text">{error}</div> : null}
          {message ? <div className="success-text">{message}</div> : null}
          <div className="two-col">
            <div className="panel">
              <div className="panel-header"><h2>{text("My Account", "حسابي")}</h2></div>
              <p><strong>{text("User", "المستخدم")}:</strong> {user?.displayName}</p>
              <p><strong>{text("Role", "الدور")}:</strong> {user?.role}</p>
              <p><strong>{text("Auth provider", "مزود الدخول")}:</strong> {user?.authProvider}</p>
              <div className="actions">
                <button className="secondary-button" type="button" onClick={() => setupUserMfa(user!.accessToken, user!.userId).then((result) => setMessage(`MFA secret: ${result.mfa_secret || ""}`)).catch((exc) => setError(exc instanceof Error ? exc.message : "MFA setup failed"))}>{text("Setup MFA", "إعداد التحقق الثنائي")}</button>
                <button className="secondary-button" type="button" onClick={() => disableUserMfa(user!.accessToken, user!.userId).then(() => setMessage(text("MFA disabled", "تم تعطيل التحقق الثنائي"))).catch((exc) => setError(exc instanceof Error ? exc.message : "MFA disable failed"))}>{text("Disable MFA", "تعطيل التحقق الثنائي")}</button>
              </div>
            </div>
            <div className="panel">
              <div className="panel-header"><h2>{text("Exports", "التصدير")}</h2></div>
              <div className="actions">
                <button className="secondary-button" type="button" onClick={() => runExport("/cases/export.csv", "cases-export.csv").catch((exc) => setError(exc instanceof Error ? exc.message : "Export failed"))}>{text("Export cases CSV", "تصدير الحالات CSV")}</button>
                <button className="secondary-button" type="button" onClick={() => runExport("/audit/export", "audit-export.jsonl").catch((exc) => setError(exc instanceof Error ? exc.message : "Export failed"))}>{text("Export audit log", "تصدير سجل التدقيق")}</button>
              </div>
            </div>
          </div>

          {user?.role === "supervisor" ? (
            <div className="two-col">
              <div className="panel">
                <div className="panel-header"><h2>{text("Create User", "إنشاء مستخدم")}</h2></div>
                <div className="form-grid">
                  <input className="input" placeholder={text("User ID", "معرف المستخدم")} value={createForm.user_id} onChange={(e) => setCreateForm({ ...createForm, user_id: e.target.value })} />
                  <input className="input" placeholder={text("Display name", "الاسم المعروض")} value={createForm.display_name} onChange={(e) => setCreateForm({ ...createForm, display_name: e.target.value })} />
                  <input className="input" type="password" placeholder={text("Password", "كلمة المرور")} value={createForm.password} onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })} />
                  <select className="select" value={createForm.role} onChange={(e) => setCreateForm({ ...createForm, role: e.target.value })}>
                    <option value="operator">Operator</option>
                    <option value="supervisor">Supervisor</option>
                    <option value="auditor">Auditor</option>
                  </select>
                  <select className="select" value={createForm.status} onChange={(e) => setCreateForm({ ...createForm, status: e.target.value })}>
                    <option value="pending">Pending</option>
                    <option value="active">Active</option>
                    <option value="inactive">Inactive</option>
                  </select>
                  <label className="checkbox-field">
                    <span>{text("Enable MFA", "تفعيل التحقق الثنائي")}</span>
                    <input type="checkbox" checked={createForm.enable_mfa} onChange={(e) => setCreateForm({ ...createForm, enable_mfa: e.target.checked })} />
                  </label>
                  <button className="primary-button" type="button" onClick={runCreate}>{text("Create user", "إنشاء مستخدم")}</button>
                </div>
              </div>
              <div className="panel">
                <div className="panel-header"><h2>{text("User Management", "إدارة المستخدمين")}</h2></div>
                <div className="form-grid">
                  <select className="select" value={selectedUser} onChange={(e) => setSelectedUser(e.target.value)}>
                    <option value="">{text("Select user", "اختر مستخدمًا")}</option>
                    {users.map((entry) => <option key={entry.user_id} value={entry.user_id}>{entry.user_id}</option>)}
                  </select>
                  <div className="actions">
                    <button className="secondary-button" type="button" disabled={!selectedUser} onClick={() => updateUser(user.accessToken, selectedUser, { status: "active" }).then(() => loadUsers()).then(() => setMessage(text("User activated", "تم تفعيل المستخدم"))).catch((exc) => setError(exc instanceof Error ? exc.message : "Update failed"))}>{text("Approve / activate", "اعتماد / تفعيل")}</button>
                    <button className="secondary-button" type="button" disabled={!selectedUser} onClick={() => updateUser(user.accessToken, selectedUser, { status: "inactive" }).then(() => loadUsers()).then(() => setMessage(text("User deactivated", "تم تعطيل المستخدم"))).catch((exc) => setError(exc instanceof Error ? exc.message : "Update failed"))}>{text("Deactivate", "تعطيل")}</button>
                    <button className="secondary-button" type="button" disabled={!selectedUser} onClick={() => setupUserMfa(user.accessToken, selectedUser).then((result) => setMessage(`MFA secret: ${result.mfa_secret || ""}`)).catch((exc) => setError(exc instanceof Error ? exc.message : "MFA setup failed"))}>{text("Reset MFA", "إعادة تعيين التحقق الثنائي")}</button>
                  </div>
                  <input className="input" type="password" value={passwordReset} onChange={(e) => setPasswordReset(e.target.value)} />
                  <button className="secondary-button" type="button" disabled={!selectedUser} onClick={() => resetUserPassword(user.accessToken, selectedUser, passwordReset).then(() => setMessage(text("Password reset", "تمت إعادة تعيين كلمة المرور"))).catch((exc) => setError(exc instanceof Error ? exc.message : "Password reset failed"))}>{text("Reset password", "إعادة تعيين كلمة المرور")}</button>
                </div>
              </div>
            </div>
          ) : null}

          {users.length > 0 ? (
            <div className="panel">
              <div className="panel-header"><h2>{text("User Directory", "دليل المستخدمين")}</h2></div>
              <table className="table">
                <thead>
                  <tr>
                    <th>{text("User", "المستخدم")}</th>
                    <th>{text("Role", "الدور")}</th>
                    <th>{text("Status", "الحالة")}</th>
                    <th>{text("MFA", "التحقق الثنائي")}</th>
                    <th>{text("Failed attempts", "محاولات فاشلة")}</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((entry) => (
                    <tr key={entry.user_id}>
                      <td>{entry.display_name} <span className="muted small">({entry.user_id})</span></td>
                      <td>{entry.role}</td>
                      <td>{entry.status}</td>
                      <td>{entry.mfa_enabled ? text("Enabled", "مفعل") : text("Disabled", "معطل")}</td>
                      <td>{entry.failed_login_attempts}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      </main>
    </RequireAuth>
  );
}
