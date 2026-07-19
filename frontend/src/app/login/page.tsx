"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { ArrowRight, KeyRound, ShieldCheck } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";

export default function LoginPage() {
  return <Suspense fallback={null}><LoginForm /></Suspense>;
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { session, login } = useAuth();
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestedPath = searchParams.get("next") || "/";
  const nextPath = requestedPath.startsWith("/") && !requestedPath.startsWith("//") ? requestedPath : "/";

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
    <main className="grid min-h-screen min-w-[1180px] grid-cols-[minmax(0,1fr)_460px] bg-slate-100">
      <section className="flex flex-col justify-between bg-slate-950 px-16 py-14 text-white">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-blue-600"><ShieldCheck className="h-5 w-5" /></div>
          <div><p className="text-base font-semibold">BizSage3</p><p className="mt-0.5 text-xs text-slate-400">智能运营诊断</p></div>
        </div>
        <div className="max-w-xl pb-16">
          <p className="text-xs font-semibold text-blue-300">BUSINESS INTELLIGENCE</p>
          <h1 className="mt-4 text-4xl font-semibold leading-tight">让经营判断回到清晰、可验证的数据上。</h1>
          <div className="mt-8 h-px w-16 bg-blue-500" />
        </div>
        <p className="text-xs text-slate-500">BizSage3 运营诊断工作台</p>
      </section>

      <section className="flex items-center bg-white px-14">
        <div className="w-full">
          <p className="text-xs font-semibold text-blue-700">SECURE ACCESS</p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-950">访问验证</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">输入管理员令牌或管理员签发的临时令牌。</p>

          <form className="mt-8 space-y-5" onSubmit={handleSubmit}>
            <div>
              <label htmlFor="access-token" className="mb-2 block text-sm font-medium text-slate-700">访问令牌</label>
              <div className="relative">
                <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  id="access-token"
                  type="password"
                  autoComplete="current-password"
                  autoFocus
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                  className="h-11 w-full rounded-md border border-slate-300 bg-white pl-10 pr-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                  placeholder="输入访问令牌"
                />
              </div>
            </div>

            {error && <div role="alert" className="border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700">{error}</div>}

            <button type="submit" disabled={!token.trim() || submitting} className="flex h-11 w-full items-center justify-center gap-2 rounded-md bg-blue-600 px-4 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50">
              <span>{submitting ? "正在验证..." : "进入工作台"}</span>
              {!submitting && <ArrowRight className="h-4 w-4" />}
            </button>
          </form>
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
