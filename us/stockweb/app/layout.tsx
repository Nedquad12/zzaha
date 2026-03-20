import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Stock Scoring Dashboard",
  description: "US Equity Scoring System",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
