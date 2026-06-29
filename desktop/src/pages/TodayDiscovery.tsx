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
import { PaperRadarApiError, getActiveSearchTask, getRuntimeMode, getSearchTask, startTodayCheckTask, stopTodayCheck, waitForLocalService, userFacingError } from "../services/api";
import { openPaperLink } from "../services/papers";

type RunState = "idle" | "checking" | "success" | "empty" | "partial_success" | "service_unavailable" | "source_failed" | "request_failed" | "internal_error" | "cancelled";
type ToastState = { title?: string; description?: string; message?: string; type: "success" | "error" | "warning" | "info"; actionLabel?: string; onAction?: () => void; secondaryActionLabel?: string; onSecondaryAction?: () => void } | null;

const SCORE_OPTIONS = [90, 80, 70, 60, 50, 40, 30, 20];
const DAY_OPTIONS = [3, 7, 14, 30, 90, 180, 365];

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
    idle: "就绪",
    checking: "检索中",
    success: "已完成",
    empty: "无匹配结果",
    partial_success: "部分完成",
    service_unavailable: "服务未启动",
    source_failed: "数据源异常",
    request_failed: "请求未完成",
    internal_error: "内部异常",
    cancelled: "已停止"
  };
  return labels[state];
}

function emptyCopy(state: RunState) {
  if (state === "service_unavailable") {
    return {
      title: "文献检索服务未启动",
      description: "PaperRadar 暂时无法进行检索。请点击重新连接，或查看日志。",
      action: "重新连接",
      secondary: "查看日志"
    };
  }
  if (state === "request_failed" || state === "internal_error") {
    return {
      title: "检索未完成",
      description: "检索过程中出现错误，部分结果可能未保存。请重新检查，或查看日志了解原因。",
      action: "重新检查",
      secondary: "查看日志"
    };
  }
  if (state === "empty") {
    return {
      title: "没有找到匹配论文",
      description: "可以放宽最低分、增加最近天数，或调整研究方向关键词。",
      action: "重新检查",
      secondary: "编辑研究方向"
    };
  }
  if (state === "checking") {
    return { title: "正在检索论文", description: "PaperRadar 正在获取、去重并评分，请稍候。", action: "检索中" };
  }
  return {
    title: "还没有论文结果",
    description: "点击“立即检查”，PaperRadar 会检索与你研究方向相关的最新论文。",
    action: "立即检查"
  };
}

