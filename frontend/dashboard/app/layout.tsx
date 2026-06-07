import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Microtrading App",
  description: "Cloud-only automated U.S. equities microtrading research platform — Phase 0",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
