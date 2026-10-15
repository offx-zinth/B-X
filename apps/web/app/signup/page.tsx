"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "../../lib/auth";
import { Card, Btn, ErrorNote } from "../../components/ui";

export default function Signup() {
  const { signup, session, loading } = useAuth();
  const router = useRouter();
  const [org, setOrg] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const input = "w-full rounded-xl border border-stone-200 bg-white px-3 py-2 text-[14px]";

  // Already signed in -> don't offer a second org signup, go home.
  useEffect(() => {
    if (!loading && session) router.replace("/");
  }, [loading, session, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr("");
    try { await signup(org.trim(), email.trim(), password); }
    catch (e: any) { setErr(e.message || "Signup failed"); }
    finally { setBusy(false); }
  };

  if (loading || session) {
    return (
      <main className="mx-auto max-w-md px-6 pb-20 pt-16">
        <p className="text-sm text-stone-500">{session ? "Already signed in — taking you home…" : "Checking session…"}</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-md px-6 pb-20 pt-16">
      <h1 className="font-display text-3xl font-semibold tracking-tight">Create your organization</h1>
      <p className="mt-2 text-sm text-stone-500">Provisions an isolated tenant with Owner role. Invite teammates later in Settings.</p>
      <Card className="mt-6 p-6">
        <form onSubmit={submit} className="space-y-3">
          <label className="block text-xs font-medium text-stone-500">Organization
            <input value={org} onChange={e => setOrg(e.target.value)} required className={`${input} mt-1`} placeholder="Sharma Tea Stall" />
          </label>
          <label className="block text-xs font-medium text-stone-500">Work email
            <input value={email} onChange={e => setEmail(e.target.value)} type="email" required className={`${input} mt-1`} placeholder="you@company.com" />
          </label>
          <label className="block text-xs font-medium text-stone-500">Password (min 8 chars)
            <input value={password} onChange={e => setPassword(e.target.value)} type="password" required minLength={8} className={`${input} mt-1`} />
          </label>
          {err && <ErrorNote msg={err} />}
          <Btn type="submit" disabled={busy || !org || !email || password.length < 8}>{busy ? "Creating…" : "Create org and continue"}</Btn>
        </form>
      </Card>
      <p className="mt-4 text-sm text-stone-500">Already have an account? <Link href="/login" className="font-semibold text-pine-700">Log in →</Link></p>
    </main>
  );
}
