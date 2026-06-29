import { invoke } from "@tauri-apps/api/core";
import type { Paper } from "../types/paper";
import type { ResearchProfile } from "../types/profile";
import type { PaperSummary } from "../types/summary";
import { mockPapers, mockProfiles, mockSummary } from "./mock";

export type ApiResult<T> = Promise<T>;
export type RuntimeMode = "mock" | "real";
export type ApiErrorKind = "local_service_unavailable" | "request_failed" | "internal_error";
export type SearchPayload = { papers: Paper[]; summary: PaperSummary | null };
export type SearchTask = {
  taskId: string;
  kind: "today" | "history";
  state: "running" | "success" | "failed" | "cancelled";
  payload: SearchPayload;
  error: string | null;
  createdAt: string;
  updatedAt: string;
};

export class PaperRadarApiError extends Error {
  kind: ApiErrorKind;
  title: string;
  detail?: string;
  endpoint?: string;

  constructor(kind: ApiErrorKind, title: string, message: string, options: { detail?: string; endpoint?: string } = {}) {
    super(message);
    this.name = "PaperRadarApiError";
    this.kind = kind;
    this.title = title;
    this.detail = options.detail;
    this.endpoint = options.endpoint;
  }
}

const SERVICE_BASE = import.meta.env.VITE_PAPERRADAR_API_BASE ?? "http://127.0.0.1:8765";
const RUNTIME_MODE: RuntimeMode = import.meta.env.VITE_PAPERRADAR_MODE === "mock" ? "mock" : "real";

export function getRuntimeMode(): RuntimeMode {
  return RUNTIME_MODE;
}

function isConnectionError(error: unknown) {
  const text = String(error);
  return error instanceof TypeError || text.includes("Failed to fetch") || text.includes("NetworkError") || text.includes("ERR_CONNECTION");
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    const response = await fetch(`${SERVICE_BASE}${path}`, {
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      ...init
    });

    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const payload = await response.json();
        if (payload?.detail) detail = String(payload.detail);
      } catch {
        const text = await response.text();
        if (text) detail = text;
      }
      throw new PaperRadarApiError(
        "request_failed",
        "请求未完成",
        "文献检索服务返回异常，请稍后重试。",
        { detail: `${detail} · ${path}`, endpoint: path }
      );
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof PaperRadarApiError) throw error;

    if (isConnectionError(error)) {
      throw new PaperRadarApiError(
        "local_service_unavailable",
        "文献检索服务暂不可用",
        "PaperRadar 无法启动本地检索服务。请点击重试，或查看日志。",
        { detail: `${error instanceof Error ? error.message : String(error)} · ${SERVICE_BASE}${path}`, endpoint: path }
      );
    }

    throw new PaperRadarApiError(
      "internal_error",
      "内部处理异常",
      "PaperRadar 处理请求时出现问题，请稍后重试。",
      { detail: error instanceof Error ? error.message : String(error), endpoint: path }
    );
  }
}

async function invokeDesktopCommand(command: "ensure_local_service" | "restart_local_service") {
  if (RUNTIME_MODE === "mock") return;
  try {
    await invoke(command);
  } catch (error) {
    // In development without the Tauri shell this can fail; the HTTP check below still gives the user-facing result.
    console.info("PaperRadar local service command did not complete", error);
  }
}
function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export async function waitForLocalService(options: { attempts?: number; intervalMs?: number; restart?: boolean } = {}) {
  const attempts = options.attempts ?? 36;
  const intervalMs = options.intervalMs ?? 500;
  let lastError: unknown = null;

  if (RUNTIME_MODE === "mock") return true;

  await invokeDesktopCommand(options.restart ? "restart_local_service" : "ensure_local_service");

  for (let index = 0; index < attempts; index += 1) {
    try {
      await getStatus();
      return true;
    } catch (error) {
      lastError = error;
      if (error instanceof PaperRadarApiError && error.kind !== "local_service_unavailable") {
        throw error;
      }
      if (index === 6 && !options.restart) {
        await invokeDesktopCommand("restart_local_service");
      }
      if (index < attempts - 1) await sleep(intervalMs);
    }
  }

  if (lastError instanceof PaperRadarApiError) throw lastError;
  throw new PaperRadarApiError(
    "local_service_unavailable",
    "文献检索服务暂不可用",
    "PaperRadar 无法启动本地检索服务。请点击重试，或查看日志。",
    { detail: lastError instanceof Error ? lastError.message : String(lastError) }
  );
}
function mockPayload(): { papers: Paper[]; summary: PaperSummary } {
  return { papers: mockPapers, summary: mockSummary };
}

