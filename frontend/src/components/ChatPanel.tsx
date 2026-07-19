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
import { Bot } from "lucide-react";
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
      <div className="flex flex-1 flex-col items-center justify-center bg-slate-100 px-8">
        <div className="max-w-md text-center">
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-md bg-blue-600 text-white shadow-sm">
            <Bot className="h-7 w-7" />
          </div>

          <h2 className="text-xl font-semibold text-slate-950">开始您的运营诊断</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            请描述您的业务场景和运营数据，AI 将为您进行多维度诊断分析。
          </p>
          <p className="mt-4 text-xs text-slate-400">
            例如：&ldquo;我经营一家美妆电商店铺，月销售额约 50 万，客单价 120 元&rdquo;
          </p>
        </div>
      </div>
    );
  }

  // --- Loading state (initial session load) ---
  if (loading && messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center bg-slate-100">
        <div className="flex flex-col items-center gap-3">
          <div className="flex gap-1">
              <span className="h-2 w-2 animate-bounce rounded-full bg-blue-400 [animation-delay:0ms]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-blue-400 [animation-delay:150ms]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-blue-400 [animation-delay:300ms]" />
          </div>
          <span className="text-sm text-gray-400">加载中...</span>
        </div>
      </div>
    );
  }

  // --- Chat view ---
  return (
    <div className="flex flex-1 flex-col bg-slate-100 min-h-0">
      {/* Scrollable messages */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-8 py-8"
      >
        <div className="mx-auto max-w-4xl space-y-5">
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
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:0ms]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:150ms]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:300ms]" />
              </div>
              <span className="text-xs text-slate-400">{stageLabel}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
