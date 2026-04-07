import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import yaml from "js-yaml";
import { ChevronDown, ChevronUp, Plus, Save, Trash2 } from "lucide-react";
import { apiGet, apiPost, apiPut } from "../api/client";
import { useAgentContext } from "../contexts/AgentContext";
import i18n from "../i18n/i18n";
import { cn } from "../lib/utils";

type TemplateSectionRow = {
  section_id: string;
  type: string;
  required_count: number;
  score_per_item: number;
  describe?: string | null;
};

/** 与后端 `MermaidPdfOptions` 一致；空字符串保存时用默认值 */
type MermaidPdfOpts = {
  landscape_width?: string;
  portrait_width?: string;
  portrait_max_height?: string;
};

/** 与后端 `PrimeBrushPdfOptions` 一致 */
type PrimeBrushPdfOpts = {
  latex_width?: string;
};

type LayoutOpts = {
  margin_cm?: number;
  body_font_size_pt?: number;
  show_binding_line?: boolean;
  show_name_column?: boolean;
  mermaid_pdf?: MermaidPdfOpts;
  primebrush_pdf?: PrimeBrushPdfOpts;
};

/** 与 ``*.tex.j2`` 同目录的 ``*.metadata_ui.yaml`` 中字段一致；由 API 返回，不在前端写死键名 */
type MetadataUiField = {
  key: string;
  label: string;
  kind: string;
  hint?: string;
  placeholder?: string;
  rows?: number;
  options?: { value: string; label: string }[];
  min?: number;
  max?: number;
  step?: number;
  omit_values?: unknown[];
};

/** 内置版面表单负责的键由 GET /api/templates/parsed 的 layout_builtin_keys 提供 */
function splitMetadataDefaults(
  raw: unknown,
  builtinKeys: Set<string>,
): { layout: LayoutOpts; extra: Record<string, unknown> } {
  const md =
    raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
  const extra: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(md)) {
    if (!builtinKeys.has(k)) {
      extra[k] = v;
    }
  }
  return {
    layout: {
      margin_cm: typeof md.margin_cm === "number" ? md.margin_cm : undefined,
      body_font_size_pt: typeof md.body_font_size_pt === "number" ? md.body_font_size_pt : undefined,
      show_binding_line: Boolean(md.show_binding_line),
      show_name_column: Boolean(md.show_name_column),
      mermaid_pdf: (() => {
        const m = md.mermaid_pdf as MermaidPdfOpts | undefined;
        if (!m || typeof m !== "object") {
          return undefined;
        }
        return {
          landscape_width: m.landscape_width != null ? String(m.landscape_width) : "",
          portrait_width: m.portrait_width != null ? String(m.portrait_width) : "",
          portrait_max_height: m.portrait_max_height != null ? String(m.portrait_max_height) : "",
        };
      })(),
      primebrush_pdf: (() => {
        const p = md.primebrush_pdf as PrimeBrushPdfOpts | undefined;
        if (!p || typeof p !== "object") {
          return undefined;
        }
        return { latex_width: p.latex_width != null ? String(p.latex_width) : "" };
      })(),
    },
    extra,
  };
}

function serializeExtraForYaml(
  key: string,
  value: unknown,
  fields: MetadataUiField[],
): unknown | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  const spec = fields.find((f) => f.key === key);
  if (!spec) {
    if (typeof value === "string" && value.trim() === "") {
      return undefined;
    }
    return value;
  }
  if (spec.kind === "text" || spec.kind === "textarea") {
    const s = String(value);
    if (s.trim() === "") {
      return undefined;
    }
    return value;
  }
  if (spec.kind === "select") {
    const s = String(value);
    const omit = spec.omit_values ?? [];
    if (omit.some((x) => String(x) === s)) {
      return undefined;
    }
    return value;
  }
  if (spec.kind === "checkbox") {
    return Boolean(value);
  }
  if (spec.kind === "number") {
    const n = Number(value);
    if (Number.isNaN(n)) {
      return undefined;
    }
    return n;
  }
  return value;
}

function metadataUiSelectValue(field: MetadataUiField, extra: Record<string, unknown>): string {
  const cur = extra[field.key];
  if (cur !== undefined && cur !== null && String(cur) !== "") {
    return String(cur);
  }
  return field.options?.[0]?.value ?? "";
}

/** 从模板文件里读到的宽度字段，转成百分比数字（20–100）供表单显示 */
function parseLinewidthPercent(raw: string | undefined, fallbackPercent: number): number {
  if (!raw?.trim()) {
    return fallbackPercent;
  }
  const m = raw.trim().match(/^(\d+(?:\.\d+)?)\\linewidth\s*$/);
  if (!m) {
    return fallbackPercent;
  }
  const v = parseFloat(m[1]) * 100;
  return Math.min(100, Math.max(20, Math.round(v * 100) / 100));
}

