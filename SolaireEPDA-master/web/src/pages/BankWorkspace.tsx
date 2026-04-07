import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import yaml from "js-yaml";
import {
  apiDelete,
  apiGet,
  apiGraphQuestionBindingsIndex,
  apiPost,
  apiPostFormData,
  apiPut,
  downloadBankExportBundle,
} from "../api/client";
import {
  BankQuestionEditorPanel,
  type BankDetailState,
  type GroupMemberJson,
  type QuestionGroupJson,
  type QuestionJson,
} from "../components/BankQuestionEditorPanel";
import type { EmbedKind } from "../lib/bankEditorEmbedKinds";
import { ContentWithPrimeBrush } from "../components/ContentWithPrimeBrush";
import { MathInsertOverlay } from "../components/MathInsertOverlay";
import { MermaidEditorModal } from "../components/MermaidEditorModal";
import { useAgentContext } from "../contexts/AgentContext";
import i18n from "../i18n/i18n";
import { localeCompareStrings } from "../lib/locale";
import { cn } from "../lib/utils";
import { collapseGroupRowsForList } from "../lib/groupQuestions";
import { QUESTION_TYPE_OPTIONS } from "../lib/questionTypes";

/** 新建题组时生成一条占位小题（与后端 QuestionGroupRecord 一致） */
function defaultItemsForNewGroup(unifiedUi: string, subStem: string): QuestionGroupJson["items"] {
  if (unifiedUi === "mixed") {
    return [
      {
        type: "choice",
        content: subStem,
        options: { A: "", B: "", C: "", D: "" },
        answer: "A",
        analysis: "",
        metadata: {},
      },
    ];
  }
  if (unifiedUi === "choice") {
    return [{ content: subStem, options: { A: "", B: "", C: "", D: "" }, answer: "A", analysis: "", metadata: {} }];
  }
  if (unifiedUi === "fill") {
    return [{ content: subStem, answer: "", analysis: "", metadata: {} }];
  }
  if (unifiedUi === "judge") {
    return [{ content: subStem, answer: "T", analysis: "", metadata: {} }];
  }
  return [{ content: subStem, answer: "", analysis: "", metadata: {} }];
}

type BankListItem = {
  id: string;
  qualified_id: string;
  collection: string;
  subject?: string;
  collection_name?: string;
  type: string;
  content_preview: string;
  metadata: Record<string, unknown>;
  storage_kind: string;
  group_id?: string | null;
  group_member_qualified_ids?: string[];
  group_material?: string | null;
};

