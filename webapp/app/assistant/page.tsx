"use client";

import { FormEvent, useState } from "react";

import { RequireAuth } from "../../components/require-auth";
import { Sidebar } from "../../components/sidebar";
import { Topbar } from "../../components/topbar";
import { queryRag } from "../../lib/api";
import type { RagResponse } from "../../lib/types";
import { useAuth } from "../../components/auth-provider";

export default function AssistantPage() {
  const { user } = useAuth();
  const [query, setQuery] = useState("What is the SLA for urgent cases?");
  const [department, setDepartment] = useState("");
  const [result, setResult] = useState<RagResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!user) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await queryRag(user.accessToken, query, 5, department || undefined);
      setResult(response);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "RAG query failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <RequireAuth>
      <main className="layout">
        <Sidebar />
        <section className="content">
          <Topbar title="Knowledge Assistant" subtitle="Real RAG endpoint backed by the domain policy corpus." />
          <form className="panel form-grid" onSubmit={onSubmit}>
            <label className="field">
              <span>Question</span>
              <textarea className="textarea" rows={4} value={query} onChange={(e) => setQuery(e.target.value)} />
            </label>
            <label className="field">
              <span>Department hint</span>
              <select className="select" value={department} onChange={(e) => setDepartment(e.target.value)}>
                <option value="">Auto / none</option>
                <option value="Immigration">Immigration</option>
                <option value="Municipal">Municipal</option>
                <option value="Licensing">Licensing</option>
                <option value="Operations">Operations</option>
              </select>
            </label>
            <button className="primary-button" type="submit" disabled={loading}>{loading ? "Retrieving..." : "Retrieve"}</button>
            {error ? <div className="error-text">{error}</div> : null}
          </form>
          {result ? (
            <div className="two-col">
              <div className="panel">
                <div className="panel-header"><h2>Answer</h2><span className="muted">{result.used_llm ? "OpenAI-assisted" : "Local retrieval fallback"}</span></div>
                <pre className="trace">{result.answer}</pre>
              </div>
              <div className="panel">
                <div className="panel-header"><h2>Retrieved Evidence</h2><span className="muted">{result.hits.length} hits</span></div>
                {result.hits.map((hit) => (
                  <div key={hit.chunk_id} className="panel" style={{ boxShadow: "none", padding: 12, marginBottom: 12 }}>
                    <strong>{hit.doc_id} / {hit.chunk_id}</strong>
                    <p className="muted">{hit.title}</p>
                    <pre className="trace">{hit.text}</pre>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </section>
      </main>
    </RequireAuth>
  );
}
