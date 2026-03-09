import { Sidebar } from "../components/sidebar";

export default function HomePage() {
  return (
    <main className="layout">
      <Sidebar />
      <section className="content">
        <section className="hero">
          <div className="eyebrow">Production Direction</div>
          <h2>Next.js + FastAPI replacement scaffold</h2>
          <p className="muted">
            This path keeps the Streamlit prototype for competition/demo use while introducing the architecture needed for a real
            multi-user platform: typed APIs, PostgreSQL, service-side auth, and a React frontend.
          </p>
        </section>
      </section>
    </main>
  );
}