function linewidthPercentToLatex(percent: number): string {
  const p = Math.min(100, Math.max(20, percent));
  if (p >= 99.999) {
    return "1\\linewidth";
  }
  const x = p / 100;
  const num = x.toFixed(4).replace(/\.?0+$/, "");
  return `${num}\\linewidth`;
}

/** 从 \\textheight 转成百分比（15–70） */
function parseTextheightPercent(raw: string | undefined, fallbackPercent: number): number {
  if (!raw?.trim()) {
    return fallbackPercent;
  }
  const m = raw.trim().match(/^(\d+(?:\.\d+)?)\\textheight\s*$/);
  if (!m) {
    return fallbackPercent;
  }
  const v = parseFloat(m[1]) * 100;
  return Math.min(70, Math.max(15, Math.round(v * 100) / 100));
}

function textheightPercentToLatex(percent: number): string {
  const p = Math.min(70, Math.max(15, percent));
  const x = p / 100;
  const num = x.toFixed(4).replace(/\.?0+$/, "");
  return `${num}\\textheight`;
}

/** 解析失败时的滑块回退（与后端模型默认几何含义一致） */
const FB_PIC_W = 90;
const FB_MER_L = 62;
const FB_MER_P = 52;
const FB_MER_H = 40;

function PdfPercentInput(props: {
  label: string;
  hint: string;
  value: number;
  min: number;
  max: number;
  onCommit: (pct: number) => void;
}) {
  const { label, hint, value, min, max, onCommit } = props;
  return (
    <label className="block text-xs text-slate-600">
      <span className="text-slate-700">{label}</span>
      <div className="mt-1 flex items-center gap-1.5">
        <input
          type="number"
          min={min}
          max={max}
          step="any"
          className="w-24 rounded border border-slate-300 px-2 py-1.5 text-sm tabular-nums"
          value={value}
          onChange={(e) => {
            const v = e.target.value;
            if (v === "") {
              return;
            }
            const n = Number(v);
            if (Number.isNaN(n)) {
              return;
            }
            onCommit(Math.min(max, Math.max(min, n)));
          }}
        />
        <span className="text-sm text-slate-600">%</span>
      </div>
      <p className="mt-0.5 text-[11px] leading-snug text-slate-400">{hint}</p>
    </label>
  );
}

type TemplateListRow = {
  id: string;
  path: string;
  layout: string;
  latex_base?: string;
  metadata_defaults?: LayoutOpts | null;
  sections: TemplateSectionRow[];
};

/** GET /api/templates/parsed */
type TemplateParsedResponse = {
  template_id: string;
  layout: string;
  latex_base: string;
  sections: TemplateSectionRow[];
  metadata_defaults: Record<string, unknown>;
  layout_builtin_keys: string[];
};

function draftFromParsed(parsed: TemplateParsedResponse): Draft {
  const keys = new Set(parsed.layout_builtin_keys);
  const { layout, extra } = splitMetadataDefaults(parsed.metadata_defaults, keys);
  return {
    template_id: parsed.template_id,
    layout: parsed.layout === "double_column" ? "double_column" : "single_column",
    latex_base: parsed.latex_base,
    sections: parsed.sections.map((s) => ({
      section_id: s.section_id,
      type: s.type,
      required_count: s.type === "text" ? 0 : Number(s.required_count ?? 0),
      score_per_item: Number(s.score_per_item ?? 0),
      describe: s.describe ?? "",
    })),
    metadata_defaults: layout,
    metadata_extra: { ...extra },
  };
}

function mermaidPdfEqual(
  a: { landscape_width: string; portrait_width: string; portrait_max_height: string },
  b: unknown,
): boolean {
  if (!b || typeof b !== "object" || Array.isArray(b)) {
    return false;
  }
  const o = b as Record<string, string>;
  return (
    a.landscape_width === o.landscape_width &&
    a.portrait_width === o.portrait_width &&
    a.portrait_max_height === o.portrait_max_height
  );
}

function primebrushPdfEqual(a: { latex_width: string }, b: unknown): boolean {
  if (!b || typeof b !== "object" || Array.isArray(b)) {
    return false;
  }
  const o = b as Record<string, string>;
  return a.latex_width === o.latex_width;
}

type LatexBasesResponse = {
  shipped: string[];
  in_project: string[];
  choices: string[];
};

