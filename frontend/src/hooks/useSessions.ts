/**
 * BizSage3 — useSessions hook.
 *
 * Manages the session list sidebar state: fetch, create, delete, and track
 * the currently-active session ID.
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { SessionSummary } from "@/types";

export interface UseSessionsReturn {
  sessions: SessionSummary[];
  activeId: string | null;
  loading: boolean;
  error: string | null;
  setActiveId: (id: string | null) => void;
  list: () => Promise<SessionSummary[]>;
  create: () => Promise<string | null>; // returns new session id, or null
  remove: (id: string) => Promise<void>;
}

export function useSessions(): UseSessionsReturn {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const list = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listSessions();
      setSessions(data);
      return data;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to list sessions";
      setError(msg);
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  const create = useCallback(async (): Promise<string | null> => {
    setLoading(true);
    setError(null);
    try {
      const detail = await api.createSession();
      // Prepend the new session to the list
      setSessions((prev) => {
        const exists = prev.some((s) => s.id === detail.id);
        if (exists) return prev;
        const summary: SessionSummary = {
          id: detail.id,
          title: detail.title,
          status: detail.status,
          stage: detail.stage,
          score: detail.score,
          limited_diagnosis: detail.limited_diagnosis,
          created_at: detail.created_at,
          updated_at: detail.updated_at,
        };
        return [summary, ...prev];
      });
      return detail.id;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create session";
      setError(msg);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const remove = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      await api.deleteSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      setActiveId((prev) => (prev === id ? null : prev));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to delete session";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  // Load sessions on mount
  useEffect(() => {
    list();
  }, [list]);

  return {
    sessions,
    activeId,
    loading,
    error,
    setActiveId,
    list,
    create,
    remove,
  };
}
