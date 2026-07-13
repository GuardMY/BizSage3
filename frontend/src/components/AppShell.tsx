"use client";

/* =============================================================================
 * AppShell – Main layout wrapper.
 *
 * Full-height flex layout:
 *   Left: SessionSidebar (w-64, dark bg)
 *   Right: Main workspace area with children
 *
 * Responsive: sidebar collapses on mobile, toggled via hamburger button.
 * ============================================================================= */

import React, { useState } from "react";

interface AppShellProps {
  sidebar: React.ReactNode;
  children: React.ReactNode;
}

export default function AppShell({ sidebar, children }: AppShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-gray-50">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`
          fixed inset-y-0 left-0 z-40 w-64
          transform transition-transform duration-300 ease-in-out
          lg:relative lg:translate-x-0
          ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}
        `}
      >
        {sidebar}
      </aside>

      {/* Main area */}
      <main className="flex flex-1 flex-col min-w-0">
        {/* Mobile header with hamburger */}
        <div className="flex items-center gap-2 border-b border-gray-200 bg-white px-4 py-2 lg:hidden">
          <button
            onClick={() => setSidebarOpen(true)}
            className="rounded-md p-1.5 text-gray-600 hover:bg-gray-100 transition-colors"
            aria-label="打开侧边栏"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
            </svg>
          </button>
          <span className="text-sm font-semibold text-gray-700">BizSage3</span>
        </div>

        {/* Children content */}
        {children}
      </main>
    </div>
  );
}
