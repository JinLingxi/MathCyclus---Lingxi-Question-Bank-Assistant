import katex from "katex";
import "katex/dist/katex.min.css";

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Plain text + `$...$` inline math → HTML string (for composition with PrimeBrush imgs). */
export function buildKatexHtml(text: string): string {
  const parts = text.split("$");
  const html: string[] = [];
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 0) {
      html.push(escapeHtml(parts[i]).replace(/\n/g, "<br/>"));
    } else {
      try {
        html.push(katex.renderToString(parts[i], { throwOnError: false, displayMode: false }));
      } catch {
        html.push(`<span class="katex-error">${escapeHtml("$" + parts[i] + "$")}</span>`);
      }
    }
  }
  return html.join("");
}

/** Renders plain text with `$...$` inline math via KaTeX. */
export function KatexText({ text, className }: { text: string; className?: string }) {
  return (
    <div
      className={className}
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: buildKatexHtml(text) }}
    />
  );
}
