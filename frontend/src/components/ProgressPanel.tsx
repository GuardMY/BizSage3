"use client";

/* =============================================================================
 * ProgressPanel – Right sidebar showing diagnosis completeness and progress.
 *
 * Features:
 *   - Completeness score gauge (circular SVG, 0-100)
 *   - Core metrics progress: X/10 provided
 *   - Secondary metrics progress: percentage
 *   - Stage indicator
 *   - "Force Diagnosis" button when score < 80 but enough data
 *   - Limited diagnosis warning
 * ============================================================================= */

import React from "react";
import type { ScoreDetail } from "@/types";

interface ProgressPanelProps {
  score: number;
  scoreDetail: ScoreDetail | null;
  stage: string;
  canForceDiagnose: boolean;
  onForceDiagnose: () => void;
}

export default function ProgressPanel({
  score,
  scoreDetail,
  stage,
  canForceDiagnose,
  onForceDiagnose,
}: ProgressPanelProps) {
  const stageLabel = stageLabelForStage(stage);

  return (
    <aside className="flex h-full w-72 flex-col border-l border-gray-200 bg-white">
      {/* Header */}
      <div className="border-b border-gray-100 px-4 py-3">
        <h3 className="text-sm font-semibold text-gray-800">诊断进度</h3>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-6">
        {/* ---- Score Gauge ---- */}
        <ScoreGauge score={score} />

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

        {/* ---- Core Metrics ---- */}
        {scoreDetail && (
          <div>
            <h4 className="mb-1.5 text-xs font-medium uppercase tracking-wider text-gray-400">
              核心指标
            </h4>
            <ProgressBar
              label="核心指标进度"
              value={scoreDetail.core_provided_count}
              max={10}
            />

            {/* Missing core metrics */}
            {scoreDetail.missing_core.length > 0 && (
              <div className="mt-2">
                <p className="mb-1 text-xs text-gray-400">缺失:</p>
                <div className="flex flex-wrap gap-1">
                  {scoreDetail.missing_core.map((code) => (
                    <span
                      key={code}
                      className="inline-block rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-600"
                    >
                      {code}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ---- Secondary Metrics ---- */}
        {scoreDetail && (
          <div>
            <h4 className="mb-1.5 text-xs font-medium uppercase tracking-wider text-gray-400">
              辅助指标
            </h4>
            <ProgressBar
              label="辅助指标覆盖度"
              value={Math.round(scoreDetail.secondary_coverage * 100)}
              max={100}
              suffix="%"
            />

            {/* Missing secondary metrics */}
            {scoreDetail.missing_secondary.length > 0 && (
              <div className="mt-2">
                <p className="mb-1 text-xs text-gray-400">缺失:</p>
                <div className="flex flex-wrap gap-1">
                  {scoreDetail.missing_secondary.map((code) => (
                    <span
                      key={code}
                      className="inline-block rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-600"
                    >
                      {code}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ---- Anomaly Status ---- */}
        {scoreDetail && !scoreDetail.anomaly_complete && (
          <div>
            <h4 className="mb-1.5 text-xs font-medium uppercase tracking-wider text-gray-400">
              异常项
            </h4>
            <div className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">
              存在 {scoreDetail.unresolved_anomalies.length} 个未解决的异常项
            </div>
          </div>
        )}

        {/* ---- Force Diagnose ---- */}
        {canForceDiagnose && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
            <div className="flex items-start gap-2">
              <svg
                className="mt-0.5 h-4 w-4 shrink-0 text-amber-500"
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
              <div>
                <p className="text-xs font-medium text-amber-800">数据尚未完备</p>
                <p className="mt-1 text-xs text-amber-700">
                  当前评分 {score}/100，部分数据缺失仍可生成初步诊断
                </p>
                <button
                  onClick={onForceDiagnose}
                  className="mt-2 w-full rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-amber-400"
                >
                  基于当前数据强制诊断
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Score Gauge (circular SVG)
// ---------------------------------------------------------------------------

function ScoreGauge({ score }: { score: number }) {
  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;

  const color =
    score >= 80 ? "text-green-500" : score >= 60 ? "text-yellow-500" : score >= 40 ? "text-orange-500" : "text-red-500";

  return (
    <div className="flex flex-col items-center">
      <svg className="h-24 w-24 -rotate-90" viewBox="0 0 80 80">
        {/* Background circle */}
        <circle
          cx="40"
          cy="40"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="6"
          className="text-gray-100"
        />
        {/* Foreground circle */}
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
      <div className="absolute mt-12 flex flex-col items-center">
        <span className="text-2xl font-bold text-gray-800">{score}</span>
        <span className="text-xs text-gray-400">完备度</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Simple horizontal progress bar
// ---------------------------------------------------------------------------

function ProgressBar({
  label,
  value,
  max,
  suffix = "",
}: {
  label: string;
  value: number;
  max: number;
  suffix?: string;
}) {
  const pct = Math.min(Math.round((value / max) * 100), 100);

  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-gray-500">{label}</span>
        <span className="font-medium text-gray-700">
          {value}/{max}{suffix}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100">
        <div
          className="h-full rounded-full bg-gradient-to-r from-indigo-400 to-indigo-600 transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
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
    collect_metrics: "提取运营指标",
    check_complete: "评估信息完备度",
    exception_ask: "生成补充问题",
    await_input: "等待您的回复",
    diagnosis_analysis: "六维度诊断分析",
    generate_report: "生成诊断报告",
  };
  return labels[stage] ?? stage;
}
