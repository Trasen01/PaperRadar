import { useEffect, useState } from "react";
import { AlertTriangle, FileText, FolderOpen, Play, Square } from "lucide-react";
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
import { PaperRadarApiError, getRuntimeMode, getStatus, startHistoryResearch, userMessageForError } from "../services/api";
import { openPaperLink } from "../services/papers";

type RunState = "idle" | "researching" | "success" | "empty" | "partial_success" | "backend_offline" | "api_failed" | "internal_error" | "cancelled";
type ToastState = { message: string; type: "success" | "error" | "warning" | "info" } | null;

function hasSourceProblem(summary: PaperSummary | null) {
  if (!summary) return false;
  return Object.values(summary.sources).some((source) => source.status === "failed" || source.status === "timeout" || source.status === "partial" || source.failed > 0);
}

function stateFromError(error: unknown): RunState {
  if (error instanceof PaperRadarApiError) {
    if (error.kind === "backend_offline") return "backend_offline";
    if (error.kind === "api_failed") return "api_failed";
    return "internal_error";
  }
  return "internal_error";
}

function statusLabel(state: RunState) {
  const labels: Record<RunState, string> = {
    idle: "待调研",
    researching: "调研中",
    success: "已完成",
    empty: "无匹配结果",
    partial_success: "部分完成",
    backend_offline: "后端未连接",
    api_failed: "请求失败",
    internal_error: "内部错误",
    cancelled: "已停止"
  };
  return labels[state];
}

function emptyCopy(state: RunState) {
  if (state === "backend_offline") return { title: "本地后端未连接", description: "无法启动历史调研，请确认后端服务正在运行。", action: "重试连接" };
  if (state === "api_failed" || state === "internal_error") return { title: "历史调研未完成", description: "调研过程中出现错误，部分结果可能未保存。", action: "重新调研" };
  if (state === "empty") return { title: "没有找到历史文献", description: "可以扩大时间范围、降低最低分，或调整研究方向关键词。", action: "调整调研条件" };
  if (state === "researching") return { title: "正在进行历史调研", description: "PaperRadar 正在系统检索较长时间范围内的文献，请稍候。", action: "调研中" };
  return { title: "还没有历史调研结果", description: "设置调研范围后，点击“开始调研”进行系统检索。", action: "开始调研" };
}

