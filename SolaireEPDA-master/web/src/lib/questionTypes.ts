/** 与后端 `QuestionType` 一致（`text` 仅用于模板节，不在此列表） */
export const QUESTION_TYPE_OPTIONS = [
  { value: "choice" },
  { value: "fill" },
  { value: "judge" },
  { value: "short_answer" },
  { value: "reasoning" },
  { value: "essay" },
] as const;

/** 题组内小题类型，与后端 `GroupInnerType` 一致 */
export const GROUP_INNER_TYPE_OPTIONS = [
  { value: "choice" },
  { value: "fill" },
  { value: "judge" },
] as const;
