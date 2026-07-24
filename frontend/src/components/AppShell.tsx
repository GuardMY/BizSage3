"use client";

import React from "react";

interface AppShellProps {
  sidebar: React.ReactNode;
  children: React.ReactNode;
}

export default function AppShell({ sidebar, children }: AppShellProps) {
  return (
    <div className="grid h-screen min-w-[1180px] grid-cols-[264px_minmax(0,1fr)] overflow-hidden bg-slate-100">
      <aside className="overflow-hidden border-r border-slate-800">{sidebar}</aside>
      <main className="min-h-0 min-w-0">{children}</main>
    </div>
  );
}
