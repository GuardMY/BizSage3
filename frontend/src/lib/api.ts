/**
 * BizSage3 — API client.
 *
 * Typed wrapper around every backend endpoint.  Uses the Next.js rewrite
 * proxy (`/api/v1/...` -> `http://localhost:8000/api/v1/...`).
 *
 * For production / bare-browser usage without the proxy, set
 * `NEXT_PUBLIC_API_BASE` to the backend origin (e.g. `http://localhost:8000`).
 */

import { consumeSSE, type SSEEvent } from "./sse";
import type {
  SessionSummary,
  SessionDetail,
  MessageRequest,
  ReportResponse,
  ReportGenerationResponse,
  AuthSession,
  TemporaryAccessToken,
  CreatedTemporaryAccessToken,
  KnowledgeDocument,
  KnowledgeRetrievalPolicy,
  KnowledgeRetrievalStrategy,
  KnowledgeSearchResult,
  KnowledgeCatalogSyncRun,
  KnowledgeSourceType,
  KnowledgeVersion,
  ReportEvidence,
} from "@/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE || "/api/v1";
}

function request(input: string, init: RequestInit = {}): Promise<Response> {
  return fetch(input, { ...init, credentials: "include" });
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text();
    let detail = body;
    try {
      const parsed = JSON.parse(body);
      detail = parsed.detail ?? parsed.message ?? body;
    } catch {
      // body is plain text
    }
    if (res.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new Event("bizsage:unauthorized"));
    }
    throw new Error(`API error ${res.status}: ${detail}`);
  }

  // 204 No Content
  if (res.status === 204) {
    return undefined as T;
  }

  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Authentication
// ---------------------------------------------------------------------------

export async function login(token: string): Promise<AuthSession> {
  const res = await request(`${apiBase()}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  return handleResponse<AuthSession>(res);
}

export async function logout(): Promise<void> {
  const res = await request(`${apiBase()}/auth/logout`, { method: "POST" });
  return handleResponse<void>(res);
}

export async function getCurrentSession(): Promise<AuthSession> {
  const res = await request(`${apiBase()}/auth/me`);
  return handleResponse<AuthSession>(res);
}

export async function listTemporaryTokens(): Promise<TemporaryAccessToken[]> {
  const res = await request(`${apiBase()}/admin/tokens`);
  return handleResponse<TemporaryAccessToken[]>(res);
}

export async function createTemporaryToken(
  name: string,
  expiresInHours: number,
): Promise<CreatedTemporaryAccessToken> {
  const res = await request(`${apiBase()}/admin/tokens`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, expires_in_hours: expiresInHours }),
  });
  return handleResponse<CreatedTemporaryAccessToken>(res);
}

export async function revokeTemporaryToken(id: string): Promise<void> {
  const res = await request(
    `${apiBase()}/admin/tokens/${encodeURIComponent(id)}/revoke`,
    { method: "POST" },
  );
  return handleResponse<void>(res);
}

export async function deleteTemporaryToken(id: string): Promise<void> {
  const res = await request(
    `${apiBase()}/admin/tokens/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
  return handleResponse<void>(res);
}

// ---------------------------------------------------------------------------
// Industry knowledge
// ---------------------------------------------------------------------------

export interface KnowledgeUploadInput {
  title?: string;
  sourceType: KnowledgeSourceType;
  file: File;
  industryTags: string;
  subIndustryTags: string;
  businessModeTags: string;
  operatingStageTags: string;
}

function knowledgeForm(input: KnowledgeUploadInput, includeTitle: boolean): FormData {
  const form = new FormData();
  if (includeTitle) form.set("title", input.title?.trim() ?? "");
  form.set("source_type", input.sourceType);
  form.set("file", input.file);
  form.set("industry_tags", input.industryTags);
  form.set("sub_industry_tags", input.subIndustryTags);
  form.set("business_mode_tags", input.businessModeTags);
  form.set("operating_stage_tags", input.operatingStageTags);
  return form;
}

export async function listKnowledgeDocuments(): Promise<KnowledgeDocument[]> {
  const res = await request(`${apiBase()}/admin/knowledge/documents`);
  return handleResponse<KnowledgeDocument[]>(res);
}

export async function searchKnowledge(query: string, limit: number): Promise<KnowledgeSearchResult[]> {
  const params = new URLSearchParams({ query, limit: String(limit) });
  const res = await request(`${apiBase()}/admin/knowledge/search?${params.toString()}`);
  return handleResponse<KnowledgeSearchResult[]>(res);
}

export async function getKnowledgeRetrievalPolicy(): Promise<KnowledgeRetrievalPolicy> {
  const res = await request(`${apiBase()}/admin/knowledge/retrieval-policy`);
  return handleResponse<KnowledgeRetrievalPolicy>(res);
}

export async function updateKnowledgeRetrievalPolicy(
  strategy: KnowledgeRetrievalStrategy,
): Promise<KnowledgeRetrievalPolicy> {
  const res = await request(`${apiBase()}/admin/knowledge/retrieval-policy`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ strategy }),
  });
  return handleResponse<KnowledgeRetrievalPolicy>(res);
}

export async function createKnowledgeDocument(input: KnowledgeUploadInput): Promise<KnowledgeDocument> {
  const res = await request(`${apiBase()}/admin/knowledge/documents`, {
    method: "POST",
    body: knowledgeForm(input, true),
  });
  return handleResponse<KnowledgeDocument>(res);
}

