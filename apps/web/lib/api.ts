export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function storedToken(): string {
  if (typeof window === "undefined") return "";
  const raw = localStorage.getItem("xray_session") || localStorage.getItem("xray_token") || "";
  const token = raw.startsWith("{") ? (() => { try { return JSON.parse(raw).token || ""; } catch { return ""; } })() : raw;
  return token || "";
}

export function headers(): Record<string, string> {
  const token = storedToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// Cookie-first auth: HttpOnly cookies (browser) carry sessions; Bearer stays
// for API clients. credentials:"include" makes the browser attach cookies.
export async function api(path: string, opts: RequestInit = {}) {
  const r = await fetch(`${API}${path}`, {
    ...opts, credentials: "include",
    headers: { ...((opts.headers as Record<string, string>) || {}), ...headers(), "Content-Type": "application/json" },
  });
  if (r.status === 401 && typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    window.location.href = "/login";
  }
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiForm(path: string, file: File) {
  const fd = new FormData(); fd.append("f", file);
  const r = await fetch(`${API}${path}`, { method: "POST", credentials: "include",
    headers: storedToken() ? { Authorization: `Bearer ${storedToken()}` } : {}, body: fd });
  if (r.status === 401 && typeof window !== "undefined") window.location.href = "/login";
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export type XNode = { id: string; type: string; name: string; properties: Record<string, any>; state?: string; confidence?: number; level?: string; last_observed?: string; source_docs?: string[] };
