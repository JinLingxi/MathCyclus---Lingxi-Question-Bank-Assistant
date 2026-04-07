/** 题组在 UI 中合并为一条展示；组卷中栏将同组连续小题聚成一块。 */

export type GroupableRow = {
  qualified_id: string;
  id: string;
  type: string;
  content_preview: string;
  group_id?: string | null;
  group_member_qualified_ids?: string[];
  group_material?: string | null;
};

function oneLinePreview(text: string, maxLen: number): string {
  const t = (text || "").replace(/\s+/g, " ").trim();
  if (t.length <= maxLen) {
    return t;
  }
  return `${t.slice(0, maxLen - 3)}...`;
}

/** 旧版「成员多行」已废弃；现后端对题组只返回一行。保留函数以兼容调用方。 */
export function collapseGroupRowsForList<T extends GroupableRow>(rows: T[]): T[] {
  return rows.map((q) => {
    if (q.type === "group" && q.group_material?.trim()) {
      const mat = oneLinePreview(q.group_material, 160);
      return {
        ...q,
        content_preview: `【题组】 ${mat}`.trim(),
      };
    }
    return q;
  });
}

export type SectionSlot<T extends GroupableRow> =
  | { kind: "single"; qid: string }
  | { kind: "group"; qids: string[]; rep: T };

/** 将连续且构成完整题组的 id 合并为一条展示槽（顺序与试卷列表一致）。 */
export function clusterAdjacentGroupSlots<T extends GroupableRow>(
  qids: string[],
  qmap: Map<string, T>,
): SectionSlot<T>[] {
  const slots: SectionSlot<T>[] = [];
  let i = 0;
  while (i < qids.length) {
    const qid = qids[i];
    const row = qmap.get(qid);
    const mids = row?.group_member_qualified_ids;
    if (!row || !mids || mids.length === 0) {
      slots.push({ kind: "single", qid });
      i++;
      continue;
    }
    const set = new Set(mids);
    const chunk: string[] = [];
    let j = i;
    while (j < qids.length && set.has(qids[j])) {
      chunk.push(qids[j]);
      j++;
    }
    if (chunk.length === mids.length && new Set(chunk).size === mids.length) {
      slots.push({ kind: "group", qids: chunk, rep: row });
      i = j;
    } else {
      slots.push({ kind: "single", qid });
      i++;
    }
  }
  return slots;
}

export function sectionSlotContainsQid<T extends GroupableRow>(slot: SectionSlot<T>, qid: string): boolean {
  if (slot.kind === "single") {
    return slot.qid === qid;
  }
  return slot.qids.includes(qid);
}