export function userFacingError(error: unknown) {
  if (error instanceof PaperRadarApiError) {
    return { title: error.title, message: error.message, detail: error.detail ?? null, kind: error.kind };
  }
  return {
    title: "操作未完成",
    message: "PaperRadar 暂时无法完成当前操作，请稍后重试。",
    detail: error instanceof Error ? error.message : String(error),
    kind: "internal_error" as ApiErrorKind
  };
}

export function userMessageForError(error: unknown) {
  return userFacingError(error).message;
}

export async function getStatus(): ApiResult<{ version: string; mode: "mock" | "local-service" }> {
  if (RUNTIME_MODE === "mock") return { version: "0.3.0", mode: "mock" };
  return requestJson<{ version: string; mode: "mock" | "local-service" }>("/api/status");
}

export async function getTodayPapers(): ApiResult<{ papers: Paper[]; summary: PaperSummary }> {
  if (RUNTIME_MODE === "mock") return mockPayload();
  return requestJson<{ papers: Paper[]; summary: PaperSummary }>("/api/papers/today");
}

export async function checkTodayPapers(params: { daysBack: number; minScore: number; arxiv: boolean; journals: boolean }): ApiResult<{ papers: Paper[]; summary: PaperSummary }> {
  if (RUNTIME_MODE === "mock") return new Promise((resolve) => setTimeout(() => resolve(mockPayload()), 650));
  return requestJson<{ papers: Paper[]; summary: PaperSummary }>("/api/papers/check", { method: "POST", body: JSON.stringify(params) });
}

export async function startTodayCheckTask(params: { daysBack: number; minScore: number; arxiv: boolean; journals: boolean }): ApiResult<SearchTask> {
  if (RUNTIME_MODE === "mock") {
    return { taskId: "mock-today", kind: "today", state: "success", payload: mockPayload(), error: null, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() };
  }
  return requestJson<SearchTask>("/api/papers/check/task", { method: "POST", body: JSON.stringify(params) });
}

export async function getHistoryPapers(): ApiResult<{ papers: Paper[]; summary: PaperSummary }> {
  if (RUNTIME_MODE === "mock") return mockPayload();
  return requestJson<{ papers: Paper[]; summary: PaperSummary }>("/api/papers/history");
}

export async function startHistoryResearch(params: { taskName: string; days: number; minScore: number; arxiv: boolean; journals: boolean }): ApiResult<{ papers: Paper[]; summary: PaperSummary }> {
  if (RUNTIME_MODE === "mock") return new Promise((resolve) => setTimeout(() => resolve(mockPayload()), 800));
  return requestJson<{ papers: Paper[]; summary: PaperSummary }>("/api/history/start", { method: "POST", body: JSON.stringify(params) });
}

export async function startHistoryResearchTask(params: { taskName: string; days: number; minScore: number; arxiv: boolean; journals: boolean }): ApiResult<SearchTask> {
  if (RUNTIME_MODE === "mock") {
    return { taskId: "mock-history", kind: "history", state: "success", payload: mockPayload(), error: null, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() };
  }
  return requestJson<SearchTask>("/api/history/start/task", { method: "POST", body: JSON.stringify(params) });
}

export async function getSearchTask(taskId: string): ApiResult<SearchTask> {
  if (RUNTIME_MODE === "mock") {
    return { taskId, kind: taskId.includes("history") ? "history" : "today", state: "success", payload: mockPayload(), error: null, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() };
  }
  return requestJson<SearchTask>(`/api/tasks/${taskId}`);
}

export async function getActiveSearchTask(kind: "today" | "history"): ApiResult<SearchTask | null> {
  if (RUNTIME_MODE === "mock") return null;
  try {
    return await requestJson<SearchTask>(`/api/tasks/active/${kind}`);
  } catch (error) {
    if (error instanceof PaperRadarApiError && error.kind === "request_failed") return null;
    throw error;
  }
}

export async function stopTodayCheck(): ApiResult<{ accepted: boolean }> {
  if (RUNTIME_MODE === "mock") return { accepted: true };
  return requestJson<{ accepted: boolean }>("/api/papers/stop", { method: "POST" });
}

export async function stopHistoryResearch(): ApiResult<{ accepted: boolean }> {
  if (RUNTIME_MODE === "mock") return { accepted: true };
  return requestJson<{ accepted: boolean }>("/api/history/stop", { method: "POST" });
}

export async function getProfiles(): ApiResult<ResearchProfile[]> {
  if (RUNTIME_MODE === "mock") return mockProfiles;
  const payload = await requestJson<{ profiles: ResearchProfile[] }>("/api/profiles");
  return payload.profiles;
}
