import { invoke } from "@tauri-apps/api/core";
import type { Paper } from "../types/paper";

export async function openPaperLink(paper: Paper) {
  if (!paper.url) {
    throw new Error("该论文暂无可用链接。");
  }
  try {
    await invoke("open_external_url", { url: paper.url });
  } catch (error) {
    const opened = window.open(paper.url, "_blank", "noopener,noreferrer");
    if (!opened) {
      throw new Error(error instanceof Error ? error.message : String(error));
    }
  }
}
