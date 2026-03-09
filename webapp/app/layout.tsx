import type { Metadata } from "next";

import { AuthProvider } from "../components/auth-provider";
import { I18nProvider } from "../components/i18n-provider";
import "./globals.css";

export const metadata: Metadata = {
  title: "Malomatia Gov Triage Webapp",
  description: "Core Ops MVP for the Malomatia Gov-Service Triage platform",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" dir="ltr">
      <body>
        <I18nProvider>
          <AuthProvider>{children}</AuthProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
