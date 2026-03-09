"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { RequireAuth } from "../../components/require-auth";
import { Sidebar } from "../../components/sidebar";
import { Topbar } from "../../components/topbar";
import { fetchCases } from "../../lib/api";
import type { CaseSummary, PaginatedCases } from "../../lib/types";
import { useAuth } from "../../components/auth-provider";

export default function QueuesPage() {
  const { user } = useAuth();
  const [department, setDepartment] = useState("");
  const [state, setState] = useState("");
  const [urgency, setUrgency] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<PaginatedCases | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user) {
      return;
    }
    fetchCases(user.accessToken, { department, state, urgency, page, page_size: 10 })
      .then(setData)
      .catch((exc) => setError(exc instanceof Error ? exc.message : "Failed to load queue"));
  }, [department, page, state, urgency, user]);

  return (
    <RequireAuth>
      <main className="layout">
        <Sidebar />
        <section className="content">
          <Topbar title="Operational Queues" subtitle="Filterable queue view backed by the FastAPI case list endpoint." />
          <div className="panel">
            <div className="toolbar">
              <label className="field">
                <span>Department</span>
                <select className="select" value={department} onChange={(e) => { setPage(1); setDepartment(e.target.value); }}>
                  <option value="">All</option>
                  <option value="Immigration">Immigration</option>
                  <option value="Municipal">Municipal</option>
                  <option value="Licensing">Licensing</option>
                </select>
              </label>
              <label className="field">
                <span>State</span>
                <select className="select" value={state} onChange={(e) => { setPage(1); setState(e.target.value); }}>
                  <option value="">All</option>
                  <option value="NEW">NEW</option>
                  <option value="TRIAGED">TRIAGED</option>
                  <option value="ESCALATED">ESCALATED</option>
                </select>
              </label>
              <label className="field">
                <span>Urgency</span>
                <select className="select" value={urgency} onChange={(e) => { setPage(1); setUrgency(e.target.value); }}>
                  <option value="">All</option>
                  <option value="Urgent">Urgent</option>
                  <option value="Warning">Warning</option>
                </select>
              </label>
              <div className="field">
                <span>Page</span>
                <div className="actions">
                  <button className="secondary-button" type="button" onClick={() => setPage((value) => Math.max(1, value - 1))}>Prev</button>
                  <button className="secondary-button" type="button" onClick={() => setPage((value) => value + 1)}>Next</button>
                </div>
              </div>
            </div>
          </div>
          {error ? <div className="error-text">{error}</div> : null}
          <div className="panel">
            <div className="panel-header">
              <h2>Cases</h2>
              <span className="muted">{data?.total ?? 0} total</span>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Request</th>
                  <th>Intent</th>
                  <th>Urgency</th>
                  <th>Department</th>
                  <th>State</th>
                  <th>SLA</th>
                </tr>
              </thead>
              <tbody>
                {(data?.items ?? []).map((record: CaseSummary) => (
                  <tr key={record.case_id}>
                    <td><Link href={`/cases/${record.case_id}`}>{record.case_id}</Link></td>
                    <td>{record.request_text}</td>
                    <td>{record.intent}</td>
                    <td>{record.urgency}</td>
                    <td>{record.department}</td>
                    <td>{record.state}</td>
                    <td><span className={`pill ${record.sla_status.toLowerCase()}`}>{record.sla_status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </RequireAuth>
  );
}
