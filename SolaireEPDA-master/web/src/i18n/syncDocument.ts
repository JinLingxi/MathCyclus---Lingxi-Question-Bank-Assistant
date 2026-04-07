const TITLES: Record<string, string> = {
  zh: "Solaire · 组卷",
  en: "SolEdu · Papers",
};

export function applyDocumentLocale(lng: string) {
  const isEn = lng.startsWith("en");
  document.documentElement.lang = isEn ? "en" : "zh-CN";
  document.title = isEn ? TITLES.en : TITLES.zh;
}
