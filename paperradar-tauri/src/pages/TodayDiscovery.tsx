import { useEffect, useState } from "react";
import { FileText, FolderOpen, Play, Square } from "lucide-react";
import type { Paper } from "../types/paper";
import type { PaperSummary } from "../types/summary";
import { PageHeader } from "../components/layout/PageHeader";
import { Button } from "../components/ui/button";
import { Select } from "../components/ui/select";
import { Switch } from "../components/ui/switch";
import { Card, CardContent } from "../components/ui/card";
import { KpiCard } from "../components/status/KpiCard";
import { SourceStatusBar } from "../components/status/SourceStatusBar";
import { PaperTable } from "../components/papers/PaperTable";
import { PaperDetailSheet } from "../components/papers/PaperDetailSheet";
import { Toast } from "../components/ui/toast";
import { checkTodayPapers, getTodayPapers } from "../services/api";
import { openPaperLink } from "../services/papers";

export function TodayDiscovery() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [summary, setSummary] = useState<PaperSummary | null>(null);
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [arxivEnabled, setArxivEnabled] = useState(true);
  const [journalsEnabled, setJournalsEnabled] = useState(true);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    getTodayPapers().then((result) => {
      setPapers(result.papers);
      setSummary(result.summary);
    });
  }, []);

  const handleCheck = async () => {
    setRunning(true);
    setToast("正在检索论文");
    try {
      const result = await checkTodayPapers({ daysBack: 7, minScore: 70, arxiv: arxivEnabled, journals: journalsEnabled });
      setPapers(result.papers);
      setSummary(result.summary);
      setToast("检索完成");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "检索失败");
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
        title="今日发现"
        description="自动检索与你研究方向相关的最新论文，并筛选出值得关注的工作。"
        actions={
          <>
            <Button variant="primary" onClick={handleCheck} disabled={running}>
              <Play className="h-4 w-4" />
              {running ? "检索中" : "立即检查"}
            </Button>
            <Button variant="secondary" disabled={!running}>
              <Square className="h-4 w-4" />
              停止
            </Button>
          </>
        }
      />

      <div className="mb-5 grid grid-cols-5 gap-4">
        <KpiCard label="上次检查" value="本地缓存" hint="后端可用时读取真实数据" />
        <KpiCard label="本次抓取" value={summary?.totalFetched ?? 0} hint="原始抓取数量" tone="blue" />
        <KpiCard label="候选论文" value={summary?.candidateCount ?? 0} hint="评分后候选" tone="green" />
        <KpiCard label="值得关注" value={papers.filter((paper) => paper.status === "worth-reading").length} hint="高相关论文" tone="green" />
        <KpiCard label="运行状态" value={running ? "检索中" : "就绪"} hint={`${summary?.failedCount ?? 0} 个异常`} tone={summary?.failedCount ? "amber" : "blue"} />
      </div>

      <Card className="mb-5">
        <CardContent className="flex flex-wrap items-center justify-between gap-4 py-4">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium text-slate-700">最近天数</span>
            <Select defaultValue="7">
              <option value="3">最近 3 天</option>
              <option value="7">最近 7 天</option>
              <option value="14">最近 14 天</option>
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
              生成今日报告
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
        title="今日论文列表"
        papers={papers}
        totalCount={summary?.candidateCount ?? papers.length}
        onOpen={handleOpen}
        onSelect={(paper) => {
          setSelectedPaper(paper);
          setDetailOpen(true);
        }}
        onPrimaryAction={handleCheck}
        emptyTitle="还没有论文结果"
        emptyDescription="点击“立即检查”，PaperRadar 会自动检索与你研究方向相关的最新论文。"
        emptyActionLabel="立即检查"
      />

      <PaperDetailSheet paper={selectedPaper} open={detailOpen} onClose={() => setDetailOpen(false)} onOpenLink={handleOpen} />
      {toast && <Toast message={toast} type={toast.includes("失败") || toast.includes("暂无") ? "error" : "success"} />}
    </>
  );
}
