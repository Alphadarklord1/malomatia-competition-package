import Link from "next/link";

import type { CaseSummary } from "../lib/types";

export function CaseTable({ cases }: { cases: CaseSummary[] }) {
  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Operational Queue</h2>
        <span className="muted">Live API-backed case list</span>
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>Case</th>
            <th>Intent</th>
            <th>Urgency</th>
            <th>Department</th>
            <th>SLA</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((record) => (
            <tr key={record.case_id}>
              <td>
                <Link href={`/cases/${record.case_id}`}>{record.case_id}</Link>
              </td>
              <td>{record.intent}</td>
              <td>{record.urgency}</td>
              <td>{record.department}</td>
              <td>
                <span className={`pill ${record.sla_status.toLowerCase()}`}>{record.sla_status}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
