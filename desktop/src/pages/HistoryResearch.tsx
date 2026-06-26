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
import { PaperRadarApiError, getRuntimeMode, startHistoryResearch, waitForLocalService, userFacingError } from "../services/api";
import { openPaperLink } from "../services/papers";

type RunState = "idle" | "researching" | "success" | "empty" | "partial_success" | "service_unavailable" | "request_failed" | "internal_error" | "cancelled";
type ToastState = { title?: string; description?: string; message?: string; type: "success" | "error" | "warning" | "info"; actionLabel?: string; onAction?: () => void; secondaryActionLabel?: string; onSecondaryAction?: () => void } | null;

const SCORE_OPTIONS = [90, 80, 70, 60, 50, 40, 30, 20];
const RANGE_OPTIONS = [90, 180, 365, 730];

function hasSourceProblem(summary: PaperSummary | null) {
  if (!summary) return false;
  return Object.values(summary.sources).some((source) => source.status === "failed" || source.status === "timeout" || source.status === "partial" || source.failed > 0);
}

function stateFromError(error: unknown): RunState {
  if (error instanceof PaperRadarApiError) {
    if (error.kind === "local_service_unavailable") return "service_unavailable";
    if (error.kind === "request_failed") return "request_failed";
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
    service_unavailable: "服务未启动",
    request_failed: "请求未完成",
    internal_error: "内部异常",
    cancelled: "已停止"
  };
  return labels[state];
}

