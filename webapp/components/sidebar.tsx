"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { useAuth } from "./auth-provider";

const navItems = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/incoming", label: "Incoming" },
  { href: "/queues", label: "Queues" },
  { href: "/review", label: "Review" },
  { href: "/notifications", label: "Notifications" },
  { href: "/assistant", label: "Knowledge Assistant" },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { signOut, user } = useAuth();

  return (
    <aside className="sidebar">
      <div>
        <div className="eyebrow">Malomatia</div>
        <h1>Gov Triage</h1>
        <p className="muted">Core Ops MVP on Next.js + FastAPI.</p>
      </div>
      <nav>
        {navItems.map((item) => (
          <Link key={item.href} className={pathname === item.href ? "nav-link active" : "nav-link"} href={item.href}>
            {item.label}
          </Link>
        ))}
      </nav>
      <div className="sidebar-footer">
        <div className="muted small">Signed in as</div>
        <strong>{user?.displayName}</strong>
        <div className="muted small">{user?.role}</div>
        <button
          className="secondary-button"
          type="button"
          onClick={() => {
            signOut();
            router.replace("/login");
          }}
        >
          Sign out
        </button>
      </div>
    </aside>
  );
}
