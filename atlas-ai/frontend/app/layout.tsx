import "./globals.css";
import type { Metadata, Viewport } from "next";
import Shell from "@/components/Shell";

export const metadata: Metadata = { title: "ATLAS AI — Autonomous Trading Terminal", description: "AI-assisted crypto day-trading agent (paper trading by default)" };
export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#080b10" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body><Shell>{children}</Shell></body>
    </html>
  );
}
