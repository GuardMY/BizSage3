"use client";

/* =============================================================================
 * SessionPage – Main workspace page that ties everything together.
 *
 * Layout:
 *   AppShell
 *     ├─ SessionSidebar (left)
 *     └─ Main workspace:
 *          ├─ Tab bar: "对话" / "诊断报告"
 *          ├─ ChatPanel + ChatInput  (tab: chat)
 *          ├─ ReportView            (tab: report)
 *          └─ ErrorBanner (dismissible)
 *
 * Uses useSessions and useDiagnosis hooks.
 * ============================================================================= */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import SessionSidebar from "@/components/SessionSidebar";
import ChatPanel from "@/components/ChatPanel";
import ChatInput from "@/components/ChatInput";
import QuickReplies from "@/components/QuickReplies";
import ReportView from "@/components/ReportView";
import ProgressPanel from "@/components/ProgressPanel";
import ErrorBanner from "@/components/ErrorBanner";
import { useSessions } from "@/hooks/useSessions";
import { useDiagnosis } from "@/hooks/useDiagnosis";
import { useAuth } from "@/components/AuthProvider";

type Tab = "chat" | "report";

export default function SessionPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params?.sessionId as string | undefined;

  // ─── Hooks ──────────────────────────────────────────────────────────────
  const sessionsHook = useSessions();
  const diagnosis = useDiagnosis();
  const auth = useAuth();

  const [activeTab, setActiveTab] = useState<Tab>("chat");

  // ─── Sync session ID ────────────────────────────────────────────────────
  useEffect(() => {
    if (sessionId) {
      sessionsHook.setActiveId(sessionId);
      diagnosis.loadSession(sessionId);
    } else {
      // Navigating away from any session — full reset.
      diagnosis.reset();
    }
    // No reset in cleanup — loadSession keeps old content visible until
    // new data arrives, preventing a flash to empty state on session switch.
  }, [sessionId]);

  // When sessions list changes, ensure activeId is reflected
  useEffect(() => {
    if (sessionId && sessionsHook.activeId !== sessionId) {
      sessionsHook.setActiveId(sessionId);
    }
  }, [sessionId, sessionsHook.activeId]);

  // ─── Handlers ───────────────────────────────────────────────────────────

  const handleSelectSession = useCallback(
    (id: string) => {
      router.push(`/sessions/${id}`);
    },
    [router],
  );

  const handleCreateSession = useCallback(async () => {
    const newId = await sessionsHook.create();
    if (newId) {
      router.push(`/sessions/${newId}`);
    }
  }, [sessionsHook, router]);

  const handleDeleteSession = useCallback(
    async (id: string) => {
      await sessionsHook.remove(id);
      if (id === sessionId) {
        router.push("/");
      }
    },
    [sessionsHook, sessionId, router],
  );

  const handleSend = useCallback(
    (content: string) => {
      diagnosis.sendMessage(content);
      // Switch to chat tab when sending a message
      setActiveTab("chat");
    },
    [diagnosis],
  );

  const handleGenerateReport = useCallback(() => {
    void diagnosis.generateReport();
  }, [diagnosis]);

  // ─── Derived State ────────────────────────────────────────────────────

  const progressScore = useMemo(() => {
    return diagnosis.completeness?.score ?? diagnosis.session?.score ?? 0;
  }, [diagnosis.completeness, diagnosis.session]);

  // ─── Render ────────────────────────────────────────────────────────────

  return (
    <AppShell
      sidebar={
        <SessionSidebar
          sessions={sessionsHook.sessions}
          activeId={sessionsHook.activeId}
          loading={sessionsHook.loading}
          onSelect={handleSelectSession}
          onCreate={handleCreateSession}
          onDelete={handleDeleteSession}
          isAdmin={auth.session?.role === "admin"}
          onAdmin={() => router.push("/admin/tokens")}
          onLogout={() => void auth.logout()}
        />
      }
    >
      {/* Error banner */}
      <ErrorBanner
        message={diagnosis.error || sessionsHook.error}
        onDismiss={diagnosis.clearError}
      />

      <div className="flex flex-1 min-h-0">
        {/* ---- Main area: Chat + Report ---- */}
        <div className="flex flex-1 flex-col min-w-0">
          {/* Tab bar */}
          <div className="flex items-center border-b border-gray-200 bg-white px-6">
            <TabButton
              active={activeTab === "chat"}
              onClick={() => setActiveTab("chat")}
            >
              对话
            </TabButton>
            <TabButton
              active={activeTab === "report"}
              onClick={() => {
                setActiveTab("report");
                void diagnosis.loadReports();
              }}
              loading={diagnosis.reportLoading || diagnosis.loading}
            >
              诊断报告
              {(diagnosis.session?.report_count ?? 0) > 0 ? (
                <span className="ml-1.5 text-xs text-gray-400">
                  {diagnosis.session?.report_count}
                </span>
              ) : diagnosis.reportGenerating ? (
                <span className="ml-1.5 inline-flex h-2 w-2 animate-pulse rounded-full bg-amber-400" />
              ) : (diagnosis.reportLoading || diagnosis.loading) ? (
                /* Reserve dot space during load to prevent layout shift */
                <span className="ml-1.5 inline-flex h-2 w-2 rounded-full invisible" />
              ) : null}
            </TabButton>
          </div>

          {/* Tab content */}
          <div className="flex flex-1 min-h-0">
            {activeTab === "chat" ? (
              /* Chat workspace */
              <div className="flex flex-1 flex-col min-h-0">
                <ChatPanel
                  messages={diagnosis.messages}
                  streaming={diagnosis.streaming}
                  streamText={diagnosis.streamText}
                  stageLabel={diagnosis.stageLabel}
                  loading={diagnosis.loading}
                />
                <QuickReplies
                  replies={diagnosis.suggestedReplies}
                  onSelect={handleSend}
                  disabled={diagnosis.streaming}
                />
                <ChatInput
                  onSend={handleSend}
                  disabled={diagnosis.streaming}
                />
              </div>
            ) : (
              /* Report workspace */
              <ReportView
                sessionId={sessionId ?? ""}
                reports={diagnosis.reports}
                loading={diagnosis.reportLoading}
                generating={diagnosis.reportGenerating}
              />
            )}
          </div>
        </div>

        {/* ---- Right sidebar: ProgressPanel ---- */}
        <div className="hidden xl:block">
          <ProgressPanel
            score={progressScore}
            completeness={diagnosis.completeness}
            stage={diagnosis.session?.stage ?? ""}
            canGenerateReport={!diagnosis.streaming && !diagnosis.reportGenerating}
            reportGenerating={diagnosis.reportGenerating}
            onGenerateReport={handleGenerateReport}
          />
        </div>
      </div>
    </AppShell>
  );
}

// ---------------------------------------------------------------------------
// Tab Button Component
// ---------------------------------------------------------------------------

function TabButton({
  active,
  onClick,
  badge,
  loading = false,
  children,
}: {
  active: boolean;
  onClick: () => void;
  badge?: string;
  loading?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`
        relative flex items-center px-4 py-3 text-sm font-medium transition-colors
        ${
          active
            ? "text-indigo-600 border-b-2 border-indigo-600"
            : "text-gray-500 hover:text-gray-700 border-b-2 border-transparent"
        }
      `}
    >
      {children}
      {badge ? (
        <span className="ml-1.5 inline-flex items-center rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-600">
          {badge}
        </span>
      ) : loading ? (
        /* Reserve badge space during session load to prevent layout shift */
        <span className="ml-1.5 inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium invisible">
          进行中
        </span>
      ) : null}
    </button>
  );
}
