import type { Paper } from "../types/paper";
import type { ResearchProfile } from "../types/profile";
import type { PaperSummary } from "../types/summary";
import { mockPapers, mockProfiles, mockSummary } from "./mock";

export type ApiResult<T> = Promise<T>;
export type RuntimeMode = "mock" | "backend";
export type ApiErrorKind = "backend_offline" | "api_failed" | "internal_error";

export class PaperRadarApiError extends Error {
  kind: ApiErrorKind;
  detail?: string;
  endpoint?: string;

  constructor(kind: ApiErrorKind, message: string, options: { detail?: string; endpoint?: string } = {}) {
    super(message);
    this.name = "PaperRadarApiError";
    this.kind = kind;
    this.detail = options.detail;
    this.endpoint = options.endpoint;
  }
}

const API_BASE = import.meta.env.VITE_PAPERRADAR_API_BASE ?? "http://127.0.0.1:8765";
const RUNTIME_MODE: RuntimeMode = import.meta.env.VITE_PAPERRADAR_MODE === "mock" ? "mock" : "backend";

export function getRuntimeMode(): RuntimeMode {
  return RUNTIME_MODE;
}

function isNetworkError(error: unknown) {
  return error instanceof TypeError || String(error).includes("Failed to fetch") || String(error).includes("NetworkError");
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
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
      throw new PaperRadarApiError("api_failed", "请求本地服务失败", { detail, endpoint: path });
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof PaperRadarApiError) throw error;
    if (isNetworkError(error)) {
      throw new PaperRadarApiError("backend_offline", "本地后端未连接", {
        detail: `${error instanceof Error ? error.message : String(error)} · ${API_BASE}${path}`,
        endpoint: path
      });
    }
    throw new PaperRadarApiError("internal_error", "本地服务出现内部错误", {
      detail: error instanceof Error ? error.message : String(error),
      endpoint: path
    });
  }
}

function mockPayload(): { papers: Paper[]; summary: PaperSummary } {
  return { papers: mockPapers, summary: mockSummary };
}

export function userMessageForError(error: unknown) {
  if (error instanceof PaperRadarApiError) {
    if (error.kind === "backend_offline") return "无法连接本地后端。请确认 PaperRadar 后端服务正在运行，然后重试。";
    if (error.kind === "api_failed") return error.detail || "本地服务请求失败。";
    return error.detail || "本地服务出现内部错误。";
  }
  return error instanceof Error ? error.message : "操作失败。";
}

export async function getStatus(): ApiResult<{ version: string; mode: "mock" | "python-backend" }> {
  if (RUNTIME_MODE === "mock") return { version: "0.3.0", mode: "mock" };
  return requestJson<{ version: string; mode: "mock" | "python-backend" }>("/api/status");
}

export async function getTodayPapers(): ApiResult<{ papers: Paper[]; summary: PaperSummary }> {
  if (RUNTIME_MODE === "mock") return mockPayload();
  return requestJson<{ papers: Paper[]; summary: PaperSummary }>("/api/papers/today");
}

export async function checkTodayPapers(params: { daysBack: number; minScore: number; arxiv: boolean; journals: boolean }): ApiResult<{ papers: Paper[]; summary: PaperSummary }> {
  if (RUNTIME_MODE === "mock") return mockPayload();
  return requestJson<{ papers: Paper[]; summary: PaperSummary }>("/api/papers/check", { method: "POST", body: JSON.stringify(params) });
}

export async function getHistoryPapers(): ApiResult<{ papers: Paper[]; summary: PaperSummary }> {
  if (RUNTIME_MODE === "mock") return mockPayload();
  return requestJson<{ papers: Paper[]; summary: PaperSummary }>("/api/papers/history");
}

export async function startHistoryResearch(params: { taskName: string; days: number; minScore: number; arxiv: boolean; journals: boolean }): ApiResult<{ papers: Paper[]; summary: PaperSummary }> {
  if (RUNTIME_MODE === "mock") return mockPayload();
  return requestJson<{ papers: Paper[]; summary: PaperSummary }>("/api/history/start", { method: "POST", body: JSON.stringify(params) });
}

export async function getProfiles(): ApiResult<ResearchProfile[]> {
  if (RUNTIME_MODE === "mock") return mockProfiles;
  const payload = await requestJson<{ profiles: ResearchProfile[] }>("/api/profiles");
  return payload.profiles;
}