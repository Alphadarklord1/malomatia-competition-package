import type { CaseRecord } from "../lib/types";

export function CaseTable({ cases }: { cases: CaseRecord[] }) {
  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Operational Queue</h2>
        <span className="muted">API-backed version should page, filter, and assign from FastAPI.</span>
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
            <tr key={record.caseId}>
              <td>{record.caseId}</td>
              <td>{record.intent}</td>
              <td>{record.urgency}</td>
              <td>{record.department}</td>
              <td>
                <span className={`pill ${record.slaStatus.toLowerCase()}`}>{record.slaStatus}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
