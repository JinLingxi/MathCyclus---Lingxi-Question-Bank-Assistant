import {
  type ChangeEvent,
  type Dispatch,
  type LegacyRef,
  type RefObject,
  type SetStateAction,
  useMemo,
} from "react";
import { useTranslation } from "react-i18next";
import { ImagePlus } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";
import { QUESTION_TYPE_OPTIONS } from "../lib/questionTypes";
import type { EmbedKind } from "../lib/bankEditorEmbedKinds";
import { ChoiceOptionsFields } from "./ChoiceOptionsFields";

export type QuestionJson = {
  id: string;
  type: string;
  content: string;
  options?: Record<string, string> | null;
  answer: string;
  analysis: string;
  metadata?: Record<string, unknown>;
  /** 题组展开时由后端填充，编辑材料时同步 */
  group_material?: string | null;
};

export type GroupMemberJson = {
  /** 混编（unified: false）时必填 */
  type?: string;
  content: string;
  options?: Record<string, string> | null;
  answer: string;
  analysis: string;
  metadata?: Record<string, unknown>;
};

export type QuestionGroupJson = {
  id: string;
  type: "group";
  material: string;
  /** false = 混编；否则为同型小题题型 */
  unified: boolean | string;
  items: GroupMemberJson[];
};

export type BankDetailState = {
  qualified_id: string;
  question: QuestionJson;
  question_display?: QuestionJson;
  file_yaml: string;
  storage_path: string;
  storage_kind: string;
  question_group?: QuestionGroupJson | null;
  question_group_preview?: { material: string; items: GroupMemberJson[]; unified?: boolean | string } | null;
};

export type { EmbedKind, MathFieldKey } from "../lib/bankEditorEmbedKinds";

type MetaRow = { key: string; value: string };

export type BankQuestionEditorPanelProps = {
  detail: BankDetailState;
  setDetail: Dispatch<SetStateAction<BankDetailState | null>>;
  busy: boolean;
  editorTab: "form" | "yaml";
  setEditorTab: Dispatch<SetStateAction<"form" | "yaml">>;
  rawYaml: string;
  setRawYaml: Dispatch<SetStateAction<string>>;
  metaRows: MetaRow[];
  setMetaRows: Dispatch<SetStateAction<MetaRow[]>>;
  contentRef: RefObject<HTMLTextAreaElement | null>;
  answerRef: RefObject<HTMLTextAreaElement | null>;
  analysisRef: RefObject<HTMLTextAreaElement | null>;
  materialGroupRef: RefObject<HTMLTextAreaElement | null>;
  imageInputRef: RefObject<HTMLInputElement | null>;
  beginMathEmbed: (kind: EmbedKind, sel: { start: number; end: number } | null) => void;
  beginMermaidEmbed: (kind: EmbedKind, sel: { start: number; end: number } | null) => void;
  beginImageEmbed: (kind: EmbedKind, sel: { start: number; end: number } | null) => void;
  onImageFileSelected: (e: ChangeEvent<HTMLInputElement>) => void;
  onRemove: () => void;
  onSave: () => void;
  onSaveYaml: () => void;
  onClose?: () => void;
  removeLabel?: string;
};

function giFieldId(i: number, f: "content" | "answer" | "analysis") {
  return `bank-gi-${i}-${f}`;
}

