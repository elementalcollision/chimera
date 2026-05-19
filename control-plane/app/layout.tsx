import "./tokens.css";
import "./canvas-styles.css";
import "./globals.css";
import "react-grid-layout/css/styles.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Chimera · Control Plane",
  description: "Read-only observability dashboard for the Chimera agent.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&display=swap"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
