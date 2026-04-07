import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ConnectionLineType,
  type Edge,
  type Node,
  type NodeProps,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  apiBankItems,
  apiGraphAttachFile,
  apiGraphBindBatch,
  apiGraphCreateNode,
  apiGraphCreateRelation,
  apiGraphDeleteNode,
  apiGraphDeleteRelation,
  apiGraphDetachFile,
  apiGraphGetTaxonomy,
  apiGraphListNodeFiles,
  apiGraphListNodes,
  apiGraphListQuestionsForNode,
  apiGraphListRelations,
  apiGraphListResourceFiles,
  apiGraphPutTaxonomy,
  apiGraphUnbindBatch,
  apiGraphUnbindBinding,
  apiGraphUpdateNode,
  apiGraphUploadMaterial,
  resourceApiUrl,
} from "../api/client";
import { CircleChordEdge } from "../graph/CircleChordEdge";
import {
  assignStraightEdges,
  layoutWithDagre,
  layoutWithForceDirected,
  mergeSavedLayout,
  nodeBoxSizeFromMaterialCount,
  removeNodeOverlaps,
} from "../graph/layoutGraph";
import { DAGRE_GRAPH, FORCE_DEFAULT, MATERIAL_BOX, OVERLAP_DEFAULT } from "../graph/layoutParams";
import { useAgentContext } from "../contexts/AgentContext";
import i18n from "../i18n/i18n";
import { localeCompareStrings } from "../lib/locale";
import { QUESTION_TYPE_OPTIONS } from "../lib/questionTypes";
import { cn } from "../lib/utils";
import { useTranslation } from "react-i18next";

type GraphNodeRow = {
  id: string;
  canonical_name: string;
  node_kind?: string;
  subject?: string | null;
  level?: string | null;
  description?: string | null;
  aliases?: string[];
  tags?: string[];
  layout_x?: number | null;
  layout_y?: number | null;
  /** 关联资料条数，用于画布节点大小 */
  file_link_count?: number;
};

type GraphRelationRow = {
  id: string;
  from_node_id: string;
  to_node_id: string;
  relation_type: string;
};

type BoundQuestion = {
  qualified_id: string;
  type: string;
  content_preview: string;
};

const REL_KEYS = ["prerequisite", "part_of", "related", "causal"] as const;

const REL_COLOR: Record<string, string> = {
  prerequisite: "#2563eb",
  part_of: "#64748b",
  related: "#059669",
  causal: "#c2410c",
};

/** 画布学科筛选：节点未填学科时的内部分组键（勿与真实学科名冲突） */
const SUBJECT_FILTER_UNSET = "__unset_subject__";

function graphSubjectFilterKey(n: Pick<GraphNodeRow, "subject">): string {
  const s = (n.subject ?? "").trim();
  return s ? s : SUBJECT_FILTER_UNSET;
}

function subjectFilterCheckboxLabel(key: string, unsetLabel: string): string {
  return key === SUBJECT_FILTER_UNSET ? unsetLabel : key;
}

/** 无向图上从中心出发的 k 步邻域（用于焦点降噪） */
function computeKHopNodes(
  centerId: string | null,
  hops: 0 | 1 | 2,
  edgePairs: { from_node_id: string; to_node_id: string }[],
): Set<string> | null {
  if (!centerId || hops === 0) return null;
  const adj = new Map<string, string[]>();
  for (const e of edgePairs) {
    const s = e.from_node_id;
    const t = e.to_node_id;
    if (!adj.has(s)) adj.set(s, []);
    if (!adj.has(t)) adj.set(t, []);
    adj.get(s)!.push(t);
    adj.get(t)!.push(s);
  }
  const dist = new Map<string, number>();
  const q: string[] = [centerId];
  dist.set(centerId, 0);
  while (q.length) {
    const u = q.shift()!;
    const d = dist.get(u)!;
    if (d >= hops) continue;
    for (const v of adj.get(u) ?? []) {
      if (!dist.has(v)) {
        dist.set(v, d + 1);
        q.push(v);
      }
    }
  }
  return new Set(dist.keys());
}

function KnowledgeNode({ data, selected }: NodeProps) {
  const kind = String(data.nodeKind ?? "concept");
  const dim = Boolean((data as { focusDimmed?: boolean }).focusDimmed);
  const sizePx = typeof (data as { sizePx?: number }).sizePx === "number" ? (data as { sizePx: number }).sizePx : 140;
  const pad = Math.max(8, Math.round(sizePx * 0.06));
  const kindCls =
    kind === "skill"
      ? "border-violet-300 bg-violet-50"
      : kind === "causal"
        ? "border-amber-300 bg-amber-50"
        : "border-slate-200 bg-white";
  return (
    <div
      className={cn(
        "relative flex shrink-0 flex-col items-center justify-center gap-1 rounded-full border text-center shadow-sm transition-opacity",
        kindCls,
        selected ? "ring-2 ring-slate-900 ring-offset-1" : "",
        dim ? "opacity-[0.2]" : "opacity-100",
      )}
      style={{
        width: sizePx,
        height: sizePx,
        minWidth: sizePx,
        minHeight: sizePx,
        maxWidth: sizePx,
        maxHeight: sizePx,
        padding: `${pad}px`,
      }}
    >
      <Handle
        type="target"
        id="t"
        position={Position.Top}
        isConnectable={false}
        className="nodrag nopan !h-px !w-px !min-w-0 !border-0 !bg-transparent !opacity-0"
        style={{ left: "50%", top: "50%", transform: "translate(-50%, -50%)" }}
      />
      <span
        className={cn(
          "rounded-full px-2 py-0.5 text-[10px] font-medium leading-none",
          kind === "skill" ? "bg-violet-200 text-violet-900" : kind === "causal" ? "bg-amber-200 text-amber-900" : "bg-slate-200 text-slate-800",
        )}
      >
        {i18n.t(`nodeKind.${kind}`, { ns: "graph", defaultValue: kind })}
      </span>
      <div className="line-clamp-3 w-full max-w-[min(92%,11rem)] text-xs font-semibold leading-snug text-slate-900">
        {String(data.label ?? "")}
      </div>
      <Handle
        type="source"
        id="s"
        position={Position.Bottom}
        isConnectable={false}
        className="nodrag nopan !h-px !w-px !min-w-0 !border-0 !bg-transparent !opacity-0"
        style={{ left: "50%", top: "50%", transform: "translate(-50%, -50%)" }}
      />
    </div>
  );
}

const nodeTypes = { knowledge: KnowledgeNode };
const edgeTypes = { circleChord: CircleChordEdge };

