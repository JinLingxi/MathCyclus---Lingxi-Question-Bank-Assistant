/** 是否在 Tauri 桌面壳内运行（用于区分浏览器开发调试）。 */
export function isTauriShell(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as unknown as Record<string, unknown>;
  return "__TAURI_INTERNALS__" in w || w.__TAURI__ !== undefined;
}
