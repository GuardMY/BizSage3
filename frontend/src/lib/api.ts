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

