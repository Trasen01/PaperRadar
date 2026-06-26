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
import { getProfiles } from "../services/api";

export function ResearchProfiles() {
  const [profiles, setProfiles] = useState<ResearchProfile[]>([]);

  useEffect(() => {
    getProfiles().then(setProfiles);
  }, []);

  const currentProfile = profiles.find((profile) => profile.isCurrent) ?? profiles[0];

  return (
    <>
      <PageHeader
        title="研究方向"
        description="管理 Profile、关键词和 AI 辅助导入，决定 PaperRadar 如何理解你的研究兴趣。"
      />

      {currentProfile && (
        <div className="space-y-5">
          <ProfileSummary profile={currentProfile} />
          <ProfileTable profiles={profiles} />
          <KeywordWorkspace keywords={currentProfile.keywords} />

          <div className="grid grid-cols-2 gap-5">
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <BrainCircuit className="h-5 w-5 text-blue-600" />
                  <CardTitle>AI 辅助生成 Profile</CardTitle>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-sm leading-6 text-slate-500">
                  输入研究方向，PaperRadar 会生成可编辑的关键词与检索式草案。生成后请人工检查再保存。
                </p>
                <Input placeholder="例如：片上光计算、光神经网络、矩阵乘法加速" />
                <div className="flex justify-end gap-2">
                  <Button variant="secondary">生成 AI 提示词</Button>
                  <Button variant="primary">解析并预览</Button>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <ClipboardPaste className="h-5 w-5 text-blue-600" />
                  <CardTitle>Profile 批量导入</CardTitle>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <textarea
                  className="h-[132px] w-full resize-none rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:bg-white focus:ring-4 focus:ring-blue-500/10"
                  placeholder="粘贴由 AI 生成或手动编写的 Profile 配置，解析后可预览并保存。"
                />
                <div className="flex justify-end gap-2">
                  <Button variant="secondary">解析并预览</Button>
                  <Button variant="primary">保存并设为当前方向</Button>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
