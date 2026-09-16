import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "InsightEngine",
  description: "Personal video knowledge system"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
