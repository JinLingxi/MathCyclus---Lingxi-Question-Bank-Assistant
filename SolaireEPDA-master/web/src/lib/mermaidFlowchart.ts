import type { Edge, Node } from "@xyflow/react";

/** Minimal flowchart TD/LR parser for React Flow preview (subset). */
export function tryParseFlowchartForReactFlow(src: string): { nodes: Node[]; edges: Edge[]; dir: "TD" | "LR" } | null {
  const lines = src
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0 && !l.startsWith("%%"));
  if (lines.length === 0) {
    return null;
  }
  const h = lines[0].match(/^flowchart\s+(TD|LR|TB|RL|BT)$/i);
  if (!h) {
    return null;
  }
  const dir = h[1].toUpperCase();
  const flowDir: "TD" | "LR" = dir === "LR" || dir === "RL" ? "LR" : "TD";
  const nodeLabels = new Map<string, string>();

  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    const nm = line.match(/^(\w+)\s*(\[[^\]]+\]|\([^)]+\))/);
    if (nm) {
      const id = nm[1];
      const label = nm[2].slice(1, -1);
      nodeLabels.set(id, label);
    }
  }

  const edges: Edge[] = [];
  let eid = 0;
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    const em = line.match(/^(\w+)\s*-->\s*(?:\|([^|]*)\|)?\s*(\w+)\s*$/);
    if (em) {
      const [, a, label, b] = em;
      nodeLabels.set(a, nodeLabels.get(a) ?? a);
      nodeLabels.set(b, nodeLabels.get(b) ?? b);
      edges.push({
        id: `e${eid++}`,
        source: a,
        target: b,
        label: label?.trim() || undefined,
      });
    }
  }

  if (nodeLabels.size === 0 && edges.length === 0) {
    return null;
  }

  const ids = [...nodeLabels.keys()];
  for (const e of edges) {
    if (!nodeLabels.has(e.source)) {
      nodeLabels.set(e.source, e.source);
    }
    if (!nodeLabels.has(e.target)) {
      nodeLabels.set(e.target, e.target);
    }
  }
  const ordered = ids.length ? ids : [...new Set(edges.flatMap((e) => [e.source, e.target]))];

  const nodes: Node[] = [];
  const step = 160;
  let x = 0;
  let y = 0;
  for (const id of ordered) {
    const label = nodeLabels.get(id) ?? id;
    nodes.push({
      id,
      type: "flowchart",
      position: flowDir === "LR" ? { x, y } : { x, y },
      data: { label, dir: flowDir },
    });
    if (flowDir === "LR") {
      x += step;
    } else {
      y += step;
    }
  }

  return { nodes, edges, dir: flowDir };
}

export function serializeFlowchartFromFlow(
  nodes: Node[],
  edges: Edge[],
  dir: "TD" | "LR",
): string {
  const lines = [`flowchart ${dir}`];
  for (const n of nodes) {
    const label = String((n.data as { label?: string })?.label ?? n.id);
    lines.push(`  ${n.id}[${label}]`);
  }
  for (const e of edges) {
    const mid = e.label ? `|${e.label}|` : "";
    lines.push(`  ${e.source} -->${mid} ${e.target}`);
  }
  return lines.join("\n");
}
