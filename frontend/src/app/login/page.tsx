"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, KeyRound, ShieldCheck } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";


export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { session, login } = useAuth();
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestedPath = searchParams.get("next") || "/";
  const nextPath = requestedPath.startsWith("/") && !requestedPath.startsWith("//")
    ? requestedPath
    : "/";

  useEffect(() => {
    if (session) router.replace(nextPath);
  }, [nextPath, router, session]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!token.trim() || submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      await login(token.trim());
      router.replace(nextPath);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen bg-gray-50">
      <section className="flex w-full items-center justify-center px-5 py-10">
        <div className="w-full max-w-sm">
          <div className="mb-10 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-gray-900 text-white">
              <ShieldCheck className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-gray-950">BizSage3</h1>
              <p className="mt-0.5 text-sm text-gray-500">智能运营诊断</p>
            </div>
          </div>

          <div className="border-t border-gray-200 pt-8">
            <h2 className="text-lg font-semibold text-gray-900">访问验证</h2>
            <p className="mt-2 text-sm leading-6 text-gray-500">
              输入管理员令牌或管理员签发的临时令牌。
            </p>

            <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
              <div>
                <label htmlFor="access-token" className="mb-2 block text-sm font-medium text-gray-700">
                  访问令牌
                </label>
                <div className="relative">
                  <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                  <input
                    id="access-token"
                    type="password"
                    autoComplete="current-password"
                    autoFocus
                    value={token}
                    onChange={(event) => setToken(event.target.value)}
                    className="h-11 w-full rounded-md border border-gray-300 bg-white pl-10 pr-3 text-sm text-gray-900 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                    placeholder="输入访问令牌"
                  />
                </div>
              </div>

              {error && (
                <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={!token.trim() || submitting}
                className="flex h-11 w-full items-center justify-center gap-2 rounded-md bg-gray-900 px-4 text-sm font-medium text-white transition hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span>{submitting ? "正在验证..." : "进入工作台"}</span>
                {!submitting && <ArrowRight className="h-4 w-4" />}
              </button>
            </form>
          </div>
        </div>
      </section>
    </main>
  );
}

function readableError(error: unknown): string {
  if (!(error instanceof Error)) return "验证失败，请稍后重试";
  const marker = error.message.indexOf(": ");
  return marker >= 0 ? error.message.slice(marker + 2) : error.message;
}
