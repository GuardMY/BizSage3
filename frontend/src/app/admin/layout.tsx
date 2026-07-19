"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowLeft, BookOpen, KeyRound, LogOut, ShieldAlert } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";

const tabs = [
  { href: "/admin/tokens", label: "临时令牌", icon: KeyRound },
  { href: "/admin/knowledge", label: "知识库", icon: BookOpen },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { session, logout } = useAuth();

  if (session?.role !== "admin") {
    return (
      <main className="flex min-h-screen min-w-[1180px] items-center justify-center bg-slate-100 px-8">
        <div className="border-t border-slate-300 pt-8 text-center">
          <ShieldAlert className="mx-auto h-9 w-9 text-amber-500" />
          <h1 className="mt-4 text-lg font-semibold text-slate-900">无管理员权限</h1>
          <Link href="/" className="mt-6 inline-flex items-center text-sm font-medium text-blue-700 hover:text-blue-800">返回工作台</Link>
        </div>
      </main>
    );
  }

  return (
    <div className="grid min-h-screen min-w-[1180px] grid-cols-[264px_minmax(0,1fr)] bg-slate-100 text-slate-900">
      <aside className="flex min-h-screen flex-col bg-slate-950 text-slate-100">
        <div className="flex h-16 items-center gap-3 border-b border-slate-800 px-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-blue-600 text-sm font-semibold text-white">B</div>
          <div>
            <p className="text-sm font-semibold text-white">BizSage3</p>
            <p className="mt-0.5 text-xs text-slate-400">管理后台</p>
          </div>
        </div>

        <div className="px-4 pt-5">
          <p className="px-2 text-xs font-medium text-slate-500">管理中心</p>
        </div>
        <nav aria-label="管理后台功能" className="space-y-1 px-4 pt-3">
          {tabs.map(({ href, label, icon: Icon }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors ${active ? "bg-blue-500/15 text-blue-200 ring-1 ring-inset ring-blue-400/25" : "text-slate-400 hover:bg-slate-900 hover:text-white"}`}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto border-t border-slate-800 p-3">
          <Link href="/" className="flex h-10 items-center gap-3 rounded-md px-3 text-sm text-slate-400 transition hover:bg-slate-900 hover:text-white">
            <ArrowLeft className="h-4 w-4" />
            返回工作台
          </Link>
          <button type="button" onClick={() => void logout()} className="flex h-10 w-full items-center gap-3 rounded-md px-3 text-sm text-slate-400 transition hover:bg-slate-900 hover:text-white">
            <LogOut className="h-4 w-4" />
            退出登录
          </button>
        </div>
      </aside>

      <div className="min-w-0">{children}</div>
    </div>
  );
}
