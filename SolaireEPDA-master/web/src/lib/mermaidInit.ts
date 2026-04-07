import mermaid from "mermaid";

let mermaidInited = false;

export function initMermaid(): void {
  if (!mermaidInited) {
    mermaid.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "loose" });
    mermaidInited = true;
  }
}
