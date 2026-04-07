import { useEffect, useRef } from "react";
import { MathfieldElement } from "mathlive";
import "mathlive";
import "mathlive/fonts.css";

type MathInsertOverlayProps = {
  open: boolean;
  onClose: () => void;
  /** Wrapped snippet e.g. `$\\frac12$` */
  onConfirm: (latexWrapped: string) => void;
};

/**
 * Modal with MathLive editor; confirms with inline-math wrapped LaTeX for KaTeX `$...$`.
 */
export function MathInsertOverlay({ open, onClose, onConfirm }: MathInsertOverlayProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const mfRef = useRef<MathfieldElement | null>(null);

  useEffect(() => {
    if (!open) {
      mfRef.current = null;
      return;
    }
    const host = hostRef.current;
    if (!host) {
      return;
    }
    const mf = new MathfieldElement();
    mf.className =
      "w-full min-h-[52px] rounded-md border border-slate-300 bg-white px-2 py-2 text-base text-slate-900";
    host.innerHTML = "";
    host.appendChild(mf);
    mfRef.current = mf;
    void mf.focus();

    return () => {
      mfRef.current = null;
      host.innerHTML = "";
    };
  }, [open]);

  if (!open) {
    return null;
  }

  function tryConfirm() {
    const mf = mfRef.current;
    if (!mf) {
      return;
    }
    const latex = mf.getValue("latex").trim();
    if (!latex) {
      return;
    }
    onConfirm(`$${latex}$`);
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="math-insert-title"
      onClick={onClose}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          onClose();
        }
      }}
    >
      <div
        className="w-full max-w-lg rounded-lg border border-slate-200 bg-white p-4 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="math-insert-title" className="text-sm font-semibold text-slate-800">
          插入公式
        </h3>
        <p className="mt-1 text-xs text-slate-500">
          在下方编辑，确认后将作为行内公式（$...$）插入到光标处。
        </p>
        <div ref={hostRef} className="mt-3 min-h-[52px]" />
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
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-40"
            onClick={tryConfirm}
          >
            插入
          </button>
        </div>
      </div>
    </div>
  );
}
