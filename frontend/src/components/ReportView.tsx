"use client";

/* =============================================================================
 * ReportView – Full diagnosis report view.
 *
 * Features:
 *   - Renders markdown using react-markdown
 *   - Download button (calls GET /api/v1/sessions/{id}/report/download)
 *   - Print-friendly styling
 *   - Severity badges for diagnosis findings
 * ============================================================================= */

import React, { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { ReportResponse } from "@/types";
import { getReportDownloadUrl } from "@/lib/api";

interface ReportViewProps {
  sessionId: string;
  reports: ReportResponse[];
  loading: boolean;
  generating: boolean;
}

export default function ReportView({
  sessionId,
  reports,
  loading,
  generating,
}: ReportViewProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const orderedReports = useMemo(
    () => [...reports].sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [reports],
  );
  const selectedReport =
    orderedReports.find((report) => report.id === selectedId) ?? orderedReports[0] ?? null;
  const severityMap = useMemo(
    () => extractSeverities(selectedReport?.markdown ?? ""),
    [selectedReport],
  );

  useEffect(() => {
    if (orderedReports.length === 0) {
      setSelectedId(null);
    } else if (!orderedReports.some((report) => report.id === selectedId)) {
      setSelectedId(orderedReports[0].id);
    }
  }, [orderedReports, selectedId]);

  // --- Loading ---
  if (loading && orderedReports.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center bg-white">
        <div className="flex flex-col items-center gap-3">
          <div className="flex gap-1">
            <span className="h-2 w-2 animate-bounce rounded-full bg-indigo-400 [animation-delay:0ms]" />
            <span className="h-2 w-2 animate-bounce rounded-full bg-indigo-400 [animation-delay:150ms]" />
            <span className="h-2 w-2 animate-bounce rounded-full bg-indigo-400 [animation-delay:300ms]" />
          </div>
          <span className="text-sm text-gray-400">加载诊断报告中...</span>
        </div>
      </div>
    );
  }

  // --- Empty ---
  if (!selectedReport) {
    return (
      <div className="flex flex-1 items-center justify-center bg-white">
        <div className="max-w-sm text-center">
          <svg
            className="mx-auto h-12 w-12 text-gray-300"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={1}
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
            />
          </svg>
          <p className="mt-3 text-sm text-gray-500">
            {generating ? "诊断报告正在后台生成" : "暂无诊断报告"}
          </p>
          <p className="mt-1 text-xs text-gray-400">
            {generating ? "生成期间可以继续对话" : "可从右侧诊断进度中生成报告"}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col bg-white">
      {/* Toolbar */}
      <div className="flex items-center justify-between border-b border-gray-200 px-6 py-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-gray-800">诊断报告</h2>
          <p className="mt-0.5 text-xs text-gray-400">
            {formatReportDate(selectedReport.created_at)}
            {generating && <span className="ml-2 text-amber-600">新报告生成中</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Severity legend */}
          <div className="hidden items-center gap-2 text-xs sm:flex">
            <SeverityDot color="green" label="优势" />
            <SeverityDot color="gray" label="正常" />
            <SeverityDot color="yellow" label="风险" />
            <SeverityDot color="red" label="严重问题" />
          </div>

          <div className="h-4 w-px bg-gray-200" />

          {/* Download button */}
          <a
            href={getReportDownloadUrl(sessionId, selectedReport.id)}
            download
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-indigo-500"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"
              />
            </svg>
            下载报告
          </a>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col sm:flex-row">
        <aside className="w-full shrink-0 overflow-x-auto border-b border-gray-200 bg-gray-50 sm:w-56 sm:overflow-y-auto sm:border-r sm:border-b-0">
          <div className="hidden border-b border-gray-200 px-3 py-2.5 text-xs font-medium text-gray-500 sm:block">
            历史报告 · {orderedReports.length}
          </div>
          <div className="flex sm:block sm:py-1">
            {generating && (
              <div className="flex min-w-36 items-center gap-2 border-r border-gray-200 px-3 py-3 text-xs text-amber-700 sm:min-w-0 sm:border-r-0 sm:border-b">
                <span className="h-2 w-2 animate-pulse rounded-full bg-amber-400" />
                后台生成中
              </div>
            )}
            {orderedReports.map((report, index) => (
              <button
                key={report.id}
                type="button"
                onClick={() => setSelectedId(report.id)}
                className={`min-w-40 border-r border-gray-200 px-3 py-3 text-left transition-colors sm:w-full sm:min-w-0 sm:border-r-0 sm:border-b ${
                  report.id === selectedReport.id
                    ? "bg-white text-gray-900"
                    : "text-gray-600 hover:bg-white"
                }`}
              >
                <span className="block text-sm font-medium">
                  {index === 0 ? "最新报告" : `历史报告 ${orderedReports.length - index}`}
                </span>
                <span className="mt-1 block text-xs text-gray-400">
                  {formatReportDate(report.created_at)}
                </span>
              </button>
            ))}
          </div>
        </aside>

        <div className="flex-1 overflow-y-auto print:overflow-visible">
          <div className="mx-auto max-w-3xl px-6 py-8 print:px-0 print:py-4">
            <div className="report-content">
              <ReactMarkdown
                components={{
                  p: ({ children, ...props }) => {
                    const text = extractText(children);
                    const sev = severityMap[text.trim()];
                    if (sev) {
                      return (
                        <p {...props} className="flex items-start gap-2">
                          <SeverityBadge sev={sev.severity} />
                          <span>{children}</span>
                        </p>
                      );
                    }
                    return <p {...props}>{children}</p>;
                  },
                }}
              >
                {selectedReport.markdown}
              </ReactMarkdown>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function formatReportDate(iso: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}

// ---------------------------------------------------------------------------
// Severity Badge
// ---------------------------------------------------------------------------

function SeverityBadge({ sev }: { sev: string }) {
  const config = SEVERITY_CONFIG[sev] ?? SEVERITY_CONFIG.正常;
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium ${config.bg} ${config.text}`}
    >
      <span className={`mr-1 h-1.5 w-1.5 rounded-full ${config.dot}`} />
      {config.label}
    </span>
  );
}

function SeverityDot({ color, label }: { color: string; label: string }) {
  const dotColors: Record<string, string> = {
    green: "bg-green-400",
    gray: "bg-gray-400",
    yellow: "bg-yellow-400",
    red: "bg-red-400",
  };
  return (
    <span className="inline-flex items-center gap-1 text-gray-500">
      <span className={`h-2 w-2 rounded-full ${dotColors[color] ?? "bg-gray-400"}`} />
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Severity Configuration
// ---------------------------------------------------------------------------

const SEVERITY_CONFIG: Record<string, { label: string; bg: string; text: string; dot: string }> = {
  优势: {
    label: "优势",
    bg: "bg-green-100",
    text: "text-green-700",
    dot: "bg-green-400",
  },
  正常: {
    label: "正常",
    bg: "bg-gray-100",
    text: "text-gray-600",
    dot: "bg-gray-400",
  },
  风险: {
    label: "风险",
    bg: "bg-yellow-100",
    text: "text-yellow-700",
    dot: "bg-yellow-400",
  },
  严重问题: {
    label: "严重问题",
    bg: "bg-red-100",
    text: "text-red-700",
    dot: "bg-red-400",
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Extract plain text from React children (recursive). */
function extractText(children: React.ReactNode): string {
  let text = "";
  React.Children.forEach(children, (child) => {
    if (typeof child === "string" || typeof child === "number") {
      text += String(child);
    } else if (React.isValidElement(child)) {
      const props = child.props as Record<string, unknown>;
      if (props.children) {
        text += extractText(props.children as React.ReactNode);
      }
    }
  });
  return text;
}

/** Scan markdown for lines that start with a known severity keyword. */
function extractSeverities(
  markdown: string,
): Record<string, { severity: string; label: string }> {
  const map: Record<string, { severity: string; label: string }> = {};
  const severities = ["优势", "正常", "风险", "严重问题"];

  for (const sev of severities) {
    const regex = new RegExp(`^${sev}[：:]\\s*(.+)$`, "gm");
    let match;
    while ((match = regex.exec(markdown)) !== null) {
      map[match[1].trim()] = { severity: sev, label: sev };
    }
  }

  return map;
}
