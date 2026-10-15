"use client";
import { useState } from "react";
import { API, headers } from "../../lib/api";
import { Card, SectionTitle, Btn, Badge, ErrorNote, EmptyState } from "../../components/ui";

export default function Optimization() {
  const [goal, setGoal] = useState("Reduce delivery delays while keeping operating cost increase below 5%.");
  const [out, setOut] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function run() {
    setBusy(true); setErr("");
    try {
      const H = { ...headers(), "Content-Type": "application/json" };
      const r = await fetch(`${API}/ai/optimize`, { method: "POST", headers: H, body: JSON.stringify({ question: goal }) }).then(r => {
        if (!r.ok) throw new Error("Optimization failed"); return r.json();
      });
      setOut(r);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-20 pt-12">
      <div className="rise max-w-2xl">
        <h1 className="balance font-display text-[44px] font-semibold leading-[1.05] tracking-tight text-stone-900">Proposals, not autopilot.</h1>
        <p className="mt-4 max-w-[60ch] text-[15px] leading-relaxed text-stone-500">The engine scores candidate interventions by simulation. Nothing executes real-world actions — every recommendation needs your approval.</p>
      </div>
      <Card className="rise-1 mt-8 flex flex-wrap items-center gap-3 p-6">
        <input value={goal} onChange={e => setGoal(e.target.value)} aria-label="Optimization goal"
          className="min-w-[280px] flex-1 rounded-xl border border-stone-200 bg-paper-50 px-3 py-2 text-[13px]" />
        <Btn onClick={run} disabled={busy}>{busy ? "Scoring…" : "Suggest optimizations"}</Btn>
      </Card>
      {err && <div className="mt-4"><ErrorNote msg={err} /></div>}
      {!out && !busy && <div className="mt-4"><EmptyState title="No candidates yet" body="Describe the objective. The engine identifies controllable variables, simulates, scores and ranks." /></div>}
      {out && (
        <div className="mt-4 grid gap-3">
          {(out.options || []).map((o: any, i: number) => (
            <Card key={i} className="p-5">
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-display text-[15px] font-semibold text-stone-900">{i + 1}. {o.name}</p>
                {out.recommended?.name === o.name && <Badge tone="good">Recommended</Badge>}
                <span className="tnum ml-auto font-mono text-xs text-stone-400">score {o.score}</span>
              </div>
              <p className="mt-1.5 text-[13px] text-stone-600">{o.reasoning}</p>
              <div className="tnum mt-3 flex flex-wrap gap-4 font-mono text-xs">
                <span className="text-pine-700">{o.expected_benefit}</span>
                <span className="text-amber-700">{o.expected_cost}</span>
                <span className="text-stone-400">risk {o.risk} · confidence {Math.round((o.confidence || 0) * 100)}%</span>
              </div>
              <p className="tnum mt-2 font-mono text-[11px] text-stone-400">affected: {(o.affected_nodes || []).join(" → ")}</p>
            </Card>
          ))}
          <p className="text-xs text-stone-400">{out.note}</p>
        </div>
      )}
    </main>
  );
}
