export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export function headers(): Record<string, string> {
  if (typeof window === "undefined") return {};
  return { Authorization: `Bearer ${localStorage.getItem("xray_token") || ""}` };
}
export async function api(path: string, opts: RequestInit = {}) {
  const r = await fetch(`${API}${path}`, { ...opts, headers: { ...((opts.headers as Record<string, string>) || {}), ...headers(), "Content-Type": "application/json" } });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
export type XNode = { id: string; type: string; name: string; properties: Record<string, any>; state?: string; confidence?: number; level?: string; last_observed?: string; source_docs?: string[] };
