/**
 * BizSage3 — useDiagnosis hook.
 *
 * Manages the active session's details, messages, SSE streaming,
 * and report state. Uses multiple useState hooks for a flat API
 * surface consumable by existing components.
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  SessionDetail,
  Message,
  ScoreDetail,
  ReportResponse,
  MessageRequest,
} from "@/types";
import * as api from "@/lib/api";

export interface UseDiagnosisReturn {
  /** The full session detail (refreshed after SSE updates). */
  session: SessionDetail | null;
  /** Flat message list sorted by sequence. */
  messages: Message[];
  /** Current completeness score breakdown. */
  scoreDetail: ScoreDetail | null;
  /** Whether a streaming request is in-flight. */
  streaming: boolean;
  /** The partial text being accumulated from assistant.delta events. */
  streamText: string;
  /** Human-readable stage label (Chinese). */
  stageLabel: string;
  /** Loading state when fetching session. */
  loading: boolean;
  /** Error message, if any. */
  error: string | null;
  /** Whether a report exists for the current session. */
  hasReport: boolean;
  /** The fetched report (null until loaded). */
  report: ReportResponse | null;
  /** Whether the report is being fetched. */
  reportLoading: boolean;

  /** Load (or reload) the session by id. */
  loadSession: (id: string) => Promise<void>;
  /** Send a user message. Returns immediately; updates arrive via SSE. */
  sendMessage: (
    content: string,
    action?: "reply" | "diagnose_with_current_data",
  ) => void;
  /** Fetch the diagnosis report. */
  loadReport: () => Promise<void>;
  /** Clear any error. */
  clearError: () => void;
  /** Reset state (on navigation away). */
  reset: () => void;
}

export function useDiagnosis(): UseDiagnosisReturn {
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [scoreDetail, setScoreDetail] = useState<ScoreDetail | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [stageLabel, setStageLabel] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasReport, setHasReport] = useState(false);
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

  const messagesRef = useRef<Message[]>([]);
  const mounted = useRef(true);
  const currentSessionId = useRef<string | null>(null);

  // Keep messagesRef in sync
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // -----------------------------------------------------------------------
  // Reset
  // -----------------------------------------------------------------------

  const reset = useCallback(() => {
    setSession(null);
    setMessages([]);
    setScoreDetail(null);
    setStreaming(false);
    setStreamText("");
    setStageLabel("");
    setLoading(false);
    setError(null);
    setHasReport(false);
    setReport(null);
    setReportLoading(false);
    currentSessionId.current = null;
  }, []);

  // -----------------------------------------------------------------------
  // Load session
  // -----------------------------------------------------------------------

  const loadSession = useCallback(async (id: string) => {
    if (!id) return;
    currentSessionId.current = id;
    try {
      setLoading(true);
      setError(null);
      const detail = await api.getSession(id);
      if (!mounted.current || currentSessionId.current !== id) return;
      setSession(detail);
      setMessages(detail.messages ?? []);
      setScoreDetail(detail.score_detail ?? null);
      setHasReport(detail.has_report ?? false);
      setStageLabel(stageLabelForStage(detail.stage));
    } catch (err) {
      if (mounted.current)
        setError(err instanceof Error ? err.message : "加载会话失败");
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, []);

  // -----------------------------------------------------------------------
  // Send message (SSE)
  // -----------------------------------------------------------------------

  const sendMessage = useCallback(
    (
      content: string,
      action: "reply" | "diagnose_with_current_data" = "reply",
    ) => {
      const sid = currentSessionId.current;
      if (!sid) return;

      // Optimistically add user message
      const userMsg: Message = {
        id: `temp-${Date.now()}`,
        role: "user",
        content,
        sequence: messagesRef.current.length + 1,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);
      messagesRef.current = [...messagesRef.current, userMsg];

      setStreaming(true);
      setStreamText("");
      setError(null);

      const clientMessageId = crypto.randomUUID
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;

      const payload: MessageRequest = {
        client_message_id: clientMessageId,
        content,
        action,
      };

      api
        .streamMessage(sid, payload, (sseEvent) => {
          if (!mounted.current) return;

          try {
            switch (sseEvent.event) {
              case "stage": {
                const data = JSON.parse(sseEvent.data) as {
                  stage: string;
                  label: string;
                };
                setStageLabel(data.label ?? data.stage ?? "");
                break;
              }
              case "assistant.delta": {
                const data = JSON.parse(sseEvent.data) as { delta: string };
                setStreamText((prev) => prev + (data.delta ?? ""));
                break;
              }
              case "assistant.message": {
                const data = JSON.parse(sseEvent.data) as { content: string };
                const assistantMsg: Message = {
                  id: `assistant-${Date.now()}`,
                  role: "assistant",
                  content: data.content ?? "",
                  sequence: 0,
                  created_at: new Date().toISOString(),
                };
                setMessages((prev) => [...prev, assistantMsg]);
                messagesRef.current = [...messagesRef.current, assistantMsg];
                setStreamText("");
                break;
              }
              case "state": {
                const data = JSON.parse(sseEvent.data) as SessionDetail;
                setSession(data);
                setMessages(data.messages ?? []);
                messagesRef.current = data.messages ?? [];
                setScoreDetail(data.score_detail ?? null);
                setHasReport(data.has_report ?? false);
                setStageLabel(stageLabelForStage(data.stage));
                setStreamText("");
                break;
              }
              case "report.ready": {
                setHasReport(true);
                break;
              }
              case "done": {
                setStreaming(false);
                setStreamText("");
                break;
              }
              case "error": {
                const data = JSON.parse(sseEvent.data) as { message: string };
                setError(data.message ?? "未知错误");
                setStreaming(false);
                setStreamText("");
                break;
              }
            }
          } catch {
            // Ignore parse errors for malformed SSE data
          }
        })
        .catch((err) => {
          if (mounted.current) {
            setError(
              err instanceof Error ? err.message : "发送消息失败",
            );
            setStreaming(false);
            setStreamText("");
          }
        });
    },
    [],
  );

  // -----------------------------------------------------------------------
  // Load report
  // -----------------------------------------------------------------------

  const loadReport = useCallback(async () => {
    const sid = currentSessionId.current;
    if (!sid) return;
    try {
      setReportLoading(true);
      const r = await api.getReport(sid);
      if (mounted.current) {
        setReport(r);
        setHasReport(true);
      }
    } catch (err) {
      if (mounted.current)
        setError(err instanceof Error ? err.message : "加载报告失败");
    } finally {
      if (mounted.current) setReportLoading(false);
    }
  }, []);

  // -----------------------------------------------------------------------
  // Clear error
  // -----------------------------------------------------------------------

  const clearError = useCallback(() => setError(null), []);

  return {
    session,
    messages,
    scoreDetail,
    streaming,
    streamText,
    stageLabel,
    loading,
    error,
    hasReport,
    report,
    reportLoading,
    loadSession,
    sendMessage,
    loadReport,
    clearError,
    reset,
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function stageLabelForStage(stage: string): string {
  const labels: Record<string, string> = {
    init: "初始化",
    scene_recognize: "识别行业场景...",
    collect_metrics: "提取运营指标...",
    check_complete: "评估信息完备度...",
    exception_ask: "生成补充问题...",
    await_input: "等待您的回复",
    diagnosis_analysis: "六维度诊断分析中...",
    generate_report: "生成诊断报告...",
  };
  return labels[stage] ?? stage;
}
