/** 公式 / Mermaid / 图片插入目标 */
export type MathFieldKey = "content" | "answer" | "analysis";

export type EmbedKind =
  | { k: "q"; f: MathFieldKey }
  | { k: "gm" }
  | { k: "gi"; i: number; f: "content" | "answer" | "analysis" }
  /** 单题 options[key] */
  | { k: "qo"; key: string }
  /** 题组小题 options[key] */
  | { k: "gio"; i: number; key: string };