type Draft = {
  template_id: string;
  layout: "single_column" | "double_column";
  latex_base: string;
  sections: TemplateSectionRow[];
  /** 内置表单维护的 metadata_defaults 子集（边距、插图尺寸等） */
  metadata_defaults: LayoutOpts;
  /** 其余键由 latex_base 配套 ``*.metadata_ui.yaml`` 动态编辑，并原样写入模板 YAML */
  metadata_extra: Record<string, unknown>;
};

function createDefaultDraft(): Draft {
  return {
    template_id: "new_template",
    layout: "single_column",
    latex_base: "exam-zh-base.tex.j2",
    sections: [
      {
        section_id: i18n.t("template:defaultSectionIntro"),
        type: "text",
        required_count: 0,
        score_per_item: 0,
        describe: "",
      },
    ],
    metadata_defaults: {},
    metadata_extra: {},
  };
}

/** 与后端 `SectionKind` 一致；展示文案由 template:sectionKind.* 提供 */
const SECTION_KIND_VALUES = [
  "text",
  "group",
  "choice",
  "fill",
  "judge",
  "short_answer",
  "reasoning",
  "essay",
] as const;

const FALLBACK_LATEX_BASES: LatexBasesResponse = {
  shipped: ["exam-zh-base.tex.j2"],
  in_project: [],
  choices: ["exam-zh-base.tex.j2"],
};

