"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { API } from "./api";

export type Session = {
  token: string;
  tenant_id: string;
  email: string;
  role: string;
  org?: string;
};

type AuthCtx = {
  session: Session | null;
  loading: boolean;
  error: string;
  login: (email: string, password: string) => Promise<void>;
  signup: (org: string, email: string, password: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
};

const Ctx = createContext<AuthCtx | null>(null);
const KEY = "xray_session";

function readStored(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(KEY) || localStorage.getItem("xray_token");
    if (!raw) return null;
    if (raw.startsWith("eyJ")) return { token: raw, tenant_id: "", email: "", role: "Viewer" };
    return JSON.parse(raw);
  } catch { return null; }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const router = useRouter();

  const persist = (s: Session | null) => {
    setSession(s);
    if (typeof window !== "undefined") {
      if (s) {
        localStorage.setItem(KEY, JSON.stringify(s));
        localStorage.setItem("xray_token", s.token);
      } else {
        localStorage.removeItem(KEY);
        localStorage.removeItem("xray_token");
      }
    }
  };

  const refresh = useCallback(async () => {
    const s = readStored();
    if (!s?.token) { setLoading(false); return; }
    try {
      const me = await fetch(`${API}/auth/me`, {
        headers: { Authorization: `Bearer ${s.token}` },
      }).then(async r => {
        if (r.status === 401) throw new Error("session expired");
        if (!r.ok) throw new Error("session check failed");
        return r.json();
      });
      const tenant = await fetch(`${API}/auth/tenant`, {
        headers: { Authorization: `Bearer ${s.token}` },
      }).then(r => (r.ok ? r.json() : null)).catch(() => null);
      persist({ token: s.token, tenant_id: me.tenant_id, email: me.email, role: me.role, org: tenant?.name });
    } catch {
      persist(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    setError("");
    const r = await fetch(`${API}/auth/login`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!r.ok) throw new Error(r.status === 401 ? "Invalid email or password." : await r.text());
    const j = await r.json();
    const tenant = await fetch(`${API}/auth/tenant`, {
      headers: { Authorization: `Bearer ${j.token}` },
    }).then(x => (x.ok ? x.json() : null)).catch(() => null);
    persist({ token: j.token, tenant_id: j.tenant_id, email, role: j.role || "Viewer", org: tenant?.name });
    router.push("/");
  }, [router]);

  const signup = useCallback(async (org: string, email: string, password: string) => {
    setError("");
    const r = await fetch(`${API}/auth/signup`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ org, email, password }),
    });
    if (!r.ok) throw new Error(r.status === 409 ? "Email already registered. Try logging in." : await r.text());
    const j = await r.json();
    persist({ token: j.token, tenant_id: j.tenant_id, email, role: "Owner", org });
    router.push("/");
  }, [router]);

  const logout = useCallback(() => {
    persist(null);
    router.push("/login");
  }, [router]);

  const v = useMemo(() => ({ session, loading, error, login, signup, logout, refresh }), [session, loading, error, login, signup, logout, refresh]);
  return <Ctx.Provider value={v}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export function authHeaders(session: Session | null): Record<string, string> {
  return session?.token ? { Authorization: `Bearer ${session.token}` } : {};
}
