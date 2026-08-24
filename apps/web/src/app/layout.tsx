import type { Metadata } from "next";
import Link from "next/link";
import { Activity, GitBranch, Upload } from "lucide-react";

import "./globals.css";

export const metadata: Metadata = {
  title: "WorkflowGuard",
  description: "Workflow verification, evaluation, testing, cost intelligence, and repair."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen bg-white">
          <aside className="fixed inset-y-0 left-0 hidden w-64 border-r border-line bg-panel px-5 py-6 lg:block">
            <Link href="/" className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-md bg-ink text-white">
                <GitBranch size={21} />
              </div>
              <div>
                <div className="text-lg font-semibold">WorkflowGuard</div>
                <div className="text-xs text-slate-500">Workflow assurance</div>
              </div>
            </Link>
            <nav className="mt-9 space-y-1">
              <NavLink href="/" icon={<Activity size={18} />} label="Dashboard" />
              <NavLink href="/workflows" icon={<GitBranch size={18} />} label="Workflows" />
              <NavLink href="/upload" icon={<Upload size={18} />} label="Upload" />
            </nav>
          </aside>
          <main className="min-h-screen lg:pl-64">
            <div className="border-b border-line bg-white px-5 py-4 lg:hidden">
              <div className="flex items-center justify-between">
                <Link href="/" className="font-semibold">WorkflowGuard</Link>
                <Link href="/upload" className="rounded-md bg-ink px-3 py-2 text-sm text-white">Upload</Link>
              </div>
            </div>
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}

function NavLink({ href, icon, label }: { href: string; icon: React.ReactNode; label: string }) {
  return (
    <Link href={href} className="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-slate-700 hover:bg-white">
      {icon}
      {label}
    </Link>
  );
}
