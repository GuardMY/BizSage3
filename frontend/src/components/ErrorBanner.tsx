"use client";

/* =============================================================================
 * ErrorBanner – Dismissible red/orange error banner at the top of the view.
 * Auto-dismisses after 10 seconds.
 * ============================================================================= */

import { useEffect, useState } from "react";

interface ErrorBannerProps {
  message: string | null;
  onDismiss: () => void;
}

export default function ErrorBanner({ message, onDismiss }: ErrorBannerProps) {
  const [visible, setVisible] = useState(false);
  const [fading, setFading] = useState(false);

  useEffect(() => {
    if (message) {
      setVisible(true);
      setFading(false);

      const timer = setTimeout(() => {
        handleDismiss();
      }, 10000);

      return () => clearTimeout(timer);
    } else {
      setVisible(false);
      setFading(false);
    }
  }, [message]);

  const handleDismiss = () => {
    setFading(true);
    setTimeout(() => {
      setVisible(false);
      setFading(false);
      onDismiss();
    }, 300);
  };

  if (!visible || !message) return null;

  return (
    <div
      className={`
        flex items-center gap-3 px-4 py-3 text-sm font-medium text-white
        bg-gradient-to-r from-red-500 to-orange-500 shadow-md
        transition-all duration-300
        ${fading ? "opacity-0 -translate-y-2" : "opacity-100 translate-y-0"}
      `}
      role="alert"
    >
      {/* Icon */}
      <svg
        className="h-5 w-5 shrink-0"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth={2}
        stroke="currentColor"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"
        />
      </svg>

      <span className="flex-1">{message}</span>

      {/* Dismiss button */}
      <button
        onClick={handleDismiss}
        className="shrink-0 rounded-full p-1 hover:bg-white/20 transition-colors"
        aria-label="关闭"
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}
