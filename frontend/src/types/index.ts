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

// ─── Metric Value ──────────────────────────────────────────────────────

export interface MetricValue {
  code: string;
  label: string;
  raw_text: string;
  status: "provided" | "unavailable";
  numeric_value: number | null;
  range_min: number | null;
  range_max: number | null;
  unit: string | null;
  period: string | null;
  confidence: number;
}

// ─── Score Detail ──────────────────────────────────────────────────────

export interface ScoreDetail {
  score: number;
  core_complete: boolean;
  core_provided_count: number;
  secondary_coverage: number;
  anomaly_complete: boolean;
  missing_core: string[];
  missing_secondary: string[];
  unresolved_anomalies: string[];
  can_limited_diagnose: boolean;
  passed: boolean;
}

// ─── Session Detail ────────────────────────────────────────────────────

export interface SessionDetail extends SessionSummary {
  scene: Record<string, string>;
  metrics: Record<string, MetricValue>;
  score_detail: ScoreDetail;
  waiting_for_input: boolean;
  error_message: string | null;
  messages: Message[];
  has_report: boolean;
}

// ─── Message Request ───────────────────────────────────────────────────

export interface MessageRequest {
  client_message_id: string;
  content: string;
  action?: "reply" | "diagnose_with_current_data";
}

// ─── Report Response ───────────────────────────────────────────────────

export interface ReportResponse {
  session_id: string;
  markdown: string;
  diagnosis: Record<string, unknown>;
  created_at: string;
}

// ─── Meta ──────────────────────────────────────────────────────────────

export interface IndustryDef {
  code: string;
  label: string;
  description: string;
}

export interface MetricDef {
  code: string;
  label: string;
  category: string;
  description: string;
  unit: string;
  is_core: boolean;
}

export interface MetaResponse {
  industries: IndustryDef[];
  core_metrics: MetricDef[];
  llm_mode: string;
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
  | "collect_metrics"
  | "check_complete"
  | "exception_ask"
  | "await_input"
  | "diagnosis_analysis"
  | "generate_report"
  | "complete"
  | "error";

export interface DiagnosisState {
  session: SessionDetail | null;
  report: ReportResponse | null;
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
  | { type: "SET_REPORT"; payload: { report: ReportResponse } }
  | { type: "SET_ERROR"; payload: { error: string } }
  | { type: "RESET" };

// ─── Utility ───────────────────────────────────────────────────────────

export interface StageLabels {
  [key: string]: string;
}

export const STAGE_LABELS: StageLabels = {
  init: "初始化",
  scene_recognize: "识别行业场景...",
  collect_metrics: "提取运营指标...",
  check_complete: "评估信息完备度...",
  exception_ask: "生成补充问题...",
  await_input: "等待您的回复",
  diagnosis_analysis: "六维度诊断分析中...",
  generate_report: "生成诊断报告...",
};
