/**
 * 图谱画布布局统一参数入口（力导向、层次种子、防重叠、节点尺寸映射）。
 * 调参时只改此处，避免散落魔法值。
 */

/** 默认节点外接正方形边长（与未按资料缩放时一致） */
export const NODE_DEFAULT_W = 140;
export const NODE_DEFAULT_H = 140;

/** 按关联资料条数映射外接正方形边长：直径约在 [88, 200] */
export const MATERIAL_BOX = {
  minSide: 88,
  maxSide: 200,
  base: 100,
  perLink: 14,
} as const;

/** Dagre 层次种子（紧一些，具体疏密由力导向决定） */
export const DAGRE_GRAPH = {
  rankdir: "TB" as const,
  nodesep: 22,
  ranksep: 32,
  marginx: 12,
  marginy: 12,
};

/** 力导向默认迭代与质心预缩放 */
export const FORCE_DEFAULT = {
  iterations: 520,
  /** 圆心相对质心缩放，收紧过散种子 */
  preScaleCenters: 0.52,
  repulsionBase: 280,
  /** 斥力分母阻尼，缓和近距离爆炸 */
  repulsionDistDamping: 1800,
  spring: 0.22,
  /** 非邻接碰撞与邻接软碰撞的额外间隙 */
  collisionPad: 3,
  adjacentCollisionFactor: 0.42,
  nonAdjacentCollisionFactor: 0.28,
  gravity: 0.014,
  stepMin: 0.055,
  stepRange: 0.14,
};

/** 防重叠迭代 */
export const OVERLAP_DEFAULT = {
  maxPasses: 100,
  /** removeNodeOverlaps 默认矩形 padding（无 sizes 时） */
  defaultPadding: 10,
  /** GraphWorkspace 传入的圆周边距 */
  canvasPadding: 4,
  overlapResolveBonus: 1,
};
