import type { Paper } from "../types/paper";
import type { ResearchProfile } from "../types/profile";
import type { PaperSummary } from "../types/summary";
import { mockPapers, mockProfiles, mockSummary } from "./mock";

export type ApiResult<T> = Promise<T>;

const API_BASE = import.meta.env.VITE_PAPERRADAR_API_BASE ?? "http://127.0.0.1:8765";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `PaperRadar backend request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

async function withFallback<T>(request: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await request();
  } catch (error) {
    console.info("PaperRadar backend unavailable, using mock data.", error);
    return fallback;
  }
}

export async function getStatus(): ApiResult<{ version: string; mode: "mock" | "python-backend" }> {
  return withFallback(() => requestJson<{ version: string; mode: "mock" | "python-backend" }>("/api/status"), {
    version: "0.3.0",
    mode: "mock"
  });
}

export async function getTodayPapers(): ApiResult<{ papers: Paper[]; summary: PaperSummary }> {
  return withFallback(() => requestJson<{ papers: Paper[]; summary: PaperSummary }>("/api/papers/today"), {
    papers: mockPapers,
    summary: mockSummary
  });
}

export async function checkTodayPapers(params: { daysBack: number; minScore: number; arxiv: boolean; journals: boolean }): ApiResult<{ papers: Paper[]; summary: PaperSummary }> {
  return withFallback(
    () => requestJson<{ papers: Paper[]; summary: PaperSummary }>("/api/papers/check", { method: "POST", body: JSON.stringify(params) }),
    { papers: mockPapers, summary: mockSummary }
  );
}

export async function getHistoryPapers(): ApiResult<{ papers: Paper[]; summary: PaperSummary }> {
  return withFallback(() => requestJson<{ papers: Paper[]; summary: PaperSummary }>("/api/papers/history"), {
    papers: mockPapers.map((paper, index) => ({
      ...paper,
      id: `h-${paper.id}`,
      publishedDate: `2026-0${Math.max(1, 6 - Math.floor(index / 2))}-${String(22 - index).padStart(2, "0")}`
    })),
    summary: mockSummary
  });
}

export async function startHistoryResearch(params: { taskName: string; days: number; minScore: number; arxiv: boolean; journals: boolean }): ApiResult<{ papers: Paper[]; summary: PaperSummary }> {
  return withFallback(
    () => requestJson<{ papers: Paper[]; summary: PaperSummary }>("/api/history/start", { method: "POST", body: JSON.stringify(params) }),
    { papers: mockPapers, summary: mockSummary }
  );
}

export async function getProfiles(): ApiResult<ResearchProfile[]> {
  const payload = await withFallback(() => requestJson<{ profiles: ResearchProfile[] }>("/api/profiles"), {
    profiles: mockProfiles
  });
  return payload.profiles;
}


