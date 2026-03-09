import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Malomatia Gov Triage Webapp",
  description: "Production-direction frontend scaffold for the Malomatia Gov-Service Triage platform",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