export function BankWorkspace({
  onError,
  onOpenGraphNode,
}: {
  onError: (s: string | null) => void;
  onOpenGraphNode?: (nodeId: string) => void;
}) {
  const { t } = useTranslation(["bank", "lib", "common"]);
  const [items, setItems] = useState<BankListItem[]>([]);
  const [collections, setCollections] = useState<{ id: string; label: string }[]>([]);
  const [subjects, setSubjects] = useState<string[]>([]);
  const [filterSubject, setFilterSubject] = useState<string>("__all__");
  const [filterCollection, setFilterCollection] = useState<string>("__all__");
  const [filterType, setFilterType] = useState<string>("__all__");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<BankDetailState | null>(null);
  const [busy, setBusy] = useState(false);
  const [importYaml, setImportYaml] = useState("");
  const [importSubject, setImportSubject] = useState(() => i18n.t("bank:defaultSubject"));
  const [importTarget, setImportTarget] = useState("imported");
  const importFileRef = useRef<HTMLInputElement>(null);
  const openModalAfterCreateRef = useRef(false);
  const [editorModalOpen, setEditorModalOpen] = useState(false);
  const [bankFilterExpanded, setBankFilterExpanded] = useState(false);
  const [newSubject, setNewSubject] = useState(() => i18n.t("bank:defaultSubject"));
  const [newCollection, setNewCollection] = useState("main");
  const [newId, setNewId] = useState("new_question_001");
  const [newType, setNewType] = useState("choice");
  /** 新建题组：混编或同型 */
  const [newGroupUnified, setNewGroupUnified] = useState<string>("choice");
  const [newGroupMaterial, setNewGroupMaterial] = useState("");
  const [editorTab, setEditorTab] = useState<"form" | "yaml">("form");
  const [rawYaml, setRawYaml] = useState("");
  const [metaRows, setMetaRows] = useState<{ key: string; value: string }[]>([]);
  const [mathOpen, setMathOpen] = useState(false);
  const [mermaidOpen, setMermaidOpen] = useState(false);
  /** 题目全限定 id → 已关联知识点（用于列表与编辑区标签） */
  const [graphLinkIndex, setGraphLinkIndex] = useState<
    Record<string, { id: string; canonical_name: string; node_kind: string }[]>
  >({});
  const contentRef = useRef<HTMLTextAreaElement>(null);
  const answerRef = useRef<HTMLTextAreaElement>(null);
  const analysisRef = useRef<HTMLTextAreaElement>(null);
  const materialGroupRef = useRef<HTMLTextAreaElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  /** 插入目标（公式 / Mermaid / 图片） */
  const embedKindRef = useRef<EmbedKind | null>(null);
  const imageEmbedKindRef = useRef<EmbedKind | null>(null);
  /** Saved when opening Math/Mermaid overlay — focus moves and loses textarea selection. */
  const embedSelectionRef = useRef<{ start: number; end: number } | null>(null);

  const { setPageContext } = useAgentContext();

  useEffect(() => {
    if (selectedId && detail) {
      const raw =
        typeof detail.question?.content === "string" ? detail.question.content : detail.qualified_id;
      const preview = raw.replace(/\s+/g, " ").slice(0, 48);
      const suffix = preview
        ? ` — ${preview}${preview.length >= 48 ? "…" : ""}`
        : "";
      setPageContext({
        current_page: "bank",
        selected_resource_type: "question",
        selected_resource_id: selectedId,
        summary: t("bank:pageContextWithId", { id: detail.qualified_id, suffix }),
      });
    } else {
      setPageContext({
        current_page: "bank",
        summary: t("bank:pageContextBrowse"),
      });
    }
    return () => setPageContext(null);
  }, [selectedId, detail, setPageContext, t]);

  const beginMathEmbed = useCallback((kind: EmbedKind, sel: { start: number; end: number } | null) => {
    embedKindRef.current = kind;
    embedSelectionRef.current = sel;
    setMathOpen(true);
  }, []);

  const beginMermaidEmbed = useCallback((kind: EmbedKind, sel: { start: number; end: number } | null) => {
    embedKindRef.current = kind;
    embedSelectionRef.current = sel;
    setMermaidOpen(true);
  }, []);

  const beginImageEmbed = useCallback((kind: EmbedKind, sel: { start: number; end: number } | null) => {
    imageEmbedKindRef.current = kind;
    embedSelectionRef.current = sel;
    imageInputRef.current?.click();
  }, []);

  const insertSnippet = useCallback((snippet: string) => {
    setDetail((d) => {
      if (!d) {
        return d;
      }
      const kind = embedKindRef.current;
      embedKindRef.current = null;
      const saved = embedSelectionRef.current;
      embedSelectionRef.current = null;
      if (!kind) {
        return d;
      }

      if (kind.k === "qo") {
        const key = kind.key;
        const opts = { ...(d.question.options ?? {}) };
        const prev = opts[key] ?? "";
        const start = saved?.start ?? prev.length;
        const end = saved?.end ?? prev.length;
        const next = prev.slice(0, start) + snippet + prev.slice(end);
        const pos = start + snippet.length;
        opts[key] = next;
        requestAnimationFrame(() => {
          const ta = document.getElementById(`bank-opt-q-${key}`) as HTMLTextAreaElement | null;
          if (ta) {
            ta.focus();
            ta.setSelectionRange(pos, pos);
          }
        });
        return { ...d, question: { ...d.question, options: opts } };
      }

      if (kind.k === "gio" && d.question_group) {
        const { i, key } = kind;
        const g = d.question_group;
        const items = [...g.items];
        const row = { ...items[i] };
        const opts = { ...(row.options ?? {}) };
        const prev = opts[key] ?? "";
        const start = saved?.start ?? prev.length;
        const end = saved?.end ?? prev.length;
        const next = prev.slice(0, start) + snippet + prev.slice(end);
        const pos = start + snippet.length;
        opts[key] = next;
        items[i] = { ...row, options: opts };
        const m = d.question.id.match(/__(\d{2})$/);
        const midx = m ? parseInt(m[1], 10) - 1 : -1;
        let q = d.question;
        if (midx === i) {
          q = { ...q, options: opts };
        }
        requestAnimationFrame(() => {
          const ta = document.getElementById(`bank-opt-gi-${i}-${key}`) as HTMLTextAreaElement | null;
          if (ta) {
            ta.focus();
            ta.setSelectionRange(pos, pos);
          }
        });
        return { ...d, question_group: { ...g, items }, question: q };
      }

      if (kind.k === "q") {
        const key = kind.f;
        const ref = kind.f === "content" ? contentRef : kind.f === "answer" ? answerRef : analysisRef;
        const prev = d.question[key];
        const start = saved?.start ?? prev.length;
        const end = saved?.end ?? prev.length;
        const next = prev.slice(0, start) + snippet + prev.slice(end);
        const pos = start + snippet.length;
        requestAnimationFrame(() => {
          const ta = ref.current;
          if (ta) {
            ta.focus();
            ta.setSelectionRange(pos, pos);
          }
        });
        return { ...d, question: { ...d.question, [key]: next } };
      }

      if (kind.k === "gm" && d.question_group) {
        const prev = d.question_group.material;
        const start = saved?.start ?? prev.length;
        const end = saved?.end ?? prev.length;
        const next = prev.slice(0, start) + snippet + prev.slice(end);
        const pos = start + snippet.length;
        requestAnimationFrame(() => {
          const ta = materialGroupRef.current;
          if (ta) {
            ta.focus();
            ta.setSelectionRange(pos, pos);
          }
        });
        return {
          ...d,
          question_group: { ...d.question_group, material: next },
          question: { ...d.question, group_material: next },
        };
      }

      if (kind.k === "gi" && d.question_group) {
        const { i, f } = kind;
        const g = d.question_group;
        const items = [...g.items];
        const row = { ...items[i] };
        const prev = (row[f] as string) ?? "";
        const start = saved?.start ?? prev.length;
        const end = saved?.end ?? prev.length;
        const next = prev.slice(0, start) + snippet + prev.slice(end);
        const pos = start + snippet.length;
        (row as { content: string; answer: string; analysis: string })[f] = next;
        items[i] = row;
        const m = d.question.id.match(/__(\d{2})$/);
        const midx = m ? parseInt(m[1], 10) - 1 : -1;
        let q = d.question;
        if (midx === i) {
          if (f === "content") {
            q = { ...q, content: next };
          } else if (f === "answer") {
            q = { ...q, answer: next };
          } else {
            q = { ...q, analysis: next };
          }
        }
        requestAnimationFrame(() => {
          const ta = document.getElementById(`bank-gi-${i}-${f}`) as HTMLTextAreaElement | null;
          if (ta) {
            ta.focus();
            ta.setSelectionRange(pos, pos);
          }
        });
        return { ...d, question_group: { ...g, items }, question: q };
      }

      return d;
    });
  }, []);

  const onImageFileSelected = useCallback(
    async (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      const kind = imageEmbedKindRef.current;
      imageEmbedKindRef.current = null;
      e.target.value = "";
      if (!file || !detail || !kind) {
        return;
      }
      setBusy(true);
      onError(null);
      try {
        const fd = new FormData();
        fd.append("file", file);
        const enc = encodeURIComponent(detail.qualified_id);
        const r = await apiPostFormData<{ marker: string }>(`/api/bank/items/${enc}/image`, fd);
        embedKindRef.current = kind;
        insertSnippet(r.marker);
      } catch (err) {
        onError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [detail, insertSnippet, onError],
  );

  const loadList = useCallback(async () => {
    onError(null);
    const [c, it, sub] = await Promise.all([
      apiGet<{ collections: { id: string; label: string }[] }>("/api/bank/collections"),
      apiGet<{ items: BankListItem[] }>("/api/bank/items"),
      apiGet<{ subjects: string[] }>("/api/bank/subjects"),
    ]);
    setCollections(c.collections.map((x) => ({ id: x.id, label: x.label })));
    setItems(it.items);
    setSubjects(sub.subjects);
    try {
      const idx = await apiGraphQuestionBindingsIndex();
      setGraphLinkIndex(idx.index ?? {});
    } catch {
      setGraphLinkIndex({});
    }
  }, [onError]);

  useEffect(() => {
    void loadList().catch((e: Error) => onError(e.message));
  }, [loadList, onError]);

  const collectionOptions = useMemo(() => {
    if (filterSubject === "__all__") {
      return collections;
    }
    return collections.filter((c) => {
      if (c.id === "main") {
        return filterSubject === "main";
      }
      return c.id.startsWith(`${filterSubject}/`);
    });
  }, [collections, filterSubject]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const collapsed = collapseGroupRowsForList(items);
    return collapsed.filter((it) => {
      if (filterSubject !== "__all__" && (it.subject ?? "") !== filterSubject) {
        return false;
      }
      if (filterCollection !== "__all__" && it.collection !== filterCollection) {
        return false;
      }
      if (filterType !== "__all__" && it.type !== filterType) {
        return false;
      }
      if (!q) {
        return true;
      }
      const gid = (it.group_id ?? "").toLowerCase();
      const gmat = (it.group_material ?? "").toLowerCase();
      return (
        it.qualified_id.toLowerCase().includes(q) ||
        it.content_preview.toLowerCase().includes(q) ||
        JSON.stringify(it.metadata ?? {}).toLowerCase().includes(q) ||
        (gid && gid.includes(q)) ||
        (gmat && gmat.includes(q))
      );
    });
  }, [items, filterSubject, filterCollection, filterType, search]);

  const bankFilterSummary = useMemo(() => {
    const all = t("bank:filterAllLabel");
    const sub = filterSubject === "__all__" ? all : filterSubject;
    const collLabel =
      filterCollection === "__all__"
        ? all
        : collections.find((c) => c.id === filterCollection)?.label ?? filterCollection;
    const typLabel =
      filterType === "__all__"
        ? all
        : filterType === "group"
          ? t("bank:typeGroup")
          : t(`lib:questionTypes.${filterType}`);
    const suffix = search.trim() ? t("bank:filterSearchActive") : "";
    return `${sub} · ${collLabel} · ${typLabel}${suffix}`;
  }, [filterSubject, filterCollection, filterType, search, collections, t]);

  /** 导入目标科目：接口科目 + 列表中已出现的科目 */
  const importSubjectList = useMemo(() => {
    const fromItems = [...new Set(items.map((i) => i.subject).filter(Boolean) as string[])];
    return [...new Set([...subjects, ...fromItems])].sort((a, b) => localeCompareStrings(a, b));
  }, [subjects, items]);

  const importSubjectSelectValue = useMemo(() => {
    if (importSubjectList.length === 0) {
      return "__custom__";
    }
    const subjTrim = importSubject.trim();
    if (subjTrim === "") {
      return "__custom__";
    }
    const match = importSubjectList.find((s) => s === importSubject || s === subjTrim);
    return match ?? "__custom__";
  }, [importSubject, importSubjectList]);

  const importSummaryHint = useMemo(() => {
    const sub = importSubject.trim() || t("bank:importSubjectUnset");
    const coll = importTarget.trim() || t("bank:importCollectionUnset");
    return `${sub} → ${coll}`;
  }, [importSubject, importTarget, t]);

  const loadDetail = useCallback(
    async (qid: string) => {
      onError(null);
      const enc = encodeURIComponent(qid);
      const d = await apiGet<{
        qualified_id: string;
        question: QuestionJson | null;
        question_display?: QuestionJson | null;
        file_yaml: string;
        storage_path: string;
        storage_kind: string;
        question_group?: QuestionGroupJson | null;
        question_group_preview?: { material: string; items: GroupMemberJson[] } | null;
      }>(`/api/bank/items/${enc}`);
      let detailState: BankDetailState;
      if (!d.question && d.question_group) {
        const ug = d.question_group.unified;
        const t = ug === false ? "choice" : typeof ug === "string" ? ug : "choice";
        detailState = {
          ...d,
          question: {
            id: `${d.question_group.id}__01`,
            type: t,
            content: "",
            answer: "",
            analysis: "",
            metadata: {},
            options: t === "choice" ? { A: "", B: "", C: "", D: "" } : null,
            group_material: d.question_group.material,
          },
          question_display: undefined,
        };
      } else {
        detailState = {
          ...(d as BankDetailState),
          question_display: d.question_display ?? undefined,
        };
      }
      setDetail(detailState);
      setRawYaml(detailState.file_yaml);
      const m = detailState.question.metadata ?? {};
      setMetaRows(Object.keys(m).length ? Object.entries(m).map(([k, v]) => ({ key: k, value: String(v) })) : [{ key: "", value: "" }]);
      setEditorTab("form");
    },
    [onError],
  );

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setEditorModalOpen(false);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        await loadDetail(selectedId);
        if (!cancelled && openModalAfterCreateRef.current) {
          openModalAfterCreateRef.current = false;
          setEditorModalOpen(true);
        }
      } catch (e) {
        if (!cancelled) {
          onError(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId, loadDetail, onError]);

  function buildQuestionFromForm(): QuestionJson {
    if (!detail) {
      throw new Error(t("bank:errors.noQuestion"));
    }
    const q = { ...detail.question };
    const meta: Record<string, unknown> = {};
    for (const row of metaRows) {
      if (row.key.trim()) {
        meta[row.key.trim()] = row.value;
      }
    }
    q.metadata = meta;
    if (q.type === "choice") {
      q.options = { ...(detail.question.options ?? { A: "", B: "", C: "", D: "" }) };
    } else {
      q.options = null;
    }
    return q;
  }

  function buildQuestionGroupFromForm(): QuestionGroupJson {
    if (!detail?.question_group) {
      throw new Error(t("bank:errors.noGroup"));
    }
    const g = detail.question_group;
    const unified = g.unified === false ? false : g.unified;
    const items = g.items.map((it) => {
      let options: Record<string, string> | undefined;
      const itemType =
        unified === false ? (it.type ?? "choice") : typeof unified === "string" ? unified : "choice";
      if (itemType === "choice") {
        options = { ...(it.options ?? { A: "", B: "", C: "", D: "" }) };
      }
      if (unified === false) {
        return {
          type: it.type ?? "choice",
          content: it.content,
          answer: it.answer,
          analysis: it.analysis ?? "",
          metadata: (it.metadata ?? {}) as Record<string, unknown>,
          ...(options ? { options } : {}),
        };
      }
      return {
        content: it.content,
        answer: it.answer,
        analysis: it.analysis ?? "",
        metadata: (it.metadata ?? {}) as Record<string, unknown>,
        ...(options ? { options } : {}),
      };
    });
    return {
      id: g.id,
      type: "group",
      material: g.material,
      unified,
      items,
    };
  }

  async function saveForm() {
    if (!detail) {
      return;
    }
    setBusy(true);
    onError(null);
    try {
      const enc = encodeURIComponent(detail.qualified_id);
      if (detail.question_group) {
        const body = buildQuestionGroupFromForm();
        await apiPut(`/api/bank/items/${enc}`, body);
      } else {
        const q = buildQuestionFromForm();
        await apiPut(`/api/bank/items/${enc}`, q);
      }
      await loadList();
      await loadDetail(detail.qualified_id);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveRawYaml() {
    if (!detail) {
      return;
    }
    setBusy(true);
    onError(null);
    try {
      {
        const parsed = yaml.load(rawYaml) as unknown;
        if (!parsed || typeof parsed !== "object") {
          throw new Error(t("bank:errors.yamlMustBeObject"));
        }
        const obj = parsed as Record<string, unknown>;
        const enc = encodeURIComponent(detail.qualified_id);
        if (obj.type === "group") {
          await apiPut(`/api/bank/items/${enc}`, obj as unknown as QuestionGroupJson);
        } else {
          const q = { ...obj } as unknown as QuestionJson;
          await apiPut(`/api/bank/items/${enc}`, q);
        }
      }
      await loadList();
      await loadDetail(detail.qualified_id);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function createQuestion() {
    setBusy(true);
    onError(null);
    try {
      const subj = newSubject.trim();
      const coll = newCollection.trim();
      const qid = newId.trim();
      let body: { subject: string; collection: string; question: QuestionJson | QuestionGroupJson };
      if (newType === "group") {
        const unified = newGroupUnified === "mixed" ? false : newGroupUnified;
        const items = defaultItemsForNewGroup(newGroupUnified, t("placeholderSubItem"));
        body = {
          subject: subj,
          collection: coll,
          question: {
            id: qid,
            type: "group",
            material: newGroupMaterial.trim() || t("sharedMaterialDefault"),
            unified,
            items,
          },
        };
      } else {
        body = {
          subject: subj,
          collection: coll,
          question: {
            id: qid,
            type: newType,
            content: t("latexStemPh"),
            options: newType === "choice" ? { A: "", B: "", C: "", D: "" } : null,
            answer: "",
            analysis: "",
            metadata: {},
          },
        };
      }
      const r = await apiPost<{ ok: boolean; qualified_id: string }>("/api/bank/items", body);
      await loadList();
      openModalAfterCreateRef.current = true;
      setSelectedId(r.qualified_id);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function doImport() {
    setBusy(true);
    onError(null);
    try {
      await apiPost("/api/bank/import", {
        yaml: importYaml,
        target_subject: importSubject.trim() || t("defaultTarget"),
        target_collection: importTarget.trim() || "imported",
      });
      setImportYaml("");
      await loadList();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function doImportFromFile(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) {
      return;
    }
    const name = f.name.toLowerCase();
    setBusy(true);
    onError(null);
    try {
      if (name.endsWith(".zip")) {
        const fd = new FormData();
        fd.append("file", f);
        fd.append("target_subject", importSubject.trim() || t("defaultTarget"));
        fd.append("target_collection", importTarget.trim() || "imported");
        const r = await apiPostFormData<{ written: number; warnings?: string[] }>("/api/bank/import-bundle", fd);
        if (r.warnings?.length) {
          window.alert(
            t("importWritten", { n: r.written, warnings: r.warnings.join("\n") }),
          );
        }
        await loadList();
      } else if (name.endsWith(".yaml") || name.endsWith(".yml")) {
        const text = await f.text();
        await apiPost("/api/bank/import", {
          yaml: text,
          target_subject: importSubject.trim() || t("defaultTarget"),
          target_collection: importTarget.trim() || "imported",
        });
        await loadList();
      } else {
        onError(t("errors.pickYamlZip"));
      }
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function doExportBundle() {
    if (filterCollection === "__all__") {
      onError(t("errors.selectCollectionFirst"));
      return;
    }
    setBusy(true);
    onError(null);
    try {
      await downloadBankExportBundle(filterCollection);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function removeQuestion() {
    if (!detail || !selectedId) {
      return;
    }
    const isGroup = Boolean(detail.question_group);
    if (
      !confirm(
        isGroup
          ? t("errors.deleteGroup", { id: detail.question_group!.id })
          : t("errors.deleteQuestion", { id: selectedId }),
      )
    ) {
      return;
    }
    setBusy(true);
    onError(null);
    try {
      const enc = encodeURIComponent(selectedId);
      const sp = detail.storage_path
        ? `?storage_path=${encodeURIComponent(detail.storage_path)}`
        : "";
      await apiDelete(`/api/bank/items/${enc}${sp}`);
      setSelectedId(null);
      setDetail(null);
      await loadList();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  /** 已保存题目：服务端展开插图占位符；编辑未保存时回退到表单原文 */
  const previewQ = useMemo(() => {
    if (!detail) return null;
    return detail.question_display ?? detail.question ?? null;
  }, [detail]);

  const previewGroup = useMemo(() => {
    if (!detail?.question_group) return null;
    const g = detail.question_group;
    const p = detail.question_group_preview;
    if (!p) return g;
    return { ...g, material: p.material, items: p.items };
  }, [detail]);

  return (
    <>
    <div className="flex h-full min-h-0 flex-col lg:flex-row">
      {/* 左：筛选 + 列表 + 导入 */}
      <section className="flex w-full shrink-0 flex-col border-slate-200 bg-white lg:w-[min(100%,300px)] lg:border-r">
        <div className="border-b border-slate-100 p-3">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{t("title")}</h2>
          <p className="mt-1 text-[11px] text-slate-500">
            {t("structureHint")}{" "}
            <code className="rounded bg-slate-100 px-0.5">{t("structurePath")}</code>
            {t("structureHintTail")}
          </p>
          <button
            type="button"
            className="mt-3 flex w-full items-center justify-between rounded-md border border-slate-200 bg-slate-50 px-2 py-1.5 text-left text-xs font-medium text-slate-800 hover:bg-slate-100"
            onClick={() => setBankFilterExpanded((v) => !v)}
          >
            <span>{t("filter")}</span>
            <span className="truncate pl-2 text-[10px] font-normal text-slate-500">
              {bankFilterExpanded ? t("filterTapToCollapse") : bankFilterSummary}
            </span>
          </button>
          {bankFilterExpanded && (
            <div className="mt-2 space-y-2">
              <label className="block text-[11px] font-medium text-slate-600">
                {t("subject")}
                <select
                  className="mt-0.5 w-full rounded-md border border-slate-300 bg-slate-50 px-2 py-1.5 text-sm"
                  value={filterSubject}
                  onChange={(e) => {
                    setFilterSubject(e.target.value);
                    setFilterCollection("__all__");
                  }}
                >
                  <option value="__all__">{t("filterAllLabel")}</option>
                  {(subjects.length ? subjects : [...new Set(items.map((i) => i.subject).filter(Boolean) as string[])]).map(
                    (s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ),
                  )}
                </select>
              </label>
              <label className="block text-[11px] font-medium text-slate-600">
                {t("collection")}
                <select
                  className="mt-0.5 w-full rounded-md border border-slate-300 bg-slate-50 px-2 py-1.5 text-sm"
                  value={filterCollection}
                  onChange={(e) => setFilterCollection(e.target.value)}
                >
                  <option value="__all__">{t("filterAllLabel")}</option>
                  {collectionOptions.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-[11px] font-medium text-slate-600">
                {t("questionType")}
                <select
                  className="mt-0.5 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                  value={filterType}
                  onChange={(e) => setFilterType(e.target.value)}
                >
                  <option value="__all__">{t("filterAllLabel")}</option>
                  <option value="group">{t("typeGroup")}</option>
                  {QUESTION_TYPE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {t(`lib:questionTypes.${o.value}`)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-[11px] font-medium text-slate-600">
                {t("search")}
                <input
                  className="mt-0.5 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t("searchPlaceholder")}
                />
              </label>
            </div>
          )}
          <div className="mt-2">
            <button
              type="button"
              className="w-full rounded-md border border-slate-800 bg-slate-50 py-1.5 text-xs font-medium text-slate-800 hover:bg-slate-100 disabled:opacity-50"
              disabled={busy || filterCollection === "__all__"}
              title={
                filterCollection === "__all__" ? t("exportNeedCollection") : undefined
              }
              onClick={() => void doExportBundle()}
            >
              {t("exportBundle")}
            </button>
            <p className="mt-1 text-[10px] leading-snug text-slate-500">
              {filterCollection === "__all__"
                ? t("exportHintNeedCollection")
                : t("exportHintScope", { path: filterCollection })}
            </p>
          </div>
          <details className="mt-3 rounded-md border border-slate-200 bg-white p-2">
            <summary className="cursor-pointer text-xs font-medium text-slate-700">{t("newQuestion")}</summary>
            <label className="mt-2 block text-[11px] font-medium text-slate-600">
              {t("newSubject")}
              <input
                className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1 text-sm"
                value={newSubject}
                onChange={(e) => setNewSubject(e.target.value)}
                placeholder={t("newSubjectPh")}
              />
            </label>
            <label className="mt-2 block text-[11px] font-medium text-slate-600">
              {t("newCollection")}
              <input
                className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1 text-sm"
                value={newCollection}
                onChange={(e) => setNewCollection(e.target.value)}
              />
            </label>
            <label className="mt-2 block text-[11px] font-medium text-slate-600">
              {t("newId")}
              <input
                className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1 font-mono text-sm"
                value={newId}
                onChange={(e) => setNewId(e.target.value)}
              />
            </label>
            <label className="mt-2 block text-[11px] font-medium text-slate-600">
              {t("newType")}
              <select
                className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1 text-sm"
                value={newType}
                onChange={(e) => setNewType(e.target.value)}
              >
                <option value="group">{t("typeGroup")}</option>
                {QUESTION_TYPE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {t(`lib:questionTypes.${o.value}`)}
                  </option>
                ))}
              </select>
            </label>
            {newType === "group" && (
              <div className="mt-2 space-y-2 rounded border border-slate-200 bg-slate-50 p-2">
                <label className="block text-[11px] font-medium text-slate-600">
                  {t("subItemMode")}
                  <select
                    className="mt-0.5 w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm"
                    value={newGroupUnified}
                    onChange={(e) => setNewGroupUnified(e.target.value)}
                  >
                    <option value="mixed">{t("mixedMode")}</option>
                    {QUESTION_TYPE_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {t("sameType", { label: t(`lib:questionTypes.${o.value}`) })}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block text-[11px] font-medium text-slate-600">
                  {t("sharedMaterial")}
                  <textarea
                    className="mt-0.5 w-full rounded border border-slate-300 bg-white px-2 py-1.5 font-mono text-xs"
                    rows={4}
                    value={newGroupMaterial}
                    onChange={(e) => setNewGroupMaterial(e.target.value)}
                    placeholder={t("sharedMaterialPh")}
                  />
                </label>
              </div>
            )}
            <button
              type="button"
              className="mt-2 w-full rounded-md border border-slate-300 py-1.5 text-xs font-medium disabled:opacity-50"
              disabled={busy || !newSubject.trim() || !newCollection.trim() || !newId.trim()}
              onClick={() => void createQuestion()}
            >
              {newType === "group" ? t("createGroup") : t("createDraft")}
            </button>
          </details>
          <details className="group mt-3 rounded-md border border-slate-200 bg-slate-50 p-2">
            <summary className="cursor-pointer list-none marker:hidden [&::-webkit-details-marker]:hidden">
              <span className="flex w-full items-start gap-2 text-left">
                <span
                  className="mt-0.5 inline-block shrink-0 text-[10px] text-slate-400 transition-transform duration-200 group-open:rotate-90"
                  aria-hidden
                >
                  ▸
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
                    <span className="text-xs font-medium text-slate-800">{t("importTitle")}</span>
                    <span className="max-w-[min(100%,11rem)] truncate text-[10px] font-normal text-slate-500">
                      {importSummaryHint}
                    </span>
                  </span>
                </span>
              </span>
            </summary>
            <p className="mt-2 text-[10px] leading-snug text-slate-500">{t("importFormats")}</p>
            <label className="mt-2 block text-[11px] font-medium text-slate-600">
              {t("targetSubject")}
              {importSubjectList.length > 0 ? (
                <div className="mt-0.5 space-y-1">
                  <select
                    className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm"
                    value={importSubjectSelectValue}
                    onChange={(e) => {
                      const v = e.target.value;
                      if (v === "__custom__") {
                        setImportSubject("");
                      } else {
                        setImportSubject(v);
                      }
                    }}
                  >
                    {importSubjectList.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                    <option value="__custom__">{t("otherSubject")}</option>
                  </select>
                  {importSubjectSelectValue === "__custom__" && (
                    <input
                      className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                      value={importSubject}
                      onChange={(e) => setImportSubject(e.target.value)}
                      placeholder={t("folderNamePh")}
                    />
                  )}
                </div>
              ) : (
                <input
                  className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1 text-sm"
                  value={importSubject}
                  onChange={(e) => setImportSubject(e.target.value)}
                  placeholder={t("folderNamePh")}
                />
              )}
            </label>
            <label className="mt-2 block text-[11px] font-medium text-slate-600">
              {t("targetCollection")}
              <input
                className="mt-0.5 w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm"
                value={importTarget}
                onChange={(e) => setImportTarget(e.target.value)}
                placeholder={t("targetCollectionPh")}
              />
            </label>
            <input
              ref={importFileRef}
              type="file"
              accept=".yaml,.yml,.zip,application/zip,application/x-yaml,text/yaml"
              className="hidden"
              aria-hidden
              onChange={(e) => void doImportFromFile(e)}
            />
            <button
              type="button"
              className="mt-2 w-full rounded-md bg-slate-900 py-1.5 text-xs font-medium text-white disabled:opacity-50"
              disabled={busy}
              onClick={() => importFileRef.current?.click()}
            >
              {t("pickAndImport")}
            </button>
            <details className="mt-2 rounded border border-slate-200 bg-white p-2">
              <summary className="cursor-pointer text-[11px] font-medium text-slate-700">{t("pasteYaml")}</summary>
              <p className="mt-1 text-[10px] text-slate-500">{t("pasteYamlHint")}</p>
              <textarea
                className="mt-2 w-full rounded border border-slate-300 font-mono text-xs"
                rows={5}
                placeholder={t("pasteYamlTextareaPh")}
                value={importYaml}
                onChange={(e) => setImportYaml(e.target.value)}
              />
              <button
                type="button"
                className="mt-2 w-full rounded-md border border-slate-800 bg-slate-50 py-1.5 text-xs font-medium text-slate-800 disabled:opacity-50"
                disabled={busy || !importYaml.trim()}
                onClick={() => void doImport()}
              >
                {t("importToCollection")}
              </button>
            </details>
          </details>
        </div>
        <ul className="min-h-0 flex-1 overflow-auto p-2">
          {items.length === 0 ? (
            <li className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 py-6 text-center text-sm text-slate-600">
              <p className="font-medium text-slate-800">{t("emptyList")}</p>
              <p className="mt-2 text-xs leading-relaxed text-slate-500">{t("emptyListHint")}</p>
            </li>
          ) : filtered.length === 0 ? (
            <li className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 py-6 text-center text-sm text-slate-600">
              <p className="font-medium text-slate-800">{t("emptyFilter")}</p>
              <p className="mt-2 text-xs text-slate-500">{t("emptyFilterHint")}</p>
            </li>
          ) : (
            filtered.map((it) => {
              const isBundle = (it.group_member_qualified_ids?.length ?? 0) > 1;
              const graphNodes = graphLinkIndex[it.qualified_id] ?? [];
              return (
                <li
                  key={it.qualified_id}
                  className={cn(
                    "mb-1 rounded-lg border px-2 py-2 transition-colors",
                    selectedId === it.qualified_id
                      ? "border-slate-900 bg-slate-100"
                      : "border-transparent bg-slate-50 hover:border-slate-200 hover:bg-white",
                  )}
                >
                  <button
                    type="button"
                    className="w-full text-left text-sm"
                    onClick={() => {
                      setSelectedId(it.qualified_id);
                      setEditorModalOpen(false);
                    }}
                  >
                    <span className="rounded bg-slate-200 px-1 py-0.5 text-[10px] font-medium text-slate-700">
                      {it.type === "group"
                        ? t("typeGroup")
                        : t(`lib:questionTypes.${it.type}`, { defaultValue: it.type })}
                    </span>
                    {isBundle ? (
                      <span className="ml-1 rounded bg-emerald-100 px-1 py-0.5 text-[10px] font-medium text-emerald-900">
                        {t("groupNItems", { n: it.group_member_qualified_ids!.length })}
                      </span>
                    ) : null}
                    <span className="ml-1 font-mono text-[11px] text-slate-800">
                      {isBundle && it.group_id ? `${it.collection} / ${it.group_id}` : it.qualified_id}
                    </span>
                    <div className="line-clamp-3 text-xs text-slate-600">{it.content_preview}</div>
                    {Object.keys(it.metadata ?? {}).length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {Object.entries(it.metadata).map(([k, v]) => (
                          <span key={k} className="rounded-full bg-slate-200/80 px-1.5 py-0.5 text-[10px] text-slate-600">
                            {k}:{String(v)}
                          </span>
                        ))}
                      </div>
                    )}
                  </button>
                  {graphNodes.length > 0 ? (
                    <div className="mt-1.5 flex flex-wrap gap-1 border-t border-slate-200/80 pt-1.5">
                      <span className="w-full text-[10px] font-medium text-slate-500">{t("knowledgePoints")}</span>
                      {graphNodes.map((n) => (
                        <button
                          key={n.id}
                          type="button"
                          className="rounded-full bg-sky-100 px-2 py-0.5 text-[10px] font-medium text-sky-900 hover:bg-sky-200"
                          onClick={() => onOpenGraphNode?.(n.id)}
                        >
                          {n.canonical_name}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </li>
              );
            })
          )}
        </ul>
      </section>

      {/* 中：编辑 */}
      <section className="min-w-0 flex-1 overflow-auto border-slate-200 bg-slate-50 p-4 lg:border-r">
        {!detail ? (
          <p className="text-sm text-slate-500">{t("selectLeft")}</p>
        ) : editorModalOpen ? (
          <p className="text-sm text-slate-600">{t("editingInModal")}</p>
        ) : (
          <>
            {graphLinkIndex[detail.qualified_id]?.length ? (
              <div className="mb-3 rounded-lg border border-sky-200 bg-sky-50/80 px-3 py-2">
                <p className="text-[11px] font-medium text-sky-900">{t("linkedNodes")}</p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {graphLinkIndex[detail.qualified_id]!.map((n) => (
                    <button
                      key={n.id}
                      type="button"
                      className="rounded-full bg-white px-2 py-0.5 text-xs font-medium text-sky-800 shadow-sm ring-1 ring-sky-200 hover:bg-sky-100"
                      onClick={() => onOpenGraphNode?.(n.id)}
                    >
                      {n.canonical_name}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            <BankQuestionEditorPanel
            detail={detail}
            setDetail={setDetail}
            busy={busy}
            editorTab={editorTab}
            setEditorTab={setEditorTab}
            rawYaml={rawYaml}
            setRawYaml={setRawYaml}
            metaRows={metaRows}
            setMetaRows={setMetaRows}
            contentRef={contentRef}
            answerRef={answerRef}
            analysisRef={analysisRef}
            materialGroupRef={materialGroupRef}
            imageInputRef={imageInputRef}
            beginMathEmbed={beginMathEmbed}
            beginMermaidEmbed={beginMermaidEmbed}
            beginImageEmbed={beginImageEmbed}
            onImageFileSelected={onImageFileSelected}
            onRemove={removeQuestion}
            onSave={saveForm}
            onSaveYaml={saveRawYaml}
            removeLabel={detail.question_group ? t("removeGroup") : t("remove")}
          />
          </>
        )}
      </section>

      {/* 右：预览 */}
      <section className="w-full shrink-0 border-slate-200 bg-white p-4 lg:w-[min(100%,340px)] lg:border-l">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{t("livePreview")}</h3>
        {!previewQ && !previewGroup ? (
          <p className="mt-4 text-sm text-slate-500">{t("previewEmpty")}</p>
        ) : previewGroup ? (
          <div className="mt-3 space-y-4 text-sm">
            <div>
              <p className="text-[11px] font-medium text-slate-500">{t("sharedMaterialLabel")}</p>
              <ContentWithPrimeBrush text={previewGroup.material} className="mt-1 text-slate-900" />
            </div>
            {previewGroup.items.map((it, i) => {
              const rowIsChoice =
                previewGroup.unified === false
                  ? (it.type ?? "choice") === "choice"
                  : typeof previewGroup.unified === "string" && previewGroup.unified === "choice";
              return (
              <div key={i} className="border-t border-slate-100 pt-3">
                <p className="text-[11px] font-medium text-slate-500">{t("subItemIndex", { n: i + 1 })}</p>
                <ContentWithPrimeBrush text={it.content} className="mt-1 text-slate-900" />
                {rowIsChoice && (
                  <div>
                    <p className="text-[11px] font-medium text-slate-500">{t("options")}</p>
                    <ul className="mt-1 list-inside list-disc text-slate-700">
                      {Object.entries(it.options ?? { A: "", B: "", C: "", D: "" }).map(([k, v]) => (
                        <li key={k}>
                          <strong>{k}</strong>{" "}
                          <span className="inline-block align-top">
                            <ContentWithPrimeBrush text={v} className="inline" />
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <details>
                  <summary className="cursor-pointer text-xs text-slate-600">{t("answer")}</summary>
                  <ContentWithPrimeBrush text={it.answer} className="mt-1" />
                </details>
                <details>
                  <summary className="cursor-pointer text-xs text-slate-600">{t("analysis")}</summary>
                  <ContentWithPrimeBrush text={it.analysis || ""} className="mt-1" />
                </details>
              </div>
            );
            })}
          </div>
        ) : (
          <div className="mt-3 space-y-4 text-sm">
            <div>
              <p className="text-[11px] font-medium text-slate-500">{t("stem")}</p>
              <ContentWithPrimeBrush text={previewQ!.content} className="mt-1 text-slate-900" />
            </div>
            {previewQ!.type === "choice" && previewQ!.options && (
              <div>
                <p className="text-[11px] font-medium text-slate-500">{t("options")}</p>
                <ul className="mt-1 list-inside list-disc text-slate-700">
                  {Object.entries(previewQ!.options).map(([k, v]) => (
                    <li key={k}>
                      <strong>{k}</strong>{" "}
                      <span className="inline-block align-top">
                        <ContentWithPrimeBrush text={v} className="inline" />
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <details>
              <summary className="cursor-pointer text-xs text-slate-600">{t("answer")}</summary>
              <ContentWithPrimeBrush text={previewQ!.answer} className="mt-1" />
            </details>
            <details>
              <summary className="cursor-pointer text-xs text-slate-600">{t("analysis")}</summary>
              <ContentWithPrimeBrush text={previewQ!.analysis || ""} className="mt-1" />
            </details>
          </div>
        )}
      </section>
    </div>
    {detail && editorModalOpen && (
      <div
        className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4"
        onClick={() => setEditorModalOpen(false)}
        role="presentation"
      >
        <div
          className="mt-4 w-full max-w-3xl max-h-[min(92vh,100%)] overflow-y-auto rounded-xl border border-slate-200 bg-slate-50 p-2 shadow-2xl"
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-modal="true"
        >
          <BankQuestionEditorPanel
            detail={detail}
            setDetail={setDetail}
            busy={busy}
            editorTab={editorTab}
            setEditorTab={setEditorTab}
            rawYaml={rawYaml}
            setRawYaml={setRawYaml}
            metaRows={metaRows}
            setMetaRows={setMetaRows}
            contentRef={contentRef}
            answerRef={answerRef}
            analysisRef={analysisRef}
            materialGroupRef={materialGroupRef}
            imageInputRef={imageInputRef}
            beginMathEmbed={beginMathEmbed}
            beginMermaidEmbed={beginMermaidEmbed}
            beginImageEmbed={beginImageEmbed}
            onImageFileSelected={onImageFileSelected}
            onRemove={removeQuestion}
            onSave={saveForm}
            onSaveYaml={saveRawYaml}
            onClose={() => setEditorModalOpen(false)}
            removeLabel={detail.question_group ? t("removeGroup") : t("remove")}
          />
        </div>
      </div>
    )}
    <MathInsertOverlay
      open={mathOpen}
      onClose={() => {
        setMathOpen(false);
        embedKindRef.current = null;
        embedSelectionRef.current = null;
      }}
      onConfirm={(snippet) => {
        insertSnippet(snippet);
      }}
    />
    <MermaidEditorModal
      open={mermaidOpen}
      onClose={() => {
        setMermaidOpen(false);
        embedKindRef.current = null;
        embedSelectionRef.current = null;
      }}
      onConfirm={(fencedBlock) => {
        insertSnippet(fencedBlock);
      }}
    />
    </>
  );
}
