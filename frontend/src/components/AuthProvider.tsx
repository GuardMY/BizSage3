"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import * as api from "@/lib/api";
import type { AuthSession } from "@/types";


interface AuthContextValue {
  session: AuthSession | null;
  loading: boolean;
  login: (token: string) => Promise<AuthSession>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [session, setSession] = useState<AuthSession | null>(null);
  const [loading, setLoading] = useState(true);
  const isPublicRoute = pathname === "/login";

  useEffect(() => {
    let cancelled = false;

    api.getCurrentSession()
      .then((current) => {
        if (!cancelled) setSession(current);
      })
      .catch(() => {
        if (!cancelled) setSession(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!loading && !session && !isPublicRoute) {
      const next = pathname && pathname !== "/"
        ? `?next=${encodeURIComponent(pathname)}`
        : "";
      router.replace(`/login${next}`);
    }
  }, [isPublicRoute, loading, pathname, router, session]);

  useEffect(() => {
    function handleUnauthorized() {
      setSession(null);
      setLoading(false);
    }
    window.addEventListener("bizsage:unauthorized", handleUnauthorized);
    return () => window.removeEventListener("bizsage:unauthorized", handleUnauthorized);
  }, []);

  const login = useCallback(async (token: string) => {
    const current = await api.login(token);
    setSession(current);
    return current;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setSession(null);
      router.replace("/login");
    }
  }, [router]);

  const value = useMemo(
    () => ({ session, loading, login, logout }),
    [session, loading, login, logout],
  );

  if (loading || (!session && !isPublicRoute)) {
    return <AuthLoading />;
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

function AuthLoading() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 text-gray-500">
      <div className="flex items-center gap-3 text-sm">
        <ShieldCheck className="h-5 w-5 animate-pulse text-indigo-600" />
        <span>正在验证访问权限...</span>
      </div>
    </div>
  );
}
