import type { Metadata } from "next";
import "./globals.css";

import { RootProviders } from "@/components/providers/root-providers";

const appName = process.env.NEXT_PUBLIC_APP_NAME ?? "Intelligent Data Platform";

export const metadata: Metadata = {
  title: appName,
  description:
    "Modular ETL and data operations platform: ingestion, pipelines, audits, testing lab, destinations, BI publish, schedules, and in-app notifications.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <RootProviders>{children}</RootProviders>
      </body>
    </html>
  );
}
