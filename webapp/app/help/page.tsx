"use client";

import { RequireAuth } from "../../components/require-auth";
import { Sidebar } from "../../components/sidebar";
import { Topbar } from "../../components/topbar";
import { useI18n } from "../../components/i18n-provider";

export default function HelpPage() {
  const { text } = useI18n();
  return (
    <RequireAuth>
      <main className="layout">
        <Sidebar />
        <section className="content">
          <Topbar
            title="Help"
            titleAr="المساعدة"
            subtitle="Role guide, workflow notes, privacy rules, and beta instructions."
            subtitleAr="دليل الأدوار وملاحظات سير العمل وقواعد الخصوصية وتعليمات النسخة التجريبية."
          />
          <div className="stack-grid">
            <div className="panel">
              <div className="panel-header"><h2>{text("Role Matrix", "مصفوفة الأدوار")}</h2></div>
              <table className="table">
                <thead>
                  <tr>
                    <th>{text("Role", "الدور")}</th>
                    <th>{text("What it can do", "ما الذي يمكنه فعله")}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr><td>Operator</td><td>{text("Approve, assign, move cases into active workflow.", "اعتماد الحالات وتعيينها وتحريكها داخل سير العمل.")}</td></tr>
                  <tr><td>Supervisor</td><td>{text("Override, review, manage users, approve signups, export audit data.", "التجاوز والمراجعة وإدارة المستخدمين والموافقة على التسجيلات وتصدير السجل.")}</td></tr>
                  <tr><td>Auditor</td><td>{text("Read-only review and audit export.", "مراجعة للقراءة فقط وتصدير السجل.")}</td></tr>
                </tbody>
              </table>
            </div>
            <div className="panel">
              <div className="panel-header"><h2>{text("Workflow Guide", "دليل سير العمل")}</h2></div>
              <ul className="plain-list">
                <li>{text("Incoming requests are approved, assigned, or escalated from the Incoming page.", "تتم معالجة الطلبات الواردة من صفحة الطلبات الواردة بالاعتماد أو التعيين أو التصعيد.")}</li>
                <li>{text("Review focuses on escalated, low-confidence, and overridden cases.", "تركز صفحة المراجعة على الحالات المصعدة ومنخفضة الثقة والتي تم تجاوزها.")}</li>
                <li>{text("Notifications surface SLA, quality, and review queue risks.", "تعرض الإشعارات مخاطر اتفاقيات مستوى الخدمة والجودة وطوابير المراجعة.")}</li>
              </ul>
            </div>
            <div className="panel">
              <div className="panel-header"><h2>{text("Privacy and Security", "الخصوصية والأمان")}</h2></div>
              <ul className="plain-list">
                <li>{text("Accounts created through signup remain pending until a supervisor activates them.", "تبقى الحسابات الجديدة في حالة انتظار حتى يعتمدها المشرف.")}</li>
                <li>{text("TOTP verification is supported for local accounts.", "يدعم النظام التحقق بخطوتين للحسابات المحلية.")}</li>
                <li>{text("Audit exports are restricted to supervisors and auditors.", "يقتصر تصدير السجل على المشرفين والمدققين.")}</li>
              </ul>
            </div>
          </div>
        </section>
      </main>
    </RequireAuth>
  );
}
