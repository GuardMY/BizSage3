"use client";

/* =============================================================================
 * ChatInput – Message input area at bottom of the chat panel.
 *
 * Features:
 *   - Auto-resizing textarea (1-4 rows)
 *   - Send button with icon
 *   - "Force Diagnose" secondary button
 *   - Enter to send, Shift+Enter for newline
 *   - Disabled state while streaming
 * ============================================================================= */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { SendHorizontal } from "lucide-react";

interface ChatInputProps {
  onSend: (content: string) => void;
  disabled: boolean;
}

export default function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`; // max ~4 rows
  }, [text]);

  // Focus textarea when enabled
  useEffect(() => {
    if (!disabled && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [disabled]);

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
  }, [text, disabled, onSend]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <div className="border-t border-slate-200 bg-white px-8 py-4">
      <div className="mx-auto max-w-4xl">
        <div className="flex items-end gap-3">
          {/* Textarea */}
          <div className="relative flex-1">
            <textarea
              ref={textareaRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="请输入您的运营数据或回答..."
              rows={1}
              disabled={disabled}
              className="
                w-full resize-none rounded-md border border-slate-300 bg-white
                px-4 py-2.5 pr-12 text-sm text-slate-800 placeholder:text-slate-400
                transition-colors
                focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100
                disabled:cursor-not-allowed disabled:opacity-50
              "
            />
          </div>

          {/* Send button */}
          <button
            onClick={handleSend}
            disabled={disabled || !text.trim()}
            className="
              flex h-10 w-10 shrink-0 items-center justify-center rounded-md
              bg-blue-600 text-white shadow-sm transition-colors
              hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40
            "
            aria-label="发送"
          >
            <SendHorizontal className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
