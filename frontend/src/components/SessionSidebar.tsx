"use client";

/* =============================================================================
 * SessionSidebar – Left sidebar with session list.
 *
 * Features:
 *   - "BizSage3" branding at top
 *   - "新建诊断" (New Diagnosis) button
 *   - Scrollable session list with status badge, score, date
 *   - Active session highlighted
 *   - Delete button on hover
 *   - Loading skeleton state
 * ============================================================================= */

import React from "react";
import { AlertTriangle, Inbox, LogOut, Plus, Settings, X } from "lucide-react";
import type { SessionSummary } from "@/types";

interface SessionSidebarProps {
  sessions: SessionSummary[];
  activeId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
  isAdmin: boolean;
  onAdmin: () => void;
  onLogout: () => void;
}

export default function SessionSidebar({
  sessions,
  activeId,
  loading,
  onSelect,
  onCreate,
  onDelete,
  isAdmin,
  onAdmin,
  onLogout,
}: SessionSidebarProps) {
  return (
    <div className="flex h-full flex-col bg-slate-950 text-slate-100">
      {/* Branding */}
      <div className="flex h-16 items-center gap-3 border-b border-slate-800 px-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-blue-600 text-sm font-bold text-white">
          B
        </div>
        <div>
          <span className="block text-sm font-semibold text-white">BizSage3</span>
          <span className="mt-0.5 block text-xs text-slate-400">智能运营诊断</span>
        </div>
      </div>

      {/* New Diagnosis Button */}
      <div className="px-4 py-4">
        <button
          onClick={onCreate}
          disabled={loading}
          className="flex h-10 w-full items-center justify-center gap-2 rounded-md bg-blue-600 px-3 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
          新建诊断
        </button>
      </div>

      {/* Session List */}
      <div className="flex-1 overflow-y-auto px-3 pb-4">
        <p className="px-2 pb-2 text-xs font-medium text-slate-500">最近诊断</p>
        {loading && sessions.length === 0 ? (
          <SessionListSkeleton />
        ) : sessions.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="space-y-1">
            {sessions.map((session) => (
              <SessionItem
                key={session.id}
                session={session}
                isActive={session.id === activeId}
                onSelect={() => onSelect(session.id)}
                onDelete={() => onDelete(session.id)}
              />
            ))}
          </ul>
        )}
      </div>

      <div className="border-t border-slate-800 p-3">
        {isAdmin && (
          <button
            onClick={onAdmin}
            className="flex h-10 w-full items-center gap-2 rounded-md px-3 text-sm text-slate-300 transition hover:bg-slate-800 hover:text-white"
          >
            <Settings className="h-4 w-4" />
            <span>管理后台</span>
          </button>
        )}
        <button
          onClick={onLogout}
          className="flex h-10 w-full items-center gap-2 rounded-md px-3 text-sm text-slate-400 transition hover:bg-slate-800 hover:text-white"
        >
          <LogOut className="h-4 w-4" />
          <span>退出登录</span>
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Session Item
// ---------------------------------------------------------------------------

interface SessionItemProps {
  session: SessionSummary;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
}

function SessionItem({ session, isActive, onSelect, onDelete }: SessionItemProps) {
  const statusConfig = STATUS_MAP[session.status] ?? STATUS_MAP.collecting;

  return (
    <li>
      <div
        onClick={onSelect}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(); } }}
        className={`
          group relative w-full rounded-md px-3 py-2.5 text-left text-sm transition-colors cursor-pointer
          ${isActive
            ? "bg-blue-500/15 ring-1 ring-inset ring-blue-400/30"
            : "hover:bg-slate-900"
          }
        `}
      >
        {/* Title & delete */}
        <div className="flex items-start justify-between gap-2">
          <span className="line-clamp-1 flex-1 font-medium text-slate-100">
            {session.title || "新诊断"}
          </span>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="shrink-0 rounded p-0.5 text-slate-500 opacity-0 transition-all hover:text-red-400 group-hover:opacity-100"
            aria-label="删除会话"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* Status badge, score, date */}
        <div className="mt-1.5 flex items-center gap-2">
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${statusConfig.bg} ${statusConfig.text}`}
          >
            <span className={`mr-1 h-1.5 w-1.5 rounded-full ${statusConfig.dot}`} />
            {statusConfig.label}
          </span>

          {session.status === "completed" && (
            <span className="text-xs text-slate-400">
              {session.score}/100
            </span>
          )}

          <span className="ml-auto text-xs text-slate-500">
            {formatDate(session.updated_at)}
          </span>
        </div>

        {/* Limited diagnosis warning */}
        {session.limited_diagnosis && (
          <div className="mt-1 flex items-center gap-1 text-xs text-amber-400">
            <AlertTriangle className="h-3 w-3" />
            有限诊断
          </div>
        )}
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function SessionListSkeleton() {
  return (
    <div className="space-y-2 px-1 pt-2">
      {[...Array(5)].map((_, i) => (
        <div key={i} className="animate-pulse rounded-md bg-slate-900 p-3">
          <div className="h-3 w-3/4 rounded bg-slate-800" />
          <div className="mt-2 flex items-center gap-2">
            <div className="h-4 w-14 rounded-full bg-slate-800" />
            <div className="h-3 w-10 rounded bg-slate-800" />
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty State
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-slate-500">
      <Inbox className="mb-2 h-8 w-8" />
      <p className="text-xs">暂无诊断会话</p>
      <p className="mt-1 text-xs text-slate-600">点击上方按钮开始新的诊断</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status mapping
// ---------------------------------------------------------------------------

const STATUS_MAP: Record<string, { label: string; bg: string; text: string; dot: string }> = {
  collecting: {
    label: "收集中",
    bg: "bg-blue-500/20",
    text: "text-blue-300",
    dot: "bg-blue-400",
  },
  analyzing: {
    label: "分析中",
    bg: "bg-yellow-500/20",
    text: "text-yellow-300",
    dot: "bg-yellow-400",
  },
  completed: {
    label: "已完成",
    bg: "bg-green-500/20",
    text: "text-green-300",
    dot: "bg-green-400",
  },
  failed: {
    label: "失败",
    bg: "bg-red-500/20",
    text: "text-red-300",
    dot: "bg-red-400",
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    const month = (d.getMonth() + 1).toString().padStart(2, "0");
    const day = d.getDate().toString().padStart(2, "0");
    return `${month}/${day}`;
  } catch {
    return "";
  }
}
