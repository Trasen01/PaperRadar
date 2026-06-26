import type { Keyword, ResearchProfile } from "../../types/profile";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Input } from "../ui/input";
import { Select } from "../ui/select";

type KeywordWorkspaceProps = {
  profile: ResearchProfile;
  keywords: Keyword[];
};

function weightVariant(weight: Keyword["weight"]) {
  if (weight === "high") return "green" as const;
  if (weight === "medium") return "blue" as const;
  return "slate" as const;
}

export function KeywordWorkspace({ profile, keywords }: KeywordWorkspaceProps) {
  const selected = keywords[0];

  return (
    <div className="grid grid-cols-[1fr_380px] gap-5">
      <Card>
        <CardHeader><div><CardTitle>关键词库</CardTitle><p className="mt-1 text-xs text-slate-500">正在编辑：{profile.name}；共 {keywords.length} 个关键词。修改后需要保存才会影响检索。</p></div></CardHeader>
        <CardContent className="p-0">
          <div className="max-h-[390px] overflow-auto">
            <div className="grid grid-cols-[120px_110px_minmax(260px,1fr)_100px] border-b border-slate-200 bg-slate-50 px-5 py-3 text-center text-xs font-semibold text-slate-500"><div>分组</div><div>权重</div><div>关键词</div><div>操作</div></div>
            {keywords.length === 0 ? <div className="p-6 text-sm text-slate-500">这个研究方向还没有关键词。</div> : keywords.map((keyword) => (
              <div key={`${keyword.group}-${keyword.text}`} className="grid min-h-[48px] grid-cols-[120px_110px_minmax(260px,1fr)_100px] items-center border-b border-slate-100 px-5 py-2 text-sm hover:bg-blue-50/40">
                <div className="text-center"><Badge>{keyword.group}</Badge></div>
                <div className="text-center"><Badge variant={weightVariant(keyword.weight)}>{keyword.weight}</Badge></div>
                <div className="truncate font-medium text-slate-900">{keyword.text}</div>
                <div className="text-center"><Button size="sm" variant="secondary">编辑</Button></div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="space-y-5">
        <Card>
          <CardHeader><CardTitle>编辑关键词</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {selected ? <>
              <label className="block text-sm font-medium text-slate-700">分组<Input className="mt-2 w-full" defaultValue={selected.group} /></label>
              <label className="block text-sm font-medium text-slate-700">权重<Select className="mt-2 w-full" defaultValue={selected.weight}><option value="high">high</option><option value="medium">medium</option><option value="low">low</option></Select></label>
              <label className="block text-sm font-medium text-slate-700">关键词<Input className="mt-2 w-full" defaultValue={selected.text} /></label>
              <div className="flex justify-end gap-2"><Button variant="danger" onClick={() => window.confirm("确认删除这个关键词？")}>删除关键词</Button><Button variant="primary">保存修改</Button></div>
            </> : <p className="text-sm text-slate-500">从左侧选择一个关键词进行编辑。</p>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>新增关键词</CardTitle></CardHeader>
          <CardContent className="space-y-3"><Input placeholder="英文关键词，例如 photonic computing" /><div className="flex justify-end gap-2"><Button variant="secondary">添加关键词</Button><Button variant="primary">保存全部关键词</Button></div></CardContent>
        </Card>
      </div>
    </div>
  );
}