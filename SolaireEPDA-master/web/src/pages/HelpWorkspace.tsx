import { Children, isValidElement, useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { BookOpen } from "lucide-react";
import "katex/dist/katex.min.css";
import { HelpMermaidBlock } from "../components/HelpMermaidBlock";
import { apiAbsoluteUrl, apiGet } from "../api/client";
import { useAgentContext } from "../contexts/AgentContext";
import { cn } from "../lib/utils";

function codeBlockPlainText(children: ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(codeBlockPlainText).join("");
  if (children == null) return "";
  return String(children);
}

type HelpIndexEntry = { id: string; title: string; audience: string; section?: string };
type HelpIndex = { pages: HelpIndexEntry[] };
type HelpPage = { id: string; title: string; audience: string; markdown: string };

const mdComponents = {
  h1: ({ children }: { children?: ReactNode }) => (
    <h1 className="mb-4 mt-8 border-b border-slate-200 pb-2 text-xl font-semibold text-slate-900 first:mt-0">{children}</h1>
  ),
  h2: ({ children }: { children?: ReactNode }) => (
    <h2 className="mb-3 mt-6 text-lg font-semibold text-slate-900">{children}</h2>
  ),
  h3: ({ children }: { children?: ReactNode }) => (
    <h3 className="mb-2 mt-4 text-base font-semibold text-slate-800">{children}</h3>
  ),
  p: ({ children }: { children?: ReactNode }) => <p className="mb-3 leading-relaxed text-slate-700">{children}</p>,
  ul: ({ children }: { children?: ReactNode }) => <ul className="mb-3 list-disc space-y-1 pl-6 text-slate-700">{children}</ul>,
  ol: ({ children }: { children?: ReactNode }) => <ol className="mb-3 list-decimal space-y-1 pl-6 text-slate-700">{children}</ol>,
  li: ({ children }: { children?: ReactNode }) => <li className="leading-relaxed">{children}</li>,
  a: ({ href, children }: { href?: string; children?: ReactNode }) => (
    <a
      href={href && href.startsWith("/api/") ? apiAbsoluteUrl(href) : href}
      className="font-medium text-sky-700 underline decoration-sky-300 underline-offset-2 hover:text-sky-900"
      target={href?.startsWith("/") ? undefined : "_blank"}
      rel={href?.startsWith("/") ? undefined : "noreferrer noopener"}
    >
      {children}
    </a>
  ),
  img: ({ src, alt }: { src?: string; alt?: string }) => (
    <figure className="my-5">
      <img
        src={src ? apiAbsoluteUrl(src) : undefined}
        alt={alt ?? ""}
        className="max-h-[min(420px,70vh)] max-w-full rounded-md border border-slate-200 bg-white p-2 shadow-sm"
        loading="lazy"
      />
      {alt ? <figcaption className="mt-2 text-center text-sm text-slate-600">{alt}</figcaption> : null}
    </figure>
  ),
  code: ({ className, children }: { className?: string; children?: ReactNode }) => {
    const inline = !className;
    if (inline) {
      return <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.9em] text-slate-800">{children}</code>;
    }
    return <code className={className}>{children}</code>;
  },
  pre: ({ children }: { children?: ReactNode }) => {
    const only = Children.toArray(children)[0];
    if (
      isValidElement(only) &&
      typeof only.props === "object" &&
      only.props !== null &&
      "className" in only.props &&
      typeof (only.props as { className?: string }).className === "string" &&
      (only.props as { className: string }).className.includes("language-mermaid")
    ) {
      const src = codeBlockPlainText((only.props as { children?: ReactNode }).children).replace(/\n$/, "");
      return <HelpMermaidBlock source={src} />;
    }
    return (
      <pre className="mb-4 overflow-x-auto rounded-lg border border-slate-200 bg-slate-900 p-3 text-sm text-slate-100 [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-inherit">
        {children}
      </pre>
    );
  },
  blockquote: ({ children }: { children?: ReactNode }) => (
    <blockquote className="mb-4 border-l-4 border-slate-300 pl-4 italic text-slate-600">{children}</blockquote>
  ),
  table: ({ children }: { children?: ReactNode }) => (
    <div className="mb-4 overflow-x-auto rounded-lg border border-slate-200">
      <table className="min-w-full border-collapse text-left text-sm text-slate-800">{children}</table>
    </div>
  ),
  thead: ({ children }: { children?: ReactNode }) => <thead className="bg-slate-100">{children}</thead>,
  th: ({ children }: { children?: ReactNode }) => (
    <th className="border-b border-slate-200 px-3 py-2 font-semibold">{children}</th>
  ),
  td: ({ children }: { children?: ReactNode }) => <td className="border-b border-slate-100 px-3 py-2">{children}</td>,
  hr: () => <hr className="my-6 border-slate-200" />,
};

