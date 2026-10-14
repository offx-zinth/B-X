"use client";
import { useEffect, useState } from "react";
import { Play } from "@phosphor-icons/react";
import { API } from "../../lib/api";
import { Card, SectionTitle, Btn, Badge, ErrorNote, EmptyState, Skeleton } from "../../components/ui";

type Tpl = { name: string; changes: any[] };

export default function Sims() {
  const [name, setName] = useState("Supplier Failure");
  const [target, setTarget] = useState("Supplier.capacity");
  const [value, setValue] = useState("0");
  const [days, setDays] = useState("14");
  const [out, setOut] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [templates, setTemplates] = useState<Tpl[]>([]);

  useEffect(() => {
    fetch(`${API}/simulations/templates/full`).then(r => r.json()).then(setTemplates).catch(() => setTemplates([]));
  }, []);

  async function run(changes?: any[], label?: string) {
    setBusy(true); setErr("");
    try {
      const H = { Authorization: `Bearer ${localStorage.getItem("xray_token")}`, "Content-Type": "application/json" };
      const body = { name: label || name, changes: changes || [{ target, value: Number(value) }], duration_days: Number(days) };
      const r = await fetch(`${API}/simulations/run`, { method: "POST", headers: H, body: JSON.stringify(body) }).then(r => {
        if (!r.ok) throw new Error("Simulation failed");
        return r.json();
      });
      setOut(r);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  const deltas = out?.result?.deltas ? Object.entries(out.result.deltas) : [];
  const comp = out?.result?.comparison || {};
  const input = "w-full rounded-xl border border-stone-200 bg-white px-3 py-2 text-[13px] text-stone-900 placeholder:text-stone-400";

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-20 pt-12">
      <div className="rise max-w-2xl">
        <h1 className="balance font-display text-[44px] font-semibold leading-[1.05] tracking-tight text-stone-900">Clone reality. Break one thing. Watch it propagate.</h1>
        <p className="mt-4 max-w-[60ch] text-[15px] leading-relaxed text-stone-500">Simulations run on a copy of the graph — live data is never mutated. Results diff against the baseline over {days} days.</p>
      </div>

      <div className="mt-8 grid gap-4 lg:grid-cols-[380px_minmax(0,1fr)]">
        <Card className="rise-1 h-fit p-6">
          <SectionTitle title={name} />
          <label className="mt-4 block text-xs font-medium text-stone-500">Scenario name
            <input value={name} onChange={e => setName(e.target.value)} className={`${input} mt-1`} />
          </label>
          <div className="mt-3 grid grid-cols-[1fr_110px] gap-2">
            <label className="block text-xs font-medium text-stone-500">Change target
              <input value={target} onChange={e => setTarget(e.target.value)} className={`tnum mt-1 font-mono ${input}`} placeholder="Supplier.capacity" />
            </label>
            <label className="block text-xs font-medium text-stone-500">New value
              <input value={value} onChange={e => setValue(e.target.value)} className={`tnum mt-1 font-mono ${input}`} placeholder="0" />
            </label>
          </div>
          <label className="mt-3 block text-xs font-medium text-stone-500">Duration (days)
            <input value={days} onChange={e => setDays(e.target.value)} className={`tnum mt-1 font-mono ${input}`} />
          </label>
          <div className="mt-5"><Btn onClick={() => run()} disabled={busy}><span className="inline-flex items-center gap-1.5"><Play size={14} weight="fill" />{busy ? "Running…" : "Run simulation"}</span></Btn></div>
          <div className="mt-6 border-t border-stone-200 pt-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-stone-400">Templates</p>
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {templates.map(t => (
                <button key={t.name} onClick={() => run(t.changes, t.name)}
                  className="btn rounded-lg border border-stone-200 bg-white px-2.5 py-1.5 text-xs text-stone-600 hover:border-pine-600 hover:text-stone-900">{t.name}</button>
              ))}
            </div>
          </div>
        </Card>

        <section className="rise-2">
          {err && <ErrorNote msg={err} />}
          {busy && <div className="space-y-2"><Skeleton className="h-8 w-2/3" /><Skeleton className="h-48" /></div>}
          {!busy && deltas.length === 0 && !out && (
            <EmptyState title="No run yet" body="Pick a template or define a change. The delta table and propagation trace appear here." />
          )}
          {deltas.length > 0 && (
            <>
            <Card className="overflow-hidden">
              <div className="flex flex-wrap items-center gap-2 border-b border-stone-200 px-6 py-4">
                <p className="font-display text-[15px] font-semibold text-stone-900">{out.scenario?.name || "Result"}</p>
                <Badge tone="good">{out.run?.status || "done"}</Badge>
                <span className="tnum ml-auto font-mono text-xs text-stone-400">{deltas.length} fields · base v{out.scenario?.base_graph_version ?? "?"} · {comp.horizon_days ?? days}d</span>
              </div>
              <table className="w-full text-left text-[13px]">
                <thead><tr className="border-b border-stone-200 text-[11px] uppercase tracking-wider text-stone-400">
                  <th className="px-6 py-2.5 font-medium">Field</th><th className="px-3 py-2.5 font-medium">Baseline</th><th className="px-3 py-2.5 font-medium">Scenario</th><th className="px-3 py-2.5 font-medium">Δ abs</th><th className="px-6 py-2.5 font-medium">Δ %</th>
                </tr></thead>
                <tbody className="tnum">
                  {deltas.map(([k, v]: any) => (
                    <tr key={k} className="border-b border-stone-100 font-mono text-xs last:border-0">
                      <td className="px-6 py-2.5 text-pine-700">{k}</td>
                      <td className="px-3 py-2.5 text-stone-400">{String(v.before)}</td>
                      <td className="px-3 py-2.5 text-stone-900">{String(v.after)}</td>
                      <td className={`px-3 py-2.5 ${(v.absolute_change ?? 0) < 0 ? "text-red-600" : "text-stone-600"}`}>{v.absolute_change ?? "—"}</td>
                      <td className="px-6 py-2.5 text-stone-500">{v.percentage_change != null ? `${v.percentage_change}%` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            {comp.time_to_impact_days && (
              <Card className="mt-3 p-5">
                <SectionTitle title="When did it hit?" hint="First day each metric diverged from baseline, with maximum impact." />
                <ul className="tnum mt-3 space-y-1.5 font-mono text-xs text-stone-600">
                  {Object.entries(comp.time_to_impact_days).slice(0, 8).map(([k, day]: any) => (
                    <li key={k} className="flex gap-2"><span className="text-pine-700">{k}</span><span className="ml-auto text-stone-400">day {day} · max Δ {(comp.maximum_impact || {})[k]}</span></li>
                  ))}
                </ul>
              </Card>
            )}
            </>
          )}
        </section>
      </div>
    </main>
  );
}
