"use client";
import { useCallback, useEffect, useState } from "react";
import { ArrowClockwise } from "@phosphor-icons/react";
import { API, XNode, headers } from "../../lib/api";
import GraphCanvas from "../../components/GraphCanvas";
import CopilotPanel from "../../components/CopilotPanel";
import { Badge, Btn, ErrorNote, Skeleton } from "../../components/ui";

const TYPE_DOT: Record<string, string> = {
  Supplier: "bg-amber-600", Production: "bg-pine-700",
  Material: "bg-stone-400", Order: "bg-stone-700", Inventory: "bg-stone-400",
  Machine: "bg-stone-500", Customer: "bg-stone-400", Employee: "bg-stone-500",
};

function SimulateFromNode({ node }: { node: XNode }) {
  const [prop, setProp] = useState("");
  const [val, setVal] = useState("0");
  const [out, setOut] = useState("");
  const firstProp = Object.keys(node.properties || {}).find(k => typeof (node.properties as any)[k] === "number") || "capacity";
  async function run() {
    const target = `${node.type}.${prop || firstProp}`;
    const r = await fetch(`${API}/simulations/run`, {
      method: "POST",
      headers: { ...headers(), "Content-Type": "application/json" },
      body: JSON.stringify({ name: `Change ${target}`, changes: [{ target, value: Number(val) }], duration_days: 14 }),
    }).then(r => r.json()).catch(() => null);
    if (r?.result?.deltas) {
      const n = Object.keys(r.result.deltas).length;
      setOut(`${n} fields changed over 14d. Open Simulations for the full delta table.`);
    } else setOut("Simulation failed — see Simulations page.");
  }
  return (
    <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-stone-200 pt-4">
      <span className="text-[12px] font-semibold text-stone-500">Simulate change</span>
      <input value={prop} onChange={e => setProp(e.target.value)} placeholder={firstProp} aria-label="Property"
        className="tnum w-28 rounded-lg border border-stone-200 px-2 py-1.5 font-mono text-xs" />
      <input value={val} onChange={e => setVal(e.target.value)} placeholder="0" aria-label="New value"
        className="tnum w-20 rounded-lg border border-stone-200 px-2 py-1.5 font-mono text-xs" />
      <Btn onClick={run}>Run</Btn>
      {out && <span className="text-xs text-stone-500">{out}</span>}
    </div>
  );
}

