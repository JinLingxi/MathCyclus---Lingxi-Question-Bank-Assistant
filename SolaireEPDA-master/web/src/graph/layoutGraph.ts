import dagre from "dagre";
import type { Edge, Node } from "@xyflow/react";
import {
  DAGRE_GRAPH,
  FORCE_DEFAULT,
  MATERIAL_BOX,
  NODE_DEFAULT_H,
  NODE_DEFAULT_W,
  OVERLAP_DEFAULT,
} from "./layoutParams";

/** 圆形节点外接正方形边长（与画布节点一致） */
export const NODE_W = NODE_DEFAULT_W;
export const NODE_H = NODE_DEFAULT_H;

/** 根据关联资料数量映射为节点外接正方形边长（圆形直径）。 */
export function nodeBoxSizeFromMaterialCount(materialCount: number): { w: number; h: number } {
  const c = Math.max(0, Math.floor(materialCount));
  const { minSide, maxSide, base, perLink } = MATERIAL_BOX;
  const s = Math.round(Math.max(minSide, Math.min(maxSide, base + c * perLink)));
  return { w: s, h: s };
}

/** 对知识点节点做层次布局；可与已保存坐标合并。 */
export function layoutWithDagre(
  nodes: Node[],
  edges: Edge[],
  sizes?: Map<string, { w: number; h: number }>,
): Node[] {
  if (nodes.length === 0) return nodes;
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: DAGRE_GRAPH.rankdir,
    nodesep: DAGRE_GRAPH.nodesep,
    ranksep: DAGRE_GRAPH.ranksep,
    marginx: DAGRE_GRAPH.marginx,
    marginy: DAGRE_GRAPH.marginy,
  });
  nodes.forEach((n) => {
    const s = sizes?.get(n.id);
    const w = s?.w ?? NODE_W;
    const h = s?.h ?? NODE_H;
    g.setNode(n.id, { width: w, height: h });
  });
  edges.forEach((e) => {
    g.setEdge(e.source, e.target);
  });
  dagre.layout(g);
  return nodes.map((n) => {
    const pos = g.node(n.id);
    if (!pos) return n;
    const s = sizes?.get(n.id);
    const w = s?.w ?? NODE_W;
    const h = s?.h ?? NODE_H;
    return {
      ...n,
      position: {
        x: pos.x - w / 2,
        y: pos.y - h / 2,
      },
    };
  });
}

export function mergeSavedLayout(nodes: Node[], saved: Map<string, { x: number; y: number }>): Node[] {
  return nodes.map((n) => {
    const s = saved.get(n.id);
    if (!s) return n;
    return { ...n, position: { x: s.x, y: s.y } };
  });
}

function rectsOverlapSized(
  ax: number,
  ay: number,
  aw: number,
  ah: number,
  bx: number,
  by: number,
  bw: number,
  bh: number,
  pad: number,
): boolean {
  return !(ax + aw + pad <= bx || bx + bw + pad <= ax || ay + ah + pad <= by || by + bh + pad <= ay);
}

/**
 * 包围盒碰撞分离：迭代推开重叠节点，保证视觉不重叠。
 */
