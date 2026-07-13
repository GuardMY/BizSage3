"use client";

/* =============================================================================
 * ProgressPanel – Right sidebar showing diagnosis completeness and progress.
 *
 * Features:
 *   - Completeness score gauge (circular SVG, 0-100)
 *   - Colleced info summary
 *   - Missing aspects list
 *   - "Generate Report" button (always available, warns when < 80%)
 * ============================================================================= */

import React from "react";
import type { CompletenessDetail } from "@/types";

interface ProgressPanelProps {
  score: number;
  completeness: CompletenessDetail | null;
  stage: string;
  canGenerateReport: boolean;
  onGenerateReport: () => void;
}

export default function ProgressPanel({
  score,
  completeness,
  stage,
  canGenerateReport,
  onGenerateReport,
}: ProgressPanelProps) {
  const stageLabel = stageLabelForStage(stage);
  const isReady = score >= 80;

  return (
    <aside className="flex h-full w-72 flex-col border-l border-gray-200 bg-white">
      {/* Header */}
      <div className="border-b border-gray-100 px-4 py-3">
        <h3 className="text-sm font-semibold text-gray-800">诊断进度</h3>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-6">
        {/* ---- Score Gauge ---- */}
        <ScoreGauge score={score} label="信息完备度" />

        {/* ---- Stage Indicator ---- */}
        <div>
          <h4 className="mb-1.5 text-xs font-medium uppercase tracking-wider text-gray-400">
            当前阶段
          </h4>
          <div className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-700">
            <span className="h-2 w-2 rounded-full bg-indigo-400" />
            {stage ? stageLabel : "等待开始"}
          </div>
        </div>

        {/* ---- Collected Info Summary ---- */}
        {completeness?.summary && (
          <div>
            <h4 className="mb-1.5 text-xs font-medium uppercase tracking-wider text-gray-400">
              已有信息
            </h4>
            <p className="rounded-lg bg-indigo-50 px-3 py-2 text-xs text-indigo-700 leading-relaxed">
              {completeness.summary}
            </p>
          </div>
        )}

        {/* ---- Missing Aspects ---- */}
        {completeness && completeness.missing_aspects.length > 0 && (
          <div>
            <h4 className="mb-1.5 text-xs font-medium uppercase tracking-wider text-gray-400">
              还需了解
            </h4>
            <ul className="space-y-1">
              {completeness.missing_aspects.map((aspect, i) => (
                <li
                  key={i}
                  className="flex items-start gap-1.5 text-xs text-gray-600"
                >
                  <span className="mt-0.5 shrink-0 text-amber-400">✗</span>
                  <span>{aspect}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* ---- Generate Report Button ---- */}
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
          {!isReady && completeness && (
            <div className="mb-2 flex items-start gap-1.5">
              <svg
                className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500"
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth={2}
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
                />
              </svg>
              <p className="text-xs text-amber-700">
                信息完备度 {score}%，报告可能不够全面
              </p>
            </div>
          )}
          <button
            onClick={onGenerateReport}
            disabled={!canGenerateReport}
            className="w-full rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            生成诊断报告
          </button>
        </div>
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Score Gauge (circular SVG)
// ---------------------------------------------------------------------------

function ScoreGauge({ score, label }: { score: number; label: string }) {
  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (Math.min(score, 100) / 100) * circumference;

  const color =
    score >= 80
      ? "text-green-500"
      : score >= 60
        ? "text-yellow-500"
        : score >= 40
          ? "text-orange-500"
          : "text-red-500";

  return (
    <div className="relative flex flex-col items-center">
      <svg className="h-24 w-24 -rotate-90" viewBox="0 0 80 80">
        <circle
          cx="40"
          cy="40"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="6"
          className="text-gray-100"
        />
        <circle
          cx="40"
          cy="40"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className={`transition-all duration-700 ease-out ${color}`}
        />
      </svg>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-bold text-gray-800">{score}</span>
        <span className="text-xs text-gray-400">{label}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function stageLabelForStage(stage: string): string {
  const labels: Record<string, string> = {
    init: "初始化",
    scene_recognize: "识别行业场景",
    greeting_guide: "自我介绍",
    chat_extract: "分析对话",
    agent_reply: "思考中",
    await_input: "等待您的回复",
    generate_report: "生成诊断报告",
  };
  return labels[stage] ?? stage;
}