function splitCsv(s: string): string[] {
  return s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

export function GraphWorkspace({
  onError,
  focusNodeId = null,
  onFocusConsumed,
}: {
  onError: (s: string | null) => void;
  focusNodeId?: string | null;
  onFocusConsumed?: () => void;
}) {
  const { t } = useTranslation(["graph", "lib", "common"]);
  const [graphNodes, setGraphNodes] = useState<GraphNodeRow[]>([]);
  const [relations, setRelations] = useState<GraphRelationRow[]>([]);
  const [subjects, setSubjects] = useState<string[]>([]);
  const [levels, setLevels] = useState<string[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [draftName, setDraftName] = useState("");
  const [draftSubject, setDraftSubject] = useState("");
  const [draftLevel, setDraftLevel] = useState("");
  const [draftDesc, setDraftDesc] = useState("");
  const [draftTags, setDraftTags] = useState("");
  const [draftAliases, setDraftAliases] = useState("");
  const [draftKind, setDraftKind] = useState<"concept" | "skill" | "causal">("concept");

  const [kindCounts, setKindCounts] = useState<Record<string, number>>({});

  const [newParent, setNewParent] = useState("");
  const [newName, setNewName] = useState("");
  const [newSubject, setNewSubject] = useState("");
  const [newLevel, setNewLevel] = useState("");
  const [newNodeKind, setNewNodeKind] = useState<"concept" | "skill" | "causal">("concept");

  const [relTo, setRelTo] = useState("");
  const [relType, setRelType] = useState("related");

  const [bankOpen, setBankOpen] = useState(false);
  const [bankItems, setBankItems] = useState<any[]>([]);
  const [bankNs, setBankNs] = useState("");
  const [bankQ, setBankQ] = useState("");
  const [bankSubject, setBankSubject] = useState("");
  const [bankType, setBankType] = useState("");
  const [bankSel, setBankSel] = useState<Set<string>>(() => new Set());

  const [fileOpen, setFileOpen] = useState(false);
  const [fileQ, setFileQ] = useState("");
  const [fileList, setFileList] = useState<{ path: string; size: number }[]>([]);
  const [fileSel, setFileSel] = useState<Set<string>>(() => new Set());
  const [nodeFiles, setNodeFiles] = useState<{ id: string; relative_path: string }[]>([]);

  const [boundQuestions, setBoundQuestions] = useState<BoundQuestion[]>([]);
  const [boundSel, setBoundSel] = useState<Set<string>>(() => new Set());

  const [layoutNonce, setLayoutNonce] = useState(0);
  const [focusHops, setFocusHops] = useState<0 | 1 | 2>(0);
  /** 邻域聚焦的几何中心（与右侧编辑选中分离；仅通过「重新聚焦」或首次开启聚焦时设定） */
  const [focusCenterId, setFocusCenterId] = useState<string | null>(null);
  const [awaitingFocusPick, setAwaitingFocusPick] = useState(false);
  /** 非聚焦视图首次进入本页时做一次力导向，之后仅「重新整理」或聚焦模式会再算力导向 */
  const nonFocusForceBootstrappedRef = useRef(false);
  const [relTypeFilter, setRelTypeFilter] = useState<Record<string, boolean>>(() => {
    const o: Record<string, boolean> = {};
    for (const k of REL_KEYS) o[k as string] = true;
    return o;
  });
  const [nodeKindFilter, setNodeKindFilter] = useState<Record<string, boolean>>({
    concept: true,
    skill: true,
    causal: true,
  });
  const [subjectFilter, setSubjectFilter] = useState<Record<string, boolean>>({});
  const [canvasPanelExpanded, setCanvasPanelExpanded] = useState(true);
  const [maintenancePanelExpanded, setMaintenancePanelExpanded] = useState(true);
  const { setPageContext } = useAgentContext();

  const selectedGraphNode = useMemo(
    () => (selectedId ? graphNodes.find((n) => n.id === selectedId) : null),
    [graphNodes, selectedId],
  );

  useEffect(() => {
    if (selectedId && selectedGraphNode) {
      setPageContext({
        current_page: "graph",
        selected_resource_type: "graph_node",
        selected_resource_id: selectedId,
        summary: t("pageSummaryWithNode", { name: selectedGraphNode.canonical_name }),
      });
    } else {
      setPageContext({
        current_page: "graph",
        summary: t("pageSummaryDefault"),
      });
    }
    return () => setPageContext(null);
  }, [selectedId, selectedGraphNode, setPageContext, t]);

  const loadAll = useCallback(async () => {
    onError(null);
    const [n, r, tx] = await Promise.all([
      apiGraphListNodes(),
      apiGraphListRelations(),
      apiGraphGetTaxonomy(),
    ]);
    setGraphNodes(n.nodes as GraphNodeRow[]);
    setKindCounts(n.kind_counts ?? {});
    setRelations(r.relations as GraphRelationRow[]);
    setSubjects(
      tx.subjects?.length ? tx.subjects : [i18n.t("defaultSubject", { ns: "graph" })],
    );
    setLevels(
      tx.levels?.length
        ? tx.levels
        : [i18n.t("defaultLevel1", { ns: "graph" }), i18n.t("defaultLevel2", { ns: "graph" })],
    );
  }, [onError]);

  useEffect(() => {
    void (async () => {
      try {
        setBusy(true);
        await loadAll();
      } catch (e) {
        onError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    })();
  }, [loadAll, onError]);

  useEffect(() => {
    if (!focusNodeId) {
      return;
    }
    setSelectedId(focusNodeId);
    queueMicrotask(() => onFocusConsumed?.());
  }, [focusNodeId, onFocusConsumed]);

  const kindFilteredNodes = useMemo(() => {
    return graphNodes.filter((n) => {
      const k = n.node_kind ?? "concept";
      return nodeKindFilter[k] !== false;
    });
  }, [graphNodes, nodeKindFilter]);

  const subjectKeysOrdered = useMemo(() => {
    const keys = new Set<string>();
    for (const n of graphNodes) {
      keys.add(graphSubjectFilterKey(n));
    }
    for (const s of subjects) {
      const t = s.trim();
      if (t) keys.add(t);
    }
    const arr = [...keys];
    arr.sort((a, b) => {
      if (a === SUBJECT_FILTER_UNSET && b !== SUBJECT_FILTER_UNSET) return 1;
      if (b === SUBJECT_FILTER_UNSET && a !== SUBJECT_FILTER_UNSET) return -1;
      return localeCompareStrings(a, b);
    });
    return arr;
  }, [graphNodes, subjects]);

  useEffect(() => {
    setSubjectFilter((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const k of subjectKeysOrdered) {
        if (!(k in next)) {
          next[k] = false;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [subjectKeysOrdered]);

  const filteredGraphNodes = useMemo(
    () =>
      kindFilteredNodes.filter((n) => subjectFilter[graphSubjectFilterKey(n)] === true),
    [kindFilteredNodes, subjectFilter],
  );

  const filteredNodeIdSet = useMemo(
    () => new Set(filteredGraphNodes.map((n) => n.id)),
    [filteredGraphNodes],
  );

  const filteredRelations = useMemo(() => {
    return relations.filter((r) => {
      if (relTypeFilter[r.relation_type] === false) return false;
      return filteredNodeIdSet.has(r.from_node_id) && filteredNodeIdSet.has(r.to_node_id);
    });
  }, [relations, relTypeFilter, filteredNodeIdSet]);

  const filteredKindCounts = useMemo(() => {
    const c: Record<string, number> = { concept: 0, skill: 0, causal: 0 };
    for (const n of kindFilteredNodes) {
      const k = n.node_kind ?? "concept";
      c[k] = (c[k] ?? 0) + 1;
    }
    return c;
  }, [kindFilteredNodes]);

  const filteredSubjectCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const n of kindFilteredNodes) {
      const sk = graphSubjectFilterKey(n);
      c[sk] = (c[sk] ?? 0) + 1;
    }
    return c;
  }, [kindFilteredNodes]);

  const filteredRelCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of filteredRelations) {
      c[r.relation_type] = (c[r.relation_type] ?? 0) + 1;
    }
    return c;
  }, [filteredRelations]);

  useEffect(() => {
    if (selectedId && !filteredNodeIdSet.has(selectedId)) {
      setSelectedId(null);
    }
  }, [filteredNodeIdSet, selectedId]);

  useEffect(() => {
    if (focusCenterId && !filteredNodeIdSet.has(focusCenterId)) {
      setFocusCenterId(null);
    }
  }, [filteredNodeIdSet, focusCenterId]);

  const focusSet = useMemo(
    () => computeKHopNodes(focusCenterId, focusHops, filteredRelations),
    [focusCenterId, focusHops, filteredRelations],
  );

  /** 邻域聚焦开启且已选定聚焦中心时，使用力导向 */
  const focusForceLayout = focusHops > 0 && focusCenterId != null;

  const nodeSizes = useMemo(() => {
    const m = new Map<string, { w: number; h: number }>();
    for (const n of filteredGraphNodes) {
      m.set(n.id, nodeBoxSizeFromMaterialCount(n.file_link_count ?? 0));
    }
    return m;
  }, [filteredGraphNodes]);

  const relationTargetCandidates = useMemo(() => {
    if (!selectedId) return [];
    const sel = graphNodes.find((n) => n.id === selectedId);
    const sk = sel?.node_kind ?? "concept";
    return graphNodes.filter((n) => {
      if (n.id === selectedId) return false;
      const nk = n.node_kind ?? "concept";
      return sk === "concept" || nk === "concept";
    });
  }, [graphNodes, selectedId]);

  const savedPositions = useMemo(() => {
    const m = new Map<string, { x: number; y: number }>();
    for (const n of graphNodes) {
      if (n.layout_x != null && n.layout_y != null) {
        m.set(n.id, { x: n.layout_x, y: n.layout_y });
      }
    }
    return m;
  }, [graphNodes]);

  useEffect(() => {
    const gn = filteredGraphNodes;
    const rel = filteredRelations;
    if (!gn.length) {
      setNodes([]);
      setEdges([]);
      return;
    }
    const baseEdges: Edge[] = rel.map((r) => ({
      id: r.id,
      source: r.from_node_id,
      target: r.to_node_id,
      data: { relationType: r.relation_type },
      zIndex: 0,
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
      style: {
        stroke: REL_COLOR[r.relation_type] ?? "#64748b",
        strokeWidth: r.relation_type === "prerequisite" ? 1.75 : 1.25,
        opacity: 0.5,
      },
    }));
    const rfNodes: Node[] = gn.map((n) => {
      const box = nodeSizes.get(n.id) ?? nodeBoxSizeFromMaterialCount(0);
      const { w, h } = box;
      return {
        id: n.id,
        type: "knowledge",
        position: { x: 0, y: 0 },
        width: w,
        height: h,
        zIndex: 1,
        style: { width: w, height: h, zIndex: 1 },
        data: {
          label: n.canonical_name,
          nodeKind: n.node_kind ?? "concept",
          sizePx: w,
        },
      };
    });
    const rfEdges = assignStraightEdges(baseEdges);

    let laid: Node[];
    if (!focusForceLayout) {
      laid = layoutWithDagre(rfNodes, rfEdges, nodeSizes);
      if (savedPositions.size > 0) {
        laid = mergeSavedLayout(laid, savedPositions);
      }
      const runNonFocusForce = !nonFocusForceBootstrappedRef.current || layoutNonce > 0;
      if (runNonFocusForce) {
        const seedMap = new Map<string, { x: number; y: number }>();
        for (const n of laid) {
          seedMap.set(n.id, n.position);
        }
        laid = layoutWithForceDirected(laid, rfEdges, {
          seed: seedMap,
          sizes: nodeSizes,
        });
        laid = removeNodeOverlaps(
          laid,
          undefined,
          undefined,
          OVERLAP_DEFAULT.canvasPadding,
          OVERLAP_DEFAULT.maxPasses,
          nodeSizes,
        );
        nonFocusForceBootstrappedRef.current = true;
      } else {
        laid = removeNodeOverlaps(
          laid,
          undefined,
          undefined,
          OVERLAP_DEFAULT.canvasPadding,
          OVERLAP_DEFAULT.maxPasses,
          nodeSizes,
        );
      }
    } else {
      let seed = layoutWithDagre(rfNodes, rfEdges, nodeSizes);
      if (savedPositions.size > 0) {
        seed = mergeSavedLayout(seed, savedPositions);
      }
      if (layoutNonce > 0) {
        const phase = layoutNonce * 0.73;
        seed = seed.map((n, i) => ({
          ...n,
          position: {
            x: n.position.x + Math.cos(phase + i * 0.4) * 24,
            y: n.position.y + Math.sin(phase + i * 0.4) * 24,
          },
        }));
      }
      const seedMap = new Map<string, { x: number; y: number }>();
      for (const n of seed) {
        seedMap.set(n.id, n.position);
      }
      laid = layoutWithForceDirected(seed, rfEdges, {
        seed: seedMap,
        sizes: nodeSizes,
      });
      laid = removeNodeOverlaps(
        laid,
        undefined,
        undefined,
        OVERLAP_DEFAULT.canvasPadding,
        OVERLAP_DEFAULT.maxPasses,
        nodeSizes,
      );
    }

    setNodes(laid);
    setEdges(rfEdges);
  }, [
    filteredGraphNodes,
    filteredRelations,
    savedPositions,
    focusForceLayout,
    layoutNonce,
    nodeSizes,
    setEdges,
    setNodes,
  ]);

  const nodesForRender = useMemo(
    () =>
      nodes.map((n) => ({
        ...n,
        zIndex: 1,
        style: { ...n.style, zIndex: 1 },
        data: {
          ...n.data,
          focusDimmed: focusSet !== null && !focusSet.has(n.id),
        },
      })),
    [nodes, focusSet],
  );

  const edgesForRender = useMemo(
    () =>
      edges.map((e) => {
        const dim =
          focusSet !== null && !(focusSet.has(e.source) && focusSet.has(e.target));
        const rt = (e.data as { relationType?: string } | undefined)?.relationType;
        const inFocusEdge =
          focusSet !== null && focusSet.has(e.source) && focusSet.has(e.target);
        const showRelationLabel = Boolean(focusSet && inFocusEdge && rt);
        const baseOp = focusSet === null ? 0.5 : dim ? 0.12 : 1;
        return {
          ...e,
          zIndex: 0,
          label: showRelationLabel ? i18n.t(`edgeKind.${rt}`, { ns: "graph", defaultValue: rt }) : undefined,
          labelShowBg: showRelationLabel,
          style: { ...e.style, opacity: baseOp },
        };
      }),
    [edges, focusSet],
  );

  useEffect(() => {
    if (!selectedId) {
      setBoundQuestions([]);
      setBoundSel(new Set());
      setNodeFiles([]);
      return;
    }
    setBoundSel(new Set());
    const n = graphNodes.find((x) => x.id === selectedId);
    if (n) {
      setDraftName(n.canonical_name ?? "");
      setDraftSubject(n.subject ?? "");
      setDraftLevel(n.level ?? "");
      setDraftDesc(n.description ?? "");
      setDraftTags((n.tags ?? []).join(", "));
      setDraftAliases((n.aliases ?? []).join(", "));
      setDraftKind((n.node_kind as "concept" | "skill" | "causal") ?? "concept");
    }
    void (async () => {
      try {
        const [q, f] = await Promise.all([
          apiGraphListQuestionsForNode(selectedId),
          apiGraphListNodeFiles(selectedId),
        ]);
        setBoundQuestions(q.questions as BoundQuestion[]);
        setNodeFiles(f.links as { id: string; relative_path: string }[]);
      } catch (e) {
        onError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [graphNodes, onError, selectedId]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedId(node.id);
      if (awaitingFocusPick) {
        setFocusCenterId(node.id);
        setAwaitingFocusPick(false);
      }
    },
    [awaitingFocusPick],
  );

  const onPaneClick = useCallback(() => {
    setSelectedId(null);
    setAwaitingFocusPick(false);
  }, []);

  const persistLayout = useCallback(
    async (nodeId: string, x: number, y: number) => {
      const n = graphNodes.find((g) => g.id === nodeId);
      if (!n) return;
      try {
        await apiGraphUpdateNode(nodeId, {
          id: nodeId,
          node_kind: n.node_kind ?? "concept",
          canonical_name: n.canonical_name,
          aliases: n.aliases ?? [],
          subject: n.subject ?? null,
          level: n.level ?? null,
          description: n.description ?? null,
          tags: n.tags ?? [],
          source: null,
          layout_x: x,
          layout_y: y,
        });
        setGraphNodes((prev) =>
          prev.map((p) => (p.id === nodeId ? { ...p, layout_x: x, layout_y: y } : p)),
        );
      } catch (e) {
        onError(e instanceof Error ? e.message : String(e));
      }
    },
    [graphNodes, onError],
  );

  const onNodeDragStop = useCallback(
    (_: React.MouseEvent, node: Node) => {
      void persistLayout(node.id, node.position.x, node.position.y);
    },
    [persistLayout],
  );

  const saveNodeEdits = async () => {
    if (!selectedId) return;
    setBusy(true);
    onError(null);
    try {
      await apiGraphUpdateNode(selectedId, {
        id: selectedId,
        node_kind: draftKind,
        canonical_name: draftName.trim(),
        aliases: splitCsv(draftAliases),
        subject: draftSubject.trim() || null,
        level: draftLevel.trim() || null,
        description: draftDesc.trim() || null,
        tags: splitCsv(draftTags),
        source: null,
        layout_x: graphNodes.find((g) => g.id === selectedId)?.layout_x ?? null,
        layout_y: graphNodes.find((g) => g.id === selectedId)?.layout_y ?? null,
      });
      await loadAll();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const addTaxonomyValue = async (kind: "subject" | "level", value: string) => {
    const v = value.trim();
    if (!v) return;
    const nextSubjects = kind === "subject" ? [...new Set([...subjects, v])] : subjects;
    const nextLevels = kind === "level" ? [...new Set([...levels, v])] : levels;
    await apiGraphPutTaxonomy({ subjects: nextSubjects, levels: nextLevels });
    setSubjects(nextSubjects);
    setLevels(nextLevels);
    if (kind === "subject") setDraftSubject(v);
    else setDraftLevel(v);
  };

  const createChildNode = async () => {
    if (!newParent.trim() || !newName.trim()) {
      onError(t("errPickParentName"));
      return;
    }
    setBusy(true);
    onError(null);
    try {
      await apiGraphCreateNode({
        parent_node_id: newParent.trim(),
        node_kind: newNodeKind,
        canonical_name: newName.trim(),
        aliases: [],
        subject: newSubject.trim() || null,
        level: newLevel.trim() || null,
        description: null,
        tags: [],
        source: null,
      });
      setNewName("");
      await loadAll();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const deleteNode = async () => {
    if (!selectedId) return;
    if (!window.confirm(t("confirmDeleteNode"))) return;
    setBusy(true);
    onError(null);
    try {
      await apiGraphDeleteNode(selectedId);
      setSelectedId(null);
      await loadAll();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const addRelation = async () => {
    if (!selectedId || !relTo) {
      onError(t("errPickNodeRel"));
      return;
    }
    setBusy(true);
    onError(null);
    try {
      await apiGraphCreateRelation({
        from_node_id: selectedId,
        to_node_id: relTo,
        relation_type: relType,
      });
      await loadAll();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const removeRelation = async (rid: string) => {
    setBusy(true);
    onError(null);
    try {
      await apiGraphDeleteRelation(rid);
      await loadAll();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const openBank = async () => {
    setBankOpen(true);
    setBankSel(new Set());
    setBankSubject("");
    setBankType("");
    try {
      const r = await apiBankItems();
      setBankItems(r.items ?? []);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  const filteredBank = useMemo(() => {
    let xs = bankItems;
    if (bankNs.trim()) {
      const s = bankNs.trim().toLowerCase();
      xs = xs.filter((it) => String(it.namespace ?? "").toLowerCase().includes(s));
    }
    if (bankSubject.trim()) {
      const s = bankSubject.trim();
      xs = xs.filter((it) => String(it.subject ?? "") === s);
    }
    if (bankType.trim()) {
      const s = bankType.trim();
      xs = xs.filter((it) => String(it.type ?? "") === s);
    }
    if (bankQ.trim()) {
      const s = bankQ.trim().toLowerCase();
      xs = xs.filter(
        (it) =>
          String(it.qualified_id ?? "")
            .toLowerCase()
            .includes(s) ||
          String(it.content_preview ?? "")
            .toLowerCase()
            .includes(s),
      );
    }
    return xs;
  }, [bankItems, bankNs, bankQ, bankSubject, bankType]);

  const toggleBankSel = (qid: string) => {
    setBankSel((prev) => {
      const n = new Set(prev);
      if (n.has(qid)) n.delete(qid);
      else n.add(qid);
      return n;
    });
  };

  const bindSelectedQuestions = async () => {
    if (!selectedId || bankSel.size === 0) {
      onError(t("errPickNodeQuestion"));
      return;
    }
    setBusy(true);
    onError(null);
    try {
      await apiGraphBindBatch(selectedId, Array.from(bankSel));
      setBankOpen(false);
      setBankSel(new Set());
      const q = await apiGraphListQuestionsForNode(selectedId);
      setBoundQuestions(q.questions as BoundQuestion[]);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const toggleBoundSel = (qid: string) => {
    setBoundSel((prev) => {
      const n = new Set(prev);
      if (n.has(qid)) n.delete(qid);
      else n.add(qid);
      return n;
    });
  };

  const unbindSelectedBound = async () => {
    if (!selectedId || boundSel.size === 0) {
      onError(t("errPickQuestionsUnbind"));
      return;
    }
    setBusy(true);
    onError(null);
    try {
      await apiGraphUnbindBatch(selectedId, Array.from(boundSel));
      setBoundSel(new Set());
      const q = await apiGraphListQuestionsForNode(selectedId);
      setBoundQuestions(q.questions as BoundQuestion[]);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const unbindQ = async (qid: string) => {
    if (!selectedId) return;
    setBusy(true);
    onError(null);
    try {
      await apiGraphUnbindBinding({ question_qualified_id: qid, node_id: selectedId });
      const q = await apiGraphListQuestionsForNode(selectedId);
      setBoundQuestions(q.questions as BoundQuestion[]);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const openFiles = async () => {
    setFileOpen(true);
    setFileSel(new Set());
    try {
      const r = await apiGraphListResourceFiles(fileQ, 600);
      setFileList(r.files ?? []);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    if (!fileOpen) return;
    const t = window.setTimeout(() => {
      void (async () => {
        try {
          const r = await apiGraphListResourceFiles(fileQ, 600);
          setFileList(r.files ?? []);
        } catch {
          /* ignore */
        }
      })();
    }, 300);
    return () => window.clearTimeout(t);
  }, [fileOpen, fileQ]);

  const attachSelectedFiles = async () => {
    if (!selectedId || fileSel.size === 0) {
      onError(t("errPickNodeFile"));
      return;
    }
    setBusy(true);
    onError(null);
    try {
      for (const p of fileSel) {
        await apiGraphAttachFile({ node_id: selectedId, relative_path: p });
      }
      setFileOpen(false);
      const f = await apiGraphListNodeFiles(selectedId);
      setNodeFiles(f.links as { id: string; relative_path: string }[]);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const uploadAndAttach = async (file: File | null) => {
    if (!file || !selectedId) return;
    setBusy(true);
    onError(null);
    try {
      const up = await apiGraphUploadMaterial(file);
      await apiGraphAttachFile({ node_id: selectedId, relative_path: up.relative_path });
      const f = await apiGraphListNodeFiles(selectedId);
      setNodeFiles(f.links as { id: string; relative_path: string }[]);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const detachFile = async (linkId: string) => {
    setBusy(true);
    onError(null);
    try {
      await apiGraphDetachFile(linkId);
      if (selectedId) {
        const f = await apiGraphListNodeFiles(selectedId);
        setNodeFiles(f.links as { id: string; relative_path: string }[]);
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const relForSelected = useMemo(() => {
    if (!selectedId) return [];
    return relations.filter((r) => r.from_node_id === selectedId || r.to_node_id === selectedId);
  }, [relations, selectedId]);

  return (
    <div className="flex h-full min-h-[70vh] flex-col gap-2 p-2">
      <div className="flex min-h-0 flex-1 flex-col gap-2 lg:flex-row">
        <div className="relative min-h-[420px] flex-1 rounded-lg border border-slate-200 bg-slate-50">
          {busy && graphNodes.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-slate-500">{t("loading")}</div>
          ) : (
            <>
              {canvasPanelExpanded ? (
              <div className="pointer-events-auto absolute left-2 top-2 z-10 max-h-[min(70vh,520px)] w-[min(100%-1rem,440px)] overflow-auto rounded-lg border border-slate-200 bg-white/95 p-2 text-[11px] shadow-md backdrop-blur">
                <div className="flex items-start justify-between gap-2">
                  <div className="font-medium text-slate-800">{t("canvasTitle")}</div>
                  <button
                    type="button"
                    className="shrink-0 rounded border border-slate-300 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-800 hover:bg-slate-100"
                    onClick={() => setCanvasPanelExpanded(false)}
                    title={t("collapseToolbar")}
                  >
                    {t("collapse")}
                  </button>
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-slate-600">
                  <span>{t("layoutIntro")}</span>
                  <button
                    type="button"
                    className="rounded border border-slate-300 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-800 hover:bg-slate-100"
                    onClick={() => setLayoutNonce((n) => n + 1)}
                    title={t("relayoutTitle")}
                  >
                    {t("relayout")}
                  </button>
                </div>
                {import.meta.env.DEV ? (
                  <details className="mt-2 rounded border border-dashed border-slate-200 bg-slate-50/90 p-1.5 text-[10px] text-slate-600">
                    <summary className="cursor-pointer select-none font-medium text-slate-700">
                      {t("layoutParams")}
                    </summary>
                    <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all font-mono text-[9px] leading-tight">
                      {JSON.stringify(
                        {
                          dagre: DAGRE_GRAPH,
                          force: FORCE_DEFAULT,
                          materialBox: MATERIAL_BOX,
                          overlap: OVERLAP_DEFAULT,
                        },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                ) : null}
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <label className="flex items-center gap-1 text-slate-600">
                    {t("focusNeighborhood")}
                    <select
                      className="rounded border border-slate-300 bg-white px-1.5 py-0.5 text-[11px]"
                      value={focusHops}
                      onChange={(e) => {
                        const v = Number(e.target.value) as 0 | 1 | 2;
                        setFocusHops((prev) => {
                          if (v === 0) {
                            setFocusCenterId(null);
                            setAwaitingFocusPick(false);
                          } else if (prev === 0 && v > 0 && selectedId) {
                            setFocusCenterId(selectedId);
                            setAwaitingFocusPick(false);
                          }
                          return v;
                        });
                      }}
                    >
                      <option value={0}>{t("focusOff")}</option>
                      <option value={1}>{t("focus1")}</option>
                      <option value={2}>{t("focus2")}</option>
                    </select>
                  </label>
                  {focusHops > 0 ? (
                    <button
                      type="button"
                      className={cn(
                        "rounded border px-2 py-0.5 text-[11px] font-medium",
                        awaitingFocusPick
                          ? "border-amber-500 bg-amber-50 text-amber-900"
                          : "border-slate-300 bg-slate-50 text-slate-800 hover:bg-slate-100",
                      )}
                      onClick={() => setAwaitingFocusPick((a) => !a)}
                      title={t("refocusTitle")}
                    >
                      {awaitingFocusPick ? t("cancelPick") : t("refocus")}
                    </button>
                  ) : null}
                  <span className="text-slate-400">
                    {focusHops > 0
                      ? awaitingFocusPick
                        ? t("pickCenterHint")
                        : focusCenterId
                          ? t("dragNoCenter")
                          : t("pickRefocusFirst")
                      : t("focusSelectCenter")}
                  </span>
                </div>
                <div className="mt-2 border-t border-slate-100 pt-2">
                  <div className="text-slate-600">{t("relTypeCanvas")}</div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                    {REL_KEYS.map((k) => (
                      <label key={k} className="inline-flex cursor-pointer items-center gap-1">
                        <input
                          type="checkbox"
                          checked={relTypeFilter[k] !== false}
                          onChange={(e) =>
                            setRelTypeFilter((prev) => ({ ...prev, [k]: e.target.checked }))
                          }
                        />
                        <span style={{ color: REL_COLOR[k] ?? "#64748b" }}>
                          {t(`edgeKind.${k}`)}
                        </span>
                        <span className="text-slate-400">({filteredRelCounts[k] ?? 0})</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="mt-2 border-t border-slate-100 pt-2">
                  <div className="text-slate-600">{t("subjectCanvas")}</div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                    {subjectKeysOrdered.map((sk) => (
                      <label key={sk} className="inline-flex cursor-pointer items-center gap-1">
                        <input
                          type="checkbox"
                          checked={subjectFilter[sk] === true}
                          onChange={(e) => {
                            setSubjectFilter((prev) => ({ ...prev, [sk]: e.target.checked }));
                            setLayoutNonce((n) => n + 1);
                          }}
                        />
                        <span>{subjectFilterCheckboxLabel(sk, t("subjectUnset"))}</span>
                        <span className="text-slate-400">({filteredSubjectCounts[sk] ?? 0})</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="mt-2 border-t border-slate-100 pt-2">
                  <div className="text-slate-600">{t("nodeTypeCanvas")}</div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                    {(["concept", "skill", "causal"] as const).map((k) => (
                      <label key={k} className="inline-flex cursor-pointer items-center gap-1">
                        <input
                          type="checkbox"
                          checked={nodeKindFilter[k] !== false}
                          onChange={(e) =>
                            setNodeKindFilter((prev) => ({ ...prev, [k]: e.target.checked }))
                          }
                        />
                        <span>{t(`nodeKind.${k}`)}</span>
                        <span className="text-slate-400">({filteredKindCounts[k] ?? 0})</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="mt-2 border-t border-slate-100 pt-2 text-slate-500">{t("canvasStyleNote")}</div>
              </div>
              ) : (
                <div className="pointer-events-auto absolute left-2 top-2 z-10">
                  <button
                    type="button"
                    className="rounded-lg border border-slate-200 bg-white/95 px-2 py-1 text-[11px] font-medium text-slate-800 shadow-md backdrop-blur hover:bg-slate-50"
                    onClick={() => setCanvasPanelExpanded(true)}
                    title={t("expandToolbar")}
                  >
                    {t("expandTools")}
                  </button>
                </div>
              )}
              <ReactFlow
                nodes={nodesForRender}
                edges={edgesForRender}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodeClick={onNodeClick}
                onPaneClick={onPaneClick}
                onNodeDragStop={onNodeDragStop}
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                connectionLineType={ConnectionLineType.Straight}
                elevateEdgesOnSelect={false}
                fitView
                minZoom={0.2}
                maxZoom={1.4}
                proOptions={{ hideAttribution: true }}
              >
                <Background />
                <Controls />
                <MiniMap zoomable pannable />
              </ReactFlow>
            </>
          )}
        </div>

        <aside
          className={cn(
            "shrink-0 rounded-lg border border-slate-200 bg-white transition-[width,max-width] duration-200 ease-out",
            maintenancePanelExpanded
              ? "min-h-0 w-full overflow-auto p-3 lg:w-[380px] lg:max-w-[380px] xl:w-[420px] xl:max-w-[420px]"
              : "flex w-full min-h-0 flex-col overflow-hidden lg:w-12 lg:min-w-12 lg:max-w-12",
          )}
        >
          {!maintenancePanelExpanded ? (
            <div className="flex flex-1 flex-col items-stretch justify-center lg:min-h-[8rem]">
              <button
                type="button"
                className="w-full rounded-md border border-slate-200 bg-slate-50 py-2 text-xs font-medium text-slate-800 hover:bg-slate-100 lg:flex lg:flex-1 lg:items-center lg:justify-center lg:py-4 lg:text-[11px]"
                onClick={() => setMaintenancePanelExpanded(true)}
                title={t("expandMaintainTitle")}
              >
                <span className="lg:hidden">{t("expandMaintain")}</span>
                <span className="hidden lg:inline lg:[writing-mode:vertical-rl] lg:tracking-wide">{t("expandMaintain")}</span>
              </button>
            </div>
          ) : (
            <>
              <div className="flex items-start justify-between gap-2">
                <h2 className="text-sm font-semibold text-slate-900">{t("maintainTitle")}</h2>
                <button
                  type="button"
                  className="shrink-0 rounded border border-slate-300 bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-800 hover:bg-slate-100"
                  onClick={() => setMaintenancePanelExpanded(false)}
                  title={t("collapsePanel")}
                >
                  {t("collapse")}
                </button>
              </div>
              <p className="mt-1 text-xs text-slate-600">{t("clickNodeHint")}</p>
          <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-600">
            <span className="text-slate-500">{t("totalNodes")}</span>
            {(["concept", "skill", "causal"] as const).map((k) => (
              <span key={k} className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5">
                {t(`nodeKind.${k}`)} {kindCounts[k] ?? 0}
              </span>
            ))}
            <span className="w-full text-slate-400">{t("filteredHint")}</span>
          </div>

          {selectedId ? (
            <div className="mt-3 space-y-3 border-t border-slate-100 pt-3">
              <div>
                <div className="text-[11px] font-medium text-slate-500">{t("internalId")}</div>
                <div className="mt-1 break-all rounded border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-[11px] text-slate-700">
                  {selectedId}
                </div>
              </div>
              <label className="block text-[11px] font-medium text-slate-600">
                {t("canonicalName")}
                <input
                  className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                  value={draftName}
                  onChange={(e) => setDraftName(e.target.value)}
                />
              </label>
              <label className="block text-[11px] font-medium text-slate-600">
                {t("nodeType")}
                <select
                  className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
                  value={draftKind}
                  onChange={(e) => setDraftKind(e.target.value as "concept" | "skill" | "causal")}
                >
                  <option value="concept">{t("nodeKind.concept")}</option>
                  <option value="skill">{t("nodeKind.skill")}</option>
                  <option value="causal">{t("nodeKind.causal")}</option>
                </select>
              </label>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <label className="block text-[11px] font-medium text-slate-600">
                  {t("subject")}
                  <select
                    className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
                    value={draftSubject}
                    onChange={(e) => setDraftSubject(e.target.value)}
                  >
                    <option value="">{t("notSelected")}</option>
                    {subjects.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block text-[11px] font-medium text-slate-600">
                  {t("level")}
                  <select
                    className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
                    value={draftLevel}
                    onChange={(e) => setDraftLevel(e.target.value)}
                  >
                    <option value="">{t("notSelected")}</option>
                    {levels.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="flex flex-wrap gap-2">
                <input
                  className="min-w-0 flex-1 rounded-md border border-slate-300 px-2 py-1 text-xs"
                  placeholder={t("newSubjectPh")}
                  id="new-subject"
                />
                <button
                  type="button"
                  className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-800"
                  onClick={() => {
                    const el = document.getElementById("new-subject") as HTMLInputElement | null;
                    void addTaxonomyValue("subject", el?.value ?? "");
                    if (el) el.value = "";
                  }}
                >
                  {t("addSubjectOption")}
                </button>
              </div>
              <div className="flex flex-wrap gap-2">
                <input
                  className="min-w-0 flex-1 rounded-md border border-slate-300 px-2 py-1 text-xs"
                  placeholder={t("newLevelPh")}
                  id="new-level"
                />
                <button
                  type="button"
                  className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-800"
                  onClick={() => {
                    const el = document.getElementById("new-level") as HTMLInputElement | null;
                    void addTaxonomyValue("level", el?.value ?? "");
                    if (el) el.value = "";
                  }}
                >
                  {t("addLevelOption")}
                </button>
              </div>
              <label className="block text-[11px] font-medium text-slate-600">
                {t("tags")}
                <input
                  className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                  value={draftTags}
                  onChange={(e) => setDraftTags(e.target.value)}
                />
              </label>
              <label className="block text-[11px] font-medium text-slate-600">
                {t("aliases")}
                <input
                  className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm font-mono"
                  value={draftAliases}
                  onChange={(e) => setDraftAliases(e.target.value)}
                />
              </label>
              <label className="block text-[11px] font-medium text-slate-600">
                {t("brief")}
                <textarea
                  className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                  rows={3}
                  value={draftDesc}
                  onChange={(e) => setDraftDesc(e.target.value)}
                />
              </label>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                  disabled={busy}
                  onClick={() => void saveNodeEdits()}
                >
                  {t("saveChanges")}
                </button>
                <button
                  type="button"
                  className="rounded-md border border-red-300 px-3 py-1.5 text-sm font-medium text-red-700"
                  disabled={busy}
                  onClick={() => void deleteNode()}
                >
                  {t("delete")}
                </button>
              </div>

              <div className="rounded-md border border-slate-200 bg-slate-50 p-2">
                <h3 className="text-xs font-semibold text-slate-700">{t("relations")}</h3>
                <div className="mt-2 grid grid-cols-1 gap-2">
                  <label className="text-[11px] font-medium text-slate-600">
                    {t("targetNode")}
                    <select
                      className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
                      value={relTo}
                      onChange={(e) => setRelTo(e.target.value)}
                    >
                      <option value="">{t("selectEllipsis")}</option>
                      {relationTargetCandidates.map((n) => (
                          <option key={n.id} value={n.id}>
                            {n.canonical_name}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label className="text-[11px] font-medium text-slate-600">
                    {t("relationType")}
                    <select
                      className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
                      value={relType}
                      onChange={(e) => setRelType(e.target.value)}
                    >
                      <option value="prerequisite">{t("edgeKind.prerequisite")}</option>
                      <option value="part_of">{t("edgeKind.part_of")}</option>
                      <option value="related">{t("edgeKind.related")}</option>
                      <option value="causal">{t("edgeKind.causal")}</option>
                    </select>
                  </label>
                  <button
                    type="button"
                    className="rounded-md bg-slate-900 py-1.5 text-sm font-medium text-white"
                    onClick={() => void addRelation()}
                  >
                    {t("createRelation")}
                  </button>
                </div>
                <ul className="mt-2 max-h-32 space-y-1 overflow-auto text-xs">
                  {relForSelected.map((r) => (
                    <li key={r.id} className="flex items-start justify-between gap-2 rounded border border-slate-200 bg-white p-1">
                      <span className="text-slate-700">
                        {t(`edgeKind.${r.relation_type}`, { defaultValue: r.relation_type })} ·{" "}
                        {r.from_node_id === selectedId ? r.to_node_id : r.from_node_id}
                      </span>
                      <button type="button" className="shrink-0 text-red-600" onClick={() => void removeRelation(r.id)}>
                        {t("remove")}
                      </button>
                    </li>
                  ))}
                  {relForSelected.length === 0 ? <li className="text-slate-500">{t("noRelations")}</li> : null}
                </ul>
              </div>

              <div className="rounded-md border border-slate-200 bg-slate-50 p-2">
                <h3 className="text-xs font-semibold text-slate-700">{t("boundQuestions")}</h3>
                <button
                  type="button"
                  className="mt-2 w-full rounded-md bg-slate-900 py-2 text-sm font-medium text-white"
                  onClick={() => void openBank()}
                >
                  {t("pickFromBank")}
                </button>
                {boundQuestions.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button
                      type="button"
                      className="rounded-md border border-red-200 bg-white px-2 py-1 text-[11px] font-medium text-red-700 disabled:opacity-50"
                      disabled={busy || boundSel.size === 0}
                      onClick={() => void unbindSelectedBound()}
                    >
                      {t("batchUnbind", { n: boundSel.size })}
                    </button>
                  </div>
                ) : null}
                <ul className="mt-2 max-h-36 space-y-1 overflow-auto text-xs">
                  {boundQuestions.map((q) => (
                    <li key={q.qualified_id} className="flex items-start gap-2 rounded border border-slate-200 bg-white p-1">
                      <input
                        type="checkbox"
                        className="mt-0.5 shrink-0"
                        checked={boundSel.has(q.qualified_id)}
                        onChange={() => toggleBoundSel(q.qualified_id)}
                        aria-label={t("pickQuestionAria", { id: q.qualified_id })}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="font-mono text-[11px]">{q.qualified_id}</div>
                        {q.content_preview ? <div className="text-slate-600">{q.content_preview}</div> : null}
                      </div>
                      <button type="button" className="shrink-0 text-red-600" onClick={() => void unbindQ(q.qualified_id)}>
                        {t("unbind")}
                      </button>
                    </li>
                  ))}
                  {boundQuestions.length === 0 ? <li className="text-slate-500">{t("noBoundQuestions")}</li> : null}
                </ul>
              </div>

              <div className="rounded-md border border-slate-200 bg-slate-50 p-2">
                <h3 className="text-xs font-semibold text-slate-700">{t("boundFiles")}</h3>
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="flex-1 rounded-md bg-slate-900 py-2 text-sm font-medium text-white"
                    onClick={() => void openFiles()}
                  >
                    {t("pickProjectFile")}
                  </button>
                  <label className="cursor-pointer rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-900">
                    {t("uploadAndLink")}
                    <input
                      type="file"
                      className="hidden"
                      onChange={(e) => void uploadAndAttach(e.target.files?.[0] ?? null)}
                    />
                  </label>
                </div>
                <ul className="mt-2 max-h-28 space-y-1 overflow-auto text-xs">
                  {nodeFiles.map((l) => (
                    <li key={l.id} className="flex items-center justify-between gap-2 rounded border border-slate-200 bg-white p-1">
                      <a
                        className="break-all text-blue-700 underline"
                        href={resourceApiUrl(l.relative_path)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {l.relative_path}
                      </a>
                      <button type="button" className="shrink-0 text-red-600" onClick={() => void detachFile(l.id)}>
                        {t("remove")}
                      </button>
                    </li>
                  ))}
                  {nodeFiles.length === 0 ? <li className="text-slate-500">{t("noFiles")}</li> : null}
                </ul>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-xs text-slate-500">{t("pickNodeFirst")}</p>
          )}

          <div className="mt-4 border-t border-slate-100 pt-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{t("newChildTitle")}</h3>
            <label className="mt-2 block text-[11px] font-medium text-slate-600">
              {t("parentNode")}
              <select
                className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
                value={newParent}
                onChange={(e) => setNewParent(e.target.value)}
              >
                <option value="">{t("selectEllipsis")}</option>
                {graphNodes.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.canonical_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="mt-2 block text-[11px] font-medium text-slate-600">
              {t("name")}
              <input
                className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </label>
            <label className="mt-2 block text-[11px] font-medium text-slate-600">
              {t("nodeType")}
              <select
                className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
                value={newNodeKind}
                onChange={(e) => setNewNodeKind(e.target.value as "concept" | "skill" | "causal")}
              >
                <option value="concept">{t("nodeKind.concept")}</option>
                <option value="skill">{t("nodeKind.skill")}</option>
                <option value="causal">{t("nodeKind.causal")}</option>
              </select>
            </label>
            <div className="mt-2 grid grid-cols-2 gap-2">
              <label className="block text-[11px] font-medium text-slate-600">
                {t("subject")}
                <select
                  className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
                  value={newSubject}
                  onChange={(e) => setNewSubject(e.target.value)}
                >
                  <option value="">{t("notSelected")}</option>
                  {subjects.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-[11px] font-medium text-slate-600">
                {t("level")}
                <select
                  className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
                  value={newLevel}
                  onChange={(e) => setNewLevel(e.target.value)}
                >
                  <option value="">{t("notSelected")}</option>
                  {levels.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <button
              type="button"
              className="mt-3 w-full rounded-md bg-slate-900 py-2 text-sm font-medium text-white disabled:opacity-50"
              disabled={busy}
              onClick={() => void createChildNode()}
            >
              {t("createAutoId")}
            </button>
          </div>
            </>
          )}
        </aside>
      </div>

      {bankOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="max-h-[85vh] w-full max-w-3xl overflow-auto rounded-lg border border-slate-200 bg-white p-4 shadow-xl">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">{t("pickQuestionTitle")}</h3>
              <button type="button" className="text-sm text-slate-600" onClick={() => setBankOpen(false)}>
                {t("close")}
              </button>
            </div>
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              <label className="text-[11px] font-medium text-slate-600">
                {t("collectionFilter")}
                <input
                  className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                  value={bankNs}
                  onChange={(e) => setBankNs(e.target.value)}
                  placeholder={t("collectionPh")}
                />
              </label>
              <label className="text-[11px] font-medium text-slate-600">
                {t("subject")}
                <select
                  className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
                  value={bankSubject}
                  onChange={(e) => setBankSubject(e.target.value)}
                >
                  <option value="">{t("all")}</option>
                  {[...new Set(bankItems.map((it) => String(it.subject ?? "").trim()).filter(Boolean))].sort((a, b) =>
                    localeCompareStrings(a, b),
                  ).map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-[11px] font-medium text-slate-600">
                {t("questionType")}
                <select
                  className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
                  value={bankType}
                  onChange={(e) => setBankType(e.target.value)}
                >
                  <option value="">{t("all")}</option>
                  {QUESTION_TYPE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {t(`questionTypes.${o.value}`, { ns: "lib" })}
                    </option>
                  ))}
                  <option value="group">{t("typeGroup")}</option>
                </select>
              </label>
              <label className="text-[11px] font-medium text-slate-600">
                {t("keyword")}
                <input
                  className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                  value={bankQ}
                  onChange={(e) => setBankQ(e.target.value)}
                  placeholder={t("keywordPh")}
                />
              </label>
            </div>
            <div className="mt-3 max-h-[50vh] overflow-auto rounded border border-slate-200">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 bg-slate-100">
                  <tr>
                    <th className="p-2">{t("thPick")}</th>
                    <th className="p-2">{t("thQid")}</th>
                    <th className="p-2">{t("thType")}</th>
                    <th className="p-2">{t("thPreview")}</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredBank.map((it) => (
                    <tr key={it.qualified_id} className="border-t border-slate-100">
                      <td className="p-2">
                        <input
                          type="checkbox"
                          checked={bankSel.has(it.qualified_id)}
                          onChange={() => toggleBankSel(it.qualified_id)}
                        />
                      </td>
                      <td className="p-2 font-mono">{it.qualified_id}</td>
                      <td className="p-2">{it.type}</td>
                      <td className="max-w-xs truncate p-2 text-slate-600">{it.content_preview}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex justify-end gap-2">
              <button type="button" className="rounded-md border border-slate-300 px-3 py-2 text-sm" onClick={() => setBankOpen(false)}>
                {t("cancel")}
              </button>
              <button
                type="button"
                className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white"
                onClick={() => void bindSelectedQuestions()}
              >
                {t("bindToNode")}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {fileOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="max-h-[85vh] w-full max-w-2xl overflow-auto rounded-lg border border-slate-200 bg-white p-4 shadow-xl">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">{t("pickFileTitle")}</h3>
              <button type="button" className="text-sm text-slate-600" onClick={() => setFileOpen(false)}>
                {t("close")}
              </button>
            </div>
            <label className="mt-3 block text-[11px] font-medium text-slate-600">
              {t("searchPath")}
              <input
                className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                value={fileQ}
                onChange={(e) => setFileQ(e.target.value)}
                placeholder={t("filterPh")}
              />
            </label>
            <div className="mt-3 max-h-[50vh] overflow-auto rounded border border-slate-200">
              <ul className="divide-y divide-slate-100 text-xs">
                {fileList.map((f) => (
                  <li key={f.path} className="flex items-center gap-2 p-2">
                    <input
                      type="checkbox"
                      checked={fileSel.has(f.path)}
                      onChange={() => {
                        setFileSel((prev) => {
                          const n = new Set(prev);
                          if (n.has(f.path)) n.delete(f.path);
                          else n.add(f.path);
                          return n;
                        });
                      }}
                    />
                    <span className="break-all font-mono">{f.path}</span>
                    <span className="shrink-0 text-slate-500">{f.size} B</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="mt-3 flex justify-end gap-2">
              <button type="button" className="rounded-md border border-slate-300 px-3 py-2 text-sm" onClick={() => setFileOpen(false)}>
                {t("cancel")}
              </button>
              <button
                type="button"
                className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white"
                onClick={() => void attachSelectedFiles()}
              >
                {t("linkToNode")}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
