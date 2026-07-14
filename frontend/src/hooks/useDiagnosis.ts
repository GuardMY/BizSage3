/**
 * BizSage3 — useDiagnosis hook.
 *
 * Manages the active session's details, messages, SSE streaming,
 * and report state.
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  SessionDetail,
  Message,
  CompletenessDetail,
  ReportResponse,
  MessageRequest,
} from "@/types";
import * as api from "@/lib/api";

export interface UseDiagnosisReturn {
  session: SessionDetail | null;
  messages: Message[];
  completeness: CompletenessDetail | null;
  streaming: boolean;
  streamText: string;
  stageLabel: string;
  loading: boolean;
  error: string | null;
  hasReport: boolean;
  reports: ReportResponse[];
  reportLoading: boolean;
  reportGenerating: boolean;

  loadSession: (id: string) => Promise<void>;
  sendMessage: (content: string) => void;
  loadReports: () => Promise<void>;
  generateReport: () => Promise<void>;
  clearError: () => void;
  reset: () => void;
}

export function useDiagnosis(): UseDiagnosisReturn {
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [completeness, setCompleteness] = useState<CompletenessDetail | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [stageLabel, setStageLabel] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasReport, setHasReport] = useState(false);
  const [reports, setReports] = useState<ReportResponse[]>([]);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportGenerating, setReportGenerating] = useState(false);

  const messagesRef = useRef<Message[]>([]);
  const mounted = useRef(true);
  const currentSessionId = useRef<string | null>(null);

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
    setCompleteness(null);
    setStreaming(false);
    setStreamText("");
    setStageLabel("");
    setLoading(false);
    setError(null);
    setHasReport(false);
    setReports([]);
    setReportLoading(false);
    setReportGenerating(false);
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
      setReports([]);
      setReportLoading(false);
      const detail = await api.getSession(id);
      if (!mounted.current || currentSessionId.current !== id) return;
      setSession(detail);
      setMessages(detail.messages ?? []);
      setCompleteness(detail.completeness ?? null);
      setHasReport(detail.has_report ?? false);
      setReportGenerating(detail.report_generating ?? false);
      if (detail.report_error) setError(detail.report_error);
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
    (content: string) => {
      const sid = currentSessionId.current;
      if (!sid) return;

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
        action: "reply",
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
                const serverCount = (data.messages ?? []).length;
                const localCount = messagesRef.current.length;
                if (serverCount >= localCount) {
                  setMessages(data.messages ?? []);
                  messagesRef.current = data.messages ?? [];
                }
                setCompleteness(data.completeness ?? null);
                setHasReport(data.has_report ?? false);
                setReportGenerating(data.report_generating ?? false);
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
            // Ignore parse errors
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
  // Load report history
  // -----------------------------------------------------------------------

  const loadReports = useCallback(async () => {
    const sid = currentSessionId.current;
    if (!sid) return;
    try {
      setReportLoading(true);
      const result = await api.getReports(sid);
      if (mounted.current) {
        setReports(result);
        setHasReport(result.length > 0);
      }
    } catch (err) {
      if (mounted.current)
        setError(err instanceof Error ? err.message : "加载报告失败");
    } finally {
      if (mounted.current) setReportLoading(false);
    }
  }, []);

  const generateReport = useCallback(async () => {
    const sid = currentSessionId.current;
    if (!sid || reportGenerating) return;

    setError(null);
    setReportGenerating(true);
    setStageLabel("诊断报告正在后台生成...");
    try {
      await api.startReportGeneration(sid);
    } catch (err) {
      const message = err instanceof Error ? err.message : "启动报告生成失败";
      if (!mounted.current) return;
      setError(message);
      try {
        const detail = await api.getSession(sid);
        if (currentSessionId.current === sid) {
          setSession(detail);
          setReportGenerating(detail.report_generating ?? false);
          setStageLabel(stageLabelForStage(detail.stage));
        }
      } catch {
        setReportGenerating(false);
      }
    }
  }, [reportGenerating]);

  useEffect(() => {
    const sid = currentSessionId.current;
    if (!sid || !reportGenerating) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const detail = await api.getSession(sid);
        if (cancelled || currentSessionId.current !== sid) return;
        setSession(detail);
        setHasReport(detail.has_report ?? false);
        setReportGenerating(detail.report_generating ?? false);

        if (detail.report_generating) {
          timer = setTimeout(poll, 1500);
          return;
        }

        setStageLabel(stageLabelForStage(detail.stage));
        if (detail.report_error) setError(detail.report_error);
        await loadReports();
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "获取报告生成状态失败");
        timer = setTimeout(poll, 3000);
      }
    };

    timer = setTimeout(poll, 800);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [reportGenerating, loadReports]);

  // -----------------------------------------------------------------------
  // Clear error
  // -----------------------------------------------------------------------

  const clearError = useCallback(() => setError(null), []);

  return {
    session,
    messages,
    completeness,
    streaming,
    streamText,
    stageLabel,
    loading,
    error,
    hasReport,
    reports,
    reportLoading,
    reportGenerating,
    loadSession,
    sendMessage,
    loadReports,
    generateReport,
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
    greeting_guide: "自我介绍...",
    chat_extract: "分析对话...",
    agent_reply: "思考中...",
    await_input: "等待您的回复",
    generate_report: "生成诊断报告...",
  };
  return labels[stage] ?? stage;
}
