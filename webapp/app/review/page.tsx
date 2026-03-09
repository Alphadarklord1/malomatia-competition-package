"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { RequireAuth } from "../../components/require-auth";
import { Sidebar } from "../../components/sidebar";
import { Topbar } from "../../components/topbar";
import { fetchReviewSummary } from "../../lib/api";
import type { ReviewCase, ReviewSummary } from "../../lib/types";
import { useAuth } from "../../components/auth-provider";

function ReviewSection({ title, subtitle, items }: { title: string; subtitle: string; items: ReviewCase[] }) {
  return (
    <div className="panel">
      <div className="panel-header">
        <h2>{title}</h2>
        <span className="muted">{subtitle}</span>
      </div>
      {items.length === 0 ? (
        <div className="muted">No cases in this review bucket.</div>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Case</th>
              <th>Request</th>
              <th>Flags</th>
              <th>State</th>
              <th>Link</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={`${title}-${item.case.case_id}`}>
                <td>{item.case.case_id}</td>
                <td>{item.case.request_text}</td>
                <td>{item.review_flags.join(", ")}</td>
                <td>{item.case.state}</td>
                <td><Link href={`/cases/${item.case.case_id}`}>Open</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function ReviewPage() {
  const { user } = useAuth();
  const [summary, setSummary] = useState<ReviewSummary | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user) {
      return;
    }
    fetchReviewSummary(user.accessToken)
      .then(setSummary)
      .catch((exc) => setError(exc instanceof Error ? exc.message : "Failed to load review summary"));
  }, [user]);

  return (
    <RequireAuth>
      <main className="layout">
        <Sidebar />
        <section className="content">
          <Topbar title="Review" subtitle="Supervisor-focused view of escalations, low-confidence cases, and recent overrides." />
          {error ? <div className="error-text">{error}</div> : null}
          <div className="stack-grid">
            <ReviewSection title="Escalated Cases" subtitle="Supervisor and human-review backlog" items={summary?.escalated ?? []} />
            <ReviewSection title="Low Confidence" subtitle="Below 0.75 confidence threshold" items={summary?.low_confidence ?? []} />
            <ReviewSection title="Recently Overridden" subtitle="Cases with override history" items={summary?.recently_overridden ?? []} />
          </div>
        </section>
      </main>
    </RequireAuth>
  );
}
