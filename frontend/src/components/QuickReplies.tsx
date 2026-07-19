"use client";

/* =============================================================================
 * QuickReplies – Clickable suggestion chips shown above the chat input.
 *
 * Displays LLM-generated quick-reply options that users can click to
 * instantly send as their message. Supports horizontal scrolling for
 * many options.
 * ============================================================================= */

import React, { useRef, useEffect } from "react";

interface QuickRepliesProps {
  replies: string[];
  onSelect: (reply: string) => void;
  disabled: boolean;
}

export default function QuickReplies({ replies, onSelect, disabled }: QuickRepliesProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Show on mount: scroll to the start position
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollLeft = 0;
    }
  }, [replies]);

  if (!replies || replies.length === 0) return null;

  return (
    <div className="border-t border-slate-100 bg-white px-8 py-3">
      <div className="mx-auto max-w-4xl">
        <div
          ref={scrollRef}
          className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin"
          style={{ scrollbarWidth: "thin" }}
        >
          {replies.map((reply, idx) => (
            <button
              key={idx}
              type="button"
              disabled={disabled}
              onClick={() => onSelect(reply)}
              className="
                shrink-0 rounded-md border border-slate-200 bg-slate-50
                px-3 py-1.5 text-sm text-slate-700
                transition-colors
                hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700
                disabled:cursor-not-allowed disabled:opacity-40
              "
            >
              {reply}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
