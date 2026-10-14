"use client";
import { useMemo } from "react";
import type { XNode } from "../lib/api";

type Edge = { id: string; source_node: string; target_node: string; type: string };

const TYPE_COLOR: Record<string, string> = {
  Supplier: "#D97706", Production: "#047857",
  Material: "#A8A29E", Order: "#44403C", Inventory: "#A8A29E",
  Machine: "#78716C", Customer: "#A8A29E", Employee: "#78716C",
};
const FALLBACK = "#A8A29E";

/** Layered DAG layout: BFS depth from roots, centered per layer. Pure SVG, no deps. */
export default function GraphCanvas({ nodes, edges, selected, impact, onSelect }: {
  nodes: XNode[]; edges: Edge[]; selected: XNode | null;
  impact: { direct?: string[]; downstream?: string[] } | null;
  onSelect: (n: XNode) => void;
}) {
  const layout = useMemo(() => {
    const ids = new Set(nodes.map(n => n.id));
    const indeg = new Map(nodes.map(n => [n.id, 0]));
    const adj = new Map<string, string[]>();
    for (const e of edges) {
      if (!ids.has(e.source_node) || !ids.has(e.target_node)) continue;
      adj.set(e.source_node, [...(adj.get(e.source_node) || []), e.target_node]);
      indeg.set(e.target_node, (indeg.get(e.target_node) || 0) + 1);
    }
    const depth = new Map<string, number>();
    const queue = nodes.filter(n => (indeg.get(n.id) || 0) === 0).map(n => n.id);
    if (queue.length === 0 && nodes.length) queue.push(nodes[0].id);
    queue.forEach(id => depth.set(id, 0));
    const q = [...queue];
    while (q.length) {
      const cur = q.shift()!;
      for (const nxt of adj.get(cur) || []) {
        const d = (depth.get(cur) || 0) + 1;
        if (d > (depth.get(nxt) ?? -1)) { depth.set(nxt, d); q.push(nxt); }
      }
    }
    nodes.forEach(n => { if (!depth.has(n.id)) depth.set(n.id, 0); });
    const layers = new Map<number, XNode[]>();
    for (const n of nodes) {
      const d = depth.get(n.id) || 0;
      layers.set(d, [...(layers.get(d) || []), n]);
    }
    const W = 220, H = 120, X0 = 60, Y0 = 60;
    const pos = new Map<string, { x: number; y: number }>();
    for (const [d, arr] of [...layers.entries()].sort((a, b) => a[0] - b[0])) {
      arr.forEach((n, i) => pos.set(n.id, { x: X0 + d * W, y: Y0 + i * H + (3 - Math.min(arr.length, 3)) * 20 }));
    }
    const maxY = Math.max(320, ...[...pos.values()].map(p => p.y)) + 120;
    const maxX = Math.max(640, ...[...pos.values()].map(p => p.x)) + 220;
    return { pos, w: maxX, h: maxY };
  }, [nodes, edges]);

  const direct = new Set(impact?.direct || []);
  const down = new Set(impact?.downstream || []);
  const dimmed = selected && (direct.size || down.size) ? true : false;

  function tone(id: string) {
    if (!selected) return { stroke: "#E7E5E4", fill: "#FFFFFF", opacity: 1 };
    if (id === selected.id) return { stroke: "#047857", fill: "#ECFDF5", opacity: 1 };
    if (direct.has(id)) return { stroke: "#DC2626", fill: "#FEF2F2", opacity: 1 };
    if (down.has(id)) return { stroke: "#D97706", fill: "#FFFBEB", opacity: 1 };
    return { stroke: "#E7E5E4", fill: "#FFFFFF", opacity: dimmed ? 0.5 : 1 };
  }

  return (
    <svg viewBox={`0 0 ${layout.w} ${layout.h}`} className="dotgrid h-full w-full" role="img" aria-label="Business operating graph">
      {edges.map(e => {
        const a = layout.pos.get(e.source_node), b = layout.pos.get(e.target_node);
        if (!a || !b) return null;
        const hot = selected && (e.source_node === selected.id || direct.has(e.source_node));
        const mx = (a.x + b.x) / 2;
        return (
          <g key={e.id} opacity={selected && !hot && e.source_node !== selected.id ? 0.3 : 1}>
            <path d={`M ${a.x + 150} ${a.y + 26} C ${mx} ${a.y + 26}, ${mx} ${b.y + 26}, ${b.x} ${b.y + 26}`}
              fill="none" stroke={hot ? "#047857" : "#D6D3D1"} strokeWidth={hot ? 2 : 1.2} />
            <text x={mx - 20} y={(a.y + b.y) / 2 + 22} fill="#A8A29E" fontSize="10">{e.type}</text>
          </g>
        );
      })}
      {nodes.map((n, i) => {
        const p = layout.pos.get(n.id)!;
        const t = tone(n.id);
        const c = TYPE_COLOR[n.type] || FALLBACK;
        const isSel = selected?.id === n.id;
        const props = Object.entries(n.properties || {}).filter(([, v]) => typeof v !== "object").slice(0, 2);
        return (
          <g key={n.id} transform={`translate(${p.x},${p.y})`} opacity={t.opacity}
             onClick={() => onSelect(n)} style={{ cursor: "pointer" }} tabIndex={0}
             onKeyDown={ev => { if (ev.key === "Enter") onSelect(n); }} role="button" aria-label={`${n.type} ${n.name}`}>
          <g className="node-enter" style={{ animationDelay: `${Math.min(i, 12) * 35}ms` }}>
            <rect width="150" height="52" rx="12" fill={t.fill}
              stroke={t.stroke} strokeWidth={isSel ? 2 : 1.2} />
            <circle cx="14" cy="16" r="4" fill={c} />
            <text x="24" y="20" fill="#78716C" fontSize="10" fontWeight="600">{n.type}</text>
            <text x="10" y="38" fill="#1C1917" fontSize="12" fontWeight="600">{n.name.slice(0, 18)}</text>
            {props.length > 0 && (
              <text x="10" y="48" fill="#A8A29E" fontSize="9" className="tnum">
                {props.map(([k, v]) => `${k} ${v}`).join(" · ").slice(0, 26)}
              </text>
            )}
            {direct.has(n.id) && <rect x="138" y="-6" width="12" height="12" rx="6" fill="#DC2626" />}
          </g>
          </g>
        );
      })}
    </svg>
  );
}
