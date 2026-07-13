"use client";

/* =============================================================================
 * ChatPanel – Main chat area with scrollable message list.
 *
 * Features:
 *   - Scrollable message list (auto-scrolls to bottom on new messages)
 *   - MessageBubble for each message
 *   - Streaming text indicator when AI is responding
 *   - Stage label during processing
 *   - Empty state with prompt
 * ============================================================================= */

import React, { useEffect, useRef } from "react";
import type { Message } from "@/types";
import MessageBubble from "./MessageBubble";

interface ChatPanelProps {
  messages: Message[];
  streaming: boolean;
  streamText: string;
  stageLabel: string;
  loading: boolean;
}

export default function ChatPanel({
  messages,
  streaming,
  streamText,
  stageLabel,
  loading,
}: ChatPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when messages change or streaming text updates
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    // Use requestAnimationFrame to let the DOM settle first
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
  }, [messages, streamText]);

  // --- Empty state ---
  if (!loading && messages.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center bg-gray-50 px-6">
        <div className="max-w-md text-center">
          {/* Icon */}
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-indigo-100">
            <svg
              className="h-8 w-8 text-indigo-500"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.5}
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5m.75-9l3-3 2.148 2.148A12.061 12.061 0 0116.5 7.605"
              />
            </svg>
          </div>

          <h2 className="text-xl font-bold text-gray-800">开始您的运营诊断</h2>
          <p className="mt-2 text-sm leading-relaxed text-gray-500">
            请描述您的业务场景和运营数据，AI 将为您进行多维度诊断分析。
          </p>
          <p className="mt-4 text-xs text-gray-400">
            例如：&ldquo;我经营一家美妆电商店铺，月销售额约 50 万，客单价 120 元&rdquo;
          </p>
        </div>
      </div>
    );
  }

  // --- Loading state (initial session load) ---
  if (loading && messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-3">
          <div className="flex gap-1">
            <span className="h-2 w-2 animate-bounce rounded-full bg-indigo-400 [animation-delay:0ms]" />
            <span className="h-2 w-2 animate-bounce rounded-full bg-indigo-400 [animation-delay:150ms]" />
            <span className="h-2 w-2 animate-bounce rounded-full bg-indigo-400 [animation-delay:300ms]" />
          </div>
          <span className="text-sm text-gray-400">加载中...</span>
        </div>
      </div>
    );
  }

  // --- Chat view ---
  return (
    <div className="flex flex-1 flex-col bg-gray-50 min-h-0">
      {/* Scrollable messages */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-6"
      >
        <div className="mx-auto max-w-3xl space-y-4">
          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              isStreaming={false}
            />
          ))}

          {/* Streaming indicator */}
          {streaming && streamText && (
            <MessageBubble
              message={{
                id: "streaming",
                role: "assistant",
                content: streamText,
                sequence: 0,
                created_at: new Date().toISOString(),
              }}
              isStreaming={true}
            />
          )}

          {/* Stage label during processing */}
          {streaming && stageLabel && (
            <div className="flex items-center justify-center gap-2 py-2">
              <div className="flex gap-1">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400 [animation-delay:0ms]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400 [animation-delay:150ms]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400 [animation-delay:300ms]" />
              </div>
              <span className="text-xs text-gray-400">{stageLabel}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
