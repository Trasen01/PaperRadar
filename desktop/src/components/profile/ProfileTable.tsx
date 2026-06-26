import type { ResearchProfile } from "../../types/profile";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

type ProfileTableProps = {
  profiles: ResearchProfile[];
  onSetCurrent?: (profile: ResearchProfile) => void;
  onEdit?: (profile: ResearchProfile) => void;
  onExport?: (profile: ResearchProfile) => void;
  onDelete?: (profile: ResearchProfile) => void;
};

export function ProfileTable({ profiles, onSetCurrent, onEdit, onExport, onDelete }: ProfileTableProps) {
  return (
    <Card>
      <CardHeader><CardTitle>研究方向配置列表</CardTitle></CardHeader>
      <CardContent className="p-0">
        <div className="overflow-auto">
          <div className="min-w-[1080px]">
            <div className="grid grid-cols-[160px_180px_minmax(280px,1fr)_90px_90px_120px_260px] border-b border-slate-200 bg-slate-50 px-5 py-3 text-center text-xs font-semibold text-slate-500">
              <div>显示名称</div><div>Profile ID</div><div>描述</div><div>检索式</div><div>关键词组</div><div>状态</div><div>操作</div>
            </div>
            {profiles.map((profile) => (
              <div key={profile.id} className="grid min-h-[52px] grid-cols-[160px_180px_minmax(280px,1fr)_90px_90px_120px_260px] items-center border-b border-slate-100 px-5 py-2 text-sm hover:bg-blue-50/40">
                <div className="font-medium text-slate-900">{profile.name}</div>
                <div className="truncate text-slate-500">{profile.id}</div>
                <div className="truncate px-4 text-slate-600" title={profile.description}>{profile.description}</div>
                <div className="text-center">{profile.queryCount}</div>
                <div className="text-center">{profile.keywordGroupCount}</div>
                <div className="text-center">{profile.isCurrent ? <Badge variant="green">当前使用中</Badge> : <Badge>备用</Badge>}</div>
                <div className="flex justify-center gap-2">
                  {!profile.isCurrent && <Button size="sm" variant="secondary" onClick={() => onSetCurrent?.(profile)}>设为当前</Button>}
                  <Button size="sm" variant="secondary" onClick={() => onEdit?.(profile)}>编辑</Button>
                  <Button size="sm" variant="ghost" onClick={() => onExport?.(profile)}>导出</Button>
                  <Button size="sm" variant="danger" onClick={() => onDelete?.(profile)}>删除</Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}