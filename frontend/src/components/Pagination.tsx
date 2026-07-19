"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

const PAGE_SIZE_OPTIONS = [20, 50, 100];

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  disabled?: boolean;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
}

export default function Pagination({
  page,
  pageSize,
  total,
  disabled = false,
  onPageChange,
  onPageSizeChange,
}: PaginationProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, pageCount);
  const start = total === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const end = Math.min(safePage * pageSize, total);

  return (
    <div className="flex h-16 items-center justify-between border-t border-slate-200 bg-white px-5">
      <p className="text-sm text-slate-500">
        共 <span className="font-medium tabular-nums text-slate-700">{total}</span> 条
        {total > 0 && <span className="ml-2 text-slate-400">第 {start}-{end} 条</span>}
      </p>

      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-slate-500" htmlFor="page-size">
          每页
          <select
            id="page-size"
            value={pageSize}
            disabled={disabled}
            onChange={(event) => onPageSizeChange(Number(event.target.value))}
            className="h-9 rounded-md border border-slate-200 bg-white px-2 text-sm font-medium text-slate-700 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-slate-50"
          >
            {PAGE_SIZE_OPTIONS.map((size) => <option key={size} value={size}>{size}</option>)}
          </select>
          条
        </label>

        <div className="flex items-center gap-1">
          <button
            type="button"
            title="上一页"
            aria-label="上一页"
            disabled={disabled || safePage <= 1}
            onClick={() => onPageChange(safePage - 1)}
            className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="min-w-20 text-center text-sm tabular-nums text-slate-600">
            {safePage} / {pageCount}
          </span>
          <button
            type="button"
            title="下一页"
            aria-label="下一页"
            disabled={disabled || safePage >= pageCount}
            onClick={() => onPageChange(safePage + 1)}
            className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>

        <label className="flex items-center gap-2 text-sm text-slate-500" htmlFor="page-jump">
          前往
          <input
            id="page-jump"
            type="number"
            min={1}
            max={pageCount}
            value={safePage}
            disabled={disabled}
            onChange={(event) => {
              const next = Number(event.target.value);
              if (Number.isInteger(next) && next >= 1 && next <= pageCount) onPageChange(next);
            }}
            className="h-9 w-14 rounded-md border border-slate-200 px-2 text-center text-sm tabular-nums text-slate-700 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-slate-50"
          />
          页
        </label>
      </div>
    </div>
  );
}
