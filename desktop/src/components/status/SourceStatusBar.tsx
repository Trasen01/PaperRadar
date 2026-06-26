import { CircleAlert, CircleCheck, CircleDashed } from "lucide-react";
import type { SourceStatusMap } from "../../types/summary";
import { Badge } from "../ui/badge";

type SourceStatusBarProps = {
  sources: SourceStatusMap;
};

function labelFor(status: string) {
  if (status === "success") return "成功";
  if (status === "partial") return "部分成功";
  if (status === "failed") return "失败";
  if (status === "timeout") return "超时";
  if (status === "disabled") return "未启用";
  return "等待中";
}

function variantFor(status: string) {
  if (status === "success") return "green" as const;
  if (status === "failed" || status === "timeout") return "red" as const;
  if (status === "partial") return "amber" as const;
  return "slate" as const;
}

function iconFor(status: string) {
  if (status === "success") return <CircleCheck className="h-4 w-4 text-emerald-600" />;
  if (status === "failed" || status === "timeout") return <CircleAlert className="h-4 w-4 text-red-600" />;
  return <CircleDashed className="h-4 w-4 text-slate-400" />;
}

export function SourceStatusBar({ sources }: SourceStatusBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {Object.entries(sources).map(([key, source]) => (
        <div key={key} className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm" title={source.error ?? undefined}>
          {iconFor(source.status)}
          <span className="font-medium text-slate-800">{source.label}</span>
          <Badge variant={variantFor(source.status)}>{labelFor(source.status)}</Badge>
          <span className="text-xs text-slate-500">
            抓取 {source.fetched} · 显示 {source.displayed} · 失败 {source.failed}
          </span>
          {source.error && <span className="max-w-[220px] truncate text-xs text-amber-700">{source.error}</span>}
        </div>
      ))}
    </div>
  );
}
