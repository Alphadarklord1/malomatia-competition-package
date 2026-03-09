import { CaseTable } from "../../components/case-table";
import { Sidebar } from "../../components/sidebar";
import { mockCases } from "../../lib/mock";

export default function DashboardPage() {
  return (
    <main className="layout">
      <Sidebar />
      <section className="content">
        <section className="hero">
          <div className="eyebrow">Operations</div>
          <h2>Government AI Triage Dashboard</h2>
          <p className="muted">
            This is the production-direction dashboard shell. Replace mock data with FastAPI calls, then wire auth, RBAC, and
            queue mutations to the API.
          </p>
        </section>
        <section className="metric-grid">
          <div>
            <div className="eyebrow">Open Cases</div>
            <div className="metric-value">128</div>
            <div className="muted">Current active queue volume across departments.</div>
          </div>
          <div>
            <div className="eyebrow">SLA Risk</div>
            <div className="metric-value">14</div>
            <div className="muted">Cases approaching breach thresholds.</div>
          </div>
          <div>
            <div className="eyebrow">Human Review</div>
            <div className="metric-value">9</div>
            <div className="muted">Escalated cases awaiting supervisor action.</div>
          </div>
        </section>
        <CaseTable cases={mockCases} />
      </section>
    </main>
  );
}
