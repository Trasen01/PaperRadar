import { ExternalLink, Search } from "lucide-react";
import type { Paper } from "../../types/paper";
import { cn } from "../../lib/utils";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { EmptyState } from "../ui/empty-state";

type PaperTableProps = {
  title: string;
  papers: Paper[];
  totalCount: number;
  onOpen: (paper: Paper) => void | Promise<void>;
  onSelect: (paper: Paper) => void;
  onPrimaryAction?: () => void;
  emptyActionLabel: string;
  emptyTitle: string;
  emptyDescription: string;
};

function normalizeSource(source: string) {
  const value = (source || "").trim();
  const lower = value.toLowerCase();
  if (!value) return "未知来源";
  if (lower.includes("arxiv")) return "arXiv";
  if (lower.includes("nature communications")) return "Nature Comm.";
  if (lower === "nature comm.") return "Nature Comm.";
  if (lower === "nature") return "Nature";
  if (value.includes("顶级期刊")) return "顶级期刊";
  return value.replace(/[|｜:：]+$/g, "").trim();
}

function sourceVariant(source: string) {
  const label = normalizeSource(source);
  if (label === "arXiv") return "blue" as const;
  if (label === "Nature" || label === "Nature Comm." || label === "顶级期刊") return "purple" as const;
  return "slate" as const;
}

function scoreVariant(score: number) {
  if (score >= 90) return "green" as const;
  if (score >= 75) return "blue" as const;
  if (score >= 60) return "amber" as const;
  return "slate" as const;
}

function shortAuthors(authors: string[]) {
  if (authors.length <= 3) return authors.join(", ");
  return `${authors.slice(0, 3).join(", ")} 等`;
}

export function PaperTable({
  title,
  papers,
  totalCount,
  onOpen,
  onSelect,
  onPrimaryAction,
  emptyActionLabel,
  emptyTitle,
  emptyDescription
}: PaperTableProps) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-card">
      <div className="flex items-center justify-between gap-4 border-b border-slate-100 px-5 py-4">
        <div>
          <h2 className="text-base font-semibold text-slate-950">{title}</h2>
          <p className="mt-1 text-xs text-slate-500">
            当前显示 {papers.length} 篇，共 {totalCount} 篇。来源和分数已标签化，链接在最后一列打开。
          </p>
        </div>
        <div className="relative w-[340px]">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:bg-white focus:ring-4 focus:ring-blue-500/10"
            placeholder="搜索标题、作者、关键词、摘要"
          />
        </div>
      </div>

      {papers.length === 0 ? (
        <div className="p-5">
          <EmptyState title={emptyTitle} description={emptyDescription} actionLabel={emptyActionLabel} onAction={onPrimaryAction} />
        </div>
      ) : (
        <div className="max-h-[620px] min-h-[420px] overflow-auto">
          <div className="min-w-[1540px]">
            <div className="paper-table-grid sticky top-0 z-10 grid items-center border-b border-slate-200 bg-slate-50/95 px-4 py-3 text-center text-xs font-semibold text-slate-500 backdrop-blur">
              <div>分数</div>
              <div>来源</div>
              <div>标题</div>
              <div>作者</div>
              <div>发布日期</div>
              <div>命中关键词</div>
              <div>链接</div>
            </div>
            {papers.map((paper) => {
              const sourceLabel = normalizeSource(paper.source);
              return (
                <div
                  key={paper.id}
                  className="paper-table-grid grid min-h-[52px] cursor-default items-center border-b border-slate-100 px-4 py-2 text-sm transition hover:bg-blue-50/50"
                  onClick={() => onSelect(paper)}
                  onDoubleClick={() => { void onOpen(paper); }}
                >
                  <div className="flex justify-center">
                    <Badge variant={scoreVariant(paper.score)}>{paper.score}</Badge>
                  </div>
                  <div className="flex justify-center">
                    <Badge className="w-full min-w-0 justify-center whitespace-normal px-3 text-center leading-4" variant={sourceVariant(sourceLabel)} title={sourceLabel}>
                      {sourceLabel}
                    </Badge>
                  </div>
                  <div className="truncate px-3 font-medium text-slate-900 hover:text-blue-700" title={`${paper.title}\n双击打开论文链接`}>
                    {paper.title}
                  </div>
                  <div className="truncate px-3 text-slate-600" title={paper.authors.join(", ")}>
                    {shortAuthors(paper.authors)}
                  </div>
                  <div className="text-center text-slate-500">{paper.publishedDate}</div>
                  <div className="flex min-w-0 flex-wrap justify-center gap-1.5 px-2">
                    {paper.matchedKeywords.slice(0, 3).map((keyword) => (
                      <Badge key={keyword} variant="slate" className="min-w-0 whitespace-normal px-2 text-center font-medium leading-4" title={paper.matchedKeywords.join(", ")}>
                        {keyword}
                      </Badge>
                    ))}
                  </div>
                  <div className="flex justify-center">
                    <Button
                      size="sm"
                      variant={paper.url ? "secondary" : "ghost"}
                      disabled={!paper.url}
                      onClick={(event) => {
                        event.stopPropagation();
                        void onOpen(paper);
                      }}
                      className={cn("h-8 w-[76px] justify-center", paper.url && "text-blue-700")}
                    >
                      {paper.url ? (
                        <>
                          打开 <ExternalLink className="h-3.5 w-3.5" />
                        </>
                      ) : (
                        "无链接"
                      )}
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
