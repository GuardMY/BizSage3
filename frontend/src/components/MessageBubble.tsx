"use client";

/* =============================================================================
 * MessageBubble – Single chat message bubble with markdown rendering.
 * ============================================================================= */

import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ExternalLink, FileText, Globe2, MapPin } from "lucide-react";
import type { ConversationCitation, Message } from "@/types";

interface MessageBubbleProps {
  message: Message;
  isStreaming?: boolean;
}

export default function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const time = formatTime(message.created_at);
  const citations = !isUser ? message.citations ?? [] : [];

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
      <div className={`flex max-w-[85%] flex-col ${isUser ? "items-end" : "items-start"}`}>
        <div
          className={`
            rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm
            ${
              isUser
                ? "bg-indigo-600 text-white rounded-tr-md"
                : "border border-gray-200 bg-white text-gray-800 rounded-tl-md"
            }
          `}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
          ) : (
            <div className="agent-markdown">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ href, children, ...props }) => (
                    <a
                      {...props}
                      href={href}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      {children}
                    </a>
                  ),
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>
          )}

          {/* Streaming cursor */}
          {isStreaming && (
            <span className="inline-block w-1.5 h-4 bg-gray-500 animate-pulse ml-0.5" />
          )}
        </div>

        {citations.length > 0 && (
          <div className="mt-2 w-full space-y-2" aria-label="引用资料">
            {citations.map((citation) => (
              <CitationCard key={citation.citation_id} citation={citation} />
            ))}
          </div>
        )}

        {/* Timestamp */}
        <span className={`text-xs text-gray-400 mt-1 ${isUser ? "mr-1" : "ml-1"}`}>
          {time}
        </span>
      </div>
    </div>
  );
}

function CitationCard({ citation }: { citation: ConversationCitation }) {
  const isWeb = citation.source_type === "web";
  const location = citationLocation(citation);
  const domain = citation.url ? displayDomain(citation.url) : "";
  const publishedAt = citation.published_at ? formatPublishedAt(citation.published_at) : "";

  return (
    <article className="border border-gray-200 bg-white px-3 py-2.5 text-xs text-gray-600 shadow-sm rounded-md">
      <div className="flex min-w-0 items-start gap-2">
        {isWeb ? (
          <Globe2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-sky-600" aria-hidden="true" />
        ) : (
          <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" aria-hidden="true" />
        )}
        <div className="min-w-0 flex-1">
          <p className="break-words font-medium text-gray-800">[资料 {citation.citation_id}] {citation.title}</p>
          {citation.quote && (
            <p className="mt-1 break-words leading-5 text-gray-600">{citation.quote}</p>
          )}
          <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-gray-500">
            {location && (
              <span className="inline-flex min-w-0 items-center gap-1">
                <MapPin className="h-3 w-3 shrink-0" aria-hidden="true" />
                <span className="break-all">{location}</span>
              </span>
            )}
            {publishedAt && <span>{publishedAt}</span>}
            {citation.url && (
              <a
                href={citation.url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex min-w-0 items-center gap-1 text-indigo-700 hover:text-indigo-900 hover:underline"
              >
                <span className="break-all">{domain || citation.url}</span>
                <ExternalLink className="h-3 w-3 shrink-0" aria-hidden="true" />
              </a>
            )}
          </div>
        </div>
      </div>
    </article>
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

function citationLocation(citation: ConversationCitation): string {
  const heading = citation.locator.heading_path;
  if (typeof heading === "string" && heading) return heading;
  const line = citation.locator.line_start;
  if (typeof line === "string" || typeof line === "number") return `第 ${line} 行`;
  const version = citation.locator.version_no;
  if (typeof version === "string" || typeof version === "number") return `版本 ${version}`;
  return "";
}

function displayDomain(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function formatPublishedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("zh-CN");
}
