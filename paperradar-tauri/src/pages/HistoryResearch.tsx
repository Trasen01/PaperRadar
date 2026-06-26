import { useEffect, useState } from "react";
import { FileText, FolderOpen, Play, Square } from "lucide-react";
import type { Paper } from "../types/paper";
import type { PaperSummary } from "../types/summary";
import { PageHeader } from "../components/layout/PageHeader";
import { Button } from "../components/ui/button";
import { Select } from "../components/ui/select";
import { Switch } from "../components/ui/switch";
import { Input } from "../components/ui/input";
import { Card, CardContent } from "../components/ui/card";
import { KpiCard } from "../components/status/KpiCard";
import { SourceStatusBar } from "../components/status/SourceStatusBar";
import { PaperTable } from "../components/papers/PaperTable";
import { PaperDetailSheet } from "../components/papers/PaperDetailSheet";
import { Toast } from "../components/ui/toast";
import { getHistoryPapers, startHistoryResearch } from "../services/api";
import { openPaperLink } from "../services/papers";

export function HistoryResearch() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [summary, setSummary] = useState<PaperSummary | null>(null);
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [arxivEnabled, setArxivEnabled] = useState(true);
  const [journalsEnabled, setJournalsEnabled] = useState(true);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    getHistoryPapers().then((result) => {
      setPapers(result.papers);
      setSummary(result.summary);
    });
  }, []);

  const handleStart = async () => {
    setRunning(true);
    setToast("正在进行历史调研");
    try {
      const result = await startHistoryResearch({ taskName: "当前方向历史调研", days: 365, minScore: 70, arxiv: arxivEnabled, journals: journalsEnabled });
      setPapers(result.papers);
      setSummary(result.summary);
      setToast("历史调研完成");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "历史调研失败");
    } finally {
      setRunning(false);
    }
  };

  const handleOpen = (paper: Paper) => {
    try {
      openPaperLink(paper);
      setToast("正在打开论文链接");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "打开链接失败");
    }
  };

  return (
    <>
      <PageHeader
        title="历史调研"
        description="面向更长时间范围进行系统检索，适合开题、综述和方向摸底。"
        actions={
          <>
            <Button variant="primary" onClick={handleStart} disabled={running}>
              <Play className="h-4 w-4" />
              {running ? "调研中" : "开始调研"}
            </Button>
            <Button variant="secondary" disabled={!running}>
              <Square className="h-4 w-4" />
              停止
            </Button>
          </>
        }
      />

      <div className="mb-5 grid grid-cols-5 gap-4">
        <KpiCard label="调研范围" value="365 天" hint="长期方向摸底" />
        <KpiCard label="本次抓取" value={summary?.totalFetched ?? 0} hint="历史范围内" tone="blue" />
        <KpiCard label="成功入库" value={summary?.candidateCount ?? 0} hint="去重后候选" tone="green" />
        <KpiCard label="缓存命中" value="按日复用" hint="后端保留缓存策略" tone="blue" />
        <KpiCard label="失败/超时" value={summary?.failedCount ?? 0} hint="按来源可查看" tone={summary?.failedCount ? "amber" : "green"} />
      </div>

      <Card className="mb-5">
        <CardContent className="flex flex-wrap items-center justify-between gap-4 py-4">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium text-slate-700">任务名称</span>
            <Input className="w-[210px]" defaultValue="当前方向历史调研" />
            <span className="text-sm font-medium text-slate-700">时间范围</span>
            <Select defaultValue="365">
              <option value="90">最近 90 天</option>
              <option value="180">最近 180 天</option>
              <option value="365">最近 365 天</option>
            </Select>
            <span className="text-sm font-medium text-slate-700">最低分</span>
            <Select defaultValue="70">
              <option value="60">60</option>
              <option value="70">70</option>
              <option value="80">80</option>
              <option value="90">90</option>
            </Select>
            <div className="flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2">
              <Switch checked={arxivEnabled} onCheckedChange={setArxivEnabled} />
              <span className="text-sm font-medium text-slate-700">arXiv：{arxivEnabled ? "已启用" : "未启用"}</span>
            </div>
            <div className="flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2">
              <Switch checked={journalsEnabled} onCheckedChange={setJournalsEnabled} />
              <span className="text-sm font-medium text-slate-700">顶级期刊：{journalsEnabled ? "已启用" : "未启用"}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary">
              <FileText className="h-4 w-4" />
              生成调研报告
            </Button>
            <Button variant="secondary">
              <FolderOpen className="h-4 w-4" />
              打开报告文件夹
            </Button>
          </div>
          {summary && <SourceStatusBar sources={summary.sources} />}
        </CardContent>
      </Card>

      <PaperTable
        title="历史调研结果"
        papers={papers}
        totalCount={summary?.candidateCount ?? papers.length}
        onOpen={handleOpen}
        onSelect={(paper) => {
          setSelectedPaper(paper);
          setDetailOpen(true);
        }}
        onPrimaryAction={handleStart}
        emptyTitle="还没有历史调研结果"
        emptyDescription="设置调研范围后，点击“开始调研”进行系统检索。"
        emptyActionLabel="开始调研"
      />

      <PaperDetailSheet paper={selectedPaper} open={detailOpen} onClose={() => setDetailOpen(false)} onOpenLink={handleOpen} />
      {toast && <Toast message={toast} type={toast.includes("失败") || toast.includes("暂无") ? "error" : "success"} />}
    </>
  );
}
