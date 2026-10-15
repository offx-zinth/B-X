"use client";
import { useEffect, useRef } from "react";
import type { XNode } from "../lib/api";
import { computeLayout } from "../lib/layout";

type Edge = { id: string; source_node: string; target_node: string; type: string };
type SigmaHandle = { kill: () => void; on: (ev: string, cb: (a: any) => void) => void; refresh: () => void };
type GraphHandle = {
  addNode: (id: string, attrs: Record<string, unknown>) => void;
  addEdge: (s: string, t: string, attrs: Record<string, unknown>) => void;
  hasNode: (id: string) => boolean;
  hasEdge: (s: string, t: string) => boolean;
  setNodeAttribute: (id: string, key: string, value: unknown) => void;
};

/** WebGL renderer (Sigma.js + graphology) for very large graphs (>2,000
 * nodes), where Canvas2D culling still spends per-frame time on edge loops.
 * Loaded dynamically by the workspace so the core bundle stays small.
 * Layout reuses the shared layered DAG positions (computed in a Web Worker
 * upstream) instead of a force simulation, keeping views deterministic.
 */
export default function GraphSigma({ nodes, edges, selected, onSelect }: {
  nodes: XNode[]; edges: Edge[]; selected: XNode | null; onSelect: (n: XNode) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const graphRef = useRef<GraphHandle | null>(null);
  const rendererRef = useRef<SigmaHandle | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [{ default: Graph }, { default: Sigma }] = await Promise.all([
        import("graphology"),
        import("sigma"),
      ]);
      if (cancelled || !ref.current) return;
      const lay = computeLayout(nodes.map(n => ({ id: n.id })), edges);
      const g = new Graph({ multi: true }) as unknown as GraphHandle & { forEachNode: (cb: (id: string) => void) => void };
      for (const n of nodes) {
        const p = lay.pos[n.id] || { x: 0, y: 0 };
        g.addNode(n.id, { x: p.x, y: p.y, size: 6, label: n.name,
          color: selected?.id === n.id ? "#047857" : "#0f766e" });
      }
      for (const e of edges) {
        if (!g.hasNode(e.source_node) || !g.hasNode(e.target_node)) continue;
        if (g.hasEdge(e.source_node, e.target_node)) continue;
        g.addEdge(e.source_node, e.target_node, { size: 1, color: "#D6D3D1" });
      }
      const renderer = new Sigma(g as any, ref.current!, {
        renderEdgeLabels: false, labelDensity: 0.04, labelRenderedSizeThreshold: 7,
      }) as unknown as SigmaHandle;
      renderer.on("clickNode", ({ node }: { node: string }) => {
        const hit = nodes.find(n => n.id === node);
        if (hit) onSelectRef.current(hit);
      });
      graphRef.current = g;
      rendererRef.current = renderer;
    })().catch(() => null);
    return () => {
      cancelled = true;
      rendererRef.current?.kill();
      rendererRef.current = null;
      graphRef.current = null;
    };
  }, [nodes, edges]);

  // Selection highlight without rebuilding the renderer.
  useEffect(() => {
    const g = graphRef.current;
    if (!g) return;
    try {
      for (const n of nodes) {
        g.setNodeAttribute(n.id, "color", selected?.id === n.id ? "#047857" : "#0f766e");
        g.setNodeAttribute(n.id, "size", selected?.id === n.id ? 9 : 6);
      }
      rendererRef.current?.refresh();
    } catch { /* node set changed mid-flight; next build effect resets */ }
  }, [selected, nodes]);

  return (
    <div ref={ref} className="h-full w-full" role="img"
      aria-label={`Business graph, ${nodes.length} nodes (WebGL virtualized)`} />
  );
}
