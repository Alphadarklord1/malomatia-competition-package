const navItems = [
  "Dashboard",
  "Incoming Requests",
  "Queues",
  "Review",
  "Knowledge Assistant",
  "Notifications",
  "Settings",
];

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div>
        <div className="eyebrow">Malomatia</div>
        <h1>Gov Triage</h1>
        <p className="muted">Production-direction React shell for the public-service operations platform.</p>
      </div>
      <nav>
        {navItems.map((item) => (
          <a key={item} className={item === "Dashboard" ? "nav-link active" : "nav-link"} href="#">
            {item}
          </a>
        ))}
      </nav>
    </aside>
  );
}
