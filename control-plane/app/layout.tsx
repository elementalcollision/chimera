import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Chimera — Control Plane",
  description: "Read-only observability dashboard for the Chimera agent.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
        <header className="border-b border-zinc-200 dark:border-zinc-800 px-6 py-3 flex items-center gap-6">
          <span className="font-semibold">Chimera</span>
          <span className="text-xs text-zinc-500">control plane · read-only</span>
        </header>
        <main className="p-6 max-w-6xl mx-auto">{children}</main>
      </body>
    </html>
  );
}
