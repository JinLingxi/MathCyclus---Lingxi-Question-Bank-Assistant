import { BaseEdge, type EdgeProps, useReactFlow } from "@xyflow/react";
import { memo } from "react";
import { NODE_DEFAULT_W } from "./layoutParams";

/** 圆形节点：连线沿两圆心方向，从圆周起止（边到边），与圆心共线 */
function CircleChordEdgeImpl({
  id,
  source,
  target,
  sourceX,
  sourceY,
  targetX,
  targetY,
  label,
  labelStyle,
  labelShowBg,
  labelBgStyle,
  labelBgPadding,
  labelBgBorderRadius,
  style,
  markerEnd,
  markerStart,
  interactionWidth,
}: EdgeProps) {
  const { getNode } = useReactFlow();
  const sn = getNode(source);
  const tn = getNode(target);
  const fallback = NODE_DEFAULT_W;
  const box = (n: typeof sn) => {
    const px = (n?.data as { sizePx?: number } | undefined)?.sizePx;
    if (typeof px === "number" && px > 0) return { w: px, h: px };
    const w = n?.width ?? n?.measured?.width ?? fallback;
    const h = n?.height ?? n?.measured?.height ?? fallback;
    return { w, h };
  };
  const { w: sw, h: sh } = box(sn);
  const { w: tw, h: th } = box(tn);
  const sr = Math.min(sw, sh) / 2;
  const tr = Math.min(tw, th) / 2;

  let dx = targetX - sourceX;
  let dy = targetY - sourceY;
  const len = Math.hypot(dx, dy);
  let path: string;
  let labelX: number;
  let labelY: number;
  if (len < 0.5) {
    path = `M ${sourceX},${sourceY} L ${targetX},${targetY}`;
    labelX = (sourceX + targetX) / 2;
    labelY = (sourceY + targetY) / 2;
  } else {
    dx /= len;
    dy /= len;
    /** 圆心极近或圆重叠时，限制沿法向伸出长度，避免路径越过对侧或数值反转 */
    const seg = Math.max(len, 0.5);
    const effS = Math.min(sr, seg * 0.48);
    const effT = Math.min(tr, seg * 0.48);
    const x1 = sourceX + dx * effS;
    const y1 = sourceY + dy * effS;
    const x2 = targetX - dx * effT;
    const y2 = targetY - dy * effT;
    path = `M ${x1},${y1} L ${x2},${y2}`;
    labelX = (x1 + x2) / 2;
    labelY = (y1 + y2) / 2;
  }

  return (
    <BaseEdge
      id={id}
      path={path}
      labelX={labelX}
      labelY={labelY}
      label={label}
      labelStyle={labelStyle}
      labelShowBg={labelShowBg}
      labelBgStyle={labelBgStyle}
      labelBgPadding={labelBgPadding}
      labelBgBorderRadius={labelBgBorderRadius}
      style={style}
      markerEnd={markerEnd}
      markerStart={markerStart}
      interactionWidth={interactionWidth}
    />
  );
}

export const CircleChordEdge = memo(CircleChordEdgeImpl);
