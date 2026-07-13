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
} from "@/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE || "/api/v1";
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
    throw new Error(`API error ${res.status}: ${detail}`);
  }

  // 204 No Content
  if (res.status === 204) {
    return undefined as T;
  }

  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

/** List all diagnosis sessions, newest first. */
export async function listSessions(): Promise<SessionSummary[]> {
  const res = await fetch(`${apiBase()}/sessions`);
  return handleResponse<SessionSummary[]>(res);
}

/** Create a new diagnosis session. */
export async function createSession(): Promise<SessionDetail> {
  const res = await fetch(`${apiBase()}/sessions`, { method: "POST" });
  return handleResponse<SessionDetail>(res);
}

/** Get a session by ID with all details. */
export async function getSession(id: string): Promise<SessionDetail> {
  const res = await fetch(`${apiBase()}/sessions/${encodeURIComponent(id)}`);
  return handleResponse<SessionDetail>(res);
}

/** Delete a session. */
export async function deleteSession(id: string): Promise<void> {
  const res = await fetch(
    `${apiBase()}/sessions/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
  return handleResponse<void>(res);
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

/** Get the diagnosis report for a session. */
export async function getReport(id: string): Promise<ReportResponse> {
  const res = await fetch(
    `${apiBase()}/sessions/${encodeURIComponent(id)}/report`,
  );
  return handleResponse<ReportResponse>(res);
}

/** Get the download URL for a report (for direct link / <a> download). */
export function getReportDownloadUrl(id: string): string {
  return `${apiBase()}/sessions/${encodeURIComponent(id)}/report/download`;
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
  const res = await fetch(
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
    throw new Error(`SSE error ${res.status}: ${detail}`);
  }

  return consumeSSE(res, onEvent);
}

