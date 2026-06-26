import type { ResearchProfile } from "../../types/profile";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent } from "../ui/card";

type ProfileSummaryProps = {
  profile: ResearchProfile;
  onEdit?: (profile: ResearchProfile) => void;
  onCopy?: (profile: ResearchProfile) => void;
  onExport?: (profile: ResearchProfile) => void;
};

export function ProfileSummary({ profile, onEdit, onCopy, onExport }: ProfileSummaryProps) {
  return (
    <Card>
      <CardContent className="grid grid-cols-[1fr_auto] gap-6">
        <div>
          <div className="mb-3 flex items-center gap-2">
            <h2 className="text-xl font-semibold tracking-tight text-slate-950">{profile.name}</h2>
            <Badge variant="green">当前使用中</Badge>
          </div>
          <p className="max-w-3xl text-sm leading-6 text-slate-500">{profile.description || "这个研究方向还没有描述。"}</p>
          <div className="mt-5 grid max-w-xl grid-cols-3 gap-3">
            <div className="rounded-2xl bg-slate-50 p-3"><div className="text-xs text-slate-500">Profile ID</div><div className="mt-1 truncate text-sm font-semibold text-slate-900">{profile.id}</div></div>
            <div className="rounded-2xl bg-slate-50 p-3"><div className="text-xs text-slate-500">检索式</div><div className="mt-1 text-sm font-semibold text-slate-900">{profile.queryCount}</div></div>
            <div className="rounded-2xl bg-slate-50 p-3"><div className="text-xs text-slate-500">关键词组</div><div className="mt-1 text-sm font-semibold text-slate-900">{profile.keywordGroupCount}</div></div>
          </div>
        </div>
        <div className="flex w-[170px] flex-col justify-end gap-2">
          <Button variant="primary" onClick={() => onEdit?.(profile)}>编辑当前方向</Button>
          <Button variant="secondary" onClick={() => onCopy?.(profile)}>复制当前方向</Button>
          <Button variant="secondary" onClick={() => onExport?.(profile)}>导出当前方向</Button>
        </div>
      </CardContent>
    </Card>
  );
}