export type KeywordWeight = "high" | "medium" | "low";

export type Keyword = {
  group: string;
  weight: KeywordWeight;
  text: string;
};

export type ResearchProfile = {
  id: string;
  name: string;
  description: string;
  queryCount: number;
  keywordGroupCount: number;
  isCurrent: boolean;
  keywords: Keyword[];
};
