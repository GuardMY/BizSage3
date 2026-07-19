"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  Ban,
  Check,
  Clock3,
  Copy,
  KeyRound,
  Plus,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import * as api from "@/lib/api";
import { formatAppDateTime } from "@/lib/time";
import type {
  CreatedTemporaryAccessToken,
  TemporaryAccessToken,
} from "@/types";


const EXPIRY_OPTIONS = [
  { hours: 1, label: "1 小时" },
  { hours: 24, label: "24 小时" },
  { hours: 24 * 7, label: "7 天" },
  { hours: 24 * 30, label: "30 天" },
];

export default function TemporaryTokenManagement() {
  const [tokens, setTokens] = useState<TemporaryAccessToken[]>([]);
  const [name, setName] = useState("");
  const [expiresInHours, setExpiresInHours] = useState(24);
  const [createdToken, setCreatedToken] = useState<CreatedTemporaryAccessToken | null>(null);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [processingTokenId, setProcessingTokenId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadTokens = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setTokens(await api.listTemporaryTokens());
    } catch (err) {
      setError(readableError(err));
    } finally {
      setLoading(false);
    }
  }, []);

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
      setTokens((current) => [created, ...current]);
      setName("");
      setCopied(false);
      setCopyError(null);
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

  async function handleRevoke(token: TemporaryAccessToken) {
    const warning = token.status === "active"
      ? "现有登录会立即失效，撤销后可永久删除。"
      : "撤销后可永久删除。";
    if (!window.confirm(`确认撤销“${token.name}”吗？${warning}`)) return;
    setProcessingTokenId(token.id);
    setError(null);
    try {
      await api.revokeTemporaryToken(token.id);
      await loadTokens();
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
      await loadTokens();
    } catch (err) {
      setError(readableError(err));
    } finally {
      setProcessingTokenId(null);
    }
  }

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      <div className="mx-auto max-w-6xl px-5 py-8 lg:px-8">
        <section className="grid gap-8 border-b border-gray-200 pb-8 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-emerald-600" />
              <h2 className="text-sm font-semibold">签发临时令牌</h2>
            </div>
            <p className="mt-2 max-w-xl text-sm leading-6 text-gray-500">
              为临时访问人员设置用途和有效期。令牌到期或被撤销后，相关会话会立即失效。
            </p>
          </div>

          <form
            onSubmit={handleCreate}
            className="space-y-4 rounded-md border border-gray-200 bg-white p-5 shadow-sm"
          >
            <div>
              <label htmlFor="token-name" className="mb-1.5 block text-sm font-medium text-gray-700">名称</label>
              <input
                id="token-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={80}
                placeholder="例如：客户演示"
                className="h-10 w-full rounded-md border border-gray-300 px-3 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
              />
            </div>
            <div>
              <label htmlFor="token-expiry" className="mb-1.5 block text-sm font-medium text-gray-700">有效期</label>
              <select
                id="token-expiry"
                value={expiresInHours}
                onChange={(event) => setExpiresInHours(Number(event.target.value))}
                className="h-10 w-full rounded-md border border-gray-300 bg-white px-3 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
              >
                {EXPIRY_OPTIONS.map((option) => (
                  <option key={option.hours} value={option.hours}>{option.label}</option>
                ))}
              </select>
            </div>
            <button
              type="submit"
              disabled={!name.trim() || submitting}
              className="flex h-10 w-full items-center justify-center gap-2 rounded-md bg-gray-900 px-4 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Plus className="h-4 w-4" />
              <span>{submitting ? "正在生成..." : "生成令牌"}</span>
            </button>
          </form>
        </section>

        {createdToken && (
          <section className="my-8 rounded-md border border-emerald-200 bg-emerald-50 p-5">
            <div className="flex items-start gap-3">
              <KeyRound className="mt-0.5 h-5 w-5 shrink-0 text-emerald-700" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-4">
                  <h2 className="text-sm font-semibold text-emerald-950">令牌已生成，仅显示一次</h2>
                  <button onClick={() => setCreatedToken(null)} className="text-xs text-emerald-800 hover:text-emerald-950">关闭</button>
                </div>
                <div className="mt-3 flex min-w-0 items-center gap-2">
                  <code className="min-w-0 flex-1 overflow-x-auto rounded bg-white px-3 py-2.5 text-sm text-gray-900 ring-1 ring-emerald-200">
                    {createdToken.token}
                  </code>
                  <button
                    type="button"
                    onClick={() => void handleCopy()}
                    title={copied ? "已复制" : "复制令牌"}
                    aria-label={copied ? "令牌已复制" : "复制令牌"}
                    className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-emerald-700 text-white hover:bg-emerald-800"
                  >
                    {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                  </button>
                </div>
                {(copyError || copied) && (
                  <p
                    role="status"
                    className={`mt-2 text-xs ${copyError ? "text-red-700" : "text-emerald-800"}`}
                  >
                    {copyError ?? "已复制到剪贴板"}
                  </p>
                )}
              </div>
            </div>
          </section>
        )}

        {error && (
          <div role="alert" className="my-6 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <section className="pt-8">
          <div className="mb-4 flex items-center justify-between gap-4">
            <div>
              <h2 className="text-sm font-semibold">已签发令牌</h2>
              <p className="mt-1 text-xs text-gray-500">共 {tokens.length} 个</p>
            </div>
            <button
              onClick={() => void loadTokens()}
              disabled={loading}
              className="text-sm font-medium text-indigo-600 hover:text-indigo-700 disabled:opacity-50"
            >
              刷新
            </button>
          </div>

          <div className="overflow-hidden rounded-md border border-gray-200 bg-white">
            <div className="hidden grid-cols-[minmax(180px,1.3fr)_minmax(140px,1fr)_minmax(150px,1fr)_110px_52px] gap-4 border-b border-gray-200 bg-gray-50 px-4 py-2.5 text-xs font-medium text-gray-500 md:grid">
              <span>名称</span><span>标识</span><span>到期时间</span><span>状态</span><span />
            </div>
            {loading ? (
              <div className="px-4 py-12 text-center text-sm text-gray-500">正在加载...</div>
            ) : tokens.length === 0 ? (
              <div className="px-4 py-12 text-center text-sm text-gray-500">暂无临时令牌</div>
            ) : (
              <ul className="divide-y divide-gray-100">
                {tokens.map((token) => (
                  <li
                    key={token.id}
                    className="grid gap-3 px-4 py-4 md:grid-cols-[minmax(180px,1.3fr)_minmax(140px,1fr)_minmax(150px,1fr)_110px_52px] md:items-center md:gap-4"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-gray-900">{token.name}</p>
                      <p className="mt-1 text-xs text-gray-400 md:hidden">{token.token_prefix}...</p>
                    </div>
                    <code className="hidden truncate text-xs text-gray-500 md:block">{token.token_prefix}...</code>
                    <div className="flex items-center gap-1.5 text-xs text-gray-500">
                      <Clock3 className="h-3.5 w-3.5" />{formatDate(token.expires_at)}
                    </div>
                    <StatusBadge status={token.status} />
                    <button
                      onClick={() => void (
                        token.status === "revoked"
                          ? handleDelete(token)
                          : handleRevoke(token)
                      )}
                      disabled={processingTokenId === token.id}
                      title={token.status === "revoked" ? "永久删除令牌" : "撤销令牌"}
                      aria-label={`${token.status === "revoked" ? "永久删除" : "撤销"} ${token.name}`}
                      className={`flex h-9 w-9 items-center justify-center rounded-md text-gray-400 disabled:cursor-not-allowed disabled:opacity-30 ${
                        token.status === "revoked"
                          ? "hover:bg-red-50 hover:text-red-600"
                          : "hover:bg-amber-50 hover:text-amber-600"
                      }`}
                    >
                      {token.status === "revoked"
                        ? <Trash2 className="h-4 w-4" />
                        : <Ban className="h-4 w-4" />}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}

function StatusBadge({ status }: { status: TemporaryAccessToken["status"] }) {
  const styles = {
    active: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    expired: "bg-amber-50 text-amber-700 ring-amber-200",
    revoked: "bg-gray-100 text-gray-500 ring-gray-200",
  }[status];
  const label = { active: "有效", expired: "已过期", revoked: "已撤销" }[status];
  return (
    <span className={`w-fit rounded px-2 py-1 text-xs font-medium ring-1 ring-inset ${styles}`}>
      {label}
    </span>
  );
}

function formatDate(value: string): string {
  return formatAppDateTime(value, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
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
      // Clipboard API can be denied outside a secure context; fall back below.
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