export function BankQuestionEditorPanel({
  detail,
  setDetail,
  busy,
  editorTab,
  setEditorTab,
  rawYaml,
  setRawYaml,
  metaRows,
  setMetaRows,
  contentRef,
  answerRef,
  analysisRef,
  materialGroupRef,
  imageInputRef,
  beginMathEmbed,
  beginMermaidEmbed,
  beginImageEmbed,
  onImageFileSelected,
  onRemove,
  onSave,
  onSaveYaml,
  onClose,
  removeLabel,
}: BankQuestionEditorPanelProps) {
  const { t } = useTranslation(["lib", "components", "bank"]);
  const removeText = removeLabel ?? t("bank:remove");
  const qg = detail.question_group;
  /** 同型题组：与 synthetic question id 的 __01 后缀对应；整组编辑时为 0 */
  const memberIdx = useMemo(() => {
    const m = detail.question.id.match(/__(\d{2})$/);
    return m ? parseInt(m[1], 10) - 1 : 0;
  }, [detail.question.id]);

  const unifiedUi = qg ? (qg.unified === false ? "mixed" : String(qg.unified)) : "choice";
  const innerTypeForItems = unifiedUi === "mixed" ? "choice" : unifiedUi;

  return (
    <div className="mx-auto max-w-3xl rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
        <div>
          <p className="font-mono text-sm text-slate-800">{detail.qualified_id}</p>
          <p className="text-[11px] text-slate-500">
            {t("components:bankEditor.storage", { kind: detail.storage_kind, path: detail.storage_path })}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {onClose && (
            <button
              type="button"
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-800 hover:bg-slate-50"
              onClick={onClose}
            >
              {t("components:bankEditor.close")}
            </button>
          )}
          <button
            type="button"
            className="rounded-md border border-red-200 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50"
            disabled={busy}
            onClick={() => void onRemove()}
          >
            {removeText}
          </button>
          <button
            type="button"
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            disabled={busy}
            onClick={() => (editorTab === "yaml" ? void onSaveYaml() : void onSave())}
          >
            {t("components:bankEditor.save")}
          </button>
        </div>
      </div>

      <Tabs value={editorTab} onValueChange={(v) => setEditorTab(v as "form" | "yaml")} className="mt-4">
        <TabsList className="grid w-full max-w-md grid-cols-2">
          <TabsTrigger value="form">{t("components:bankEditor.tabForm")}</TabsTrigger>
          <TabsTrigger value="yaml">{t("components:bankEditor.tabYaml")}</TabsTrigger>
        </TabsList>
        <TabsContent value="form" className="mt-4 space-y-3 text-sm">
          <input
            ref={imageInputRef as LegacyRef<HTMLInputElement>}
            type="file"
            accept="image/*"
            className="hidden"
            aria-hidden
            onChange={(e) => void onImageFileSelected(e)}
          />
          {qg ? (
            <>
              <p className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1.5 text-xs text-emerald-900">
                {t("components:bankEditor.groupHint", { id: detail.question.id })}
              </p>
              <label className="block text-xs font-medium text-slate-600">
                {t("components:bankEditor.groupRootId")}
                <input
                  className="mt-1 w-full cursor-not-allowed rounded-md border border-slate-200 bg-slate-50 px-2 py-1.5 font-mono text-sm"
                  readOnly
                  value={qg.id}
                />
              </label>
              <label className="block text-xs font-medium text-slate-600">
                {t("components:bankEditor.unified")}
                <select
                  className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5"
                  value={unifiedUi}
                  onChange={(e) => {
                    const u = e.target.value;
                    const unifiedVal = u === "mixed" ? false : u;
                    let items = qg.items.map((it) => ({ ...it }));
                    if (u === "mixed") {
                      /* 混编：不批量改各小题 options */
                    } else if (u === "choice") {
                      items = items.map((it) => ({
                        ...it,
                        options:
                          it.options && Object.keys(it.options).length
                            ? it.options
                            : { A: "", B: "", C: "", D: "" },
                      }));
                    } else {
                      items = items.map((it) => {
                        const { options: _omit, ...rest } = it as GroupMemberJson & {
                          options?: Record<string, string>;
                        };
                        return rest as GroupMemberJson;
                      });
                    }
                    setDetail({
                      ...detail,
                      question_group: { ...qg, unified: unifiedVal, items },
                      question: {
                        ...detail.question,
                        type: u === "mixed" ? "choice" : u,
                        options:
                          u === "mixed"
                            ? detail.question.options
                            : u === "choice"
                              ? detail.question.options ?? { A: "", B: "", C: "", D: "" }
                              : null,
                      },
                    });
                  }}
                >
                  <option value="mixed">{t("components:bankEditor.mixedOpt")}</option>
                  {QUESTION_TYPE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {t(`lib:questionTypes.${o.value}`)}
                    </option>
                  ))}
                </select>
              </label>
              <div className="block">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-medium text-slate-600">{t("components:bankEditor.sharedLatex")}</span>
                  <div className="flex shrink-0 flex-wrap gap-1">
                    <button
                      type="button"
                      className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
                      onClick={() => {
                        const el = materialGroupRef.current;
                        const sel = el ? { start: el.selectionStart, end: el.selectionEnd } : null;
                        beginMathEmbed({ k: "gm" }, sel);
                      }}
                    >
                      {t("components:bankEditor.insertMath")}
                    </button>
                    <button
                      type="button"
                      className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
                      onClick={() => {
                        const el = materialGroupRef.current;
                        const sel = el ? { start: el.selectionStart, end: el.selectionEnd } : null;
                        beginMermaidEmbed({ k: "gm" }, sel);
                      }}
                    >
                      {t("components:bankEditor.insertDiagram")}
                    </button>
                    <button
                      type="button"
                      className="inline-flex items-center gap-0.5 rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                      disabled={busy}
                      title={t("components:bankEditor.insertImageTitle")}
                      onClick={() => {
                        const el = materialGroupRef.current;
                        const sel = el ? { start: el.selectionStart, end: el.selectionEnd } : null;
                        beginImageEmbed({ k: "gm" }, sel);
                      }}
                    >
                      <ImagePlus className="h-3.5 w-3.5" aria-hidden />
                      <span className="hidden sm:inline">{t("components:bankEditor.image")}</span>
                    </button>
                  </div>
                </div>
                <textarea
                  ref={materialGroupRef as LegacyRef<HTMLTextAreaElement>}
                  className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 font-mono text-sm"
                  rows={5}
                  value={qg.material}
                  onChange={(e) =>
                    setDetail({
                      ...detail,
                      question_group: { ...qg, material: e.target.value },
                      question: { ...detail.question, group_material: e.target.value },
                    })
                  }
                />
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
                    onClick={() => {
                    const emptyChoiceOpts = { A: "", B: "", C: "", D: "" };
                    const newItem =
                      unifiedUi === "mixed"
                        ? { type: "choice" as const, content: "", answer: "", analysis: "", metadata: {}, options: emptyChoiceOpts }
                        : innerTypeForItems === "choice"
                          ? { content: "", answer: "", analysis: "", metadata: {}, options: emptyChoiceOpts }
                          : { content: "", answer: "", analysis: "", metadata: {} };
                    setDetail({
                      ...detail,
                      question_group: {
                        ...qg,
                        items: [...qg.items, newItem],
                      },
                    });
                  }}
                >
                  {t("components:bankEditor.addSub")}
                </button>
                {qg.items.length > 1 && (
                  <button
                    type="button"
                    className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
                    onClick={() => {
                      setDetail({
                        ...detail,
                        question_group: { ...qg, items: qg.items.slice(0, -1) },
                      });
                    }}
                  >
                    {t("components:bankEditor.removeLastSub")}
                  </button>
                )}
              </div>
              {qg.items.map((it, i) => (
                <div key={i} className="rounded-lg border border-slate-200 bg-slate-50/80 p-3">
                  <p className="mb-2 text-xs font-semibold text-slate-700">
                    {t("components:bankEditor.subItem", { n: i + 1 })}
                  </p>
                  {unifiedUi === "mixed" && (
                    <label className="mb-2 block text-xs font-medium text-slate-600">
                      {t("components:bankEditor.fieldType")}
                      <select
                        className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5"
                        value={it.type ?? "choice"}
                        onChange={(e) => {
                          const nt = e.target.value;
                          const items = [...qg.items];
                          const cur = items[i];
                          if (nt === "choice") {
                            items[i] = {
                              ...cur,
                              type: nt,
                              options: cur.options ?? { A: "", B: "", C: "", D: "" },
                            };
                          } else {
                            const { options: _o, ...rest } = cur as GroupMemberJson & { options?: Record<string, string> };
                            items[i] = { ...rest, type: nt };
                          }
                          setDetail({ ...detail, question_group: { ...qg, items } });
                        }}
                      >
                        {QUESTION_TYPE_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>
                            {t(`lib:questionTypes.${o.value}`)}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <div className="block">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-xs font-medium text-slate-600">{t("components:bankEditor.fieldContent")}</span>
                      <div className="flex shrink-0 flex-wrap gap-1">
                        <button
                          type="button"
                          className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
                          onClick={() => {
                            const el = document.getElementById(giFieldId(i, "content")) as HTMLTextAreaElement | null;
                            const sel = el ? { start: el.selectionStart, end: el.selectionEnd } : null;
                            beginMathEmbed({ k: "gi", i, f: "content" }, sel);
                          }}
                        >
                          {t("components:bankEditor.insertMath")}
                        </button>
                        <button
                          type="button"
                          className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
                          onClick={() => {
                            const el = document.getElementById(giFieldId(i, "content")) as HTMLTextAreaElement | null;
                            const sel = el ? { start: el.selectionStart, end: el.selectionEnd } : null;
                            beginMermaidEmbed({ k: "gi", i, f: "content" }, sel);
                          }}
                        >
                          {t("components:bankEditor.insertDiagram")}
                        </button>
                        <button
                          type="button"
                          className="inline-flex items-center gap-0.5 rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                          disabled={busy}
                          title={t("components:bankEditor.insertImageTitle")}
                          onClick={() => {
                            const el = document.getElementById(giFieldId(i, "content")) as HTMLTextAreaElement | null;
                            const sel = el ? { start: el.selectionStart, end: el.selectionEnd } : null;
                            beginImageEmbed({ k: "gi", i, f: "content" }, sel);
                          }}
                        >
                          <ImagePlus className="h-3.5 w-3.5" aria-hidden />
                          <span className="hidden sm:inline">{t("components:bankEditor.image")}</span>
                        </button>
                      </div>
                    </div>
                    <textarea
                      id={giFieldId(i, "content")}
                      className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 font-mono text-sm"
                      rows={4}
                      value={it.content}
                      onChange={(e) => {
                        const items = [...qg.items];
                        items[i] = { ...items[i], content: e.target.value };
                        const q =
                          memberIdx === i ? { ...detail.question, content: e.target.value, group_material: qg.material } : detail.question;
                        setDetail({ ...detail, question_group: { ...qg, items }, question: q });
                      }}
                    />
                  </div>
                  {(unifiedUi === "mixed" ? it.type === "choice" : innerTypeForItems === "choice") && (
                    <div className="mt-2">
                      <ChoiceOptionsFields
                        options={it.options ?? { A: "", B: "", C: "", D: "" }}
                        onCommit={(opts) => {
                          const items = [...qg.items];
                          items[i] = { ...items[i], options: opts };
                          const m = detail.question.id.match(/__(\d{2})$/);
                          const midx = m ? parseInt(m[1], 10) - 1 : -1;
                          let q = detail.question;
                          if (midx === i) {
                            q = { ...q, options: opts };
                          }
                          setDetail({ ...detail, question_group: { ...qg, items }, question: q });
                        }}
                        idPrefix={`bank-opt-gi-${i}`}
                        busy={busy}
                        makeEmbedKind={(key) => ({ k: "gio", i, key })}
                        beginMathEmbed={beginMathEmbed}
                        beginMermaidEmbed={beginMermaidEmbed}
                        beginImageEmbed={beginImageEmbed}
                      />
                    </div>
                  )}
                  <div className="mt-2 block">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-xs font-medium text-slate-600">{t("components:bankEditor.fieldAnswer")}</span>
                      <div className="flex shrink-0 flex-wrap gap-1">
                        <button
                          type="button"
                          className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
                          onClick={() => {
                            const el = document.getElementById(giFieldId(i, "answer")) as HTMLTextAreaElement | null;
                            beginMathEmbed({ k: "gi", i, f: "answer" }, el ? { start: el.selectionStart, end: el.selectionEnd } : null);
                          }}
                        >
                          {t("components:bankEditor.insertMath")}
                        </button>
                        <button
                          type="button"
                          className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
                          onClick={() => {
                            const el = document.getElementById(giFieldId(i, "answer")) as HTMLTextAreaElement | null;
                            beginMermaidEmbed({ k: "gi", i, f: "answer" }, el ? { start: el.selectionStart, end: el.selectionEnd } : null);
                          }}
                        >
                          {t("components:bankEditor.insertDiagram")}
                        </button>
                        <button
                          type="button"
                          className="inline-flex items-center gap-0.5 rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                          disabled={busy}
                          title={t("components:bankEditor.insertImageTitle")}
                          onClick={() => {
                            const el = document.getElementById(giFieldId(i, "answer")) as HTMLTextAreaElement | null;
                            beginImageEmbed({ k: "gi", i, f: "answer" }, el ? { start: el.selectionStart, end: el.selectionEnd } : null);
                          }}
                        >
                          <ImagePlus className="h-3.5 w-3.5" aria-hidden />
                          <span className="hidden sm:inline">{t("components:bankEditor.image")}</span>
                        </button>
                      </div>
                    </div>
                    <textarea
                      id={giFieldId(i, "answer")}
                      className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 font-mono text-sm"
                      rows={2}
                      value={it.answer}
                      onChange={(e) => {
                        const items = [...qg.items];
                        items[i] = { ...items[i], answer: e.target.value };
                        const q = memberIdx === i ? { ...detail.question, answer: e.target.value } : detail.question;
                        setDetail({ ...detail, question_group: { ...qg, items }, question: q });
                      }}
                    />
                  </div>
                  <div className="mt-2 block">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-xs font-medium text-slate-600">{t("components:bankEditor.fieldAnalysis")}</span>
                      <div className="flex shrink-0 flex-wrap gap-1">
                        <button
                          type="button"
                          className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
                          onClick={() => {
                            const el = document.getElementById(giFieldId(i, "analysis")) as HTMLTextAreaElement | null;
                            beginMathEmbed({ k: "gi", i, f: "analysis" }, el ? { start: el.selectionStart, end: el.selectionEnd } : null);
                          }}
                        >
                          {t("components:bankEditor.insertMath")}
                        </button>
                        <button
                          type="button"
                          className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
                          onClick={() => {
                            const el = document.getElementById(giFieldId(i, "analysis")) as HTMLTextAreaElement | null;
                            beginMermaidEmbed({ k: "gi", i, f: "analysis" }, el ? { start: el.selectionStart, end: el.selectionEnd } : null);
                          }}
                        >
                          {t("components:bankEditor.insertDiagram")}
                        </button>
                        <button
                          type="button"
                          className="inline-flex items-center gap-0.5 rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                          disabled={busy}
                          title={t("components:bankEditor.insertImageTitle")}
                          onClick={() => {
                            const el = document.getElementById(giFieldId(i, "analysis")) as HTMLTextAreaElement | null;
                            beginImageEmbed({ k: "gi", i, f: "analysis" }, el ? { start: el.selectionStart, end: el.selectionEnd } : null);
                          }}
                        >
                          <ImagePlus className="h-3.5 w-3.5" aria-hidden />
                          <span className="hidden sm:inline">{t("components:bankEditor.image")}</span>
                        </button>
                      </div>
                    </div>
                    <textarea
                      id={giFieldId(i, "analysis")}
                      className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 font-mono text-sm"
                      rows={2}
                      value={it.analysis ?? ""}
                      onChange={(e) => {
                        const items = [...qg.items];
                        items[i] = { ...items[i], analysis: e.target.value };
                        const q = memberIdx === i ? { ...detail.question, analysis: e.target.value } : detail.question;
                        setDetail({ ...detail, question_group: { ...qg, items }, question: q });
                      }}
                    />
                  </div>
                </div>
              ))}
            </>
          ) : (
            <>
              <label className="block text-xs font-medium text-slate-600">
                {t("components:bankEditor.fieldId")}
                <input
                  className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 font-mono text-sm"
                  value={detail.question.id}
                  onChange={(e) => setDetail({ ...detail, question: { ...detail.question, id: e.target.value } })}
                />
              </label>
              <label className="block text-xs font-medium text-slate-600">
                {t("components:bankEditor.fieldType")}
                <select
                  className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5"
                  value={detail.question.type}
                  onChange={(e) => {
                    const nt = e.target.value;
                    const cur = detail.question;
                    if (nt === "choice") {
                      setDetail({
                        ...detail,
                        question: {
                          ...cur,
                          type: nt,
                          options: cur.options ?? { A: "", B: "", C: "", D: "" },
                        },
                      });
                    } else {
                      const { options: _omit, ...rest } = cur;
                      setDetail({ ...detail, question: { ...rest, type: nt, options: null } });
                    }
                  }}
                >
                  {QUESTION_TYPE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {t(`lib:questionTypes.${o.value}`)}
                    </option>
                  ))}
                </select>
              </label>
              <div className="block">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-medium text-slate-600">{t("components:bankEditor.contentLatex")}</span>
                  <div className="flex shrink-0 flex-wrap gap-1">
                    <button
                      type="button"
                      className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
                      onClick={() => {
                        const el = contentRef.current;
                        const sel = el ? { start: el.selectionStart, end: el.selectionEnd } : null;
                        beginMathEmbed({ k: "q", f: "content" }, sel);
                      }}
                    >
                      {t("components:bankEditor.insertMath")}
                    </button>
                    <button
                      type="button"
                      className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
                      onClick={() => {
                        const el = contentRef.current;
                        const sel = el ? { start: el.selectionStart, end: el.selectionEnd } : null;
                        beginMermaidEmbed({ k: "q", f: "content" }, sel);
                      }}
                    >
                      {t("components:bankEditor.insertDiagram")}
                    </button>
                    <button
                      type="button"
                      className="inline-flex items-center gap-0.5 rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                      disabled={busy}
                      title={t("components:bankEditor.insertImageTitle")}
                      onClick={() => {
                        const el = contentRef.current;
                        const sel = el ? { start: el.selectionStart, end: el.selectionEnd } : null;
                        beginImageEmbed({ k: "q", f: "content" }, sel);
                      }}
                    >
                      <ImagePlus className="h-3.5 w-3.5" aria-hidden />
                      <span className="hidden sm:inline">{t("components:bankEditor.image")}</span>
                    </button>
                  </div>
                </div>
                <textarea
                  ref={contentRef as LegacyRef<HTMLTextAreaElement>}
                  className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 font-mono text-sm"
                  rows={6}
                  value={detail.question.content}
                  onChange={(e) => setDetail({ ...detail, question: { ...detail.question, content: e.target.value } })}
                />
              </div>
              {detail.question.type === "choice" && (
                <div className="mt-2">
                  <ChoiceOptionsFields
                    options={detail.question.options ?? { A: "", B: "", C: "", D: "" }}
                    onCommit={(opts) => setDetail({ ...detail, question: { ...detail.question, options: opts } })}
                    idPrefix="bank-opt-q"
                    busy={busy}
                    makeEmbedKind={(key) => ({ k: "qo", key })}
                    beginMathEmbed={beginMathEmbed}
                    beginMermaidEmbed={beginMermaidEmbed}
                    beginImageEmbed={beginImageEmbed}
                  />
                </div>
              )}
              <div className="block">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-medium text-slate-600">{t("components:bankEditor.fieldAnswer")}</span>
                  <div className="flex shrink-0 flex-wrap gap-1">
                    <button
                      type="button"
                      className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
                      onClick={() => {
                        const el = answerRef.current;
                        const sel = el ? { start: el.selectionStart, end: el.selectionEnd } : null;
                        beginMathEmbed({ k: "q", f: "answer" }, sel);
                      }}
                    >
                      {t("components:bankEditor.insertMath")}
                    </button>
                    <button
                      type="button"
                      className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
                      onClick={() => {
                        const el = answerRef.current;
                        const sel = el ? { start: el.selectionStart, end: el.selectionEnd } : null;
                        beginMermaidEmbed({ k: "q", f: "answer" }, sel);
                      }}
                    >
                      {t("components:bankEditor.insertDiagram")}
                    </button>
                    <button
                      type="button"
                      className="inline-flex items-center gap-0.5 rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                      disabled={busy}
                      title={t("components:bankEditor.insertImageTitle")}
                      onClick={() => {
                        const el = answerRef.current;
                        const sel = el ? { start: el.selectionStart, end: el.selectionEnd } : null;
                        beginImageEmbed({ k: "q", f: "answer" }, sel);
                      }}
                    >
                      <ImagePlus className="h-3.5 w-3.5" aria-hidden />
                      <span className="hidden sm:inline">{t("components:bankEditor.image")}</span>
                    </button>
                  </div>
                </div>
                <textarea
                  ref={answerRef as LegacyRef<HTMLTextAreaElement>}
                  className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 font-mono text-sm"
                  rows={2}
                  value={detail.question.answer}
                  onChange={(e) => setDetail({ ...detail, question: { ...detail.question, answer: e.target.value } })}
                />
              </div>
              <div className="block">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-medium text-slate-600">{t("components:bankEditor.fieldAnalysis")}</span>
                  <div className="flex shrink-0 flex-wrap gap-1">
                    <button
                      type="button"
                      className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
                      onClick={() => {
                        const el = analysisRef.current;
                        const sel = el ? { start: el.selectionStart, end: el.selectionEnd } : null;
                        beginMathEmbed({ k: "q", f: "analysis" }, sel);
                      }}
                    >
                      {t("components:bankEditor.insertMath")}
                    </button>
                    <button
                      type="button"
                      className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
                      onClick={() => {
                        const el = analysisRef.current;
                        const sel = el ? { start: el.selectionStart, end: el.selectionEnd } : null;
                        beginMermaidEmbed({ k: "q", f: "analysis" }, sel);
                      }}
                    >
                      {t("components:bankEditor.insertDiagram")}
                    </button>
                    <button
                      type="button"
                      className="inline-flex items-center gap-0.5 rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                      disabled={busy}
                      title={t("components:bankEditor.insertImageTitle")}
                      onClick={() => {
                        const el = analysisRef.current;
                        const sel = el ? { start: el.selectionStart, end: el.selectionEnd } : null;
                        beginImageEmbed({ k: "q", f: "analysis" }, sel);
                      }}
                    >
                      <ImagePlus className="h-3.5 w-3.5" aria-hidden />
                      <span className="hidden sm:inline">{t("components:bankEditor.image")}</span>
                    </button>
                  </div>
                </div>
                <textarea
                  ref={analysisRef as LegacyRef<HTMLTextAreaElement>}
                  className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 font-mono text-sm"
                  rows={3}
                  value={detail.question.analysis}
                  onChange={(e) => setDetail({ ...detail, question: { ...detail.question, analysis: e.target.value } })}
                />
              </div>
              <div>
                <p className="text-xs font-medium text-slate-600">{t("components:bankEditor.tagsCustomFields")}</p>
                <div className="mt-2 space-y-2">
                  {metaRows.map((row, i) => (
                    <div key={i} className="flex gap-2">
                      <input
                        className="flex-1 rounded-md border border-slate-300 px-2 py-1 text-sm"
                        placeholder={t("components:bankEditor.keyPh")}
                        value={row.key}
                        onChange={(e) => {
                          const next = [...metaRows];
                          next[i] = { ...row, key: e.target.value };
                          setMetaRows(next);
                        }}
                      />
                      <input
                        className="flex-1 rounded-md border border-slate-300 px-2 py-1 text-sm"
                        placeholder={t("components:bankEditor.valuePh")}
                        value={row.value}
                        onChange={(e) => {
                          const next = [...metaRows];
                          next[i] = { ...row, value: e.target.value };
                          setMetaRows(next);
                        }}
                      />
                      <button
                        type="button"
                        className="rounded border border-slate-300 px-2 text-xs"
                        onClick={() => setMetaRows(metaRows.filter((_, j) => j !== i))}
                      >
                        −
                      </button>
                    </div>
                  ))}
                  <button
                    type="button"
                    className="text-xs text-slate-600 underline"
                    onClick={() => setMetaRows([...metaRows, { key: "", value: "" }])}
                  >
                    {t("components:bankEditor.addField")}
                  </button>
                </div>
              </div>
            </>
          )}
        </TabsContent>
        <TabsContent value="yaml" className="mt-4">
          <textarea
            className="w-full rounded-md border border-slate-300 font-mono text-xs leading-relaxed"
            rows={24}
            value={rawYaml}
            onChange={(e) => setRawYaml(e.target.value)}
          />
          <p className="mt-2 text-[11px] text-slate-500">
            {qg ? t("components:bankEditor.saveHintGroup") : t("components:bankEditor.saveHintSingle")}
          </p>
        </TabsContent>
      </Tabs>
    </div>
  );
}
