"use client";

import { useI18n } from "./i18n-provider";

export function Topbar({
  title,
  subtitle,
  titleAr,
  subtitleAr,
}: {
  title: string;
  subtitle: string;
  titleAr?: string;
  subtitleAr?: string;
}) {
  const { text } = useI18n();
  return (
    <section className="hero">
      <div className="eyebrow">{text("Operations", "العمليات")}</div>
      <h2>{text(title, titleAr || title)}</h2>
      <p className="muted">{text(subtitle, subtitleAr || subtitle)}</p>
    </section>
  );
}
