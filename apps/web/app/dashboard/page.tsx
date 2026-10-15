"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { API, headers } from "../../lib/api";
import { Card, SectionTitle, Badge, MetricStrip, ErrorNote, Skeleton } from "../../components/ui";

export default function Dashboard() {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = headers()["Authorization"];
    if (!t) { setLoading(false); setErr("Log in to view your workspace."); return; }
    fetch(`${API}/dashboard/`, { headers: headers() })
      .then(r => { if (r.status === 401 && typeof window !== "undefined") window.location.href = "/login"; if (!r.ok) throw new Error("Dashboard load failed"); return r.json(); })
      .then(setD).catch((e: any) => setErr(e.message)).finally(() => setLoading(false));
  }, []);

  if (loading) return <main className="mx-auto max-w-[1400px] px-6 pb-20 pt-12"><Skeleton className="h-24" /><div className="mt-4 grid gap-4 sm:grid-cols-3"><Skeleton className="h-24" /><Skeleton className="h-24" /><Skeleton className="h-24" /></div></main>;
  if (err) return <main className="mx-auto max-w-[1400px] px-6 pb-20 pt-12"><ErrorNote msg={err} /><p className="mt-3 text-sm text-stone-500"><Link href="/login" className="font-semibold text-pine-700">Go to login →</Link></p></main>;

  const bs = d.business_state || {};
  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-20 pt-12">
      <div className="rise flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="balance font-display text-[44px] font-semibold leading-[1.05] tracking-tight text-stone-900">How the business actually operates.</h1>
          <p className="mt-4 max-w-[60ch] text-[15px] leading-relaxed text-stone-500">Live operational state compiled from your data — graph version {d.data_freshness?.graph_version ?? 0}, model confidence {Math.round((d.model_confidence || 0) * 100)}%.</p>
        </div>
        <Link href="/workspace" className="btn rounded-xl bg-pine-700 px-4 py-2 text-[13.5px] font-semibold text-white hover:bg-pine-800">Open Business Graph</Link>
      </div>

      <div className="rise-1 mt-8">
        <MetricStrip items={[
          { label: "Nodes", value: String(bs.nodes ?? 0), sub: `${bs.edges ?? 0} edges` },
          { label: "Active formulas", value: String(bs.active_formulas ?? 0), sub: `${bs.pending_formulas ?? 0} pending approval` },
          { label: "Model confidence", value: `${Math.round((d.model_confidence || 0) * 100)}%`, sub: d.data_freshness?.last_observed ? `fresh ${String(d.data_freshness.last_observed).slice(0, 10)}` : "no observations" },
        ]} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card className="rise-2 p-6">
          <SectionTitle title="Bottlenecks & critical dependencies" hint="Highest fan-out nodes — failure here cascades furthest." />
          <ul className="mt-4 space-y-2">
            {(d.current_bottlenecks || []).map((b: any, i: number) => (
              <li key={i} className="flex items-center gap-3 rounded-xl bg-paper-100 px-4 py-3">
                <span className="tnum font-mono text-xs text-stone-400">{i + 1}</span>
                <p className="truncate text-[13.5px] font-medium text-stone-900">{b.node?.name} <span className="text-stone-400">· {b.node?.type}</span></p>
                <span className="tnum ml-auto font-mono text-xs text-stone-400">fan-out {b.fanout}</span>
              </li>
            ))}
            {!(d.current_bottlenecks || []).length && <p className="text-[13px] text-stone-400">No bottlenecks detected.</p>}
          </ul>
        </Card>
        <Card className="rise-3 p-6">
          <SectionTitle title="Risk hotspots" hint="Deterministic scan — single-supplier, inventory cover, backlog." />
          <ul className="mt-4 space-y-2">
            {(d.risk_hotspots || []).map((r: any, i: number) => (
              <li key={i} className="flex items-center gap-3 rounded-xl bg-paper-100 px-4 py-3 text-[13.5px]">
                <Badge tone={r.severity === "HIGH" ? "bad" : r.severity === "MEDIUM" ? "warn" : "good"}>{r.severity}</Badge>
                <span className="text-stone-800">{r.detail}</span>
              </li>
            ))}
          </ul>
          <div className="mt-5 border-t border-stone-200 pt-4">
            <SectionTitle title="Recommended actions" />
            <ul className="mt-3 space-y-1.5">
              {(d.recommended_actions || []).map((a: string, i: number) => (
                <li key={i} className="flex gap-2 text-[13.5px] text-stone-700"><span className="text-pine-700">→</span>{a}</li>
              ))}
            </ul>
          </div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card className="p-6">
          <SectionTitle title="Recent changes" hint="Audit trail — who changed what, with before/after." />
          <ul className="tnum mt-3 space-y-1.5 font-mono text-xs text-stone-500">
            {(d.recent_changes || []).slice(0, 6).map((a: any) => (
              <li key={a.id} className="flex gap-2"><span className="text-stone-300">{String(a.timestamp).slice(0, 16).replace("T", " ")}</span><span className="text-pine-700">{a.action}</span><span className="truncate text-stone-400">{a.resource}</span></li>
            ))}
            {!(d.recent_changes || []).length && <li>No changes recorded yet.</li>}
          </ul>
        </Card>
        <Card className="p-6">
          <SectionTitle title="Active simulations" hint="Runs reference immutable graph versions — reproducible." />
          <ul className="mt-3 space-y-1.5 text-[13px]">
            {(d.active_simulations || []).slice(0, 5).map((s: any) => (
              <li key={s.id} className="flex items-center gap-2"><Badge tone={s.status === "done" ? "good" : "bad"}>{s.status}</Badge><span className="tnum font-mono text-xs text-stone-500">{s.id.slice(0, 8)}</span></li>
            ))}
            {!(d.active_simulations || []).length && <li className="text-stone-400">No simulations yet. <Link href="/simulations" className="font-semibold text-pine-700">Run one →</Link></li>}
          </ul>
        </Card>
      </div>
    </main>
  );
}
