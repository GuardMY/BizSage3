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

export interface ConversationCitation {
  citation_id: string;
  source_type: "knowledge" | "web";
  title: string;
  url?: string | null;
  quote: string;
  locator: Record<string, unknown>;
  provider?: string | null;
  published_at?: string | null;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sequence: number;
  suggested_replies?: string[];  // quick-reply options (assistant messages only)
  citations?: ConversationCitation[] | null;
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

export interface PaginatedResponse<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

// Platform industry knowledge base

export type KnowledgeSourceType = "methodology" | "benchmark_rule" | "case_sop";
export type KnowledgeRetrievalStrategy = "strict" | "progressive" | "industry_only" | "unfiltered" | "scene_boost";

export interface KnowledgeRetrievalPolicy {
  strategy: KnowledgeRetrievalStrategy;
}

export interface KnowledgeIngestionJob {
  id: string;
  state: string;
  parser: string | null;
  error: string | null;
  retry_count: number;
  indexed_at: string | null;
  created_at: string;
}

export interface KnowledgeVersion {
  id: string;
  document_id: string;
  version_no: number;
  original_filename: string;
  content_type: string;
  source_type: KnowledgeSourceType;
  sha256: string;
  status: "draft" | "parsing" | "indexing" | "pending_review" | "published" | "superseded" | "revoked";
  effective_from: string | null;
  effective_to: string | null;
  industry_tags: string[];
  sub_industry_tags: string[];
  business_mode_tags: string[];
  operating_stage_tags: string[];
  chunk_count: number;
  latest_job: KnowledgeIngestionJob | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocument {
  id: string;
  title: string;
  managed_source_key: string | null;
  current_version_id: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  versions: KnowledgeVersion[];
}

export interface KnowledgeDocumentVersionListItem {
  document_id: string;
  document_title: string;
  managed_source_key: string | null;
  current_version_id: string | null;
  is_current: boolean;
  version: KnowledgeVersion;
}

export interface KnowledgeSearchResult {
  chunk_id: string;
  document_id: string;
  version_id: string;
  document_title: string;
  source_type: KnowledgeSourceType;
  version_no: number;
  quote: string;
  locator: Record<string, unknown>;
  rank: number;
  semantic_score_percent: number;
  keyword_match_percent: number;
  source_weight_percent: number;
  combined_score_percent: number;
}

export type KnowledgeCatalogSyncItemState =
  | "queued"
  | "running"
  | "published"
  | "skipped"
  | "failed"
  | "revoked";

export interface KnowledgeCatalogSyncItem {
  id: string;
  source_key: string;
  filename: string;
  sha256: string | null;
  action: "scan" | "create" | "update" | "skip" | "revoke";
  state: KnowledgeCatalogSyncItemState;
  document_id: string | null;
  version_id: string | null;
  error: string | null;
  retry_count: number;
  started_at: string | null;
  finished_at: string | null;
}

export interface KnowledgeCatalogSyncRun {
  id: string;
  trigger: "startup" | "manual" | "retry";
  state: "queued" | "scanning" | "running" | "completed" | "partial_failed" | "failed";
  error: string | null;
  total_count: number;
  pending_count: number;
  processing_count: number;
  published_count: number;
  skipped_count: number;
  failed_count: number;
  revoked_count: number;
  progress_percent: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
  items: KnowledgeCatalogSyncItem[];
}

export interface ReportEvidence {
  evidence_no: number;
  document_id: string;
  version_id: string;
  document_title: string;
  source_type: KnowledgeSourceType;
  version_no: number;
  effective_from: string | null;
  status: "published" | "superseded";
  quote: string;
  locator: Record<string, unknown>;
  retrieved_at: string;
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
    citations?: ConversationCitation[] | null;
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

export interface SSESuggestedReplies {
  event: "suggested_replies";
  data: {
    message_id: string;
    replies: string[];
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
  | SSESuggestedReplies
  | SSEStateEvent
  | SSEReportReady
  | SSEErrorEvent
  | SSEDoneEvent;

// ─── Diagnosis State (for frontend useReducer) ─────────────────────────

export type DiagnosisStage =
  | "init"
  | "scene_recognize"
  | "retrieve_industry_knowledge"
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