export function removeNodeOverlaps(
  nodes: Node[],
  width = NODE_W,
  height = NODE_H,
  padding = OVERLAP_DEFAULT.defaultPadding,
  maxPasses = OVERLAP_DEFAULT.maxPasses,
  sizes?: Map<string, { w: number; h: number }>,
): Node[] {
  if (nodes.length <= 1) return nodes;
  const positions = nodes.map((n) => ({ x: n.position.x, y: n.position.y }));
  const getBox = (i: number) => {
    const s = sizes?.get(nodes[i].id);
    const w = s?.w ?? width;
    const h = s?.h ?? height;
    return { w, h };
  };
  for (let pass = 0; pass < maxPasses; pass++) {
    let changed = false;
    for (let i = 0; i < positions.length; i++) {
      for (let j = i + 1; j < positions.length; j++) {
        const a = positions[i];
        const b = positions[j];
        const { w: aw, h: ah } = getBox(i);
        const { w: bw, h: bh } = getBox(j);
        if (!rectsOverlapSized(a.x, a.y, aw, ah, b.x, b.y, bw, bh, padding)) continue;
        const cx = a.x + aw / 2;
        const cy = a.y + ah / 2;
        const cx2 = b.x + bw / 2;
        const cy2 = b.y + bh / 2;
        let dx = cx2 - cx;
        let dy = cy2 - cy;
        const dist = Math.hypot(dx, dy) || 0.001;
        /** 与圆形节点一致：两圆不相交的最小圆心距，勿用对角线式 hypot 以免推得过散 */
        const ri = Math.min(aw, ah) / 2;
        const rj = Math.min(bw, bh) / 2;
        const minCenterDist = ri + rj + padding;
        const need = Math.max(0, minCenterDist - dist) + OVERLAP_DEFAULT.overlapResolveBonus;
        dx = (dx / dist) * (need / 2);
        dy = (dy / dist) * (need / 2);
        a.x -= dx;
        a.y -= dy;
        b.x += dx;
        b.y += dy;
        changed = true;
      }
    }
    if (!changed) break;
  }
  return nodes.map((n, i) => ({
    ...n,
    position: positions[i],
  }));
}

export type ForceLayoutOptions = {
  iterations?: number;
  /** 初始位置（左上坐标），用于热启动 */
  seed?: Map<string, { x: number; y: number }>;
  /** 节点外接矩形尺寸；用于斥力/弹簧与防重叠 */
  sizes?: Map<string, { w: number; h: number }>;
  /**
   * 将圆心相对质心缩放（0~1），收紧 dagre 等给出的过散种子，再进入迭代。
   * 全图过松时必用；默认约 0.52。
   */
  preScaleCenters?: number;
};

/** 与画布圆形一致：内接于正方形，半径 = 边长的一半（不可用 hypot/2，否则会大 √2 倍） */
function nodeRadius(nodeId: string, sizes: Map<string, { w: number; h: number }> | undefined): number {
  const s = sizes?.get(nodeId);
  const w = s?.w ?? NODE_W;
  const h = s?.h ?? NODE_H;
  return Math.min(w, h) / 2;
}

/**
 * 弹簧-电荷力导向：边为弹簧（远则拉近、近则推回理想长度），节点间库仑斥力，弱质心引力，迭代至近似平衡。
 */
