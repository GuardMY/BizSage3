"use client";

import { ArrowLeft, LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import KnowledgeManagement from "@/components/KnowledgeManagement";

export default function KnowledgePage() {
  const router = useRouter();
  const { logout } = useAuth();

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={() => router.push("/")}
              title="返回工作台"
              aria-label="返回工作台"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-800"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <div className="min-w-0">
              <h2 className="truncate text-base font-semibold">管理后台</h2>
              <p className="text-xs text-gray-500">BizSage3 管理员</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => void logout()}
            className="flex h-9 items-center gap-2 rounded-md px-3 text-sm text-gray-600 hover:bg-gray-100 hover:text-gray-900"
          >
            <LogOut className="h-4 w-4" />
            <span>退出</span>
          </button>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-5 py-8 lg:px-8">
        <KnowledgeManagement />
      </div>
    </main>
  );
}
