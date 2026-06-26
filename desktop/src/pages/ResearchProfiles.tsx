import { useEffect, useState } from "react";
import { BrainCircuit, ClipboardPaste } from "lucide-react";
import type { ResearchProfile } from "../types/profile";
import { PageHeader } from "../components/layout/PageHeader";
import { ProfileSummary } from "../components/profile/ProfileSummary";
import { ProfileTable } from "../components/profile/ProfileTable";
import { KeywordWorkspace } from "../components/profile/KeywordWorkspace";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { EmptyState } from "../components/ui/empty-state";
import { Toast } from "../components/ui/toast";
import { PaperRadarApiError, getProfiles, getRuntimeMode, userMessageForError } from "../services/api";

type LoadState = "loading" | "ready" | "empty" | "backend_offline" | "error";
type ToastState = { message: string; type: "success" | "error" | "warning" | "info" } | null;

export function ResearchProfiles() {
  const [profiles, setProfiles] = useState<ResearchProfile[]>([]);
  const [state, setState] = useState<LoadState>("loading");
  const [toast, setToast] = useState<ToastState>(null);
  const [errorDetail, setErrorDetail] = useState<string | null>(null);
  const mockMode = getRuntimeMode() === "mock";

  const loadProfiles = async () => {
    setState("loading");
    setErrorDetail(null);
    try {
      const result = await getProfiles();
      setProfiles(result);
      setState(result.length ? "ready" : "empty");
    } catch (error) {
      if (error instanceof PaperRadarApiError && error.kind === "backend_offline") setState("backend_offline");
      else setState("error");
      setErrorDetail(error instanceof PaperRadarApiError ? error.detail ?? null : String(error));
      setToast({ message: userMessageForError(error), type: "error" });
    }
  };

  useEffect(() => {
    void loadProfiles();
  }, []);

  const currentProfile = profiles.find((profile) => profile.isCurrent) ?? profiles[0];
  const actionToast = (message: string) => setToast({ message, type: "info" });
  const deleteProfile = (profile: ResearchProfile) => {
    if (window.confirm(`确认删除研究方向“${profile.name}”？此操作只作用于这一行。`)) {
      actionToast(`已确认删除“${profile.name}”的操作入口，保存能力将在后续接入。`);
    }
  };

  return (
    <>
      <PageHeader title="研究方向" description="管理研究方向配置、关键词和 AI 辅助导入，决定 PaperRadar 如何理解你的研究兴趣。" />
      {mockMode && <div className="mb-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">当前为演示数据模式，列表内容来自内置示例。</div>}

      {state === "loading" && <EmptyState title="正在加载研究方向" description="PaperRadar 正在读取本地研究方向配置。" />}
      {state === "backend_offline" && <EmptyState title="无法加载研究方向配置" description="本地后端未连接，无法读取你的研究方向。请确认后端服务正在运行。" actionLabel="重试连接" onAction={loadProfiles} secondaryActionLabel="查看日志" onSecondaryAction={() => actionToast("日志入口将在后续接入。")} />}
      {state === "error" && <EmptyState title="研究方向加载失败" description="读取研究方向时出现错误，请重试或查看错误详情。" actionLabel="重试" onAction={loadProfiles} />}
      {state === "empty" && <EmptyState title="还没有研究方向配置" description="创建一个研究方向配置后，PaperRadar 才能按你的兴趣筛选论文。" actionLabel="AI 辅助生成" onAction={() => actionToast("AI 辅助生成入口将在导入功能中继续完善。")} />}

      {state === "ready" && currentProfile && (
        <div className="space-y-5">
          <ProfileSummary profile={currentProfile} onEdit={actionToast.bind(null, "正在编辑当前方向")} onCopy={(profile) => actionToast(`复制“${profile.name}”`)} onExport={(profile) => actionToast(`导出“${profile.name}”`)} />
          <ProfileTable profiles={profiles} onSetCurrent={(profile) => actionToast(`将“${profile.name}”设为当前方向`)} onEdit={(profile) => actionToast(`编辑“${profile.name}”`)} onExport={(profile) => actionToast(`导出“${profile.name}”`)} onDelete={deleteProfile} />
          <KeywordWorkspace profile={currentProfile} keywords={currentProfile.keywords} />

          <div className="grid grid-cols-2 gap-5">
            <Card><CardHeader><div className="flex items-center gap-2"><BrainCircuit className="h-5 w-5 text-blue-600" /><CardTitle>AI 辅助生成研究方向</CardTitle></div></CardHeader><CardContent className="space-y-4"><p className="text-sm leading-6 text-slate-500">输入研究方向，PaperRadar 会生成可编辑的关键词与检索式草案。生成后请人工检查再保存。</p><Input placeholder="例如：片上光计算、光神经网络、矩阵乘法加速" /><div className="flex justify-end gap-2"><Button variant="secondary">生成 AI 提示词</Button><Button variant="primary">解析并预览</Button></div></CardContent></Card>
            <Card><CardHeader><div className="flex items-center gap-2"><ClipboardPaste className="h-5 w-5 text-blue-600" /><CardTitle>研究方向批量导入</CardTitle></div></CardHeader><CardContent className="space-y-4"><textarea className="h-[132px] w-full resize-none rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:bg-white focus:ring-4 focus:ring-blue-500/10" placeholder="粘贴由 AI 生成或手动编写的研究方向配置，解析后可预览并保存。" /><div className="flex justify-end gap-2"><Button variant="secondary">解析并预览</Button><Button variant="primary">保存并设为当前方向</Button></div></CardContent></Card>
          </div>
        </div>
      )}

      {errorDetail && <div className="mt-4 rounded-2xl border border-red-100 bg-red-50 p-4 text-xs leading-5 text-red-800">{errorDetail}</div>}
      {toast && <Toast message={toast.message} type={toast.type} />}
    </>
  );
}