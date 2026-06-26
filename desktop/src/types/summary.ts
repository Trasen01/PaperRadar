export type SourceStatusValue = "success" | "partial" | "failed" | "timeout" | "disabled" | "pending";

export type SourceStatus = {
  label: string;
  enabled: boolean;
  status: SourceStatusValue;
  fetched: number;
  stored: number;
  displayed: number;
  failed: number;
  error: string | null;
};

export type SourceStatusMap = {
  arxiv: SourceStatus;
  journals: SourceStatus;
};

export type PaperSummary = {
  totalFetched: number;
  candidateCount: number;
  displayedCount: number;
  hiddenCount: number;
  failedCount: number;
  sources: SourceStatusMap;
};
