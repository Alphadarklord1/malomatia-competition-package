"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { useAuth } from "./auth-provider";
import { useI18n } from "./i18n-provider";

const navItems = [
  { href: "/dashboard", label: "Dashboard", labelAr: "لوحة التحكم" },
  { href: "/incoming", label: "Incoming", labelAr: "الطلبات الواردة" },
  { href: "/queues", label: "Queues", labelAr: "الطوابير" },
  { href: "/review", label: "Review", labelAr: "المراجعة" },
  { href: "/notifications", label: "Notifications", labelAr: "الإشعارات" },
  { href: "/assistant", label: "Knowledge Assistant", labelAr: "مساعد المعرفة" },
  { href: "/settings", label: "Settings", labelAr: "الإعدادات" },
  { href: "/help", label: "Help", labelAr: "المساعدة" },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { signOut, user } = useAuth();
  const { language, setLanguage, text } = useI18n();

  return (
    <aside className="sidebar">
      <div>
        <div className="eyebrow">Malomatia</div>
        <h1>Gov Triage</h1>
        <p className="muted">{text("Core Ops MVP on Next.js + FastAPI.", "منتج تشغيلي أولي مبني على Next.js وFastAPI.")}</p>
        <div className="actions language-toggle">
          <button className={language === "en" ? "secondary-button active-toggle" : "secondary-button"} type="button" onClick={() => setLanguage("en")}>
            English
          </button>
          <button className={language === "ar" ? "secondary-button active-toggle" : "secondary-button"} type="button" onClick={() => setLanguage("ar")}>
            العربية
          </button>
        </div>
      </div>
      <nav>
        {navItems.map((item) => (
          <Link key={item.href} className={pathname === item.href ? "nav-link active" : "nav-link"} href={item.href}>
            {text(item.label, item.labelAr)}
          </Link>
        ))}
      </nav>
      <div className="sidebar-footer">
        <div className="muted small">{text("Signed in as", "مسجل الدخول باسم")}</div>
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
          {text("Sign out", "تسجيل الخروج")}
        </button>
      </div>
    </aside>
  );
}
