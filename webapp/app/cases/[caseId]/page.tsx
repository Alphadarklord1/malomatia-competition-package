"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { RequireAuth } from "../../../components/require-auth";
import { Sidebar } from "../../../components/sidebar";
import { Topbar } from "../../../components/topbar";
import { approveCase, fetchCase, fetchTimeline, overrideCase } from "../../../lib/api";
import type { CaseDetail, TimelineEvent } from "../../../lib/types";
import { useAuth } from "../../../components/auth-provider";

export default function CaseDetailPage() {
  const params = useParams<{ caseId: string }>();
  const { user } = useAuth();
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busyAction, setBusyAction] = useState("");

  useEffect(() => {
    if (!user || !params.caseId) {
      return;
    }
    Promise.all([fetchCase(user.accessToken, params.caseId), fetchTimeline(user.accessToken, params.caseId)])
      .then(([caseData, timelineData]) => {
        setDetail(caseData);
        setTimeline(timelineData.events);
      })
      .catch((exc) => setError(exc instanceof Error ? exc.message : "Failed to load case"));
  }, [params.caseId, user]);

  async function runAction(action: "approve" | "override") {
    if (!user || !params.caseId) {
      return;
    }
    setBusyAction(action);
    setError("");
    try {
      const response = action === "approve"
        ? await approveCase(user.accessToken, params.caseId, reason)
        : await overrideCase(user.accessToken, params.caseId, reason);
      setDetail(response.case);
      const timelineData = await fetchTimeline(user.accessToken, params.caseId);
      setTimeline(timelineData.events);
      setReason("");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : `Failed to ${action} case`);
    } finally {
      setBusyAction("");
    }
  }

  return (
    <RequireAuth>
      <main className="layout">
        <Sidebar />
        <section className="content">
          <Topbar title={`Case ${params.caseId ?? ""}`} subtitle="Detail view with explanation trace and workflow actions." />
          {error ? <div className="error-text">{error}</div> : null}
          {detail ? (
            <>
              <div className="detail-grid">
                <div>
                  <div className="eyebrow" style={{ color: "#5f6b76" }}>Citizen Request</div>
                  <h3>{detail.request_text_en}</h3>
                  <p className="muted">{detail.request_text_ar}</p>
                </div>
                <div>
                  <div className="eyebrow" style={{ color: "#5f6b76" }}>Routing</div>
                  <p><strong>Intent:</strong> {detail.intent_en}</p>
                  <p><strong>Urgency:</strong> {detail.urgency_en}</p>
                  <p><strong>Department:</strong> {detail.department_en}</p>
                  <p><strong>Confidence:</strong> {detail.confidence.toFixed(2)}</p>
                  <p><strong>SLA:</strong> <span className={`pill ${detail.sla_status.toLowerCase()}`}>{detail.sla_status}</span></p>
                </div>
              </div>
              <div className="two-col">
                <div className="panel">
                  <div className="panel-header"><h2>Explanation Trace</h2><span className="muted">Policy-grounded</span></div>
                  <p><strong>Reason:</strong> {detail.explanation.reason_en}</p>
                  <p><strong>Detected keywords:</strong> {detail.explanation.detected_keywords_en}</p>
                  <p><strong>Detected time:</strong> {detail.explanation.detected_time_en}</p>
                  <p><strong>Policy rule:</strong> {detail.explanation.policy_rule}</p>
                  <label className="field">
                    <span>Action reason</span>
                    <textarea className="textarea" value={reason} onChange={(e) => setReason(e.target.value)} rows={4} />
                  </label>
                  <div className="actions">
                    <button className="primary-button" type="button" onClick={() => runAction("approve")} disabled={busyAction !== ""}>
                      {busyAction === "approve" ? "Approving..." : "Approve"}
                    </button>
                    {user?.role === "supervisor" ? (
                      <button className="secondary-button" type="button" onClick={() => runAction("override")} disabled={busyAction !== ""}>
                        {busyAction === "override" ? "Overriding..." : "Override to Human Review"}
                      </button>
                    ) : null}
                  </div>
                </div>
                <div className="panel">
                  <div className="panel-header"><h2>Timeline</h2><span className="muted">Workflow + audit</span></div>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Type</th>
                        <th>Actor</th>
                        <th>Time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {timeline.map((event, index) => (
                        <tr key={`${event.source}-${event.event_type}-${index}`}>
                          <td>{event.source} / {event.event_type}</td>
                          <td>{event.actor_user_id} ({event.actor_role})</td>
                          <td>{new Date(event.timestamp_utc).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          ) : <div className="panel">Loading case...</div>}
        </section>
      </main>
    </RequireAuth>
  );
}
