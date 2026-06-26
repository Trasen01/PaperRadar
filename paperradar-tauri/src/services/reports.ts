export async function generateTodayReport() {
  return { ok: true, message: "报告生成入口已保留，下一阶段接入 Python 报告服务。" };
}

export async function openReportFolder() {
  return { ok: true, message: "打开报告文件夹入口已保留，下一阶段通过 Tauri shell 接入。" };
}