export function HelpWorkspace({ onError }: { onError: (msg: string | null) => void }) {
  const { t } = useTranslation("help");
  const { setPageContext } = useAgentContext();
  const [index, setIndex] = useState<HelpIndexEntry[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [page, setPage] = useState<HelpPage | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const title = page?.title;
    setPageContext({
      current_page: "help",
      summary: title ? t("pageSummaryWithTitle", { title }) : t("pageSummaryDefault"),
    });
    return () => setPageContext(null);
  }, [page?.title, setPageContext, t]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        onError(null);
        const data = await apiGet<HelpIndex>("/api/help/index");
        if (cancelled) return;
        const pages = data.pages as HelpIndexEntry[];
        setIndex(pages);
        if (pages.length > 0) {
          const intro = pages.find((p) => p.section === "intro");
          setSelectedId((intro ?? pages[0]).id);
        }
      } catch (e) {
        if (!cancelled) {
          onError(e instanceof Error ? e.message : String(e));
          setIndex([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [onError]);

  useEffect(() => {
    if (!selectedId) {
      setPage(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        onError(null);
        const data = await apiGet<HelpPage>(`/api/help/page/${encodeURIComponent(selectedId)}`);
        if (!cancelled) setPage(data);
      } catch (e) {
        if (!cancelled) {
          onError(e instanceof Error ? e.message : String(e));
          setPage(null);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId, onError]);

  const introPages = useMemo(() => (index ?? []).filter((p) => p.section === "intro"), [index]);
  const guidePages = useMemo(() => (index ?? []).filter((p) => p.section === "guide"), [index]);
  const advancedPages = useMemo(() => (index ?? []).filter((p) => p.section === "advanced"), [index]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-50">
      <div className="shrink-0 border-b border-slate-200 bg-white px-6 py-4">
        <div className="flex items-center gap-2 text-slate-800">
          <BookOpen className="h-5 w-5" strokeWidth={1.75} />
          <h1 className="text-lg font-semibold">{t("title")}</h1>
          <span className="text-xs text-slate-500">{t("subtitle")}</span>
        </div>
      </div>
      <div className="flex min-h-0 flex-1">
        <aside className="w-[17rem] shrink-0 overflow-y-auto border-r border-slate-200 bg-white p-3">
          {loading && <p className="px-2 text-xs text-slate-500">{t("loading")}</p>}
          {!loading && index && index.length === 0 && <p className="px-2 text-xs text-slate-500">{t("empty")}</p>}
          {!loading && introPages.length > 0 && (
            <div className="mb-4">
              <div className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                {t("sectionIntro")}
              </div>
              <ul className="space-y-0.5">
                {introPages.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(p.id)}
                      className={cn(
                        "w-full rounded-md px-2 py-1.5 text-left text-sm",
                        selectedId === p.id ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-100",
                      )}
                    >
                      {p.title}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {!loading && guidePages.length > 0 && (
            <div className="mb-4">
              <div className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                {t("sectionGuide")}
              </div>
              <ul className="space-y-0.5">
                {guidePages.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(p.id)}
                      className={cn(
                        "w-full rounded-md px-2 py-1.5 text-left text-sm",
                        selectedId === p.id ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-100",
                      )}
                    >
                      {p.title}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {!loading && advancedPages.length > 0 && (
            <div className="mb-4">
              <div className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                {t("sectionAdvanced")}
              </div>
              <ul className="space-y-0.5">
                {advancedPages.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(p.id)}
                      className={cn(
                        "w-full rounded-md px-2 py-1.5 text-left text-sm",
                        selectedId === p.id ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-100",
                      )}
                    >
                      {p.title}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>
        <div className="min-w-0 flex-1 overflow-y-auto px-6 py-6">
          {page && (
            <article className="mx-auto max-w-3xl">
              <h2 className="mb-6 text-2xl font-semibold text-slate-900">{page.title}</h2>
              <div className="help-md [&_.katex-display]:my-4 [&_.katex-display]:overflow-x-auto [&_.katex-display]:py-1">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                  components={mdComponents}
                >
                  {page.markdown}
                </ReactMarkdown>
              </div>
            </article>
          )}
          {!page && loading && <p className="text-sm text-slate-500">{t("loadingBody")}</p>}
        </div>
      </div>
    </div>
  );
}
