/**
 * BizSage3 — Home page.
 *
 * On mount: fetches existing sessions and redirects to the most recent one,
 * or creates a new session and redirects to it.
 */

"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import * as api from "@/lib/api";

export default function HomePage() {
  const router = useRouter();
  const initiated = useRef(false);

  useEffect(() => {
    if (initiated.current) return;
    initiated.current = true;

    let cancelled = false;

    async function boot() {
      try {
        const sessions = await api.listSessions();

        if (cancelled) return;

        if (sessions.length > 0) {
          // Redirect to the most recent session
          const latest = sessions.reduce((a, b) =>
            new Date(a.updated_at) > new Date(b.updated_at) ? a : b,
          );
          router.replace(`/sessions/${latest.id}`);
        } else {
          // Create a new session
          const detail = await api.createSession();
          if (!cancelled) {
            router.replace(`/sessions/${detail.id}`);
          }
        }
      } catch {
        // If everything fails, navigate to a fallback
        if (!cancelled) {
          router.replace("/sessions/new");
        }
      }
    }

    boot();

    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <div className="main-area" style={{
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      minHeight: "100vh",
      color: "var(--text-muted)",
      fontSize: "0.9375rem",
    }}>
      <div style={{ textAlign: "center" }}>
        <div
          className="typing-indicator"
          style={{ display: "inline-flex", marginBottom: "0.75rem" }}
        >
          <span /><span /><span />
        </div>
        <p>正在初始化 BizSage3...</p>
      </div>
    </div>
  );
}