export function TodayDiscovery() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [summary, setSummary] = useState<PaperSummary | null>(null);
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [toast, setToast] = useState<ToastState>(null);
  const [arxivEnabled, setArxivEnabled] = useState(true);
  const [journalsEnabled, setJournalsEnabled] = useState(true);
  const [daysBack, setDaysBack] = useState(7);
  const [minScore, setMinScore] = useState(70);
  const [state, setState] = useState<RunState>("idle");
  const [lastErrorDetail, setLastErrorDetail] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);

  const mockMode = getRuntimeMode() === "mock";
  const running = state === "checking";
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
      setToast({ title: "文献检索服务已就绪", description: "现在可以开始检索论文。", type: "success" });
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

  const applyTaskSnapshot = (task: Awaited<ReturnType<typeof getSearchTask>>) => {
    if (task.state === "running" || task.state === "success") {
      setPapers(task.payload.papers);
      setSummary(task.payload.summary);
    }
  };

  useEffect(() => {
    if (mockMode) return;
    getActiveSearchTask("today").then((task) => {
      if (!task) return;
      setTaskId(task.taskId);
      applyTaskSnapshot(task);
      if (task.state === "running") setState("checking");
      if (task.state === "success") setState(task.payload.papers.length === 0 ? "empty" : hasSourceProblem(task.payload.summary) ? "partial_success" : "success");
      if (task.state === "cancelled") setState("cancelled");
      if (task.state === "failed") setState("request_failed");
    }).catch(() => undefined);
  }, [mockMode]);

  useEffect(() => {
    if (!taskId || state !== "checking") return;
    let cancelled = false;
    const poll = async () => {
      try {
        const task = await getSearchTask(taskId);
        if (cancelled) return;
        applyTaskSnapshot(task);
        if (task.state === "running") return;
        if (task.state === "success") {
          const nextState: RunState = task.payload.papers.length === 0 ? "empty" : hasSourceProblem(task.payload.summary) ? "partial_success" : "success";
          setState(nextState);
          setToast({
            title: nextState === "empty" ? "检索完成" : nextState === "partial_success" ? "检索部分完成" : "检索完成",
            description: nextState === "empty" ? "没有找到匹配论文，可以调整筛选条件后重试。" : `当前显示 ${task.payload.papers.length} 篇，候选 ${task.payload.summary?.candidateCount ?? task.payload.papers.length} 篇。`,
            type: nextState === "partial_success" ? "warning" : "success"
          });
        } else if (task.state === "cancelled") {
          setState("cancelled");
        } else {
          setState("request_failed");
          setLastErrorDetail(task.error);
        }
      } catch (error) {
        if (cancelled) return;
        const info = userFacingError(error);
        setState(stateFromError(error));
        setLastErrorDetail(info.detail);
      }
    };
    void poll();
    const timer = window.setInterval(poll, 900);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [taskId, state]);

  const handleCheck = async () => {
    if (serviceUnavailable) {
      await checkService();
      return;
    }

    setState("checking");
    setLastErrorDetail(null);
    setToast({ title: mockMode ? "演示检索中" : "正在检索论文", description: "PaperRadar 正在获取、去重并评分。", type: "info" });
    setPapers([]);
    setSummary(null);

    try {
      const task = await startTodayCheckTask({ daysBack, minScore, arxiv: arxivEnabled, journals: journalsEnabled });
      setTaskId(task.taskId);
      setPapers(task.payload.papers);
      setSummary(task.payload.summary);
      setState(task.state === "running" ? "checking" : task.payload.papers.length === 0 ? "empty" : "success");
    } catch (error) {
      const nextState = stateFromError(error);
      const info = userFacingError(error);
      setState(nextState);
      setLastErrorDetail(info.detail);
      setToast({ title: info.title, description: info.message, type: "error", actionLabel: nextState === "service_unavailable" ? "重试" : "重新检查", onAction: nextState === "service_unavailable" ? checkService : handleCheck, secondaryActionLabel: "查看日志", onSecondaryAction: showLogs });
    }
  };

  const handleOpen = async (paper: Paper) => {
    try {
      await openPaperLink(paper);
      setToast({ title: "正在打开论文链接", description: "将使用系统默认浏览器打开。", type: "info" });
    } catch (error) {
      setToast({ title: "无法打开论文链接", description: error instanceof Error ? error.message : "该论文暂无可用链接。", type: "error" });
    }
  };

  const copy = emptyCopy(state);
  const tableVisible = state === "checking" || state === "success" || state === "partial_success" || state === "cancelled";

  return (
    <>
      <PageHeader
        title="今日发现"
        description="自动检索与你研究方向相关的最新论文，并筛选出值得关注的工作。"
        actions={
          <>
            <Button variant="primary" onClick={serviceUnavailable ? checkService : handleCheck} disabled={running}>
              <Play className="h-4 w-4" />
              {serviceUnavailable ? "重新连接" : running ? "检索中" : "立即检查"}
            </Button>
            <Button variant="secondary" disabled={!running} onClick={() => { void stopTodayCheck(); setState("cancelled"); }}>
              <Square className="h-4 w-4" />
              停止
            </Button>
          </>
        }
      />

      {mockMode && <div className="mb-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">当前为演示数据模式，不会启动真实检索。</div>}

      <div className="mb-5 grid grid-cols-5 gap-4">
        <KpiCard label="上次检查" value={state === "idle" || serviceUnavailable ? "从未" : "刚刚"} hint={serviceUnavailable ? "无法检索" : "点击立即检查开始"} />
        <KpiCard label="本次抓取" value={summary ? summary.totalFetched : "--"} hint="原始抓取数量" tone="blue" />
        <KpiCard label="候选论文" value={summary ? summary.candidateCount : "--"} hint="评分后候选" tone="green" />
        <KpiCard label="值得关注" value={summary ? papers.filter((paper) => paper.status === "worth-reading").length : "--"} hint="高相关论文" tone="green" />
        <KpiCard label="运行状态" value={statusLabel(state)} hint={serviceUnavailable ? "无法检索" : summary ? `${summary.failedCount} 个异常` : "等待用户操作"} tone={state === "service_unavailable" || state === "request_failed" || state === "internal_error" ? "red" : state === "partial_success" ? "amber" : "blue"} />
      </div>

      <Card className="mb-5">
        <CardContent className="flex flex-wrap items-center justify-between gap-4 py-4">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium text-slate-700">最近天数</span>
            <Select value={String(daysBack)} onChange={(event) => setDaysBack(Number(event.target.value))}>
              {DAY_OPTIONS.map((day) => <option key={day} value={day}>最近 {day} 天</option>)}
            </Select>
            <span className="text-sm font-medium text-slate-700">最低分</span>
            <Select value={String(minScore)} onChange={(event) => setMinScore(Number(event.target.value))}>
              {SCORE_OPTIONS.map((score) => <option key={score} value={score}>{score}</option>)}
            </Select>
            <div className="flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2"><Switch checked={arxivEnabled} onCheckedChange={setArxivEnabled} /><span className="text-sm font-medium text-slate-700">arXiv：{arxivEnabled ? "已启用" : "未启用"}</span></div>
            <div className="flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2"><Switch checked={journalsEnabled} onCheckedChange={setJournalsEnabled} /><span className="text-sm font-medium text-slate-700">顶级期刊：{journalsEnabled ? "已启用" : "未启用"}</span></div>
          </div>
          <div className="flex items-center gap-2"><Button variant="secondary"><FileText className="h-4 w-4" />生成今日报告</Button><Button variant="secondary"><FolderOpen className="h-4 w-4" />打开报告文件夹</Button></div>
          {summary && <SourceStatusBar sources={summary.sources} />}
        </CardContent>
      </Card>

      <PaperTable
        title="今日论文列表"
        papers={tableVisible ? papers : []}
        totalCount={tableVisible ? summary?.candidateCount ?? papers.length : 0}
        onOpen={handleOpen}
        onSelect={(paper) => { setSelectedPaper(paper); setDetailOpen(true); }}
        onPrimaryAction={serviceUnavailable ? checkService : handleCheck}
        emptyTitle={copy.title}
        emptyDescription={copy.description}
        emptyActionLabel={copy.action}
      />

      <PaperDetailSheet paper={selectedPaper} open={detailOpen} onClose={() => setDetailOpen(false)} onOpenLink={handleOpen} />
      {toast && <Toast {...toast} />}
    </>
  );
}
