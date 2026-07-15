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
    <div className="border-t border-gray-100 bg-gray-50/80 px-4 py-2.5">
      <div className="mx-auto max-w-4xl">
        {/* Label */}
        <p className="mb-1.5 text-xs font-medium text-gray-400">快捷回复</p>

        {/* Scrollable chip row */}
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
                shrink-0 rounded-full border border-gray-300 bg-white
                px-3.5 py-1.5 text-sm text-gray-700
                transition-all duration-150
                hover:border-indigo-400 hover:bg-indigo-50 hover:text-indigo-700
                active:scale-95 active:bg-indigo-100
                disabled:cursor-not-allowed disabled:opacity-40 disabled:active:scale-100
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
