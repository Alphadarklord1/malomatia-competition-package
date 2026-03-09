"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { RequireAuth } from "../../components/require-auth";
import { Sidebar } from "../../components/sidebar";
import { Topbar } from "../../components/topbar";
import { approveCase, assignCase, fetchCases, overrideCase } from "../../lib/api";
import type { CaseSummary } from "../../lib/types";
import { useAuth } from "../../components/auth-provider";

type DraftAssignment = {
  team: string;
  user: string;
  reason: string;
};

export default function IncomingPage() {
  const { user } = useAuth();
  const [records, setRecords] = useState<CaseSummary[]>([]);
  const [stateFilter, setStateFilter] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [busyCaseId, setBusyCaseId] = useState("");
  const [drafts, setDrafts] = useState<Record<string, DraftAssignment>>({});

  useEffect(() => {
    if (!user) {
      return;
    }
    fetchCases(user.accessToken, {
      page: 1,
      page_size: 12,
      state: stateFilter || undefined,
      search: search || undefined,
    })
      .then((response) => setRecords(response.items))
      .catch((exc) => setError(exc instanceof Error ? exc.message : "Failed to load incoming requests"));
  }, [search, stateFilter, user]);

  const visibleStates = useMemo(() => ["", "NEW", "TRIAGED", "ASSIGNED"], []);

  function updateDraft(caseId: string, next: Partial<DraftAssignment>) {
    setDrafts((current) => ({
      ...current,
      [caseId]: {
        team: current[caseId]?.team || "Immigration",
        user: current[caseId]?.user || "",
        reason: current[caseId]?.reason || "",
        ...next,
      },
    }));
  }

  async function runAction(caseId: string, action: "approve" | "assign" | "override") {
    if (!user) {
      return;
    }
    setBusyCaseId(caseId);
    setError("");
    try {
      if (action === "approve") {
        await approveCase(user.accessToken, caseId, drafts[caseId]?.reason || "");
      } else if (action === "assign") {
        await assignCase(
          user.accessToken,
          caseId,
          drafts[caseId]?.team || "Immigration",
          drafts[caseId]?.user || "",
          drafts[caseId]?.reason || "",
        );
      } else {
        await overrideCase(user.accessToken, caseId, drafts[caseId]?.reason || "");
      }
      const refreshed = await fetchCases(user.accessToken, {
        page: 1,
        page_size: 12,
        state: stateFilter || undefined,
        search: search || undefined,
      });
      setRecords(refreshed.items);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : `Failed to ${action} case`);
    } finally {
      setBusyCaseId("");
    }
  }

  return (
    <RequireAuth>
      <main className="layout">
        <Sidebar />
        <section className="content">
          <Topbar title="Incoming Requests" subtitle="Card-based triage view for approve, assign, and supervisor override actions." />
          <div className="panel toolbar toolbar-four">
            <label className="field">
              <span>Search</span>
              <input className="input" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Case ID or request text" />
            </label>
            <label className="field">
              <span>State</span>
              <select className="select" value={stateFilter} onChange={(e) => setStateFilter(e.target.value)}>
                {visibleStates.map((item) => (
                  <option key={item || "all"} value={item}>
                    {item || "All incoming"}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {error ? <div className="error-text">{error}</div> : null}
          <div className="card-grid">
            {records.map((record) => {
              const draft = drafts[record.case_id] || { team: record.department, user: "", reason: "" };
              return (
                <div key={record.case_id} className="panel card-panel">
                  <div className="panel-header">
                    <div>
                      <h2>{record.request_text}</h2>
                      <div className="muted small">{record.case_id}</div>
                    </div>
                    <span className={`pill ${record.sla_status.toLowerCase()}`}>{record.sla_status}</span>
                  </div>
                  <div className="detail-grid compact-grid">
                    <div>
                      <p><strong>Intent:</strong> {record.intent}</p>
                      <p><strong>Urgency:</strong> {record.urgency}</p>
                      <p><strong>Department:</strong> {record.department}</p>
                    </div>
                    <div>
                      <p><strong>State:</strong> {record.state}</p>
                      <p><strong>Assigned team:</strong> {record.assigned_team || "Unassigned"}</p>
                      <p><strong>Assigned user:</strong> {record.assigned_user || "Unassigned"}</p>
                    </div>
                  </div>
                  <div className="form-grid">
                    <div className="toolbar toolbar-three">
                      <label className="field">
                        <span>Team</span>
                        <select className="select" value={draft.team} onChange={(e) => updateDraft(record.case_id, { team: e.target.value })}>
                          <option value="Immigration">Immigration</option>
                          <option value="Municipal">Municipal</option>
                          <option value="Licensing">Licensing</option>
                          <option value="Human Review">Human Review</option>
                        </select>
                      </label>
                      <label className="field">
                        <span>Assignee</span>
                        <input className="input" value={draft.user} onChange={(e) => updateDraft(record.case_id, { user: e.target.value })} placeholder="ops_user_1" />
                      </label>
                      <label className="field">
                        <span>Reason</span>
                        <input className="input" value={draft.reason} onChange={(e) => updateDraft(record.case_id, { reason: e.target.value })} placeholder="Why this action?" />
                      </label>
                    </div>
                    <div className="actions">
                      <button className="primary-button" type="button" disabled={busyCaseId === record.case_id} onClick={() => runAction(record.case_id, "approve")}>
                        {busyCaseId === record.case_id ? "Working..." : "Approve"}
                      </button>
                      <button className="secondary-button" type="button" disabled={busyCaseId === record.case_id} onClick={() => runAction(record.case_id, "assign")}>
                        Assign
                      </button>
                      {user?.role === "supervisor" ? (
                        <button className="secondary-button" type="button" disabled={busyCaseId === record.case_id} onClick={() => runAction(record.case_id, "override")}>
                          Override
                        </button>
                      ) : null}
                      <Link className="secondary-button link-button" href={`/cases/${record.case_id}`}>Open detail</Link>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </main>
    </RequireAuth>
  );
}
