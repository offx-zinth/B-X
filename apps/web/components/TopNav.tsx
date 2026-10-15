"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ShareNetwork } from "@phosphor-icons/react";
import { useAuth } from "../lib/auth";
import { Badge } from "./ui";

const LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/", label: "Data" },
  { href: "/workspace", label: "Business Graph" },
  { href: "/simulations", label: "Simulations" },
  { href: "/reports", label: "Reports" },
  { href: "/optimization", label: "Optimization" },
  { href: "/settings", label: "Settings" },
];

export default function TopNav() {
  const path = usePathname();
  const { session, loading, logout } = useAuth();
  return (
    <header className="sticky top-0 z-40 border-b border-stone-200 bg-paper-50/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-8 px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-[10px] bg-pine-700 text-white">
            <ShareNetwork size={17} weight="regular" />
          </span>
          <span className="font-display text-[16px] font-semibold tracking-tight text-stone-900">Business X-Ray</span>
        </Link>
        <nav className="flex flex-wrap items-center gap-1" aria-label="Primary">
          {LINKS.map(l => {
            const active = path === l.href;
            return (
              <Link key={l.href} href={l.href} aria-current={active ? "page" : undefined}
                className={`rounded-lg px-3 py-1.5 text-[13.5px] font-medium transition-colors ${active ? "bg-stone-900 text-white" : "text-stone-500 hover:bg-stone-200/60 hover:text-stone-900"}`}>
                {l.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <span className="hidden items-center gap-1.5 rounded-full border border-stone-200 bg-white px-3 py-1 text-[12px] font-medium text-stone-500 sm:flex">
            <span className="h-1.5 w-1.5 rounded-full bg-pine-600" /> Base reality · live
          </span>
          {!loading && !session && (
            <span className="flex items-center gap-2 text-[13px]">
              <Link href="/login" className="font-semibold text-stone-600 hover:text-stone-900">Log in</Link>
              <Link href="/signup" className="rounded-lg bg-stone-900 px-3 py-1.5 font-semibold text-white">Sign up</Link>
            </span>
          )}
          {!loading && session && (
            <span className="flex items-center gap-2 text-[12px]">
              <span className="hidden max-w-[220px] truncate text-stone-500 md:block">{session.org || "Workspace"} · {session.email}</span>
              <Badge>{session.role}</Badge>
              <button onClick={logout} className="rounded-lg border border-stone-200 bg-white px-2.5 py-1 font-semibold text-stone-600 hover:text-stone-900">Log out</button>
            </span>
          )}
        </div>
      </div>
    </header>
  );
}
