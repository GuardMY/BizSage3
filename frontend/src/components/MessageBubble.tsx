"use client";

/* =============================================================================
 * MessageBubble – Single chat message bubble with markdown rendering.
 * ============================================================================= */

import React from "react";
import ReactMarkdown from "react-markdown";
import type { Message } from "@/types";

interface MessageBubbleProps {
  message: Message;
  isStreaming?: boolean;
}

export default function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const time = formatTime(message.created_at);

  return (
    <div
      className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"} items-start`}
    >
      {/* Avatar */}
      <div
        className={`
          flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center
          text-sm font-bold shadow-sm
          ${isUser ? "bg-indigo-500 text-white" : "bg-gray-200 text-gray-600"}
        `}
      >
        {isUser ? "我" : "AI"}
      </div>

      {/* Bubble */}
      <div className={`flex flex-col ${isUser ? "items-end" : "items-start"} max-w-[75%]`}>
        <div
          className={`
            rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm
            ${
              isUser
                ? "bg-gradient-to-br from-indigo-500 to-purple-600 text-white rounded-tr-md"
                : "bg-gray-100 text-gray-800 rounded-tl-md"
            }
          `}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
          ) : (
            <div className="prose prose-sm max-w-none prose-p:leading-relaxed prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-headings:my-2 prose-h3:text-base prose-h4:text-sm prose-code:bg-gray-200 prose-code:px-1 prose-code:rounded prose-code:text-sm prose-a:text-blue-600 prose-strong:font-semibold prose-blockquote:border-l-gray-300 prose-blockquote:text-gray-500">
              <ReactMarkdown>{message.content}</ReactMarkdown>
            </div>
          )}

          {/* Streaming cursor */}
          {isStreaming && (
            <span className="inline-block w-1.5 h-4 bg-gray-500 animate-pulse ml-0.5" />
          )}
        </div>

        {/* Timestamp */}
        <span className={`text-xs text-gray-400 mt-1 ${isUser ? "mr-1" : "ml-1"}`}>
          {time}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    const hh = d.getHours().toString().padStart(2, "0");
    const mm = d.getMinutes().toString().padStart(2, "0");
    return `${hh}:${mm}`;
  } catch {
    return "";
  }
}
