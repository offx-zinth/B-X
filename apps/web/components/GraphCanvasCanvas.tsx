"use client";
import { useEffect, useRef, useState } from "react";
import type { XNode } from "../lib/api";
import { computeLayout, type LayoutResult } from "../lib/layout";

type Edge = { id: string; source_node: string; target_node: string; type: string };

/** Canvas2D viewport renderer for large graphs (>300 nodes).
 * Same layered DAG layout as GraphCanvas, but with node culling (only
 * viewport-visible nodes/edges draw) and pan/zoom transforms, so 1,500+
 * nodes pan at 60fps without O(N) DOM nodes. Layout runs in a Web Worker
 * (falls back inline when Worker is unavailable, e.g. SSR/tests).
 */
export default function GraphCanvasCanvas({ nodes, edges, selected, onSelect }: {
  nodes: XNode[]; edges: Edge[]; selected: XNode | null; onSelect: (n: XNode) => void;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ sx: number; sy: number; vx: number; vy: number } | null>(null);
  const [layout, setLayout] = useState<{ pos: Map<string, { x: number; y: number }> }>(() => ({
    pos: new Map(Object.entries(computeLayout(nodes.map(n => ({ id: n.id })), edges).pos)),
  }));

  useEffect(() => {
    let worker: Worker | null = null;
    let cancelled = false;
    const apply = (r: LayoutResult) => {
      if (!cancelled) setLayout({ pos: new Map(Object.entries(r.pos)) });
    };
    try {
      worker = new Worker(new URL("../lib/layout.worker.ts", import.meta.url));
      worker.onmessage = ev => { if (ev.data?.layout) apply(ev.data.layout); };
      worker.onerror = () => apply(computeLayout(nodes.map(n => ({ id: n.id })), edges));
      worker.postMessage({ nodes: nodes.map(n => ({ id: n.id })), edges });
    } catch {
      apply(computeLayout(nodes.map(n => ({ id: n.id })), edges));
    }
    return () => { cancelled = true; worker?.terminate(); };
  }, [nodes, edges]);

  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = cv.getBoundingClientRect();
    cv.width = rect.width * dpr;
    cv.height = rect.height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    const vw = { x0: -view.x / view.k, y0: -view.y / view.k, x1: (rect.width - view.x) / view.k, y1: (rect.height - view.y) / view.k };
    ctx.save();
    ctx.translate(view.x, view.y);
    ctx.scale(view.k, view.k);
    // Edges first (culled)
    ctx.lineWidth = 1.2 / view.k + 0.4;
    for (const e of edges) {
      const a = layout.pos.get(e.source_node), b = layout.pos.get(e.target_node);
      if (!a || !b) continue;
      if (b.x < vw.x0 - 200 || a.x > vw.x1 + 200 || a.y < vw.y0 - 200 || a.y > vw.y1 + 200) continue;
      ctx.strokeStyle = "#D6D3D1";
      ctx.beginPath();
      ctx.moveTo(a.x + 150, a.y + 26);
      ctx.bezierCurveTo((a.x + b.x) / 2, a.y + 26, (a.x + b.x) / 2, b.y + 26, b.x, b.y + 26);
      ctx.stroke();
    }
    // Nodes (culled)
    for (const n of nodes) {
      const p = layout.pos.get(n.id);
      if (!p) continue;
      if (p.x < vw.x0 - 200 || p.x > vw.x1 + 200 || p.y < vw.y0 - 200 || p.y > vw.y1 + 200) continue;
      const isSel = selected?.id === n.id;
      ctx.fillStyle = isSel ? "#ECFDF5" : "#FFFFFF";
      ctx.strokeStyle = isSel ? "#047857" : "#E7E5E4";
      ctx.lineWidth = isSel ? 2 : 1.2;
      ctx.beginPath();
      (ctx as any).roundRect?.(p.x, p.y, 150, 52, 12) ?? ctx.rect(p.x, p.y, 150, 52);
      ctx.fill(); ctx.stroke();
      ctx.fillStyle = "#1C1917";
      ctx.font = "600 12px sans-serif";
      ctx.fillText(n.name.slice(0, 18), p.x + 10, p.y + 38);
      ctx.fillStyle = "#78716C";
      ctx.font = "600 10px sans-serif";
      ctx.fillText(n.type, p.x + 24, p.y + 20);
    }
    ctx.restore();
  }, [nodes, edges, layout, view, selected]);

  function toWorld(ev: React.MouseEvent) {
    const cv = ref.current!;
    const r = cv.getBoundingClientRect();
    return { x: (ev.clientX - r.left - view.x) / view.k, y: (ev.clientY - r.top - view.y) / view.k };
  }

  return (
    <canvas
      ref={ref}
      className="h-full w-full cursor-grab active:cursor-grabbing"
      role="img"
      aria-label={`Business graph, ${nodes.length} nodes (canvas virtualized)`}
      onWheel={e => {
        const k = Math.min(2.5, Math.max(0.4, view.k * (e.deltaY < 0 ? 1.1 : 0.9)));
        setView(v => ({ ...v, k }));
      }}
      onMouseDown={e => { drag.current = { sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y }; }}
      onMouseMove={e => {
        if (!drag.current) return;
        setView(v => ({ ...v, x: drag.current!.vx + (e.clientX - drag.current!.sx), y: drag.current!.vy + (e.clientY - drag.current!.sy) }));
      }}
      onMouseUp={e => {
        const moved = drag.current && Math.hypot(e.clientX - drag.current.sx, e.clientY - drag.current.sy) > 4;
        drag.current = null;
        if (moved) return;
        const w = toWorld(e);
        const hit = nodes.find(n => {
          const p = layout.pos.get(n.id);
          return p && w.x >= p.x && w.x <= p.x + 150 && w.y >= p.y && w.y <= p.y + 52;
        });
        if (hit) onSelect(hit);
      }}
      onMouseLeave={() => { drag.current = null; }}
    />
  );
}
