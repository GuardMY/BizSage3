"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  Ban,
  Check,
  Clock3,
  Copy,
  KeyRound,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import Pagination from "@/components/Pagination";
import * as api from "@/lib/api";
import { formatAppDateTime } from "@/lib/time";
import type { CreatedTemporaryAccessToken, TemporaryAccessToken } from "@/types";

const EXPIRY_OPTIONS = [
  { hours: 1, label: "1 小时" },
  { hours: 24, label: "24 小时" },
  { hours: 24 * 7, label: "7 天" },
  { hours: 24 * 30, label: "30 天" },
];

export default function TemporaryTokenManagement() {
  const [tokens, setTokens] = useState<TemporaryAccessToken[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [name, setName] = useState("");
  const [expiresInHours, setExpiresInHours] = useState(24);
  const [createdToken, setCreatedToken] = useState<CreatedTemporaryAccessToken | null>(null);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [processingTokenId, setProcessingTokenId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadTokens = useCallback(async (targetPage = page, targetPageSize = pageSize) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.listTemporaryTokens(targetPage, targetPageSize);
      setTokens(result.items);
      setTotal(result.total);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setLoading(false);
    }
  }, [page, pageSize]);

  useEffect(() => {
    void loadTokens();
  }, [loadTokens]);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    setCreatedToken(null);
    try {
      const created = await api.createTemporaryToken(name.trim(), expiresInHours);
      setCreatedToken(created);
      setName("");
      setCopied(false);
      setCopyError(null);
      if (page === 1) await loadTokens(1, pageSize);
      else setPage(1);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCopy() {
    if (!createdToken) return;
    setCopyError(null);
    try {
      await copyToClipboard(createdToken.token);
      setCopied(true);
    } catch {
      setCopied(false);
      setCopyError("复制失败，请手动选择上方令牌进行复制");
    }
  }

  async function refreshAfterMutation() {
    const targetPage = tokens.length === 1 && page > 1 ? page - 1 : page;
    if (targetPage === page) await loadTokens(targetPage, pageSize);
    else setPage(targetPage);
  }

  async function handleRevoke(token: TemporaryAccessToken) {
    const warning = token.status === "active"
      ? "现有登录会立即失效，撤销后可永久删除。"
      : "撤销后可永久删除。";
    if (!window.confirm(`确认撤销“${token.name}”吗？${warning}`)) return;
    setProcessingTokenId(token.id);
    setError(null);
    try {
      await api.revokeTemporaryToken(token.id);
      await refreshAfterMutation();
    } catch (err) {
      setError(readableError(err));
    } finally {
      setProcessingTokenId(null);
    }
  }

  async function handleDelete(token: TemporaryAccessToken) {
    if (!window.confirm(`永久删除“${token.name}”吗？此操作无法恢复。`)) return;
    setProcessingTokenId(token.id);
    setError(null);
    try {
      await api.deleteTemporaryToken(token.id);
      await refreshAfterMutation();
    } catch (err) {
      setError(readableError(err));
    } finally {
      setProcessingTokenId(null);
    }
  }

  return (
    <section className="space-y-7">
      <header className="flex items-end justify-between border-b border-slate-200 pb-6">
        <div className="flex items-start gap-4">
          <div className="flex h-11 w-11 items-center justify-center rounded-md bg-blue-600 text-white shadow-sm">
            <KeyRound className="h-5 w-5" />
          </div>
          <div>
            <p className="text-xs font-semibold text-blue-700">ACCESS CONTROL</p>
            <h2 className="mt-1 text-xl font-semibold text-slate-950">临时访问令牌</h2>
            <p className="mt-1 text-sm text-slate-500">签发、撤销和管理外部协作人员的临时访问权限。</p>
          </div>
        </div>
      </header>

      <section className="grid grid-cols-[minmax(0,1fr)_380px] gap-10 border-b border-slate-200 pb-8">
        <div className="pt-1">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <ShieldCheck className="h-4 w-4 text-emerald-600" />
            签发临时令牌
          </div>
          <p className="mt-3 max-w-xl text-sm leading-6 text-slate-500">
            为临时访问人员设置用途和有效期。令牌到期或被撤销后，相关会话会立即失效。
          </p>
        </div>

        <form onSubmit={handleCreate} className="border border-slate-200 bg-white p-5 shadow-sm">
          <div className="space-y-4">
            <div>
              <label htmlFor="token-name" className="mb-1.5 block text-sm font-medium text-slate-700">名称</label>
              <input
                id="token-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={80}
                placeholder="例如：客户演示"
                className="h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
            <div>
              <label htmlFor="token-expiry" className="mb-1.5 block text-sm font-medium text-slate-700">有效期</label>
              <select
                id="token-expiry"
                value={expiresInHours}
                onChange={(event) => setExpiresInHours(Number(event.target.value))}
                className="h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              >
                {EXPIRY_OPTIONS.map((option) => <option key={option.hours} value={option.hours}>{option.label}</option>)}
              </select>
            </div>
            <button
              type="submit"
              disabled={!name.trim() || submitting}
              className="flex h-10 w-full items-center justify-center gap-2 rounded-md bg-blue-600 px-4 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Plus className="h-4 w-4" />
              <span>{submitting ? "正在生成..." : "生成令牌"}</span>
            </button>
          </div>
        </form>
      </section>

      {createdToken && (
        <section className="border border-emerald-200 bg-emerald-50 px-5 py-4">
          <div className="flex items-start gap-3">
            <KeyRound className="mt-0.5 h-5 w-5 shrink-0 text-emerald-700" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-4">
                <h3 className="text-sm font-semibold text-emerald-950">令牌已生成，仅显示一次</h3>
                <button type="button" onClick={() => setCreatedToken(null)} className="text-xs font-medium text-emerald-800 hover:text-emerald-950">关闭</button>
              </div>
              <div className="mt-3 flex min-w-0 items-center gap-2">
                <code className="min-w-0 flex-1 overflow-x-auto border border-emerald-200 bg-white px-3 py-2.5 text-sm text-slate-900">{createdToken.token}</code>
                <button
                  type="button"
                  onClick={() => void handleCopy()}
                  title={copied ? "已复制" : "复制令牌"}
                  aria-label={copied ? "令牌已复制" : "复制令牌"}
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-emerald-700 text-white transition hover:bg-emerald-800"
                >
                  {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                </button>
              </div>
              {(copyError || copied) && <p role="status" className={`mt-2 text-xs ${copyError ? "text-red-700" : "text-emerald-800"}`}>{copyError ?? "已复制到剪贴板"}</p>}
            </div>
          </div>
        </section>
      )}

      {error && <div role="alert" className="border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <section>
        <div className="mb-4 flex items-center justify-between gap-4">
          <div>
            <h3 className="text-base font-semibold text-slate-900">已签发令牌</h3>
            <p className="mt-1 text-sm text-slate-500">可随时撤销失效令牌，保护访问范围。</p>
          </div>
          <button
            type="button"
            onClick={() => void loadTokens()}
            disabled={loading}
            title="刷新令牌列表"
            aria-label="刷新令牌列表"
            className="flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 text-slate-500 transition hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>

        <div className="overflow-hidden border border-slate-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse text-left">
              <thead className="bg-slate-50">
                <tr className="border-b border-slate-200 text-xs font-semibold text-slate-500">
                  <th className="w-[30%] px-5 py-3">名称</th>
                  <th className="w-[20%] px-5 py-3">令牌标识</th>
                  <th className="w-[22%] px-5 py-3">到期时间</th>
                  <th className="w-[16%] px-5 py-3">状态</th>
                  <th className="w-16 px-3 py-3"><span className="sr-only">操作</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {loading ? (
                  <tr><td colSpan={5} className="px-5 py-14 text-center text-sm text-slate-500">正在加载...</td></tr>
                ) : tokens.length === 0 ? (
                  <tr><td colSpan={5} className="px-5 py-14 text-center text-sm text-slate-500">暂无临时令牌</td></tr>
                ) : tokens.map((token) => (
                  <tr key={token.id} className="transition hover:bg-slate-50/70">
                    <td className="px-5 py-4 text-sm font-medium text-slate-900">{token.name}</td>
                    <td className="px-5 py-4"><code className="text-xs text-slate-500">{token.token_prefix}...</code></td>
                    <td className="px-5 py-4"><span className="flex items-center gap-1.5 text-sm text-slate-500"><Clock3 className="h-3.5 w-3.5" />{formatDate(token.expires_at)}</span></td>
                    <td className="px-5 py-4"><StatusBadge status={token.status} /></td>
                    <td className="px-3 py-4 text-right">
                      <button
                        type="button"
                        onClick={() => void (token.status === "revoked" ? handleDelete(token) : handleRevoke(token))}
                        disabled={processingTokenId === token.id}
                        title={token.status === "revoked" ? "永久删除令牌" : "撤销令牌"}
                        aria-label={`${token.status === "revoked" ? "永久删除" : "撤销"} ${token.name}`}
                        className={`inline-flex h-8 w-8 items-center justify-center rounded-md transition disabled:cursor-not-allowed disabled:opacity-30 ${token.status === "revoked" ? "text-slate-400 hover:bg-red-50 hover:text-red-600" : "text-slate-400 hover:bg-amber-50 hover:text-amber-600"}`}
                      >
                        {token.status === "revoked" ? <Trash2 className="h-4 w-4" /> : <Ban className="h-4 w-4" />}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            page={page}
            pageSize={pageSize}
            total={total}
            disabled={loading}
            onPageChange={setPage}
            onPageSizeChange={(size) => {
              setPage(1);
              setPageSize(size);
            }}
          />
        </div>
      </section>
    </section>
  );
}

function StatusBadge({ status }: { status: TemporaryAccessToken["status"] }) {
  const config = {
    active: ["有效", "bg-emerald-50 text-emerald-700 ring-emerald-200"],
    expired: ["已过期", "bg-amber-50 text-amber-700 ring-amber-200"],
    revoked: ["已撤销", "bg-slate-100 text-slate-600 ring-slate-200"],
  }[status];
  return <span className={`inline-flex rounded px-2 py-1 text-xs font-medium ring-1 ring-inset ${config[1]}`}>{config[0]}</span>;
}

function formatDate(value: string): string {
  return formatAppDateTime(value, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}

function readableError(error: unknown): string {
  if (!(error instanceof Error)) return "操作失败，请稍后重试";
  const marker = error.message.indexOf(": ");
  return marker >= 0 ? error.message.slice(marker + 2) : error.message;
}

async function copyToClipboard(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      // Fall through for pages without Clipboard API permission.
    }
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);

  let succeeded = false;
  try {
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    succeeded = document.execCommand("copy");
  } finally {
    textarea.remove();
  }

  if (!succeeded) throw new Error("Clipboard access is unavailable");
}
