export type PaperSource = "arXiv" | "Nature" | "Nature Comm." | "顶级期刊" | "Other";

export type PaperStatus = "candidate" | "worth-reading" | "stored" | "failed";

export type Paper = {
  id: string;
  title: string;
  authors: string[];
  source: PaperSource;
  publishedDate: string;
  score: number;
  matchedKeywords: string[];
  abstract: string;
  url: string | null;
  doi: string | null;
  status: PaperStatus;
};
