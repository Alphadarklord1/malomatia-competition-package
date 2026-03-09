"use client";

import { useEffect, useState } from "react";

import { RequireAuth } from "../../components/require-auth";
import { Sidebar } from "../../components/sidebar";
import { Topbar } from "../../components/topbar";
import { CaseTable } from "../../components/case-table";
import { fetchCases, fetchDashboardSummary } from "../../lib/api";
import type { CaseSummary, DashboardSummary } from "../../lib/types";
import { useAuth } from "../../components/auth-provider";

export default function DashboardPage() {
  const { user } = useAuth();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user) {
      return;
    }
    Promise.all([
      fetchDashboardSummary(user.accessToken),
      fetchCases(user.accessToken, { page: 1, page_size: 5 }),
    ])
      .then(([dashboard, queue]) => {
        setSummary(dashboard);
        setCases(queue.items);
      })
      .catch((exc) => setError(exc instanceof Error ? exc.message : "Failed to load dashboard"));
  }, [user]);

  return (
    <RequireAuth>
      <main className="layout">
        <Sidebar />
        <section className="content">
          <Topbar title="Government AI Triage Dashboard" subtitle="Live dashboard backed by FastAPI and seeded Postgres data." />
          {error ? <div className="error-text">{error}</div> : null}
          <section className="metric-grid">
            <div>
              <div className="eyebrow" style={{ color: "#5f6b76" }}>Open Cases</div>
              <div className="metric-value">{summary?.open_cases ?? "--"}</div>
              <div className="muted">Current active queue volume.</div>
            </div>
            <div>
              <div className="eyebrow" style={{ color: "#5f6b76" }}>SLA Risk</div>
              <div className="metric-value">{summary?.sla_at_risk ?? "--"}</div>
              <div className="muted">Cases at risk or already breached.</div>
            </div>
            <div>
              <div className="eyebrow" style={{ color: "#5f6b76" }}>Escalated</div>
              <div className="metric-value">{summary?.escalated_cases ?? "--"}</div>
              <div className="muted">Cases currently in supervisor or human review flow.</div>
            </div>
            <div>
              <div className="eyebrow" style={{ color: "#5f6b76" }}>Overrides</div>
              <div className="metric-value">{summary?.override_count ?? "--"}</div>
              <div className="muted">Supervisor override events in the database.</div>
            </div>
          </section>
          <div className="two-col">
            <CaseTable cases={cases} />
            <div className="panel">
              <div className="panel-header">
                <h2>Queue Snapshot</h2>
                <span className="muted">Open case distribution</span>
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Department</th>
                    <th>Count</th>
                  </tr>
                </thead>
                <tbody>
                  {(summary?.by_department ?? []).map((row) => (
                    <tr key={row.department}>
                      <td>{row.department}</td>
                      <td>{row.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </main>
    </RequireAuth>
  );
}