export function TemplateWorkspace({ onError }: { onError: (s: string | null) => void }) {
  const { t } = useTranslation("template");
  const { setPageContext } = useAgentContext();
  const [templates, setTemplates] = useState<TemplateListRow[]>([]);
  const [path, setPath] = useState("");
  const [draft, setDraft] = useState<Draft>(() => createDefaultDraft());
  const [yamlTab, setYamlTab] = useState("");
  const [tab, setTab] = useState<"visual" | "yaml">("visual");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [latexBasesInfo, setLatexBasesInfo] = useState<LatexBasesResponse>(FALLBACK_LATEX_BASES);
  const [metadataUi, setMetadataUi] = useState<{
    fields: MetadataUiField[];
    source: string | null;
    warnings: string[];
  }>({ fields: [], source: null, warnings: [] });

  const [layoutBuiltinKeys, setLayoutBuiltinKeys] = useState<string[]>([]);
  const [editorDefaults, setEditorDefaults] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (!path) {
      setPageContext({ current_page: "template", summary: t("pageSummaryPick") });
    } else {
      const leaf = path.includes("/") ? path.split("/").pop() : path;
      setPageContext({
        current_page: "template",
        selected_resource_type: "template_file",
        selected_resource_id: path,
        summary: t("pageSummaryEdit", { path: leaf ?? path }),
      });
    }
    return () => setPageContext(null);
  }, [path, setPageContext, t]);

  const shippedSet = useMemo(() => new Set(latexBasesInfo.shipped), [latexBasesInfo.shipped]);
  const layoutBuiltinKeySet = useMemo(() => new Set(layoutBuiltinKeys), [layoutBuiltinKeys]);

  const refreshList = useCallback(async () => {
    const [tplRes, bases] = await Promise.all([
      apiGet<{ templates: TemplateListRow[] }>("/api/templates"),
      apiGet<LatexBasesResponse>("/api/templates/latex-bases").catch(() => FALLBACK_LATEX_BASES),
    ]);
    setLatexBasesInfo(
      bases.choices.length > 0
        ? bases
        : { ...bases, choices: FALLBACK_LATEX_BASES.choices },
    );
    setTemplates(tplRes.templates);
    return tplRes.templates;
  }, []);

  useEffect(() => {
    onError(null);
    void refreshList()
      .then((list) => {
        setPath((prev) => prev || (list[0]?.path ?? ""));
      })
      .catch((e: Error) => onError(e.message));
  }, [onError, refreshList]);

  useEffect(() => {
    void apiGet<{ metadata_defaults: Record<string, unknown> }>("/api/templates/editor-metadata-defaults")
      .then((r) => setEditorDefaults(r.metadata_defaults))
      .catch(() => setEditorDefaults(null));
  }, []);

  useEffect(() => {
    if (!path) {
      return;
    }
    onError(null);
    const q = encodeURIComponent(path);
    void Promise.all([
      apiGet<{ yaml: string }>(`/api/templates/raw?path=${q}`),
      apiGet<TemplateParsedResponse>(`/api/templates/parsed?path=${q}`),
    ])
      .then(([raw, parsed]) => {
        setYamlTab(raw.yaml);
        setLayoutBuiltinKeys(parsed.layout_builtin_keys);
        setDraft(draftFromParsed(parsed));
      })
      .catch((e: Error) => onError(e.message));
  }, [path, onError]);

  useEffect(() => {
    if (!path || !draft.latex_base) {
      setMetadataUi({ fields: [], source: null, warnings: [] });
      return;
    }
    const q = new URLSearchParams({ template_path: path, latex_base: draft.latex_base });
    void apiGet<{ fields: MetadataUiField[]; source: string | null; warnings?: string[] }>(
      `/api/templates/latex-metadata-ui?${q}`,
    )
      .then((r) =>
        setMetadataUi({
          fields: r.fields ?? [],
          source: r.source ?? null,
          warnings: r.warnings ?? [],
        }),
      )
      .catch(() => setMetadataUi({ fields: [], source: null, warnings: [] }));
  }, [path, draft.latex_base]);

  const yamlDump = useMemo(() => {
    const lo = draft.metadata_defaults;
    const loOut: Record<string, unknown> = {};
    const def = editorDefaults;
    const mDef = (def?.mermaid_pdf ?? {}) as MermaidPdfOpts;
    const pDef = (def?.primebrush_pdf ?? {}) as PrimeBrushPdfOpts;

    if (lo.margin_cm != null && !Number.isNaN(lo.margin_cm)) {
      if (!(def != null && lo.margin_cm === def.margin_cm)) {
        loOut.margin_cm = lo.margin_cm;
      }
    }
    if (lo.body_font_size_pt != null && !Number.isNaN(lo.body_font_size_pt)) {
      loOut.body_font_size_pt = lo.body_font_size_pt;
    }
    if (lo.show_binding_line) {
      loOut.show_binding_line = true;
    }
    if (lo.show_name_column) {
      loOut.show_name_column = true;
    }
    const mermaidOut = {
      landscape_width: lo.mermaid_pdf?.landscape_width?.trim() || mDef.landscape_width || "",
      portrait_width: lo.mermaid_pdf?.portrait_width?.trim() || mDef.portrait_width || "",
      portrait_max_height: lo.mermaid_pdf?.portrait_max_height?.trim() || mDef.portrait_max_height || "",
    };
    const primebrushOut = {
      latex_width: lo.primebrush_pdf?.latex_width?.trim() || pDef.latex_width || "",
    };
    if (!(def != null && mermaidPdfEqual(mermaidOut, def.mermaid_pdf))) {
      loOut.mermaid_pdf = mermaidOut;
    }
    if (!(def != null && primebrushPdfEqual(primebrushOut, def.primebrush_pdf))) {
      loOut.primebrush_pdf = primebrushOut;
    }
    for (const [k, v] of Object.entries(draft.metadata_extra)) {
      if (layoutBuiltinKeySet.has(k)) {
        continue;
      }
      const ser = serializeExtraForYaml(k, v, metadataUi.fields);
      if (ser !== undefined) {
        loOut[k] = ser;
      }
    }
    const cleaned: Record<string, unknown> = {
      template_id: draft.template_id,
      layout: draft.layout,
      latex_base: draft.latex_base,
      sections: draft.sections.map((s) => {
        const row: Record<string, unknown> = {
          section_id: s.section_id,
          type: s.type,
          required_count: s.type === "text" ? 0 : s.required_count,
          score_per_item: s.score_per_item,
        };
        if (s.describe && s.describe.trim()) {
          row.describe = s.describe;
        }
        return row;
      }),
    };
    cleaned.metadata_defaults = loOut;
    return yaml.dump(cleaned, { lineWidth: 120, noRefs: true });
  }, [draft, metadataUi.fields, editorDefaults, layoutBuiltinKeySet]);

  async function save() {
    if (!path) {
      return;
    }
    onError(null);
    setBusy(true);
    setMsg(null);
    try {
      const body = tab === "yaml" ? yamlTab : yamlDump;
      await apiPut("/api/templates/raw", { path, yaml: body });
      const q = encodeURIComponent(path);
      const [raw, parsed] = await Promise.all([
        apiGet<{ yaml: string }>(`/api/templates/raw?path=${q}`),
        apiGet<TemplateParsedResponse>(`/api/templates/parsed?path=${q}`),
      ]);
      setYamlTab(raw.yaml);
      setLayoutBuiltinKeys(parsed.layout_builtin_keys);
      setDraft(draftFromParsed(parsed));
      await refreshList();
      setMsg(t("saved"));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function createNew() {
    const n = newName.trim() || t("newTemplateDefault");
    onError(null);
    setBusy(true);
    try {
      const r = await apiPost<{ ok: boolean; path: string }>(
        `/api/templates/create?name=${encodeURIComponent(n)}`,
        {},
      );
      await refreshList();
      setPath(r.path);
      setNewName("");
      setMsg(t("created"));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function updateSection(i: number, patch: Partial<TemplateSectionRow>) {
    setDraft((d) => {
      const sections = [...d.sections];
      const cur = { ...sections[i], ...patch };
      if (cur.type === "text") {
        cur.required_count = 0;
      }
      sections[i] = cur;
      return { ...d, sections };
    });
  }

  function moveSection(i: number, dir: -1 | 1) {
    setDraft((d) => {
      const j = i + dir;
      if (j < 0 || j >= d.sections.length) {
        return d;
      }
      const sections = [...d.sections];
      [sections[i], sections[j]] = [sections[j], sections[i]];
      return { ...d, sections };
    });
  }

  function removeSection(i: number) {
    setDraft((d) => ({ ...d, sections: d.sections.filter((_, k) => k !== i) }));
  }

  function addSection(type: string) {
    const label = t(`sectionKind.${type}`);
    setDraft((d) => ({
      ...d,
      sections: [
        ...d.sections,
        {
          section_id: t("newSection", { label }),
          type,
          required_count: type === "text" ? 0 : 1,
          score_per_item: type === "text" ? 0 : 5,
          describe: "",
        },
      ],
    }));
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-slate-200 bg-white px-4 py-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs font-medium text-slate-600">
            {t("pickFile")}
            <select
              className="mt-1 block min-w-[240px] rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              value={path}
              onChange={(e) => setPath(e.target.value)}
            >
              {templates.map((t) => (
                <option key={t.path} value={t.path}>
                  {t.id} — {t.path}
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-end gap-2">
            <label className="text-xs font-medium text-slate-600">
              {t("newFileName")}
              <input
                className="mt-1 block w-40 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                placeholder={t("newFilePh")}
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </label>
            <button
              type="button"
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium"
              disabled={busy}
              onClick={() => void createNew()}
            >
              <Plus className="mr-1 inline h-4 w-4" />
              {t("create")}
            </button>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              className={cn(
                "rounded-md px-3 py-1.5 text-sm",
                tab === "visual" ? "bg-slate-900 text-white" : "border border-slate-300 bg-white",
              )}
              onClick={() => setTab("visual")}
            >
              {t("visual")}
            </button>
            <button
              type="button"
              className={cn(
                "rounded-md px-3 py-1.5 text-sm",
                tab === "yaml" ? "bg-slate-900 text-white" : "border border-slate-300 bg-white",
              )}
              onClick={() => {
                setYamlTab(yamlDump);
                setTab("yaml");
              }}
            >
              {t("editSource")}
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-md bg-emerald-700 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
              disabled={busy || !path}
              onClick={() => void save()}
            >
              <Save className="h-4 w-4" />
              {t("save")}
            </button>
          </div>
        </div>
        {msg && <p className="mt-2 text-sm text-emerald-700">{msg}</p>}
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-4">
        {tab === "yaml" ? (
          <textarea
            className="h-[min(70vh,800px)] w-full rounded-lg border border-slate-300 bg-slate-50 p-3 font-mono text-sm"
            value={yamlTab}
            onChange={(e) => setYamlTab(e.target.value)}
          />
        ) : (
          <div className="mx-auto max-w-3xl space-y-6">
            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="text-sm font-semibold text-slate-800">{t("basicInfo")}</h2>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <label className="text-xs text-slate-600">
                  {t("templateId")}
                  <input
                    className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                    value={draft.template_id}
                    onChange={(e) => setDraft((d) => ({ ...d, template_id: e.target.value }))}
                  />
                </label>
                <label className="text-xs text-slate-600">
                  {t("columns")}
                  <select
                    className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                    value={draft.layout}
                    onChange={(e) =>
                      setDraft((d) => ({
                        ...d,
                        layout: e.target.value === "double_column" ? "double_column" : "single_column",
                      }))
                    }
                  >
                    <option value="single_column">{t("colSingle")}</option>
                    <option value="double_column">{t("colDouble")}</option>
                  </select>
                </label>
                <label className="text-xs text-slate-600 sm:col-span-2">
                  {t("layoutTemplate")}
                  <p className="mt-0.5 text-[11px] leading-snug text-slate-400">{t("layoutTemplateHint")}</p>
                  <select
                    className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                    value={draft.latex_base}
                    onChange={(e) => setDraft((d) => ({ ...d, latex_base: e.target.value }))}
                  >
                    {!latexBasesInfo.choices.includes(draft.latex_base) && (
                      <option value={draft.latex_base}>
                        {draft.latex_base}
                        {t("currentYaml")}
                      </option>
                    )}
                    {latexBasesInfo.choices.map((name) => (
                      <option key={name} value={name}>
                        {name}
                        {shippedSet.has(name) ? t("shipped") : ""}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </section>

            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="text-sm font-semibold text-slate-800">{t("defaultLayoutTitle")}</h2>
              <p className="mt-1 text-[11px] text-slate-500">{t("defaultLayoutHint")}</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <label className="text-xs text-slate-600">
                  {t("marginCm")}
                  <input
                    type="number"
                    step={0.1}
                    min={0.5}
                    max={4}
                    className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                    placeholder={t("marginPh")}
                    value={draft.metadata_defaults.margin_cm ?? ""}
                    onChange={(e) => {
                      const v = e.target.value;
                      setDraft((d) => ({
                        ...d,
                        metadata_defaults: {
                          ...d.metadata_defaults,
                          margin_cm: v === "" ? undefined : Number(v),
                        },
                      }));
                    }}
                  />
                </label>
                <label className="text-xs text-slate-600">
                  {t("bodyPt")}
                  <input
                    type="number"
                    step={0.5}
                    min={9}
                    max={14}
                    className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                    placeholder={t("bodyPh")}
                    value={draft.metadata_defaults.body_font_size_pt ?? ""}
                    onChange={(e) => {
                      const v = e.target.value;
                      setDraft((d) => ({
                        ...d,
                        metadata_defaults: {
                          ...d.metadata_defaults,
                          body_font_size_pt: v === "" ? undefined : Number(v),
                        },
                      }));
                    }}
                  />
                </label>
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={draft.metadata_defaults.show_binding_line ?? false}
                    onChange={(e) =>
                      setDraft((d) => ({
                        ...d,
                        metadata_defaults: { ...d.metadata_defaults, show_binding_line: e.target.checked },
                      }))
                    }
                  />
                  {t("bindingMark")}
                </label>
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={draft.metadata_defaults.show_name_column ?? false}
                    onChange={(e) =>
                      setDraft((d) => ({
                        ...d,
                        metadata_defaults: { ...d.metadata_defaults, show_name_column: e.target.checked },
                      }))
                    }
                  />
                  {t("nameBox")}
                </label>
              </div>
            </section>

            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="text-sm font-semibold text-slate-800">{t("extendTitle")}</h2>
              <p className="mt-1 text-[11px] text-slate-500">{t("extendHint")}</p>
              {metadataUi.source && (
                <p className="mt-1 text-[11px] text-slate-400">{t("layoutSpecFile", { path: metadataUi.source })}</p>
              )}
              {metadataUi.warnings.length > 0 && (
                <ul className="mt-2 list-inside list-disc text-[11px] text-amber-800">
                  {metadataUi.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              )}
              {metadataUi.fields.length === 0 ? (
                <p className="mt-3 text-xs text-slate-500">{t("noExtendFields")}</p>
              ) : (
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {metadataUi.fields.map((field) => {
                    const patchExtra = (v: unknown) =>
                      setDraft((d) => ({
                        ...d,
                        metadata_extra: { ...d.metadata_extra, [field.key]: v },
                      }));
                    const hintEl = field.hint ? (
                      <p className="mt-1 text-[11px] leading-snug text-slate-400">{field.hint}</p>
                    ) : null;
                    if (field.kind === "textarea") {
                      return (
                        <label key={field.key} className="text-xs text-slate-600 sm:col-span-2">
                          {field.label}
                          <textarea
                            rows={field.rows ?? 3}
                            className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                            placeholder={field.placeholder}
                            value={
                              draft.metadata_extra[field.key] != null
                                ? String(draft.metadata_extra[field.key])
                                : ""
                            }
                            onChange={(e) => patchExtra(e.target.value)}
                          />
                          {hintEl}
                        </label>
                      );
                    }
                    if (field.kind === "text") {
                      return (
                        <label key={field.key} className="text-xs text-slate-600 sm:col-span-2">
                          {field.label}
                          <input
                            type="text"
                            className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                            placeholder={field.placeholder}
                            value={
                              draft.metadata_extra[field.key] != null
                                ? String(draft.metadata_extra[field.key])
                                : ""
                            }
                            onChange={(e) => patchExtra(e.target.value)}
                          />
                          {hintEl}
                        </label>
                      );
                    }
                    if (field.kind === "select" && field.options?.length) {
                      return (
                        <label key={field.key} className="text-xs text-slate-600 sm:col-span-2">
                          {field.label}
                          <select
                            className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                            value={metadataUiSelectValue(field, draft.metadata_extra)}
                            onChange={(e) => patchExtra(e.target.value)}
                          >
                            {field.options.map((opt) => (
                              <option key={opt.value} value={opt.value}>
                                {opt.label}
                              </option>
                            ))}
                          </select>
                          {hintEl}
                        </label>
                      );
                    }
                    if (field.kind === "checkbox") {
                      return (
                        <label key={field.key} className="flex items-center gap-2 text-sm text-slate-700 sm:col-span-2">
                          <input
                            type="checkbox"
                            checked={Boolean(draft.metadata_extra[field.key])}
                            onChange={(e) => patchExtra(e.target.checked)}
                          />
                          {field.label}
                          {hintEl}
                        </label>
                      );
                    }
                    if (field.kind === "number") {
                      const n = draft.metadata_extra[field.key];
                      const numStr =
                        typeof n === "number" && !Number.isNaN(n)
                          ? String(n)
                          : n != null && String(n) !== ""
                            ? String(n)
                            : "";
                      return (
                        <label key={field.key} className="text-xs text-slate-600">
                          {field.label}
                          <input
                            type="number"
                            min={field.min}
                            max={field.max}
                            step={field.step ?? "any"}
                            className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                            value={numStr}
                            onChange={(e) => {
                              const v = e.target.value;
                              if (v === "") {
                                setDraft((d) => {
                                  const next = { ...d.metadata_extra };
                                  delete next[field.key];
                                  return { ...d, metadata_extra: next };
                                });
                                return;
                              }
                              const x = Number(v);
                              patchExtra(Number.isNaN(x) ? v : x);
                            }}
                          />
                          {hintEl}
                        </label>
                      );
                    }
                    return (
                      <p key={field.key} className="text-xs text-amber-700 sm:col-span-2">
                        {t("unsupportedFieldType")}
                      </p>
                    );
                  })}
                </div>
              )}
            </section>

            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="text-sm font-semibold text-slate-800">{t("figureSizeTitle")}</h2>
              <p className="mt-1 text-xs text-slate-500">{t("figureSizeHint")}</p>
              <div className="mt-4 space-y-5">
                <div>
                  <p className="mb-2 text-xs font-medium text-slate-800">{t("geoFigures")}</p>
                  <PdfPercentInput
                    label={t("widthInLine")}
                    hint={t("widthInLineHintGeo")}
                    min={20}
                    max={100}
                    value={parseLinewidthPercent(draft.metadata_defaults.primebrush_pdf?.latex_width, FB_PIC_W)}
                    onCommit={(pct) =>
                      setDraft((d) => ({
                        ...d,
                        metadata_defaults: {
                          ...d.metadata_defaults,
                          primebrush_pdf: {
                            ...d.metadata_defaults.primebrush_pdf,
                            latex_width: linewidthPercentToLatex(pct),
                          },
                        },
                      }))
                    }
                  />
                </div>
                <div className="border-t border-slate-100 pt-4">
                  <p className="mb-2 text-xs font-medium text-slate-800">{t("flowH")}</p>
                  <PdfPercentInput
                    label={t("widthInLine")}
                    hint={t("widthInLineHintFlowH")}
                    min={20}
                    max={100}
                    value={parseLinewidthPercent(
                      draft.metadata_defaults.mermaid_pdf?.landscape_width,
                      FB_MER_L,
                    )}
                    onCommit={(pct) =>
                      setDraft((d) => ({
                        ...d,
                        metadata_defaults: {
                          ...d.metadata_defaults,
                          mermaid_pdf: {
                            ...d.metadata_defaults.mermaid_pdf,
                            landscape_width: linewidthPercentToLatex(pct),
                          },
                        },
                      }))
                    }
                  />
                </div>
                <div className="border-t border-slate-100 pt-4">
                  <p className="mb-2 text-xs font-medium text-slate-800">{t("flowV")}</p>
                  <div className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:gap-6">
                    <PdfPercentInput
                      label={t("widthInLine")}
                      hint={t("widthInLineHintFlowV")}
                      min={20}
                      max={90}
                      value={parseLinewidthPercent(
                        draft.metadata_defaults.mermaid_pdf?.portrait_width,
                        FB_MER_P,
                      )}
                      onCommit={(pct) =>
                        setDraft((d) => ({
                          ...d,
                          metadata_defaults: {
                            ...d.metadata_defaults,
                            mermaid_pdf: {
                              ...d.metadata_defaults.mermaid_pdf,
                              portrait_width: linewidthPercentToLatex(pct),
                            },
                          },
                        }))
                      }
                    />
                    <PdfPercentInput
                      label={t("maxPageHeight")}
                      hint={t("maxPageHeightHint")}
                      min={15}
                      max={70}
                      value={parseTextheightPercent(
                        draft.metadata_defaults.mermaid_pdf?.portrait_max_height,
                        FB_MER_H,
                      )}
                      onCommit={(pct) =>
                        setDraft((d) => ({
                          ...d,
                          metadata_defaults: {
                            ...d.metadata_defaults,
                            mermaid_pdf: {
                              ...d.metadata_defaults.mermaid_pdf,
                              portrait_max_height: textheightPercentToLatex(pct),
                            },
                          },
                        }))
                      }
                    />
                  </div>
                </div>
              </div>
            </section>

            <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-sm font-semibold text-slate-800">{t("structureTitle")}</h2>
                <select
                  className="rounded-md border border-slate-300 px-2 py-1 text-sm"
                  defaultValue=""
                  onChange={(e) => {
                    const v = e.target.value;
                    e.target.value = "";
                    if (v) {
                      addSection(v);
                    }
                  }}
                >
                  <option value="">{t("addSection")}</option>
                  {SECTION_KIND_VALUES.map((kind) => (
                    <option key={kind} value={kind}>
                      {t(`sectionKind.${kind}`)}
                    </option>
                  ))}
                </select>
              </div>
              <ul className="mt-4 space-y-3">
                {draft.sections.map((s, i) => (
                  <li key={i} className="rounded-lg border border-slate-200 bg-slate-50/80 p-3">
                    <div className="flex flex-wrap items-start gap-2">
                      <div className="flex flex-col gap-0.5">
                        <button
                          type="button"
                          className="rounded border border-slate-300 bg-white p-0.5"
                          title={t("moveUp")}
                          onClick={() => moveSection(i, -1)}
                        >
                          <ChevronUp className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          className="rounded border border-slate-300 bg-white p-0.5"
                          title={t("moveDown")}
                          onClick={() => moveSection(i, 1)}
                        >
                          <ChevronDown className="h-4 w-4" />
                        </button>
                      </div>
                      <div className="min-w-0 flex-1 space-y-2">
                        <input
                          className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm font-medium"
                          value={s.section_id}
                          onChange={(e) => updateSection(i, { section_id: e.target.value })}
                          placeholder={t("sectionTitlePh")}
                        />
                        <div className="flex flex-wrap gap-2">
                          <select
                            className="rounded border border-slate-300 px-2 py-1 text-sm"
                            value={s.type}
                            onChange={(e) => {
                              const type = e.target.value;
                              updateSection(i, {
                                type,
                                required_count: type === "text" ? 0 : Math.max(1, s.required_count),
                                score_per_item: type === "text" ? 0 : s.score_per_item,
                              });
                            }}
                          >
                            {SECTION_KIND_VALUES.map((kind) => (
                              <option key={kind} value={kind}>
                                {t(`sectionKind.${kind}`)}
                              </option>
                            ))}
                          </select>
                          {s.type !== "text" && (
                            <>
                              <label className="flex items-center gap-1 text-xs text-slate-600">
                                {t("questionCount")}
                                <input
                                  type="number"
                                  min={0}
                                  className="w-16 rounded border border-slate-300 px-1 py-0.5 text-sm"
                                  value={s.required_count}
                                  onChange={(e) =>
                                    updateSection(i, { required_count: Number(e.target.value) })
                                  }
                                />
                              </label>
                              <label className="flex items-center gap-1 text-xs text-slate-600">
                                {t("scoreEach")}
                                <input
                                  type="number"
                                  min={0}
                                  step={0.5}
                                  className="w-16 rounded border border-slate-300 px-1 py-0.5 text-sm"
                                  value={s.score_per_item}
                                  onChange={(e) =>
                                    updateSection(i, { score_per_item: Number(e.target.value) })
                                  }
                                />
                              </label>
                            </>
                          )}
                          {s.type === "text" && (
                            <span className="text-xs text-slate-500">{t("textNoCount")}</span>
                          )}
                        </div>
                        <label className="block text-xs text-slate-600">
                          {t("describeOptional")}
                          <textarea
                            className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                            rows={3}
                            value={s.describe ?? ""}
                            onChange={(e) => updateSection(i, { describe: e.target.value })}
                          />
                        </label>
                      </div>
                      <button
                        type="button"
                        className="rounded-md border border-red-200 p-1.5 text-red-700 hover:bg-red-50"
                        title={t("deleteSection")}
                        onClick={() => removeSection(i)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
