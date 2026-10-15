// Shared graph layout: layered DAG (BFS depth, centered per layer).
// Runs in a Web Worker (layout.worker.ts) so large graphs never block the
// main thread while panning. Falls back to inline execution when Worker is
// unavailable (SSR, tests).
export type LayoutNode = { id: string };
export type LayoutEdge = { source_node: string; target_node: string };

export type LayoutResult = { pos: Record<string, { x: number; y: number }>; w: number; h: number };

export function computeLayout(nodes: LayoutNode[], edges: LayoutEdge[]): LayoutResult {
  const ids = new Set(nodes.map(n => n.id));
  const indeg = new Map(nodes.map(n => [n.id, 0]));
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    if (!ids.has(e.source_node) || !ids.has(e.target_node)) continue;
    adj.set(e.source_node, [...(adj.get(e.source_node) || []), e.target_node]);
    indeg.set(e.target_node, (indeg.get(e.target_node) || 0) + 1);
  }
  const depth = new Map<string, number>();
  const seeds = nodes.filter(n => (indeg.get(n.id) || 0) === 0).map(n => n.id);
  if (seeds.length === 0 && nodes.length) seeds.push(nodes[0].id);
  seeds.forEach(id => depth.set(id, 0));
  const q = [...seeds];
  while (q.length) {
    const cur = q.shift()!;
    for (const nxt of adj.get(cur) || []) {
      const d = (depth.get(cur) || 0) + 1;
      if (d > (depth.get(nxt) ?? -1)) { depth.set(nxt, d); q.push(nxt); }
    }
  }
  nodes.forEach(n => { if (!depth.has(n.id)) depth.set(n.id, 0); });
  const layers = new Map<number, string[]>();
  for (const n of nodes) {
    const d = depth.get(n.id) || 0;
    layers.set(d, [...(layers.get(d) || []), n.id]);
  }
  const W = 220, H = 120, X0 = 60, Y0 = 60;
  const pos: Record<string, { x: number; y: number }> = {};
  let maxX = 640, maxY = 320;
  for (const [d, arr] of [...layers.entries()].sort((a, b) => a[0] - b[0])) {
    arr.forEach((id, i) => {
      const p = { x: X0 + d * W, y: Y0 + i * H };
      pos[id] = p;
      if (p.x + 220 > maxX) maxX = p.x + 220;
      if (p.y + 120 > maxY) maxY = p.y + 120;
    });
  }
  return { pos, w: maxX, h: maxY };
}
