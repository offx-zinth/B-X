"use client";
import { useState } from "react";
import { API } from "../../lib/api";
import { Card, SectionTitle, Btn, Badge, MetricStrip, ErrorNote, Skeleton } from "../../components/ui";

export default function Reports() {
  const [r, setR] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function load() {
    setBusy(true); setErr("");
    try {
      const H = { Authorization: `Bearer ${localStorage.getItem("xray_token")}` };
      setR(await fetch(`${API}/reports/`, { headers: H }).then(r => { if (!r.ok) throw new Error("Report failed"); return r.json(); }));
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  function exportCSV() {
    const t = localStorage.getItem("xray_token");
    window.open(`${API}/reports/export.csv`, "_blank");
    void t;
  }

  const tone = (v: string) => v === "HIGH" ? "bad" : v === "MEDIUM" ? "warn" : "good";

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-20 pt-12">
      <div className="rise flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="balance font-display text-[44px] font-semibold leading-[1.05] tracking-tight text-stone-900">Business health, with receipts.</h1>
          <p className="mt-4 max-w-[60ch] text-[15px] leading-relaxed text-stone-500">Every claim traces back to graph nodes and simulation runs — no black-box scores.</p>
        </div>
        <div className="flex gap-2">
        <Btn onClick={load} disabled={busy}>{busy ? "Analyzing…" : r ? "Regenerate" : "Generate report"}</Btn>
        {r && <Btn variant="ghost" onClick={exportCSV}>Export CSV</Btn>}
        </div>
      </div>

      {err && <div className="mt-4"><ErrorNote msg={err} /></div>}
      {busy && <div className="mt-6 grid gap-4 sm:grid-cols-3"><Skeleton className="h-24" /><Skeleton className="h-24" /><Skeleton className="h-24" /></div>}

      {!r && !busy && (
        <Card className="rise-1 mt-8 grid place-items-center px-6 py-14 text-center">
          <div className="max-w-sm">
            <p className="font-display text-[15px] font-semibold text-stone-900">No report yet</p>
            <p className="mt-1.5 text-[13px] text-stone-500">Generate to score operational, bottleneck and supplier risk from the live graph.</p>
          </div>
        </Card>
      )}

      {r && (
        <>
          <div className="rise-1 mt-8">
            <MetricStrip items={[
              { label: "Operational risk", value: r.operational_risk },
              { label: "Bottleneck risk", value: r.bottleneck_risk },
              { label: "Top bottlenecks", value: String(r.top_bottlenecks?.length ?? 0), sub: "by dependency fan-out" },
            ]} />
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Card className="rise-2 p-6">
              <SectionTitle title="Top bottlenecks" />
              <ul className="mt-4 space-y-2">
                {(r.top_bottlenecks || []).map((b: any, i: number) => (
                  <li key={i} className="flex items-center gap-3 rounded-xl bg-paper-100 px-4 py-3">
                    <span className="tnum font-mono text-xs text-stone-400">{i + 1}</span>
                    <div className="min-w-0">
                      <p className="truncate text-[13.5px] font-medium text-stone-900">{b.node?.name} <span className="text-stone-400">· {b.node?.type}</span></p>
                    </div>
                    <span className="tnum ml-auto font-mono text-xs text-stone-400">fan-out {b.fanout}</span>
                    <Badge tone={tone(r.bottleneck_risk)}>{r.bottleneck_risk}</Badge>
                  </li>
                ))}
              </ul>
            </Card>
            <Card className="rise-3 p-6">
              <SectionTitle title="Recommendations" hint="Each maps to a scenario you can run to verify before acting." />
              <ul className="mt-4 space-y-2">
                {(r.recommendations || []).map((rec: string, i: number) => (
                  <li key={i} className="flex gap-3 rounded-xl bg-paper-100 px-4 py-3 text-[13.5px] text-stone-800">
                    <span className="text-pine-700">→</span>{rec}
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </>
      )}
    </main>
  );
}
