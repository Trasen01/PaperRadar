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
    abstract:
      "This work proposes a programmable photonic tensor core for accelerating matrix multiplication in optical neural networks, with a calibration strategy that improves stability under device drift.",
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
    abstract:
      "The paper demonstrates a hybrid photonic memory cell based on phase-change materials and evaluates its use for low-power inference in recurrent architectures.",
    url: "https://www.nature.com/articles/mock-neuromorphic-photonics",
    doi: "10.1038/mock.2026.002",
    status: "worth-reading"
  },
  {
    id: "p-003",
    title: "Integrated coherent optical matrix processors for scientific machine learning",
    authors: ["D. Park", "N. Li", "S. Massar"],
    source: "arXiv",
    publishedDate: "2026-06-19",
    score: 82,
    matchedKeywords: ["optical matrix processor", "scientific ML", "coherent"],
    abstract:
      "A coherent integrated optical matrix processor is benchmarked on scientific machine learning workloads, emphasizing precision limits and calibration costs.",
    url: "https://arxiv.org/abs/2606.00003",
    doi: null,
    status: "candidate"
  },
  {
    id: "p-004",
    title: "Large-scale silicon photonic accelerators with adaptive error correction",
    authors: ["H. Zhao", "P. Mehta", "J. Sun", "K. Vahala"],
    source: "Nature",
    publishedDate: "2026-06-17",
    score: 91,
    matchedKeywords: ["silicon photonics", "accelerator", "error correction"],
    abstract:
      "The authors report a silicon photonic accelerator with adaptive error correction, addressing long-standing stability concerns in large-scale optical computing.",
    url: "https://www.nature.com/articles/mock-silicon-photonic-accelerators",
    doi: "10.1038/mock.2026.004",
    status: "worth-reading"
  },
  {
    id: "p-005",
    title: "Benchmarking analog optical solvers for sparse linear systems",
    authors: ["A. Singh", "M. Ito", "C. Liu"],
    source: "arXiv",
    publishedDate: "2026-06-15",
    score: 76,
    matchedKeywords: ["analog solver", "sparse linear system"],
    abstract:
      "This benchmark compares analog optical solvers against digital baselines for sparse linear systems and identifies where optical noise dominates performance.",
    url: "https://arxiv.org/abs/2606.00005",
    doi: null,
    status: "candidate"
  },
  {
    id: "p-006",
    title: "Photonic reservoir computing for robust time-series forecasting",
    authors: ["F. Garcia", "T. Novak", "R. Hughes"],
    source: "arXiv",
    publishedDate: "2026-06-13",
    score: 72,
    matchedKeywords: ["reservoir computing", "time-series"],
    abstract:
      "A compact photonic reservoir is evaluated on noisy forecasting tasks, showing robustness under constrained training budgets.",
    url: "https://arxiv.org/abs/2606.00006",
    doi: null,
    status: "candidate"
  },
  {
    id: "p-007",
    title: "Wafer-scale packaging for optical AI accelerators",
    authors: ["S. Rhodes", "Y. Tan", "I. Petrov"],
    source: "顶级期刊",
    publishedDate: "2026-06-11",
    score: 69,
    matchedKeywords: ["wafer-scale", "optical AI", "packaging"],
    abstract:
      "The study focuses on packaging constraints for optical AI accelerator systems, including thermal management, coupling loss and module-level yield.",
    url: "https://example.com/paperradar/mock-paper-007",
    doi: null,
    status: "candidate"
  },
  {
    id: "p-008",
    title: "Differentiable design of nanophotonic circuits for matrix multiplication",
    authors: ["K. O'Brien", "J. Lee", "A. Rahman"],
    source: "arXiv",
    publishedDate: "2026-06-09",
    score: 85,
    matchedKeywords: ["nanophotonic circuits", "matrix multiplication"],
    abstract:
      "A differentiable design flow is introduced for nanophotonic matrix multiplication circuits, balancing fabrication constraints and compute density.",
    url: "https://arxiv.org/abs/2606.00008",
    doi: null,
    status: "worth-reading"
  },
  {
    id: "p-009",
    title: "Noise-aware training for photonic neural network deployment",
    authors: ["L. Ma", "E. Schmidt", "P. Nair"],
    source: "arXiv",
    publishedDate: "2026-06-07",
    score: 79,
    matchedKeywords: ["noise-aware training", "photonic neural network"],
    abstract:
      "The authors provide a noise-aware training pipeline that maps neural models onto photonic hardware while preserving accuracy under stochastic perturbations.",
    url: "https://arxiv.org/abs/2606.00009",
    doi: null,
    status: "candidate"
  },
  {
    id: "p-010",
    title: "Optical interconnect fabrics for distributed accelerator clusters",
    authors: ["N. Cohen", "M. Rossi", "J. Patel"],
    source: "Nature Comm.",
    publishedDate: "2026-06-05",
    score: 81,
    matchedKeywords: ["optical interconnect", "accelerator cluster"],
    abstract:
      "This paper studies optical interconnect fabrics for distributed accelerator clusters and quantifies the impact on latency-sensitive workloads.",
    url: "https://www.nature.com/articles/mock-optical-interconnect",
    doi: "10.1038/mock.2026.010",
    status: "candidate"
  }
];

export const mockSummary: PaperSummary = {
  totalFetched: 158,
  candidateCount: 158,
  displayedCount: 10,
  hiddenCount: 148,
  failedCount: 1,
  sources: {
    arxiv: {
      label: "arXiv",
      enabled: true,
      status: "success",
      fetched: 122,
      stored: 122,
      displayed: 7,
      failed: 0,
      error: null
    },
    journals: {
      label: "顶级期刊",
      enabled: true,
      status: "partial",
      fetched: 36,
      stored: 35,
      displayed: 3,
      failed: 1,
      error: "1 篇记录缺少摘要，已跳过评分。"
    }
  }
};

export const mockProfiles: ResearchProfile[] = [
  {
    id: "optical_computing",
    name: "光计算",
    description:
      "Optical and photonic computing, including optical neural networks, photonic processors, matrix multiplication, analog solvers and neuromorphic photonics.",
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
