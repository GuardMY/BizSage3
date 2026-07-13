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

interface ChatInputProps {
  onSend: (content: string, action?: "reply" | "diagnose_with_current_data") => void;
  disabled: boolean;
  canForceDiagnose: boolean;
}

export default function ChatInput({ onSend, disabled, canForceDiagnose }: ChatInputProps) {
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
    onSend(trimmed, "reply");
    setText("");
  }, [text, disabled, onSend]);

  const handleForceDiagnose = useCallback(() => {
    if (disabled) return;
    onSend("", "diagnose_with_current_data");
  }, [disabled, onSend]);

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
    <div className="border-t border-gray-200 bg-white px-4 py-3">
      <div className="mx-auto max-w-4xl">
        <div className="flex items-end gap-2">
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
                w-full resize-none rounded-xl border border-gray-300 bg-gray-50
                px-4 py-2.5 pr-12 text-sm text-gray-800 placeholder-gray-400
                transition-colors
                focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-400/20
                disabled:cursor-not-allowed disabled:opacity-50
              "
            />
          </div>

          {/* Send button */}
          <button
            onClick={handleSend}
            disabled={disabled || !text.trim()}
            className="
              flex h-10 w-10 shrink-0 items-center justify-center rounded-xl
              bg-indigo-600 text-white shadow-sm transition-all
              hover:bg-indigo-500 active:scale-95
              disabled:cursor-not-allowed disabled:opacity-40 disabled:active:scale-100
            "
            aria-label="发送"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5"
              />
            </svg>
          </button>
        </div>

        {/* Bottom row: Force Diagnose */}
        <div className="mt-2 flex items-center justify-between">
          <div>
            {canForceDiagnose && (
              <button
                onClick={handleForceDiagnose}
                disabled={disabled}
                className="
                  inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5
                  text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200
                  transition-colors hover:bg-amber-100
                  disabled:cursor-not-allowed disabled:opacity-40
                "
              >
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                </svg>
                基于当前数据强制诊断
              </button>
            )}
          </div>
          <span className="text-xs text-gray-400">Enter 发送 · Shift+Enter 换行</span>
        </div>
      </div>
    </div>
  );
}
