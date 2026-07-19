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
import { AlertTriangle } from "lucide-react";
import type { CompletenessDetail } from "@/types";

interface ProgressPanelProps {
  score: number;
  completeness: CompletenessDetail | null;
  stage: string;
  canGenerateReport: boolean;
  reportGenerating: boolean;
  onGenerateReport: () => void;
}

export default function ProgressPanel({
  score,
  completeness,
  stage,
  canGenerateReport,
  reportGenerating,
  onGenerateReport,
}: ProgressPanelProps) {
  const stageLabel = stageLabelForStage(stage);
  const isReady = score >= 80;

  return (
    <aside className="flex h-full w-full flex-col bg-white">
      {/* Header */}
      <div className="flex h-16 items-center border-b border-slate-200 px-5">
        <div><p className="text-xs font-semibold text-blue-700">ANALYSIS</p><h3 className="mt-0.5 text-sm font-semibold text-slate-900">诊断进度</h3></div>
      </div>

      <div className="flex-1 space-y-6 overflow-y-auto px-5 py-6">
        {/* ---- Score Gauge ---- */}
        <ScoreGauge score={score} label="信息完备度" />

        {/* ---- Stage Indicator ---- */}
        <div>
          <h4 className="mb-1.5 text-xs font-medium text-slate-400">
            当前阶段
          </h4>
          <div className="flex items-center gap-2 rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-700">
            <span className="h-2 w-2 rounded-full bg-blue-500" />
            {stage ? stageLabel : "等待开始"}
          </div>
        </div>

        {/* ---- Collected Info Summary ---- */}
        {completeness?.summary && (
          <div>
            <h4 className="mb-1.5 text-xs font-medium text-slate-400">
              已有信息
            </h4>
            <p className="rounded-md bg-blue-50 px-3 py-2 text-xs leading-relaxed text-blue-800">
              {completeness.summary}
            </p>
          </div>
        )}

        {/* ---- Missing Aspects ---- */}
        {completeness && completeness.missing_aspects.length > 0 && (
          <div>
            <h4 className="mb-1.5 text-xs font-medium text-slate-400">
              还需了解
            </h4>
            <ul className="space-y-1">
              {completeness.missing_aspects.map((aspect, i) => (
                <li
                  key={i}
                  className="flex items-start gap-1.5 text-xs text-slate-600"
                >
                  <span className="mt-0.5 shrink-0 text-amber-400">✗</span>
                  <span>{aspect}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* ---- Generate Report Button ---- */}
        <div className="border border-slate-200 bg-slate-50 p-3">
          {!isReady && completeness && (
            <div className="mb-2 flex items-start gap-1.5">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
              <p className="text-xs text-amber-700">
                信息完备度 {score}%，报告可能不够全面
              </p>
            </div>
          )}
          <button
            onClick={onGenerateReport}
            disabled={!canGenerateReport}
            className="h-10 w-full rounded-md bg-blue-600 px-3 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {reportGenerating ? "报告后台生成中..." : "生成诊断报告"}
          </button>
          {reportGenerating && (
            <p className="mt-2 text-center text-xs text-slate-500">
              可继续对话，完成后会自动更新
            </p>
          )}
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
          className="text-slate-100"
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
        <span className="text-2xl font-semibold text-slate-800">{score}</span>
        <span className="text-xs text-slate-400">{label}</span>
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