export function HistoryResearch() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [summary, setSummary] = useState<PaperSummary | null>(null);
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [toast, setToast] = useState<ToastState>(null);
  const [arxivEnabled, setArxivEnabled] = useState(true);
  const [journalsEnabled, setJournalsEnabled] = useState(true);
  const [state, setState] = useState<RunState>("idle");
  const [errorDetail, setErrorDetail] = useState<string | null>(null);

  const mockMode = getRuntimeMode() === "mock";
  const running = state === "researching";
  const backendOffline = state === "backend_offline";

  const checkBackend = async () => {
    if (mockMode) return;
    try {
      await getStatus();
      if (state === "backend_offline") setState("idle");
      setToast({ message: "本地后端连接正常", type: "success" });
    } catch (error) {
      setState("backend_offline");
      setErrorDetail(error instanceof PaperRadarApiError ? error.detail ?? null : String(error));
      setToast({ message: userMessageForError(error), type: "error" });
    }
  };

  useEffect(() => {
    if (!mockMode) void checkBackend();
  }, []);

  const handleStart = async () => {
    if (backendOffline) {
      await checkBackend();
      return;
    }
    setState("researching");
    setErrorDetail(null);
    setToast({ message: mockMode ? "正在使用演示数据" : "正在进行历史调研", type: "info" });
    setPapers([]);
    setSummary(null);
    try {
      const result = await startHistoryResearch({ taskName: "当前方向历史调研", days: 365, minScore: 70, arxiv: arxivEnabled, journals: journalsEnabled });
      setPapers(result.papers);
      setSummary(result.summary);
      const nextState = result.papers.length === 0 ? "empty" : hasSourceProblem(result.summary) ? "partial_success" : "success";
      setState(nextState);
      setToast({ message: nextState === "empty" ? "调研完成，但没有找到匹配文献" : nextState === "partial_success" ? "调研部分完成，请查看来源状态" : "历史调研完成", type: nextState === "partial_success" ? "warning" : "success" });
    } catch (error) {
      const nextState = stateFromError(error);
      setState(nextState);
      setErrorDetail(error instanceof PaperRadarApiError ? error.detail ?? null : String(error));
      setToast({ message: userMessageForError(error), type: "error" });
    }
  };

  const handleOpen = (paper: Paper) => {
    try {
      openPaperLink(paper);
      setToast({ message: "正在打开论文链接", type: "info" });
    } catch (error) {
      setToast({ message: error instanceof Error ? error.message : "打开链接失败", type: "error" });
    }
  };

  const copy = emptyCopy(state);

  return (
    <>
      <PageHeader
        title="历史调研"
        description="面向更长时间范围进行系统检索，适合开题、综述和方向摸底。"
        actions={
          <>
            <Button variant="primary" onClick={handleStart} disabled={running}>
              <Play className="h-4 w-4" />
              {backendOffline ? "重试连接" : running ? "调研中" : "开始调研"}
            </Button>
            <Button variant="secondary" disabled={!running} onClick={() => setState("cancelled")}>
              <Square className="h-4 w-4" />
              停止
            </Button>
          </>
        }
      />

      {mockMode && <div className="mb-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">当前为演示数据模式，不会连接本地后端。</div>}

      <div className="mb-5 grid grid-cols-5 gap-4">
        <KpiCard label="调研范围" value="365 天" hint="适合方向摸底" />
        <KpiCard label="本次抓取" value={summary ? summary.totalFetched : "--"} hint="历史范围内" tone="blue" />
        <KpiCard label="成功入库" value={summary ? summary.candidateCount : "--"} hint="去重后候选" tone="green" />
        <KpiCard label="结果复用" value="自动判断" hint="当天已获取的结果会自动复用，避免重复检索" tone="blue" />
        <KpiCard label="运行状态" value={statusLabel(state)} hint={errorDetail ?? (summary ? `${summary.failedCount} 个异常` : "等待用户操作")} tone={state === "backend_offline" || state === "api_failed" || state === "internal_error" ? "red" : state === "partial_success" ? "amber" : "blue"} />
      </div>

      <Card className="mb-5"><CardContent className="flex flex-wrap items-center justify-between gap-4 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm font-medium text-slate-700">任务名称</span><Input className="w-[210px]" defaultValue="当前方向历史调研" />
          <span className="text-sm font-medium text-slate-700">时间范围</span><Select defaultValue="365"><option value="90">最近 90 天</option><option value="180">最近 180 天</option><option value="365">最近 365 天</option></Select>
          <span className="text-sm font-medium text-slate-700">最低分</span><Select defaultValue="70"><option value="90">90</option><option value="80">80</option><option value="70">70</option><option value="60">60</option><option value="50">50</option><option value="40">40</option><option value="30">30</option><option value="20">20</option></Select>
          <div className="flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2"><Switch checked={arxivEnabled} onCheckedChange={setArxivEnabled} /><span className="text-sm font-medium text-slate-700">arXiv：{arxivEnabled ? "已启用" : "未启用"}</span></div>
          <div className="flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2"><Switch checked={journalsEnabled} onCheckedChange={setJournalsEnabled} /><span className="text-sm font-medium text-slate-700">顶级期刊：{journalsEnabled ? "已启用" : "未启用"}</span></div>
        </div>
        <div className="flex items-center gap-2"><Button variant="secondary"><FileText className="h-4 w-4" />生成调研报告</Button><Button variant="secondary"><FolderOpen className="h-4 w-4" />打开报告文件夹</Button></div>
        {summary && <SourceStatusBar sources={summary.sources} />}
      </CardContent></Card>

      <PaperTable
        title="历史调研结果"
        papers={state === "success" || state === "partial_success" ? papers : []}
        totalCount={summary?.candidateCount ?? 0}
        onOpen={handleOpen}
        onSelect={(paper) => { setSelectedPaper(paper); setDetailOpen(true); }}
        onPrimaryAction={state === "backend_offline" ? checkBackend : handleStart}
        emptyTitle={copy.title}
        emptyDescription={copy.description}
        emptyActionLabel={copy.action}
      />

      {errorDetail && (state === "api_failed" || state === "internal_error") && <div className="mt-4 rounded-2xl border border-red-100 bg-red-50 p-4 text-sm text-red-800"><div className="mb-1 flex items-center gap-2 font-medium"><AlertTriangle className="h-4 w-4" />错误详情</div><div className="break-all text-xs leading-5">{errorDetail}</div></div>}
      <PaperDetailSheet paper={selectedPaper} open={detailOpen} onClose={() => setDetailOpen(false)} onOpenLink={handleOpen} />
      {toast && <Toast message={toast.message} type={toast.type} />}
    </>
  );
}