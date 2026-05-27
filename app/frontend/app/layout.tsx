import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DRAAD — Dispatch & Regelcontrole voor Alliander Dienst",
  description: "BEI-BLS compliant dispatch coverage analysis for Liander field operations",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="nl" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
