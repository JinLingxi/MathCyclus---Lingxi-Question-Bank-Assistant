import { useEffect, useRef, type ReactNode } from "react";
import mermaid from "mermaid";

import { resourceApiUrl } from "../api/client";
import { initMermaid } from "../lib/mermaidInit";
import { buildKatexHtml } from "./KatexText";

/** PrimeBrush / Mermaid / EMBED Web markers, or raw ```mermaid fences (client render). */
const SEGMENT_RE =
  /:::((?:PRIMEBRUSH|MERMAID|EMBED)_IMG):([^:]+):::|```mermaid\s*\n([\s\S]*?)```/g;

function MermaidFencePreview({ body }: { body: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    initMermaid();
    const id = `mmd-prev-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    let cancelled = false;
    void (async () => {
      try {
        const { svg } = await mermaid.render(id, body.trim());
        if (!cancelled && ref.current) {
          ref.current.innerHTML = svg;
        }
      } catch {
        if (ref.current) {
          ref.current.textContent = "Mermaid 无法渲染（请检查语法）";
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [body]);
  return (
    <div
      ref={ref}
      className="my-2 max-h-72 w-full max-w-full overflow-auto rounded border border-slate-200 bg-slate-50 p-2 text-xs text-slate-600"
    />
  );
}

/**
 * KaTeX + `:::PRIMEBRUSH_IMG` / `:::MERMAID_IMG` / `:::EMBED_IMG` 占位图 + 源码围栏 `` ```mermaid `` 实时渲染。
 */
export function ContentWithPrimeBrush({ text, className }: { text: string; className?: string }) {
  const nodes: ReactNode[] = [];
  let last = 0;
  let key = 0;
  SEGMENT_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = SEGMENT_RE.exec(text)) !== null) {
    if (m.index > last) {
      const seg = text.slice(last, m.index);
      nodes.push(
        <span
          key={key++}
          // eslint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{ __html: buildKatexHtml(seg) }}
        />,
      );
    }
    if (m[1] != null && m[1] !== "") {
      const rel = (m[2] ?? "").trim();
      nodes.push(
        <img
          key={key++}
          className="my-2 max-h-72 max-w-full object-contain"
          src={resourceApiUrl(rel)}
          alt=""
        />,
      );
    } else {
      nodes.push(<MermaidFencePreview key={key++} body={m[3] ?? ""} />);
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) {
    const seg = text.slice(last);
    nodes.push(
      <span
        key={key++}
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: buildKatexHtml(seg) }}
      />,
    );
  }
  if (nodes.length === 0) {
    return (
      <div
        className={className}
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: buildKatexHtml(text) }}
      />
    );
  }
  return <div className={className}>{nodes}</div>;
}
