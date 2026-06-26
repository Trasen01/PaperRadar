import type { ResearchProfile } from "../../types/profile";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

type ProfileTableProps = {
  profiles: ResearchProfile[];
};

export function ProfileTable({ profiles }: ProfileTableProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Profile 列表</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-auto">
          <div className="min-w-[980px]">
            <div className="grid grid-cols-[160px_180px_minmax(260px,1fr)_90px_90px_110px_180px] border-b border-slate-200 bg-slate-50 px-5 py-3 text-xs font-semibold text-slate-500">
              <div>显示名称</div>
              <div>Profile ID</div>
              <div>描述</div>
              <div>检索式</div>
              <div>关键词组</div>
              <div>当前状态</div>
              <div>操作</div>
            </div>
            {profiles.map((profile) => (
              <div
                key={profile.id}
                className="grid min-h-[48px] grid-cols-[160px_180px_minmax(260px,1fr)_90px_90px_110px_180px] items-center border-b border-slate-100 px-5 py-2 text-sm hover:bg-blue-50/40"
              >
                <div className="font-medium text-slate-900">{profile.name}</div>
                <div className="truncate text-slate-500">{profile.id}</div>
                <div className="truncate pr-4 text-slate-600" title={profile.description}>
                  {profile.description}
                </div>
                <div>{profile.queryCount}</div>
                <div>{profile.keywordGroupCount}</div>
                <div>{profile.isCurrent ? <Badge variant="green">当前</Badge> : <Badge>备用</Badge>}</div>
                <div className="flex gap-2">
                  <Button size="sm" variant="secondary">
                    编辑
                  </Button>
                  <Button size="sm" variant="ghost">
                    导出
                  </Button>
                  <Button size="sm" variant="danger">
                    删除
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
