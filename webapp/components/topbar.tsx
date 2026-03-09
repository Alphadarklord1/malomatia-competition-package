export function Topbar({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <section className="hero">
      <div className="eyebrow">Operations</div>
      <h2>{title}</h2>
      <p className="muted">{subtitle}</p>
    </section>
  );
}
