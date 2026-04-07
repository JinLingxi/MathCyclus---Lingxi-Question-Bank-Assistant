import { Handle, Position, type NodeProps } from "@xyflow/react";

/** React Flow node with draggable connection handles (TD: top/bottom, LR: left/right). */
export function FlowchartFlowNode({ data }: NodeProps) {
  const dir = (data as { dir?: "TD" | "LR" }).dir ?? "TD";
  const isLR = dir === "LR";
  const label = String((data as { label?: string }).label ?? "");

  return (
    <div className="min-w-[4rem] max-w-[12rem] rounded border border-slate-400 bg-white px-2 py-1.5 text-center text-xs shadow-sm">
      <Handle
        type="target"
        position={isLR ? Position.Left : Position.Top}
        className="!h-2 !w-2 !border border-slate-400 !bg-slate-200"
      />
      <div className="break-words text-slate-800">{label}</div>
      <Handle
        type="source"
        position={isLR ? Position.Right : Position.Bottom}
        className="!h-2 !w-2 !border border-slate-400 !bg-slate-200"
      />
    </div>
  );
}
