"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, KeyRound, LogOut, ShieldAlert } from "lucide-react";
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
      <main className="flex min-h-screen items-center justify-center bg-gray-50 px-5">
        <div className="w-full max-w-md border-t border-gray-300 pt-8 text-center">
          <ShieldAlert className="mx-auto h-9 w-9 text-amber-500" />
          <h1 className="mt-4 text-lg font-semibold text-gray-900">无管理员权限</h1>
          <Link
            href="/"
            className="mt-6 inline-flex items-center text-sm font-medium text-indigo-600 hover:text-indigo-700"
          >
            返回工作台
          </Link>
        </div>
      </main>
    );
  }

  return (
    <div className="flex min-h-screen bg-gray-50 text-gray-900">
      <aside className="flex w-56 shrink-0 flex-col border-r border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-5 py-5">
          <Link href="/" className="text-xs font-medium text-gray-500 hover:text-gray-900">BizSage3</Link>
          <h1 className="mt-1 text-base font-semibold">管理后台</h1>
        </div>

        <nav aria-label="管理后台功能" className="flex-1 space-y-1 p-3">
          {tabs.map(({ href, label, icon: Icon }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors ${
                  active
                    ? "bg-indigo-50 text-indigo-700"
                    : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                }`}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-gray-200 p-3">
          <button
            type="button"
            onClick={() => void logout()}
            className="flex h-10 w-full items-center gap-3 rounded-md px-3 text-sm text-gray-600 hover:bg-gray-100 hover:text-gray-900"
          >
            <LogOut className="h-4 w-4" />
            退出登录
          </button>
        </div>
      </aside>

      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
