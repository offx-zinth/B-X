"use client";
import { useEffect, useState } from "react";
import { API, headers } from "../../lib/api";
import { Card, SectionTitle, Btn, Badge, ErrorNote } from "../../components/ui";

export default function Settings() {
  const [me, setMe] = useState<any>(null);
  const [users, setUsers] = useState<any[]>([]);
  const [audit, setAudit] = useState<any[]>([]);
  const [versions, setVersions] = useState<any[]>([]);
  const [err, setErr] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("Viewer");

  const H = () => headers();

  async function load() {
    try {
      setMe(await fetch(`${API}/auth/me`, { headers: H() }).then(r => r.json()));
      setUsers(await fetch(`${API}/auth/users`, { headers: H() }).then(r => r.json()).catch(() => []));
      setAudit(await fetch(`${API}/audit?limit=30`, { headers: H() }).then(r => r.json()).catch(() => []));
      setVersions(await fetch(`${API}/graph/versions`, { headers: H() }).then(r => r.json()).catch(() => []));
    } catch (e: any) { setErr(e.message); }
  }

  async function invite() {
    setErr("");
    const r = await fetch(`${API}/auth/users`, { method: "POST", headers: { ...H(), "Content-Type": "application/json" }, body: JSON.stringify({ email, password: "secret123", role }) });
    if (!r.ok) { setErr(await r.text()); return; }
    setEmail(""); load();
  }

  useEffect(() => { load(); }, []);

  const input = "rounded-xl border border-stone-200 bg-white px-3 py-2 text-[13px]";
  return (
    <main className="mx-auto max-w-[1400px] px-6 pb-20 pt-12">
      <h1 className="font-display text-[44px] font-semibold tracking-tight text-stone-900">Settings</h1>
      <p className="mt-2 text-[15px] text-stone-500">Organization, roles, versions and audit trail.</p>
      {err && <div className="mt-4"><ErrorNote msg={err} /></div>}
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card className="p-6">
          <SectionTitle title="Account" hint="Tenant isolation is enforced at the API layer on every query." />
          {me && <div className="tnum mt-3 font-mono text-xs text-stone-600"><p>{me.email}</p><p className="mt-1">role {me.role} · tenant {String(me.tenant_id).slice(0, 8)}</p></div>}
          <div className="mt-5 border-t border-stone-200 pt-4">
            <SectionTitle title="Users & roles" hint="Owner · Admin · Analyst · Viewer. Invites need Admin." />
            <ul className="mt-3 space-y-1.5 text-[13px]">
              {(Array.isArray(users) ? users : []).map((u: any) => (
                <li key={u.id} className="flex items-center gap-2"><span>{u.email}</span><Badge>{u.role}</Badge></li>
              ))}
              {!users?.length && <li className="text-[13px] text-stone-400">No user list (Viewer role hides admin).</li>}
            </ul>
            <div className="mt-3 flex flex-wrap gap-2">
              <input value={email} onChange={e => setEmail(e.target.value)} placeholder="teammate@co.com" aria-label="Invite email" className={input} />
              <select value={role} onChange={e => setRole(e.target.value)} aria-label="Role" className={input}>
                <option>Viewer</option><option>Analyst</option><option>Admin</option><option>Owner</option>
              </select>
              <Btn onClick={invite}>Invite</Btn>
            </div>
          </div>
        </Card>
        <Card className="p-6">
          <SectionTitle title="Graph versions" hint="Immutable snapshots. Simulations pin a version for reproducibility." />
          <ul className="tnum mt-3 space-y-1.5 font-mono text-xs text-stone-600">
            {versions.map((v: any) => (
              <li key={v.id} className="flex gap-2"><span className="text-pine-700">v{v.version}</span><span>{v.node_count}n/{v.edge_count}e/{v.formula_count}f</span><span className="text-stone-400">{v.source}</span></li>
            ))}
            {!versions.length && <li>No versions yet — upload data or seed the demo.</li>}
          </ul>
          <div className="mt-5 border-t border-stone-200 pt-4">
            <SectionTitle title="Audit log" hint="Login, uploads, graph changes, approvals, simulations, AI actions." />
            <ul className="tnum mt-3 max-h-64 space-y-1.5 overflow-y-auto font-mono text-[11px] text-stone-500">
              {audit.map((a: any) => (
                <li key={a.id} className="flex gap-2"><span className="text-stone-300">{String(a.timestamp).slice(0, 16).replace("T", " ")}</span><span className="text-pine-700">{a.action}</span><span className="truncate">{a.resource}</span></li>
              ))}
            </ul>
          </div>
        </Card>
      </div>
    </main>
  );
}