export function layoutWithForceDirected(
  nodes: Node[],
  edges: Edge[],
  opts?: ForceLayoutOptions,
): Node[] {
  const iterations = opts?.iterations ?? FORCE_DEFAULT.iterations;
  const sizes = opts?.sizes;
  const n = nodes.length;
  if (n === 0) return nodes;

  const idToIdx = new Map<string, number>();
  nodes.forEach((node, i) => idToIdx.set(node.id, i));

  const halfW = nodes.map((node) => (sizes?.get(node.id)?.w ?? NODE_W) / 2);
  const halfH = nodes.map((node) => (sizes?.get(node.id)?.h ?? NODE_H) / 2);

  /** 圆心坐标（力学一律在圆心空间计算，避免把左上角间距当成圆心距） */
  const cx = nodes.map((node, i) => {
    const s = opts?.seed?.get(node.id);
    const tlX = s ? s.x : node.position.x;
    return tlX + halfW[i];
  });
  const cy = nodes.map((node, i) => {
    const s = opts?.seed?.get(node.id);
    const tlY = s ? s.y : node.position.y;
    return tlY + halfH[i];
  });

  const preScale = opts?.preScaleCenters ?? FORCE_DEFAULT.preScaleCenters;
  if (n > 1 && preScale > 0 && preScale < 1) {
    let mx = 0;
    let my = 0;
    for (let i = 0; i < n; i++) {
      mx += cx[i];
      my += cy[i];
    }
    mx /= n;
    my /= n;
    for (let i = 0; i < n; i++) {
      cx[i] = mx + (cx[i] - mx) * preScale;
      cy[i] = my + (cy[i] - my) * preScale;
    }
  }

  const radii = nodes.map((node) => nodeRadius(node.id, sizes));

  const edgeIdxs: { si: number; ti: number }[] = [];
  for (const e of edges) {
    const si = idToIdx.get(e.source);
    const ti = idToIdx.get(e.target);
    if (si !== undefined && ti !== undefined && si !== ti) {
      edgeIdxs.push({ si, ti });
    }
  }

  /** 有边相连的节点对：仅用弹簧定距，避免斥力把相邻节点再推开 */
  const adjacentPair = new Set<string>();
  for (const { si, ti } of edgeIdxs) {
    const a = Math.min(si, ti);
    const b = Math.max(si, ti);
    adjacentPair.add(`${a},${b}`);
  }

  const repulsionBase = FORCE_DEFAULT.repulsionBase;
  const spring = FORCE_DEFAULT.spring;
  const pad = FORCE_DEFAULT.collisionPad;
  const repDamp = FORCE_DEFAULT.repulsionDistDamping;

  for (let iter = 0; iter < iterations; iter++) {
    const fx = new Float64Array(n);
    const fy = new Float64Array(n);

    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = cx[j] - cx[i];
        let dy = cy[j] - cy[i];
        let distSq = dx * dx + dy * dy;
        if (distSq < 4) distSq = 4;
        const dist = Math.sqrt(distSq);
        const ri = radii[i];
        const rj = radii[j];
        const pairKey = `${i},${j}`;
        const isAdjacent = adjacentPair.has(pairKey);

        if (!isAdjacent) {
          /** 1/dist^2 在远距离过弱、近距离过强；加阻尼项使中距离斥力更可控 */
          const rep = (repulsionBase * ri * rj) / (distSq + repDamp);
          const rx = (dx / dist) * rep;
          const ry = (dy / dist) * rep;
          fx[i] -= rx;
          fy[i] -= ry;
          fx[j] += rx;
          fy[j] += ry;
        }

        const minD = ri + rj + pad;
        if (dist < minD && dist > 0.001) {
          const push =
            (minD - dist) *
            (isAdjacent ? FORCE_DEFAULT.adjacentCollisionFactor : FORCE_DEFAULT.nonAdjacentCollisionFactor);
          const ux = dx / dist;
          const uy = dy / dist;
          fx[i] -= ux * push;
          fy[i] -= uy * push;
          fx[j] += ux * push;
          fy[j] += uy * push;
        }
      }
    }

    for (const { si, ti } of edgeIdxs) {
      let dx = cx[ti] - cx[si];
      let dy = cy[ti] - cy[si];
      const dist = Math.hypot(dx, dy) || 0.01;
      const rs = radii[si];
      const rt = radii[ti];
      /** 相邻两圆边到边间距 = 较小圆直径 ⇒ 圆心距 = r_s + r_t + min(d_s, d_t) */
      const ideal = rs + rt + 2 * Math.min(rs, rt);
      const f = spring * (dist - ideal);
      dx = (dx / dist) * f;
      dy = (dy / dist) * f;
      fx[si] += dx;
      fy[si] += dy;
      fx[ti] -= dx;
      fy[ti] -= dy;
    }

    let mx = 0;
    let my = 0;
    for (let i = 0; i < n; i++) {
      mx += cx[i];
      my += cy[i];
    }
    mx /= n;
    my /= n;
    const gravity = FORCE_DEFAULT.gravity;
    for (let i = 0; i < n; i++) {
      fx[i] -= (cx[i] - mx) * gravity;
      fy[i] -= (cy[i] - my) * gravity;
    }

    const t = 1 - iter / iterations;
    const step = FORCE_DEFAULT.stepMin + t * FORCE_DEFAULT.stepRange;
    for (let i = 0; i < n; i++) {
      cx[i] += fx[i] * step;
      cy[i] += fy[i] * step;
    }
  }

  return nodes.map((node, i) => ({
    ...node,
    position: { x: cx[i] - halfW[i], y: cy[i] - halfH[i] },
  }));
}

/**
 * 圆周边到边连线（类型 `circleChord`），几何由 CircleChordEdge 根据圆心共线计算。
 * Handle 仍在圆心，便于布局引擎；实际绘制从圆周起止。
 */
export function assignStraightEdges(edges: Edge[]): Edge[] {
  return edges.map(
    (e) =>
      ({
        ...e,
        type: "circleChord" as const,
        sourceHandle: "s",
        targetHandle: "t",
      }) as Edge,
  );
}