export default function Workspace() {
  const [nodes, setNodes] = useState<XNode[]>([]);
  const [edges, setEdges] = useState<any[]>([]);
  const [formulas, setFormulas] = useState<any[]>([]);
  const [sel, setSel] = useState<XNode | null>(null);
  const [impact, setImpact] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [filter, setFilter] = useState<string>("All");
  const [editing, setEditing] = useState<string | null>(null);
  const [editExpr, setEditExpr] = useState("");

  const H = () => headers();

  const load = useCallback(async () => {
    setErr("");
    try {
      const [n, e, f] = await Promise.all([
        fetch(`${API}/graph/nodes`, { headers: H() }).then(r => { if (!r.ok) throw new Error("Graph load failed"); return r.json(); }),
        fetch(`${API}/graph/edges`, { headers: H() }).then(r => r.json()),
        fetch(`${API}/formulas/`, { headers: H() }).then(r => r.json()).catch(() => []),
      ]);
      setNodes(n); setEdges(e); setFormulas(f);
    } catch (e: any) { setErr(e.message + ". Create an org on the Data page first."); }
    finally { setLoading(false); }
  }, []);

  async function select(n: XNode) {
    setSel(n);
    try {
      const im = await fetch(`${API}/graph/impact/${n.id}`, { headers: H() }).then(r => r.json());
      setImpact(im);
    } catch { /* keep selection without impact */ }
  }

  async function setFormula(id: string, action: "approve" | "reject") {
    await fetch(`${API}/formulas/${id}/${action}`, { method: "POST", headers: H() });
    load();
  }

  async function saveFormula(id: string) {
    const r = await fetch(`${API}/formulas/${id}`, {
      method: "PATCH", headers: { ...H(), "Content-Type": "application/json" },
      body: JSON.stringify({ expression: editExpr }),
    });
    if (!r.ok) { setErr("Edit rejected: " + (await r.text())); return; }
    setEditing(null); load();
  }

  useEffect(() => { load(); }, [load]);

  const types = ["All", ...Array.from(new Set(nodes.map(n => n.type)))];
  const shown = filter === "All" ? nodes : nodes.filter(n => n.type === filter);
  const edgeCount = (id: string) => edges.filter(e => e.source_node === id || e.target_node === id).length;

  return (
    <main className="mx-auto grid max-w-[1400px] grid-cols-1 gap-0 lg:grid-cols-[240px_minmax(0,1fr)_360px]">
      {/* Explorer */}
      <aside className="border-b border-stone-200 p-5 lg:border-b-0 lg:border-r">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-stone-400">Explorer</p>
        <div className="mt-3 flex flex-wrap gap-1 lg:flex-col">
          {types.map(t => (
            <button key={t} onClick={() => setFilter(t)}
              className={`btn flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] ${filter === t ? "bg-stone-900 text-white" : "text-stone-500 hover:bg-stone-200/60 hover:text-stone-900"}`}>
              {t !== "All" && <span className={`h-2 w-2 rounded-full ${TYPE_DOT[t] || "bg-stone-400"}`} />}
              {t}
              <span className={`tnum ml-auto text-[11px] ${filter === t ? "text-stone-300" : "text-stone-400"}`}>{t === "All" ? nodes.length : nodes.filter(n => n.type === t).length}</span>
            </button>
          ))}
        </div>
        <div className="mt-5 border-t border-stone-200 pt-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-stone-400">Legend</p>
          <ul className="mt-2.5 space-y-1.5 text-xs text-stone-500">
            <li className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-red-600" /> Direct impact</li>
            <li className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-amber-600" /> Secondary impact</li>
            <li className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-stone-300" /> No known impact</li>
          </ul>
        </div>
        <div className="mt-4"><Btn variant="ghost" onClick={load}><span className="inline-flex items-center gap-1.5"><ArrowClockwise size={14} weight="regular" /> Refresh</span></Btn></div>
      </aside>

      {/* Graph */}
      <section className="min-h-[60dvh] p-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h1 className="font-display text-[26px] font-semibold tracking-tight text-stone-900">Base reality</h1>
          <div className="tnum flex gap-4 text-xs text-stone-400">
            <span><b className="text-stone-900">{nodes.length}</b> nodes</span>
            <span><b className="text-stone-900">{edges.length}</b> edges</span>
            <span><b className="text-stone-900">{formulas.filter((f: any) => f.status === "approved").length}</b> active formulas</span>
          </div>
        </div>

        {err && <div className="mt-3"><ErrorNote msg={err} /></div>}

        <div className="mt-4 overflow-hidden rounded-2xl border border-stone-200 bg-white" style={{ height: "52dvh", minHeight: 380 }}>
          {loading ? (
            <div className="space-y-2 p-4"><Skeleton className="h-10" /><Skeleton className="h-64" /></div>
          ) : nodes.length === 0 ? (
            <div className="grid h-full place-items-center p-8 text-center">
              <div className="max-w-sm">
                <p className="font-display text-[15px] font-semibold text-stone-900">Graph is empty</p>
                <p className="mt-1.5 text-[13px] text-stone-500">Upload a CSV on the Data page — columns like customer_id and supplier_id become typed relationships automatically.</p>
              </div>
            </div>
          ) : (
            <GraphCanvas nodes={shown} edges={edges} selected={sel} impact={impact} onSelect={select} />
          )}
        </div>

        {/* Inspector */}
        <div className="mt-4 rounded-2xl border border-stone-200 bg-white p-5">
          {sel ? (
            <div className="rise">
              <div className="flex flex-wrap items-center gap-2">
                <Badge>{sel.type}</Badge>
                <p className="font-display text-[15px] font-semibold text-stone-900">{sel.name}</p>
                <span className="tnum ml-auto font-mono text-[11px] text-stone-400">conf {Math.round((sel.confidence ?? 1) * 100)}% · {(sel as any).level || "INFERRED"}</span>
              </div>
              {((sel as any).source_docs || []).length > 0 && (
                <p className="mt-1.5 text-xs text-stone-400">Source: {((sel as any).source_docs as string[]).join(", ")}{sel.last_observed ? ` · observed ${String((sel as any).last_observed).slice(0, 10)}` : ""}</p>
              )}
              <div className="tnum mt-4 grid grid-cols-4 gap-3 text-[13px]">
                <div><p className="text-[11px] uppercase tracking-wider text-stone-400">Edges</p><p className="font-mono text-stone-900">{edgeCount(sel.id)}</p></div>
                <div><p className="text-[11px] uppercase tracking-wider text-stone-400">Downstream</p><p className="font-mono text-stone-900">{impact?.affected_count ?? "—"}</p></div>
                <div><p className="text-[11px] uppercase tracking-wider text-stone-400">Direct</p><p className="font-mono text-stone-900">{impact?.direct?.length ?? "—"}</p></div>
                <div><p className="text-[11px] uppercase tracking-wider text-stone-400">Upstream</p><p className="font-mono text-stone-900">{impact?.upstream_count ?? "—"}</p></div>
              </div>
              <div className="mt-3 grid gap-1.5 sm:grid-cols-2">
                {Object.entries(sel.properties || {}).filter(([, v]) => typeof v !== "object").slice(0, 6).map(([k, v]) => (
                  <div key={k} className="tnum flex justify-between rounded-lg bg-paper-100 px-2.5 py-1.5 font-mono text-xs"><span className="text-stone-400">{sel.type}.{k}</span><span className="text-stone-900">{String(v)}</span></div>
                ))}
              </div>
              <SimulateFromNode node={sel} />
            </div>
          ) : (
            <p className="text-[13px] text-stone-400">Select a node to inspect properties, provenance and downstream impact.</p>
          )}
        </div>

        {/* Formulas */}
        <div className="mt-4 rounded-2xl border border-stone-200 bg-white p-5">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-stone-400">Formula links</p>
          {formulas.length === 0 ? (
            <p className="mt-2 text-[13px] text-stone-400">No formulas yet. Ask Copilot to propose one — approval is always manual.</p>
          ) : (
            <ul className="mt-2.5 space-y-1.5">
              {formulas.map((f: any) => (
                <li key={f.id} className="tnum rounded-lg bg-paper-100 px-3 py-2 font-mono text-xs">
                  {editing === f.id ? (
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="text-pine-700">{f.target} =</span>
                      <input value={editExpr} onChange={e => setEditExpr(e.target.value)} aria-label="Edit formula"
                        className="min-w-[200px] flex-1 rounded-lg border border-stone-200 bg-white px-2 py-1 text-xs text-stone-900" />
                      <button onClick={() => saveFormula(f.id)} className="font-sans font-semibold text-pine-700 hover:text-pine-800">Save</button>
                      <button onClick={() => setEditing(null)} className="font-sans text-stone-400 hover:text-stone-600">Cancel</button>
                    </span>
                  ) : (
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="text-pine-700">{f.target} = {f.expression}</span>
                      <Badge tone={f.status === "approved" ? "good" : f.status === "rejected" ? "bad" : "warn"}>{f.status}</Badge>
                      <span className="ml-auto flex gap-2 font-sans text-[11px] font-semibold">
                        {f.status === "pending" && <button onClick={() => setFormula(f.id, "approve")} className="text-pine-700 hover:text-pine-800">Approve</button>}
                        <button onClick={() => { setEditing(f.id); setEditExpr(f.expression); }} className="text-stone-500 hover:text-stone-800">Edit</button>
                        {f.status !== "rejected" && <button onClick={() => setFormula(f.id, "reject")} className="text-stone-400 hover:text-red-600">Reject</button>}
                      </span>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <CopilotPanel onGraphRefresh={load} />
    </main>
  );
}
