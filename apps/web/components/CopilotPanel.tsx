"use client";
import { useEffect, useState } from "react";
import { PaperPlaneRight } from "@phosphor-icons/react";
import { API, headers } from "../lib/api";
import { Btn, ErrorNote, Badge } from "./ui";

type Msg = { role: "user" | "ai"; text: string; detail?: any };

function ExplanationBlock({ e }: { e: any }) {
  return (
    <div className="mt-2.5 space-y-2.5 border-t border-stone-200 pt-2.5">
      {e.bottleneck?.reason && (
        <div className="rounded-lg bg-white px-2.5 py-2 ring-1 ring-stone-200">
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-amber-700">Bottleneck</p>
          <p className="mt-0.5 text-xs text-stone-700">{e.bottleneck.reason}</p>
        </div>
      )}
      {e.metrics_changed?.length > 0 && (
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-stone-400">Metrics</p>
          <ul className="tnum mt-1 space-y-0.5 font-mono text-[11px]">
            {e.metrics_changed.slice(0, 5).map((m: any) => (
              <li key={m.ref} className="flex gap-1.5">
                <span className="text-pine-700">{m.ref}</span>
                <span className="text-stone-400">{m.before}→{m.after}</span>
                <span className={Number(m.change_pct) < 0 ? "ml-auto text-red-600" : "ml-auto text-stone-500"}>{m.change_pct}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {e.why?.length > 0 && (
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-stone-400">Why</p>
          <ul className="mt-1 space-y-1">
            {e.why.slice(0, 4).map((w: any) => (
              <li key={w.ref} className="text-[11px] leading-snug text-stone-600">
                <span className="font-mono text-pine-700">{w.ref}</span>
                {w.day != null && <span className="text-stone-400"> (day {w.day})</span>} — {w.explanation}
              </li>
            ))}
          </ul>
        </div>
      )}
      {e.interventions?.length > 0 && (
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-stone-400">Interventions</p>
          <ul className="mt-1 space-y-0.5 text-[11px] text-stone-600">
            {e.interventions.slice(0, 3).map((i: any, j: number) => (
              <li key={j}><span className="text-pine-700">→</span> {i.action} <span className="text-stone-400">— {i.why}</span></li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function CopilotPanel({ onGraphRefresh }: { onGraphRefresh?: () => void }) {
  const [q, setQ] = useState("What happens if we lose our largest supplier?");
  const [log, setLog] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [ai, setAi] = useState<any>(null);

  useEffect(() => {
    fetch(`${API}/ai/status`).then(r => r.json()).then(setAi).catch(() => setAi(null));
  }, []);

  async function ask() {
    if (!q.trim() || busy) return;
    setBusy(true); setErr("");
    setLog(l => [...l, { role: "user", text: q }]);
    try {
      const H = { ...headers(), "Content-Type": "application/json" };
      const r = await fetch(`${API}/ai/ask`, { method: "POST", headers: H, body: JSON.stringify({ question: q }) }).then(r => {
        if (r.status === 401 && typeof window !== "undefined") window.location.href = "/login";
        if (!r.ok) throw new Error("Copilot request failed");
        return r.json();
      });
      setLog(l => [...l, { role: "ai", text: r.answer || "Done.", detail: r }]);
    } catch (e: any) {
      setErr(e.message || "Request failed");
    } finally { setBusy(false); }
  }

  async function approveFormula(id: string) {
    const H = headers();
    await fetch(`${API}/formulas/${id}/approve`, { method: "POST", headers: H });
    onGraphRefresh?.();
    setLog(l => [...l, { role: "ai", text: `Formula approved and active in the graph.` }]);
  }

  return (
    <aside className="flex min-h-0 flex-col border-l border-stone-200 bg-white" aria-label="AI copilot">
      <div className="border-b border-stone-200 px-5 py-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-pine-700">Copilot</p>
        <p className="mt-0.5 text-xs text-stone-400">Orchestrates the graph engine. Never edits silently.</p>
        {ai && (
          <p className="tnum mt-2 flex flex-wrap items-center gap-1.5 font-mono text-[10px] text-stone-400">
            <span className={`h-1.5 w-1.5 rounded-full ${ai.live ? "bg-pine-600" : "bg-amber-500"}`} />
            {ai.provider} · {ai.model}
            {ai.deterministic_fallback && <span className="text-amber-600">no LLM key — deterministic tools</span>}
          </p>
        )}
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto bg-paper-50 px-4 py-4">
        {log.length === 0 && (
          <div className="rounded-2xl border border-dashed border-stone-300 bg-white p-4 text-[13px] leading-relaxed text-stone-400">
            Ask about impact, bottlenecks, or formulas. Try: “What happens if we lose our largest supplier?”
          </div>
        )}
        {log.map((m, i) => (
          <div key={i} className={`rise rounded-2xl border px-3.5 py-3 text-[13px] leading-relaxed ${m.role === "user" ? "border-stone-200 bg-white text-stone-900" : "border-pine-100 bg-pine-50/60 text-stone-800"}`}>
            <p>{m.text}</p>
            {m.detail?.steps && (
              <ol className="mt-2 space-y-1 border-t border-stone-200 pt-2 text-xs text-stone-500">
                {m.detail.steps.map((s: string, j: number) => <li key={j} className="flex gap-2"><span className="tnum text-stone-400">{j + 1}.</span>{s}</li>)}
              </ol>
            )}
            {m.detail?.tool_calls?.length > 0 && (
              <div className="mt-2 flex flex-wrap items-center gap-1 border-t border-stone-200 pt-2">
                <span className="text-[10px] uppercase tracking-[0.12em] text-stone-400">tools</span>
                {Array.from(new Set<string>(m.detail.tool_calls.map((t: any) => t.tool))).map((t: string) => (
                  <span key={t} className="rounded bg-white px-1.5 py-0.5 font-mono text-[10px] text-stone-500 ring-1 ring-stone-200">{t}</span>
                ))}
                {m.detail.grounding && (
                  <span className={`ml-auto text-[10px] font-medium ${m.detail.grounding.fully_grounded ? "text-pine-700" : "text-amber-600"}`}>
                    {m.detail.grounding.fully_grounded ? "grounded in graph" : `${m.detail.grounding.ungrounded_refs.length} ungrounded ref(s)`}
                  </span>
                )}
              </div>
            )}
            {m.detail?.explanation && <ExplanationBlock e={m.detail.explanation} />}
            {m.detail?.proposal && (
              <div className="mt-2 rounded-xl bg-white p-2.5 ring-1 ring-stone-200">
                <div className="flex items-center gap-2"><Badge tone="warn">Needs approval</Badge></div>
                <p className="tnum mt-1.5 font-mono text-xs text-pine-700">{m.detail.proposal.target} = {m.detail.proposal.expression}</p>
                <div className="mt-2 flex items-center gap-2">
                  <Btn onClick={() => approveFormula(m.detail.proposal.id)}>Apply</Btn>
                  <span className="text-xs text-stone-400">Edit or reject in Workspace.</span>
                </div>
              </div>
            )}
            {m.detail?.bottlenecks && (
              <ul className="mt-2 space-y-1 border-t border-stone-200 pt-2 text-xs text-stone-600">
                {m.detail.bottlenecks.slice(0, 3).map((b: any, j: number) => (
                  <li key={j} className="flex gap-2"><span className="text-pine-700">{b.node?.name}</span><span className="text-stone-400">fan-out {b.fanout}</span></li>
                ))}
              </ul>
            )}
            {m.detail?.risks && (
              <ul className="mt-2 space-y-1 border-t border-stone-200 pt-2 text-xs text-stone-600">
                {m.detail.risks.map((r: any, j: number) => (
                  <li key={j} className="flex gap-2"><Badge tone={r.severity === "HIGH" ? "bad" : r.severity === "MEDIUM" ? "warn" : "good"}>{r.severity}</Badge><span>{r.detail}</span></li>
                ))}
              </ul>
            )}
            {m.detail?.simulation?.deltas && !m.detail?.explanation && (
              <div className="tnum mt-2 font-mono text-[11px] text-stone-500">
                {Object.entries(m.detail.simulation.deltas).slice(0, 4).map(([k, v]: any) => (
                  <div key={k}>{k}: {v.before} → {v.after}</div>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && <p className="text-xs text-stone-400">Running graph tools…</p>}
        {err && <ErrorNote msg={err} />}
      </div>
      <div className="border-t border-stone-200 bg-white p-3">
        <div className="flex gap-2">
          <input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === "Enter") ask(); }}
            placeholder="Ask about the business…" aria-label="Ask copilot"
            className="min-w-0 flex-1 rounded-xl border border-stone-200 bg-paper-50 px-3 py-2 text-[13px] text-stone-900 placeholder:text-stone-400" />
          <Btn onClick={ask} disabled={busy}><span className="inline-flex items-center gap-1.5"><PaperPlaneRight size={14} weight="fill" />{busy ? "…" : "Run"}</span></Btn>
        </div>
      </div>
    </aside>
  );
}