import { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-2xl border border-stone-200 bg-white ${className}`}>{children}</div>;
}

export function SectionTitle({ kicker, title, hint }: { kicker?: string; title: string; hint?: string }) {
  return (
    <div>
      {kicker && <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-pine-700">{kicker}</p>}
      <h2 className="balance mt-1 font-display text-xl font-semibold tracking-tight text-stone-900">{title}</h2>
      {hint && <p className="mt-1 max-w-[65ch] text-[13px] leading-relaxed text-stone-500">{hint}</p>}
    </div>
  );
}

export function Btn({ children, onClick, variant = "primary", disabled, type = "button" }: {
  children: ReactNode; onClick?: () => void; variant?: "primary" | "ghost" | "danger"; disabled?: boolean; type?: "button" | "submit";
}) {
  const v = variant === "primary"
    ? "bg-pine-700 text-white hover:bg-pine-800 disabled:opacity-40"
    : variant === "danger"
    ? "border border-red-200 bg-red-50 text-red-700 hover:bg-red-100"
    : "border border-stone-200 bg-white text-stone-700 hover:border-stone-300 hover:bg-stone-50";
  return <button type={type} disabled={disabled} onClick={onClick} className={`btn rounded-xl px-4 py-2 text-[13.5px] font-semibold ${v}`}>{children}</button>;
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "good" | "warn" | "bad" }) {
  const t = tone === "good" ? "border-pine-100 bg-pine-50 text-pine-700"
    : tone === "warn" ? "border-amber-200 bg-amber-50 text-amber-700"
    : tone === "bad" ? "border-red-200 bg-red-50 text-red-700"
    : "border-stone-200 bg-stone-100 text-stone-500";
  return <span className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${t}`}>{children}</span>;
}

export function MetricStrip({ items }: { items: { label: string; value: string; sub?: string }[] }) {
  return (
    <dl className="grid grid-cols-3 divide-x divide-stone-200 rounded-2xl border border-stone-200 bg-white">
      {items.map(m => (
        <div key={m.label} className="px-6 py-5">
          <dt className="text-[11px] font-medium uppercase tracking-[0.12em] text-stone-400">{m.label}</dt>
          <dd className="tnum mt-1 font-display text-[28px] font-semibold tracking-tight text-stone-900">{m.value}</dd>
          {m.sub && <dd className="mt-0.5 text-xs text-stone-400">{m.sub}</dd>}
        </div>
      ))}
    </dl>
  );
}

export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className="grid place-items-center rounded-2xl border border-dashed border-stone-300 bg-white px-6 py-12 text-center">
      <div className="max-w-sm">
        <p className="font-display text-[15px] font-semibold text-stone-900">{title}</p>
        <p className="mt-1.5 text-[13px] leading-relaxed text-stone-500">{body}</p>
        {action && <div className="mt-4">{action}</div>}
      </div>
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-stone-200/70 ${className}`} />;
}

export function ErrorNote({ msg }: { msg: string }) {
  return <p role="alert" className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">{msg}</p>;
}