function emptyCopy(state: RunState) {
  if (state === "service_unavailable") {
    return { title: "文献检索服务未启动", description: "PaperRadar 暂时无法进行历史调研。请点击重新连接，或查看日志。", action: "重新连接", secondary: "查看日志" };
  }
  if (state === "request_failed" || state === "internal_error") {
    return { title: "历史调研未完成", description: "调研过程中出现错误，部分结果可能未保存。请重新调研，或查看日志了解原因。", action: "重新调研", secondary: "查看日志" };
  }
  if (state === "empty") {
    return { title: "没有找到历史文献", description: "可以扩大时间范围、降低最低分，或调整研究方向关键词。", action: "重新调研" };
  }
  if (state === "researching") {
    return { title: "正在进行历史调研", description: "PaperRadar 正在系统检索较长时间范围内的文献，请稍候。", action: "调研中" };
  }
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
  const [taskName, setTaskName] = useState("当前方向历史调研");
  const [days, setDays] = useState(365);
  const [minScore, setMinScore] = useState(70);
  const [state, setState] = useState<RunState>("idle");
  const [lastErrorDetail, setLastErrorDetail] = useState<string | null>(null);

  const mockMode = getRuntimeMode() === "mock";
  const running = state === "researching";
  const serviceUnavailable = state === "service_unavailable";

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 4200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const showLogs = () => {
    setToast({ title: "日志已记录", description: lastErrorDetail ? "详细错误已保留在本地日志中。" : "当前没有新的错误日志。", type: "info" });
  };

  const checkService = async () => {
    if (mockMode) return true;
    try {
      await waitForLocalService({ restart: state === "service_unavailable" });
      if (state === "service_unavailable") setState("idle");
      setLastErrorDetail(null);
      setToast({ title: "文献检索服务已就绪", description: "现在可以开始历史调研。", type: "success" });
      return true;
    } catch (error) {
      const info = userFacingError(error);
      setState("service_unavailable");
      setLastErrorDetail(info.detail);
      setToast({ title: "文献检索服务暂不可用", description: "PaperRadar 无法启动本地检索服务。请点击重试，或查看日志。", type: "error", actionLabel: "重试", onAction: checkService, secondaryActionLabel: "查看日志", onSecondaryAction: showLogs });
      return false;
    }
  };

  useEffect(() => {
    if (!mockMode) void checkService();
  }, []);

  const handleStart = async () => {
    if (serviceUnavailable) {
      await checkService();
      return;
    }

    setState("researching");
    setLastErrorDetail(null);
    setToast({ title: mockMode ? "演示调研中" : "正在进行历史调研", description: "PaperRadar 正在系统检索、去重并评分。", type: "info" });
    setPapers([]);
    setSummary(null);

    try {
      const result = await startHistoryResearch({ taskName, days, minScore, arxiv: arxivEnabled, journals: journalsEnabled });
      setPapers(result.papers);
      setSummary(result.summary);
      const nextState: RunState = result.papers.length === 0 ? "empty" : hasSourceProblem(result.summary) ? "partial_success" : "success";
      setState(nextState);
      setToast({
        title: nextState === "empty" ? "调研完成" : nextState === "partial_success" ? "调研部分完成" : "历史调研完成",
        description: nextState === "empty" ? "没有找到匹配文献，可以调整调研条件后重试。" : `当前显示 ${result.papers.length} 篇，候选 ${result.summary.candidateCount} 篇。`,
        type: nextState === "partial_success" ? "warning" : "success"
      });
    } catch (error) {
      const nextState = stateFromError(error);
      const info = userFacingError(error);
      setState(nextState);
      setLastErrorDetail(info.detail);
      setToast({ title: info.title, description: info.message, type: "error", actionLabel: nextState === "service_unavailable" ? "重试" : "重新调研", onAction: nextState === "service_unavailable" ? checkService : handleStart, secondaryActionLabel: "查看日志", onSecondaryAction: showLogs });
    }
  };

  const handleOpen = (paper: Paper) => {
    try {
      openPaperLink(paper);
      setToast({ title: "正在打开论文链接", description: "将使用系统默认浏览器打开。", type: "info" });
    } catch (error) {
      setToast({ title: "无法打开论文链接", description: error instanceof Error ? error.message : "该论文暂无可用链接。", type: "error" });
    }
  };

  const copy = emptyCopy(state);
  const tableVisible = state === "success" || state === "partial_success";

  return (
    <>
      <PageHeader
        title="历史调研"
        description="面向更长时间范围进行系统检索，适合开题、综述和方向摸底。"
        actions={
          <>
            <Button variant="primary" onClick={serviceUnavailable ? checkService : handleStart} disabled={running}>
              <Play className="h-4 w-4" />
              {serviceUnavailable ? "重新连接" : running ? "调研中" : "开始调研"}
            </Button>
            <Button variant="secondary" disabled={!running} onClick={() => setState("cancelled")}>
              <Square className="h-4 w-4" />
              停止
            </Button>
          </>
        }
      />

      {mockMode && <div className="mb-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">当前为演示数据模式，不会启动真实调研。</div>}

      <div className="mb-5 grid grid-cols-5 gap-4">
        <KpiCard label="调研范围" value={`${days} 天`} hint="适合方向摸底" />
        <KpiCard label="本次抓取" value={summary ? summary.totalFetched : "--"} hint="历史范围内" tone="blue" />
        <KpiCard label="成功入库" value={summary ? summary.candidateCount : "--"} hint="去重后候选" tone="green" />
        <KpiCard label="结果复用" value="自动判断" hint="当天已获取的结果会自动复用，避免重复检索" tone="blue" />
        <KpiCard label="运行状态" value={statusLabel(state)} hint={serviceUnavailable ? "无法调研" : summary ? `${summary.failedCount} 个异常` : "等待用户操作"} tone={state === "service_unavailable" || state === "request_failed" || state === "internal_error" ? "red" : state === "partial_success" ? "amber" : "blue"} />
      </div>

      <Card className="mb-5">
        <CardContent className="flex flex-wrap items-center justify-between gap-4 py-4">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium text-slate-700">任务名称</span><Input className="w-[210px]" value={taskName} onChange={(event) => setTaskName(event.target.value)} />
            <span className="text-sm font-medium text-slate-700">时间范围</span>
            <Select value={String(days)} onChange={(event) => setDays(Number(event.target.value))}>
              {RANGE_OPTIONS.map((day) => <option key={day} value={day}>最近 {day} 天</option>)}
            </Select>
            <span className="text-sm font-medium text-slate-700">最低分</span>
            <Select value={String(minScore)} onChange={(event) => setMinScore(Number(event.target.value))}>
              {SCORE_OPTIONS.map((score) => <option key={score} value={score}>{score}</option>)}
            </Select>
            <div className="flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2"><Switch checked={arxivEnabled} onCheckedChange={setArxivEnabled} /><span className="text-sm font-medium text-slate-700">arXiv：{arxivEnabled ? "已启用" : "未启用"}</span></div>
            <div className="flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2"><Switch checked={journalsEnabled} onCheckedChange={setJournalsEnabled} /><span className="text-sm font-medium text-slate-700">顶级期刊：{journalsEnabled ? "已启用" : "未启用"}</span></div>
          </div>
          <div className="flex items-center gap-2"><Button variant="secondary"><FileText className="h-4 w-4" />生成调研报告</Button><Button variant="secondary"><FolderOpen className="h-4 w-4" />打开报告文件夹</Button></div>
          {summary && <SourceStatusBar sources={summary.sources} />}
        </CardContent>
      </Card>

      <PaperTable
        title="历史调研结果"
        papers={tableVisible ? papers : []}
        totalCount={tableVisible ? summary?.candidateCount ?? papers.length : 0}
        onOpen={handleOpen}
        onSelect={(paper) => { setSelectedPaper(paper); setDetailOpen(true); }}
        onPrimaryAction={serviceUnavailable ? checkService : handleStart}
        emptyTitle={copy.title}
        emptyDescription={copy.description}
        emptyActionLabel={copy.action}
      />

      <PaperDetailSheet paper={selectedPaper} open={detailOpen} onClose={() => setDetailOpen(false)} onOpenLink={handleOpen} />
      {toast && <Toast {...toast} />}
    </>
  );
}