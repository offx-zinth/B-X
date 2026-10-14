"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { UploadSimple, PlugsConnected, Code, ArrowRight } from "@phosphor-icons/react";
import { API } from "../lib/api";
import { Card, SectionTitle, Btn, Badge, MetricStrip, EmptyState, Skeleton, ErrorNote } from "../components/ui";

type Source = { id: string; filename: string; row_count: number; status: string };

const STEPS = ["Upload", "Normalize", "Compile", "Graph", "Rules", "Simulate", "Explain", "Report"];

export default function Portal() {
  const [sources, setSources] = useState<Source[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [authed, setAuthed] = useState(false);
  const [seeding, setSeeding] = useState(false);

  async function seed() {
    setSeeding(true); setErr("");
    try {
      const r = await fetch(`${API}/ingest/seed`, {
        method: "POST", headers: { Authorization: `Bearer ${localStorage.getItem("xray_token")}` },
      }).then(r => { if (!r.ok) throw new Error("Seed failed"); return r.json(); });
      setMsg(r.seeded ? `Demo graph ready — ${r.nodes} nodes, ${r.edges} edges, ${r.formulas} formulas.` : `Tenant already has data (${r.nodes} nodes).`);
      load();
    } catch (e: any) { setErr(e.message); } finally { setSeeding(false); }
  }

  async function load() {
    const t = localStorage.getItem("xray_token");
    if (!t) { setLoading(false); return; }
    setAuthed(true);
    try {
      const s = await fetch(`${API}/ingest/sources`, { headers: { Authorization: `Bearer ${t}` } }).then(r => {
        if (!r.ok) throw new Error("Could not load sources");
        return r.json();
      });
      setSources(s);
    } catch (e: any) { setErr(e.message); } finally { setLoading(false); }
  }

  async function login() {
    setErr("");
    const r = await fetch(`${API}/auth/signup`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ org: "Acme Manufacturing", email: `demo-${Date.now()}@acme.co`, password: "secret123" }),
    }).then(r => r.json()).catch(() => null);
    if (r?.token) { localStorage.setItem("xray_token", r.token); setMsg(`Workspace ready — tenant ${r.tenant_id.slice(0, 8)}`); load(); }
    else setErr("Signup failed. Is the API running at " + API + "?");
  }

  async function upload(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]; if (!f) return;
    setErr(""); setMsg(`Parsing ${f.name}…`);
    const fd = new FormData(); fd.append("f", f);
    try {
      const r = await fetch(`${API}/ingest/upload`, {
        method: "POST", headers: { Authorization: `Bearer ${localStorage.getItem("xray_token")}` }, body: fd,
      }).then(r => { if (!r.ok) throw new Error("Upload failed"); return r.json(); });
      setMsg(r.stats); load();
    } catch (e: any) { setErr(e.message); setMsg(""); }
  }

  useEffect(() => { load(); }, []);

  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-20 pt-12">
      <div className="rise max-w-2xl">
        <h1 className="balance font-display text-[44px] font-semibold leading-[1.05] tracking-tight text-stone-900">Give us your business data. Get back an operating graph.</h1>
        <p className="mt-4 max-w-[60ch] text-[15px] leading-relaxed text-stone-500">
          Upload exports from the tools you already use. X-Ray normalizes them into entities, processes and dependencies — the graph stays the source of truth.
        </p>
      </div>

      {!authed && !loading && (
        <Card className="rise-1 mt-8 flex flex-wrap items-center gap-4 p-6">
          <div className="min-w-[220px] flex-1">
            <p className="font-display text-[15px] font-semibold text-stone-900">Create your demo organization</p>
            <p className="mt-0.5 text-[13px] text-stone-500">One click provisions an isolated tenant. No SSO in the MVP.</p>
          </div>
          <Btn onClick={login}><span className="inline-flex items-center gap-1.5">Create org and continue <ArrowRight size={14} weight="bold" /></span></Btn>
        </Card>
      )}

      <div className="mt-6 grid gap-4 lg:grid-cols-5">
        <Card className="rise-1 card-hover p-6 lg:col-span-3">
          <div className="flex items-center gap-2.5">
            <UploadSimple size={18} weight="regular" className="text-pine-700" />
            <p className="font-display text-[16px] font-semibold text-stone-900">Upload files</p>
          </div>
          <p className="mt-1 text-[13px] text-stone-500">CSV · XLSX · PDF · JSON — parsed into typed entities, not random nodes.</p>
          <label className="btn mt-5 grid cursor-pointer place-items-center rounded-2xl border border-dashed border-stone-300 bg-paper-50 px-4 py-12 text-center text-[13.5px] text-stone-600 hover:border-pine-600 hover:bg-pine-50/50">
            Drop a file or click to browse
            <input type="file" className="sr-only" onChange={upload} disabled={!authed} />
          </label>
          {!authed && <p className="mt-2 text-xs text-stone-400">Create an org first to enable uploads.</p>}
        </Card>
        <div className="grid gap-4 lg:col-span-2">
          <Card className="rise-2 flex items-center gap-3.5 p-6 opacity-70">
            <PlugsConnected size={18} weight="regular" className="shrink-0 text-stone-400" />
            <div>
              <div className="flex items-center gap-2"><p className="font-display text-[15px] font-semibold text-stone-900">Connect software</p><Badge>Soon</Badge></div>
              <p className="mt-1 text-[13px] text-stone-500">ERP, CRM, accounting and HR sync land after file ingest is solid.</p>
            </div>
          </Card>
          <Card className="rise-3 flex items-center gap-3.5 p-6 opacity-70">
            <Code size={18} weight="regular" className="shrink-0 text-stone-400" />
            <div>
              <div className="flex items-center gap-2"><p className="font-display text-[15px] font-semibold text-stone-900">API endpoint</p><Badge>Soon</Badge></div>
              <p className="tnum mt-1 font-mono text-[12px] text-stone-500">POST /ingest/events</p>
            </div>
          </Card>
        </div>
      </div>

      {msg && <p className="mt-4 rounded-xl border border-pine-100 bg-pine-50 px-4 py-2.5 text-[13px] text-pine-700">{msg}</p>}
      {err && <div className="mt-4"><ErrorNote msg={err} /></div>}

      <div className="mt-12 grid gap-10 lg:grid-cols-[1fr_300px]">
        <section>
          <SectionTitle title="Data sources" hint="Each file is parsed, classified and compiled into graph types — never dumped as random nodes." />
          <div className="mt-4">
            {loading ? (
              <div className="space-y-2">{[0, 1, 2].map(i => <Skeleton key={i} className="h-12" />)}</div>
            ) : sources.length === 0 ? (
              <EmptyState title="No data yet" body="Upload orders, inventory or suppliers to see the pipeline light up." action={<Link href="/workspace" className="inline-flex items-center gap-1 text-[13px] font-semibold text-pine-700 hover:text-pine-800">Open the workspace <ArrowRight size={13} weight="bold" /></Link>} />
            ) : (
              <ul className="divide-y divide-stone-200 rounded-2xl border border-stone-200 bg-white">
                {sources.map(s => (
                  <li key={s.id} className="flex items-center gap-3 px-5 py-3.5">
                    <Badge tone="good">parsed</Badge>
                    <span className="text-[13.5px] font-medium text-stone-900">{s.filename}</span>
                    <span className="tnum ml-auto text-xs text-stone-400">{s.row_count} rows</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
        <section>
          <SectionTitle title="The loop" />
          <ol className="mt-4">
            {STEPS.map((s, i) => (
              <li key={s} className="flex items-center gap-3 border-l border-stone-200 py-2 pl-4">
                <span className="tnum grid h-6 w-6 place-items-center rounded-md bg-stone-100 font-mono text-[11px] text-stone-500 ring-1 ring-inset ring-stone-200">{i + 1}</span>
                <span className="text-[13px] text-stone-600">{s}</span>
              </li>
            ))}
          </ol>
          <div className="mt-5 flex gap-2">
            <Link href="/workspace"><Btn>Open workspace</Btn></Link>
            <Link href="/reports"><Btn variant="ghost">View reports</Btn></Link>
            <Btn variant="ghost" onClick={seed} disabled={!authed || seeding}>{seeding ? "Loading…" : "Load demo dataset"}</Btn>
          </div>
        </section>
      </div>

      {(sources.length > 0 || msg) && (
        <div className="mt-10">
          <MetricStrip items={[
            { label: "Sources", value: String(sources.length), sub: "files parsed" },
            { label: "Rows", value: sources.reduce((a, s) => a + (s.row_count || 0), 0).toLocaleString(), sub: "records normalized" },
            { label: "Isolation", value: "tenant_id", sub: "enforced at API layer" },
          ]} />
        </div>
      )}
    </main>
  );
}
