"use client";

import { useEffect } from "react";
import { LoaderCircle, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import * as api from "@/lib/api";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      try {
        const sessions = await api.listSessions();
        if (cancelled) return;
        if (sessions.length > 0) {
          const latest = sessions.reduce((a, b) => new Date(a.updated_at) > new Date(b.updated_at) ? a : b);
          router.replace(`/sessions/${latest.id}`);
        } else {
          const detail = await api.createSession();
          if (!cancelled) router.replace(`/sessions/${detail.id}`);
        }
      } catch {
        if (!cancelled) router.replace("/sessions/new");
      }
    }

    void boot();
    return () => { cancelled = true; };
  }, [router]);

  return (
    <main className="flex min-h-screen min-w-[1180px] items-center justify-center bg-slate-100 text-slate-900">
      <div className="flex items-center gap-4">
        <div className="flex h-11 w-11 items-center justify-center rounded-md bg-blue-600 text-white"><ShieldCheck className="h-5 w-5" /></div>
        <div>
          <p className="text-base font-semibold">BizSage3</p>
          <p className="mt-1 flex items-center gap-2 text-sm text-slate-500"><LoaderCircle className="h-3.5 w-3.5 animate-spin text-blue-600" />正在初始化工作台</p>
        </div>
      </div>
    </main>
  );
}
