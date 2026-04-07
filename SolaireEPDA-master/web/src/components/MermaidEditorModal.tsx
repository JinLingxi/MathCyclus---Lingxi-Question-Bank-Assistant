import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import mermaid from "mermaid";
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";

import "@xyflow/react/dist/style.css";

import { FlowchartFlowNode } from "./FlowchartFlowNode";
import { initMermaid } from "../lib/mermaidInit";
import { serializeFlowchartFromFlow, tryParseFlowchartForReactFlow } from "../lib/mermaidFlowchart";

const DEFAULT_SOURCE = "flowchart TD\n  A[开始] --> B[结束]";

const nodeTypes = { flowchart: FlowchartFlowNode };

type MermaidEditorModalProps = {
  open: boolean;
  onClose: () => void;
  /** Full fenced block to insert, e.g. ```mermaid\n...\n```\n */
  onConfirm: (fencedBlock: string) => void;
};

function MermaidFlowInner({ onClose, onConfirm }: Pick<MermaidEditorModalProps, "onClose" | "onConfirm">) {
  const [source, setSource] = useState(DEFAULT_SOURCE);
  const previewRef = useRef<HTMLDivElement>(null);
  const flowDirRef = useRef<"TD" | "LR">("TD");
  const skipNextParse = useRef(false);
  const [flowDirUi, setFlowDirUi] = useState<"TD" | "LR">("TD");

  const parsed = useMemo(() => tryParseFlowchartForReactFlow(source), [source]);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(parsed?.nodes ?? []);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(parsed?.edges ?? []);

  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);
  useEffect(() => {
    edgesRef.current = edges;
  }, [edges]);

  useEffect(() => {
    if (skipNextParse.current) {
      skipNextParse.current = false;
      return;
    }
    const p = tryParseFlowchartForReactFlow(source);
    flowDirRef.current = p?.dir ?? "TD";
    setFlowDirUi(flowDirRef.current);
    if (p) {
      setNodes(
        p.nodes.map((n) => ({
          ...n,
          type: "flowchart",
          data: { ...(n.data as object), dir: flowDirRef.current },
        })),
      );
      setEdges(p.edges);
    }
  }, [source, setNodes, setEdges]);

  useEffect(() => {
    initMermaid();
    const id = `mmd-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    let cancelled = false;
    void (async () => {
      try {
        const { svg } = await mermaid.render(id, source);
        if (!cancelled && previewRef.current) {
          previewRef.current.innerHTML = svg;
        }
      } catch {
        if (previewRef.current) {
          previewRef.current.textContent = "预览无法渲染（仍可插入源码，导出 PDF 需本机安装 mmdr）";
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source]);

  const syncGraphToSource = useCallback(() => {
    skipNextParse.current = true;
    setSource(serializeFlowchartFromFlow(nodesRef.current, edgesRef.current, flowDirRef.current));
  }, []);

  const onConnect = useCallback((params: Connection) => {
    setEdges((eds) => {
      const next = addEdge({ ...params, id: `e${Date.now()}` }, eds);
      requestAnimationFrame(() => {
        skipNextParse.current = true;
        setSource(serializeFlowchartFromFlow(nodesRef.current, next, flowDirRef.current));
      });
      return next;
    });
  }, [setEdges]);

  const onNodeDragStop = useCallback(() => {
    requestAnimationFrame(() => {
      skipNextParse.current = true;
      setSource(serializeFlowchartFromFlow(nodesRef.current, edgesRef.current, flowDirRef.current));
    });
  }, []);

  const onNodesDelete = useCallback(() => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        skipNextParse.current = true;
        setSource(serializeFlowchartFromFlow(nodesRef.current, edgesRef.current, flowDirRef.current));
      });
    });
  }, []);

  const onEdgesDelete = useCallback(() => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        skipNextParse.current = true;
        setSource(serializeFlowchartFromFlow(nodesRef.current, edgesRef.current, flowDirRef.current));
      });
    });
  }, []);

  const addNode = useCallback(() => {
    const id = `n${Date.now().toString(36)}`;
    const dir = flowDirRef.current;
    setNodes((nds) => {
      const offset = nds.length * 48;
      const next: Node[] = [
        ...nds,
        {
          id,
          type: "flowchart",
          position: { x: 40 + offset, y: 40 + offset },
          data: { label: "新节点", dir },
        },
      ];
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          skipNextParse.current = true;
          setSource(serializeFlowchartFromFlow(next, edgesRef.current, dir));
        });
      });
      return next;
    });
  }, [setNodes]);

  const onNodeDoubleClick = useCallback((_e: React.MouseEvent, node: Node) => {
    const label = String((node.data as { label?: string }).label ?? "");
    const nextLabel = window.prompt("节点文字", label);
    if (nextLabel === null) {
      return;
    }
    setNodes((nds) =>
      nds.map((n) => (n.id === node.id ? { ...n, data: { ...n.data, label: nextLabel } } : n)),
    );
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        skipNextParse.current = true;
        setSource(serializeFlowchartFromFlow(nodesRef.current, edgesRef.current, flowDirRef.current));
      });
    });
  }, [setNodes]);

  const onDirChange = useCallback(
    (d: "TD" | "LR") => {
      flowDirRef.current = d;
      setFlowDirUi(d);
      setNodes((nds) =>
        nds.map((n) => ({
          ...n,
          data: { ...n.data, dir: d },
        })),
      );
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          skipNextParse.current = true;
          setSource(serializeFlowchartFromFlow(nodesRef.current, edgesRef.current, d));
        });
      });
    },
    [setNodes],
  );

  function handleInsert() {
    const block = "```mermaid\n" + source.trim() + "\n```\n";
    onConfirm(block);
    onClose();
  }

  const flowHint = parsed
    ? null
    : "当前文本不是可解析的简单 flowchart TD/LR；仍可在画布上拖拽添加节点与连线，或只编辑左侧源码。";

  return (
    <>
      <h3 id="mermaid-editor-title" className="text-sm font-semibold text-slate-800">
        Mermaid / 流程图
      </h3>
      <p className="mt-1 text-xs text-slate-500">
        左侧为源码；右侧为实时预览。下方画布可<strong>拖拽节点</strong>、<strong>从节点边缘拖线到另一节点</strong>
        连线、<strong>双击节点</strong>改文字、选中后按{" "}
        <kbd className="rounded bg-slate-100 px-1">Delete</kbd> 删除。插入后为 ```mermaid 围栏（导出 PDF 需本机 mmdr）。
      </p>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div>
          <p className="text-[11px] font-medium text-slate-600">源码</p>
          <textarea
            className="mt-1 h-48 w-full rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            spellCheck={false}
          />
          <button
            type="button"
            className="mt-2 rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50 disabled:opacity-40"
            onClick={syncGraphToSource}
          >
            从画布同步到源码
          </button>
        </div>
        <div>
          <p className="text-[11px] font-medium text-slate-600">实时预览（mermaid.js）</p>
          <div
            ref={previewRef}
            className="mt-1 flex min-h-[12rem] items-center justify-center overflow-auto rounded border border-slate-200 bg-slate-50 p-2 text-xs text-slate-500"
          />
        </div>
      </div>

      <div className="mt-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[11px] font-medium text-slate-600">画布（拖拽构建）</p>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1 text-[11px] text-slate-600">
              方向
              <select
                className="rounded border border-slate-300 px-1 py-0.5 text-[11px]"
                value={flowDirUi}
                onChange={(e) => onDirChange(e.target.value as "TD" | "LR")}
              >
                <option value="TD">上下 TD</option>
                <option value="LR">左右 LR</option>
              </select>
            </label>
            <button
              type="button"
              className="rounded border border-slate-600 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-800 hover:bg-slate-100"
              onClick={addNode}
            >
              添加节点
            </button>
            {flowHint && <span className="text-[10px] text-amber-700">{flowHint}</span>}
          </div>
        </div>
        <div className="mt-1 h-72 w-full rounded border border-slate-200">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeDragStop={onNodeDragStop}
            onNodesDelete={onNodesDelete}
            onEdgesDelete={onEdgesDelete}
            onNodeDoubleClick={onNodeDoubleClick}
            nodeTypes={nodeTypes}
            fitView
            nodesDraggable
            nodesConnectable
            elementsSelectable
            deleteKeyCode={["Backspace", "Delete"]}
          >
            <Background />
            <Controls />
          </ReactFlow>
        </div>
      </div>

      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          onClick={onClose}
        >
          取消
        </button>
        <button
          type="button"
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800"
          onClick={handleInsert}
        >
          插入到题目
        </button>
      </div>
    </>
  );
}

export function MermaidEditorModal({ open, onClose, onConfirm }: MermaidEditorModalProps) {
  const [reset, setReset] = useState(0);

  useEffect(() => {
    if (open) {
      setReset((k) => k + 1);
    }
  }, [open]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="mermaid-editor-title"
      onClick={onClose}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          onClose();
        }
      }}
    >
      <div
        className="max-h-[95vh] w-full max-w-4xl overflow-auto rounded-lg border border-slate-200 bg-white p-4 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <ReactFlowProvider key={reset}>
          <MermaidFlowInner onClose={onClose} onConfirm={onConfirm} />
        </ReactFlowProvider>
      </div>
    </div>
  );
}
