import type { Paper } from "../types/paper";
import type { ResearchProfile } from "../types/profile";
import type { PaperSummary } from "../types/summary";

export const mockPapers: Paper[] = [
  {
    id: "p-001",
    title: "Programmable photonic tensor cores for high-throughput optical neural networks",
    authors: ["Y. Chen", "M. Feldmann", "A. Tait", "S. Fan"],
    source: "arXiv",
    publishedDate: "2026-06-22",
    score: 94,
    matchedKeywords: ["photonic computing", "tensor core", "optical neural network"],
    abstract: "A programmable photonic tensor core for accelerating matrix multiplication in optical neural networks.",
    url: "https://arxiv.org/abs/2606.00001",
    doi: null,
    status: "worth-reading"
  },
  {
    id: "p-002",
    title: "Neuromorphic photonics with phase-change materials for energy-efficient inference",
    authors: ["R. Kumar", "L. Wang", "E. Miller"],
    source: "Nature Comm.",
    publishedDate: "2026-06-20",
    score: 88,
    matchedKeywords: ["neuromorphic photonics", "phase-change", "inference"],
    abstract: "A hybrid photonic memory cell based on phase-change materials for low-power inference.",
    url: "https://www.nature.com/articles/mock-neuromorphic-photonics",
    doi: "10.1038/mock.2026.002",
    status: "worth-reading"
  },
  {
    id: "p-003",
    title: "Wafer-scale packaging for optical AI accelerators",
    authors: ["S. Rhodes", "Y. Tan", "I. Petrov"],
    source: "Optica",
    publishedDate: "2026-06-11",
    score: 69,
    matchedKeywords: ["wafer-scale", "optical AI", "packaging"],
    abstract: "Packaging constraints for optical AI accelerator systems, including thermal management and coupling loss.",
    url: "https://example.com/paperradar/mock-paper-007",
    doi: null,
    status: "candidate"
  }
];

export const mockSummary: PaperSummary = {
  totalFetched: 3,
  candidateCount: 3,
  displayedCount: 3,
  hiddenCount: 0,
  failedCount: 0,
  sources: {
    arxiv: {
      label: "arXiv",
      enabled: true,
      status: "success",
      fetched: 1,
      stored: 1,
      displayed: 1,
      failed: 0,
      error: null
    },
    journals: {
      label: "顶级期刊",
      enabled: true,
      status: "success",
      fetched: 2,
      stored: 2,
      displayed: 2,
      failed: 0,
      error: null
    }
  }
};

export const mockProfiles: ResearchProfile[] = [
  {
    id: "optical_computing",
    name: "光计算",
    description: "Optical and photonic computing, including optical neural networks, photonic processors, matrix multiplication, analog solvers and neuromorphic photonics.",
    queryCount: 15,
    keywordGroupCount: 8,
    isCurrent: true,
    keywords: [
      { group: "core", weight: "high", text: "photonic computing" },
      { group: "core", weight: "high", text: "optical neural network" },
      { group: "hardware", weight: "medium", text: "silicon photonics accelerator" },
      { group: "model", weight: "medium", text: "neuromorphic photonics" },
      { group: "algorithm", weight: "low", text: "analog optical solver" }
    ]
  },
  {
    id: "ai_agents",
    name: "AI Agent",
    description: "Autonomous agent systems, planning, tool use, memory, browser control and local workflow automation.",
    queryCount: 9,
    keywordGroupCount: 5,
    isCurrent: false,
    keywords: [
      { group: "agent", weight: "high", text: "tool-using agents" },
      { group: "memory", weight: "medium", text: "long-term memory" }
    ]
  }
];

