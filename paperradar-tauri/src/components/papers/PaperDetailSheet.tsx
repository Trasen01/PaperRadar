import { X } from "lucide-react";
import type { Paper } from "../../types/paper";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";

type PaperDetailSheetProps = {
  paper: Paper | null;
  open: boolean;
  onClose: () => void;
  onOpenLink: (paper: Paper) => void;
};

export function PaperDetailSheet({ paper, open, onClose, onOpenLink }: PaperDetailSheetProps) {
  if (!open || !paper) return null;

  return (
    <div className="fixed inset-y-0 right-0 z-40 w-[460px] border-l border-slate-200 bg-white shadow-soft">
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div>
            <div className="text-sm font-semibold text-slate-950">论文详情</div>
            <div className="text-xs text-slate-500">摘要、关键词和外部链接</div>
          </div>
          <button className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700" onClick={onClose}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-5">
          <div className="mb-4 flex flex-wrap gap-2">
            <Badge variant="green">分数 {paper.score}</Badge>
            <Badge variant="blue">{paper.source}</Badge>
            <Badge variant={paper.status === "worth-reading" ? "green" : "slate"}>
              {paper.status === "worth-reading" ? "值得关注" : "候选论文"}
            </Badge>
          </div>
          <h3 className="text-xl font-semibold leading-8 text-slate-950">{paper.title}</h3>
          <p className="mt-3 text-sm leading-6 text-slate-500">{paper.authors.join(", ")}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            {paper.matchedKeywords.map((keyword) => (
              <Badge key={keyword} variant="slate">
                {keyword}
              </Badge>
            ))}
          </div>
          <div className="mt-6 rounded-2xl bg-slate-50 p-4">
            <div className="mb-2 text-xs font-semibold text-slate-500">摘要</div>
            <p className="text-sm leading-7 text-slate-700">{paper.abstract}</p>
          </div>
          <div className="mt-5 space-y-2 text-sm text-slate-600">
            <div>发布日期：{paper.publishedDate}</div>
            <div>DOI：{paper.doi || "暂无"}</div>
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-slate-100 p-4">
          <Button variant="secondary" disabled={!paper.url}>
            复制链接
          </Button>
          <Button variant="primary" disabled={!paper.url} onClick={() => onOpenLink(paper)}>
            打开论文链接
          </Button>
        </div>
      </div>
    </div>
  );
}
