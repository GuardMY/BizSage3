"use client";

/* =============================================================================
 * ErrorBanner – Dismissible red/orange error banner at the top of the view.
 * Auto-dismisses after 10 seconds.
 * ============================================================================= */

import { useEffect, useState } from "react";
import { AlertCircle, X } from "lucide-react";

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
        flex items-center gap-3 border-b border-red-200 bg-red-50 px-5 py-3 text-sm font-medium text-red-800
        transition-all duration-300
        ${fading ? "opacity-0 -translate-y-2" : "opacity-100 translate-y-0"}
      `}
      role="alert"
    >
      <AlertCircle className="h-5 w-5 shrink-0" />

      <span className="flex-1">{message}</span>

      {/* Dismiss button */}
      <button
        onClick={handleDismiss}
        className="shrink-0 rounded-md p-1 transition-colors hover:bg-red-100"
        aria-label="关闭"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
