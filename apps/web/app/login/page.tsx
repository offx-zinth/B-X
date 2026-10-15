"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "../../lib/auth";
import { Card, Btn, ErrorNote } from "../../components/ui";

export default function Login() {
  const { login, session, loading } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("demo@acme.co");
  const [password, setPassword] = useState("secret123");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const input = "w-full rounded-xl border border-stone-200 bg-white px-3 py-2 text-[14px]";

  // Already signed in (session in nav) -> don't show the form, go home.
  useEffect(() => {
    if (!loading && session) router.replace("/");
  }, [loading, session, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr("");
    try { await login(email.trim(), password); }
    catch (e: any) { setErr(e.message || "Login failed"); }
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
      <h1 className="font-display text-3xl font-semibold tracking-tight">Log in</h1>
      <p className="mt-2 text-sm text-stone-500">Each login is scoped to one tenant. Data never leaks across organizations.</p>
      <Card className="mt-6 p-6">
        <form onSubmit={submit} className="space-y-3">
          <label className="block text-xs font-medium text-stone-500">Work email
            <input value={email} onChange={e => setEmail(e.target.value)} type="email" required className={`${input} mt-1`} />
          </label>
          <label className="block text-xs font-medium text-stone-500">Password
            <input value={password} onChange={e => setPassword(e.target.value)} type="password" required minLength={8} className={`${input} mt-1`} />
          </label>
          {err && <ErrorNote msg={err} />}
          <Btn type="submit" disabled={busy}>{busy ? "Signing in…" : "Log in"}</Btn>
        </form>
      </Card>
      <p className="mt-4 text-sm text-stone-500">No organization yet? <Link href="/signup" className="font-semibold text-pine-700">Create one →</Link></p>
    </main>
  );
}
