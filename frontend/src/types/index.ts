/* =====================================================================
 * BizSage3 — TypeScript type definitions matching the backend API schemas
 * ===================================================================== */

// ─── Session ───────────────────────────────────────────────────────────

export interface SessionSummary {
  id: string;
  title: string;
  status: SessionStatus;
  stage: string;
  score: number;
  limited_diagnosis: boolean;
  created_at: string; // ISO datetime
  updated_at: string; // ISO datetime
}

export type SessionStatus =
  | "collecting"
  | "analyzing"
  | "completed"
  | "failed";

// ─── Message ───────────────────────────────────────────────────────────

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sequence: number;
  created_at: string;
}

// ─── Completeness Detail ───────────────────────────────────────────────

export interface CompletenessDetail {
  score: number;
  summary: string;
  missing_aspects: string[];
}

// ─── Session Detail ────────────────────────────────────────────────────

export interface SessionDetail extends SessionSummary {
  scene: Record<string, string>;
  raw_facts: string[];
  completeness: CompletenessDetail;
  waiting_for_input: boolean;
  error_message: string | null;
  messages: Message[];
  has_report: boolean;
  report_count: number;
  report_generating: boolean;
  report_error: string | null;
}

// ─── Message Request ───────────────────────────────────────────────────

export interface MessageRequest {
  client_message_id: string;
  content: string;
  action?: "reply";
}

// ─── Report Response ───────────────────────────────────────────────────

export interface ReportResponse {
  id: string;
  session_id: string;
  markdown: string;
  diagnosis: Record<string, unknown>;
  created_at: string;
}

export interface ReportGenerationResponse {
  session_id: string;
  status: "generating";
}

// Authentication and temporary access tokens

export interface AuthSession {
  role: "admin" | "user";
  expires_at: string;
}

export type TemporaryTokenStatus = "active" | "expired" | "revoked";

export interface TemporaryAccessToken {
  id: string;
  name: string;
  token_prefix: string;
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  status: TemporaryTokenStatus;
}

export interface CreatedTemporaryAccessToken extends TemporaryAccessToken {
  token: string;
}

// ─── Meta ──────────────────────────────────────────────────────────────

export interface MetricDef {
  code: string;
  label: string;
  category: string;
  description: string;
  unit: string;
  is_core: boolean;
}

// ─── SSE Events ────────────────────────────────────────────────────────

export interface SSEStageEvent {
  event: "stage";
  data: {
    stage: string;
    label: string;
  };
}

export interface SSEAssistantDelta {
  event: "assistant.delta";
  data: {
    target: string;
    delta: string;
  };
}

export interface SSEAssistantMessage {
  event: "assistant.message";
  data: {
    content: string;
  };
}

export interface SSEStateEvent {
  event: "state";
  data: SessionDetail;
}

export interface SSEReportReady {
  event: "report.ready";
  data: {
    session_id: string;
  };
}

export interface SSEErrorEvent {
  event: "error";
  data: {
    message: string;
  };
}

export interface SSEDoneEvent {
  event: "done";
  data: {
    session_id: string;
  };
}

export type SSEEvent =
  | SSEStageEvent
  | SSEAssistantDelta
  | SSEAssistantMessage
  | SSEStateEvent
  | SSEReportReady
  | SSEErrorEvent
  | SSEDoneEvent;

// ─── Diagnosis State (for frontend useReducer) ─────────────────────────

export type DiagnosisStage =
  | "init"
  | "scene_recognize"
  | "greeting_guide"
  | "chat_extract"
  | "agent_reply"
  | "await_input"
  | "generate_report"
  | "complete"
  | "error";

export interface DiagnosisState {
  session: SessionDetail | null;
  reports: ReportResponse[];
  loading: boolean;
  generating: boolean;
  streaming: boolean;
  streamText: string;
  stageLabel: string;
  stage: DiagnosisStage;
  error: string | null;
}

export type DiagnosisAction =
  | { type: "INIT_START"; payload: { sessionId: string } }
  | { type: "INIT_SUCCESS"; payload: { session: SessionDetail } }
  | { type: "INIT_ERROR"; payload: { error: string } }
  | { type: "SEND_START" }
  | { type: "SEND_STAGE"; payload: { stage: string; label: string } }
  | { type: "SEND_DELTA"; payload: { delta: string } }
  | { type: "SEND_MESSAGE"; payload: { content: string } }
  | { type: "SEND_STATE"; payload: { session: SessionDetail } }
  | { type: "SEND_REPORT_READY" }
  | { type: "SEND_DONE" }
  | { type: "SEND_ERROR"; payload: { error: string } }
  | { type: "SET_REPORTS"; payload: { reports: ReportResponse[] } }
  | { type: "SET_ERROR"; payload: { error: string } }
  | { type: "RESET" };

// ─── Utility ───────────────────────────────────────────────────────────

export interface StageLabels {
  [key: string]: string;
}

export const STAGE_LABELS: StageLabels = {
  init: "初始化",
  scene_recognize: "识别行业场景...",
  greeting_guide: "自我介绍...",
  chat_extract: "分析对话...",
  agent_reply: "思考中...",
  await_input: "等待您的回复",
  generate_report: "生成诊断报告...",
};
