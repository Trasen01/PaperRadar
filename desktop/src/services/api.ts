import type { Paper } from "../types/paper";
import type { ResearchProfile } from "../types/profile";
import type { PaperSummary } from "../types/summary";
import { mockPapers, mockProfiles, mockSummary } from "./mock";

export type ApiResult<T> = Promise<T>;
export type RuntimeMode = "mock" | "real";
export type ApiErrorKind = "local_service_unavailable" | "request_failed" | "internal_error";

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

export async function getHistoryPapers(): ApiResult<{ papers: Paper[]; summary: PaperSummary }> {
  if (RUNTIME_MODE === "mock") return mockPayload();
  return requestJson<{ papers: Paper[]; summary: PaperSummary }>("/api/papers/history");
}

export async function startHistoryResearch(params: { taskName: string; days: number; minScore: number; arxiv: boolean; journals: boolean }): ApiResult<{ papers: Paper[]; summary: PaperSummary }> {
  if (RUNTIME_MODE === "mock") return new Promise((resolve) => setTimeout(() => resolve(mockPayload()), 800));
  return requestJson<{ papers: Paper[]; summary: PaperSummary }>("/api/history/start", { method: "POST", body: JSON.stringify(params) });
}

export async function getProfiles(): ApiResult<ResearchProfile[]> {
  if (RUNTIME_MODE === "mock") return mockProfiles;
  const payload = await requestJson<{ profiles: ResearchProfile[] }>("/api/profiles");
  return payload.profiles;
}