import type { Paper } from "../types/paper";

export function openPaperLink(paper: Paper) {
  if (!paper.url) {
    throw new Error("该论文暂无可用链接。");
  }
  window.open(paper.url, "_blank", "noopener,noreferrer");
}
