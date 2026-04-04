import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Vulcan OmniPro 220 — Technical Expert",
  description: "AI-powered technical support for the Vulcan OmniPro 220 multiprocess welder",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet" />
      </head>
      <body className="bg-vulcan-bg text-vulcan-text antialiased">{children}</body>
    </html>
  );
}