export async function createKnowledgeDocumentVersion(
  documentId: string,
  input: KnowledgeUploadInput,
): Promise<KnowledgeDocument> {
  const res = await request(
    `${apiBase()}/admin/knowledge/documents/${encodeURIComponent(documentId)}/versions`,
    { method: "POST", body: knowledgeForm(input, false) },
  );
  return handleResponse<KnowledgeDocument>(res);
}

export async function publishKnowledgeVersion(versionId: string): Promise<KnowledgeVersion> {
  const res = await request(
    `${apiBase()}/admin/knowledge/versions/${encodeURIComponent(versionId)}/publish`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
  );
  return handleResponse<KnowledgeVersion>(res);
}

export async function revokeKnowledgeVersion(versionId: string): Promise<void> {
  const res = await request(
    `${apiBase()}/admin/knowledge/versions/${encodeURIComponent(versionId)}/revoke`,
    { method: "POST" },
  );
  return handleResponse<void>(res);
}

export async function retryKnowledgeIngestion(versionId: string): Promise<KnowledgeVersion> {
  const res = await request(
    `${apiBase()}/admin/knowledge/versions/${encodeURIComponent(versionId)}/retry`,
    { method: "POST" },
  );
  return handleResponse<KnowledgeVersion>(res);
}

export async function getLatestIndustrySync(): Promise<KnowledgeCatalogSyncRun | null> {
  const res = await request(`${apiBase()}/admin/knowledge/industry-sync/latest`);
  return handleResponse<KnowledgeCatalogSyncRun | null>(res);
}

export async function startIndustrySync(): Promise<KnowledgeCatalogSyncRun> {
  const res = await request(`${apiBase()}/admin/knowledge/industry-sync`, {
    method: "POST",
  });
  return handleResponse<KnowledgeCatalogSyncRun>(res);
}

export async function retryFailedIndustrySync(runId: string): Promise<KnowledgeCatalogSyncRun> {
  const res = await request(
    `${apiBase()}/admin/knowledge/industry-sync/${encodeURIComponent(runId)}/retry-failed`,
    { method: "POST" },
  );
  return handleResponse<KnowledgeCatalogSyncRun>(res);
}

export function getKnowledgePreviewUrl(documentId: string, versionId: string): string {
  return `${apiBase()}/knowledge/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}/preview`;
}

export function getKnowledgeOriginalUrl(documentId: string, versionId: string): string {
  return `${apiBase()}/knowledge/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}/original`;
}

export async function getReportEvidences(reportId: string): Promise<ReportEvidence[]> {
  const res = await request(`${apiBase()}/reports/${encodeURIComponent(reportId)}/evidences`);
  return handleResponse<ReportEvidence[]>(res);
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

/** List all diagnosis sessions, newest first. */
export async function listSessions(): Promise<SessionSummary[]> {
  const res = await request(`${apiBase()}/sessions`);
  return handleResponse<SessionSummary[]>(res);
}

/** Create a new diagnosis session. */
export async function createSession(): Promise<SessionDetail> {
  const res = await request(`${apiBase()}/sessions`, { method: "POST" });
  return handleResponse<SessionDetail>(res);
}

/** Get a session by ID with all details. */
export async function getSession(id: string): Promise<SessionDetail> {
  const res = await request(`${apiBase()}/sessions/${encodeURIComponent(id)}`);
  return handleResponse<SessionDetail>(res);
}

/** Delete a session. */
export async function deleteSession(id: string): Promise<void> {
  const res = await request(
    `${apiBase()}/sessions/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
  return handleResponse<void>(res);
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

/** List all diagnosis reports for a session, newest first. */
export async function getReports(id: string): Promise<ReportResponse[]> {
  const res = await request(
    `${apiBase()}/sessions/${encodeURIComponent(id)}/reports`,
  );
  return handleResponse<ReportResponse[]>(res);
}

/** Start report generation in the backend. */
export async function startReportGeneration(
  id: string,
): Promise<ReportGenerationResponse> {
  const res = await request(
    `${apiBase()}/sessions/${encodeURIComponent(id)}/reports`,
    { method: "POST" },
  );
  return handleResponse<ReportGenerationResponse>(res);
}

/** Get the download URL for one report. */
export function getReportDownloadUrl(id: string, reportId: string): string {
  return `${apiBase()}/sessions/${encodeURIComponent(id)}/reports/${encodeURIComponent(reportId)}/download`;
}

// ---------------------------------------------------------------------------
// Chat (SSE Streaming)
// ---------------------------------------------------------------------------

/**
 * Send a message and stream SSE events.
 *
 * The caller provides an `onEvent` callback that is invoked for each parsed
 * SSE event (`stage`, `assistant.delta`, `assistant.message`, `state`,
 * `report.ready`, `error`, `done`).
 *
 * This function resolves when the stream ends (after `done`) or rejects on
 * network / HTTP errors.
 */
export async function streamMessage(
  id: string,
  payload: MessageRequest,
  onEvent: (event: SSEEvent) => void,
): Promise<void> {
  const res = await request(
    `${apiBase()}/sessions/${encodeURIComponent(id)}/messages`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );

  if (!res.ok) {
    const body = await res.text();
    let detail = body;
    try {
      const parsed = JSON.parse(body);
      detail = parsed.detail ?? parsed.message ?? body;
    } catch {
      // plain text
    }
    if (res.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new Event("bizsage:unauthorized"));
    }
    throw new Error(`SSE error ${res.status}: ${detail}`);
  }

  return consumeSSE(res, onEvent);
}

