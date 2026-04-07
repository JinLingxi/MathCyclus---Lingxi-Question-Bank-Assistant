import { useEffect, useId, useRef } from "react";
import mermaid from "mermaid";

let mermaidInit = false;

function ensureMermaidInit() {
  if (mermaidInit) return;
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: "neutral",
    fontFamily: "ui-sans-serif, system-ui, sans-serif",
  });
  mermaidInit = true;
}

/** Renders a Mermaid diagram from fenced ```mermaid source (help manual only). */
export function HelpMermaidBlock({ source }: { source: string }) {
  const uid = useId().replace(/:/g, "");
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ensureMermaidInit();
    const el = hostRef.current;
    if (!el) return;
    const id = `help-mmd-${uid}-${Math.random().toString(36).slice(2, 9)}`;
    let cancelled = false;
    void mermaid.render(id, source.trim()).then(
      ({ svg }) => {
        if (!cancelled && hostRef.current) {
          hostRef.current.innerHTML = svg;
        }
      },
      () => {
        if (!cancelled && hostRef.current) {
          hostRef.current.innerHTML =
            '<p class="text-sm text-red-600">流程图无法渲染，请稍后再试。</p>';
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [source, uid]);

  return (
    <div
      className="my-5 overflow-x-auto rounded-lg border border-slate-200 bg-slate-50 p-4 [&_svg]:mx-auto [&_svg]:max-w-full"
      ref={hostRef}
      role="img"
      aria-label="流程图"
    />
  );
}
