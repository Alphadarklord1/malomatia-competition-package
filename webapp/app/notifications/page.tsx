"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { RequireAuth } from "../../components/require-auth";
import { Sidebar } from "../../components/sidebar";
import { Topbar } from "../../components/topbar";
import { acknowledgeNotification, fetchNotifications } from "../../lib/api";
import type { NotificationItem } from "../../lib/types";
import { useAuth } from "../../components/auth-provider";

export default function NotificationsPage() {
  const { user } = useAuth();
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [includeAcked, setIncludeAcked] = useState(false);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");

  async function load(nextIncludeAcked = includeAcked) {
    if (!user) {
      return;
    }
    const response = await fetchNotifications(user.accessToken, nextIncludeAcked);
    setItems(response.items);
  }

  useEffect(() => {
    if (!user) {
      return;
    }
    load(includeAcked).catch((exc) => setError(exc instanceof Error ? exc.message : "Failed to load notifications"));
  }, [includeAcked, user]);

  async function ack(notificationId: string) {
    if (!user) {
      return;
    }
    setBusyId(notificationId);
    setError("");
    try {
      await acknowledgeNotification(user.accessToken, notificationId);
      await load(includeAcked);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to acknowledge notification");
    } finally {
      setBusyId("");
    }
  }

  return (
    <RequireAuth>
      <main className="layout">
        <Sidebar />
        <section className="content">
          <Topbar title="Notifications" subtitle="Operational alerts for SLA, quality, and review queue conditions." />
          <div className="panel toolbar toolbar-four">
            <label className="field checkbox-field">
              <span>Show acknowledged</span>
              <input type="checkbox" checked={includeAcked} onChange={(e) => setIncludeAcked(e.target.checked)} />
            </label>
          </div>
          {error ? <div className="error-text">{error}</div> : null}
          <div className="stack-grid">
            {items.map((item) => (
              <div key={item.notification_id} className="panel">
                <div className="panel-header">
                  <div>
                    <h2>{item.title}</h2>
                    <div className="muted small">{item.category} / {item.severity}</div>
                  </div>
                  <span className={`pill ${item.severity === "high" ? "breached" : "at_risk"}`}>
                    {item.severity.toUpperCase()}
                  </span>
                </div>
                <p>{item.message}</p>
                <div className="actions">
                  {item.case_id ? <Link className="secondary-button link-button" href={`/cases/${item.case_id}`}>Open case</Link> : null}
                  {!item.ack_at_utc ? (
                    <button className="primary-button" type="button" disabled={busyId === item.notification_id} onClick={() => ack(item.notification_id)}>
                      {busyId === item.notification_id ? "Acknowledging..." : "Acknowledge"}
                    </button>
                  ) : (
                    <span className="muted">Acknowledged by {item.ack_by_user}</span>
                  )}
                </div>
              </div>
            ))}
            {items.length === 0 ? <div className="panel muted">No notifications for the current filter.</div> : null}
          </div>
        </section>
      </main>
    </RequireAuth>
  );
}
