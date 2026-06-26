import { ReactNode } from "react";
import { cn } from "../../lib/utils";

type KpiCardProps = {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: "blue" | "green" | "amber" | "red" | "slate";
};

const tones = {
  blue: "from-blue-50 to-white text-blue-700",
  green: "from-emerald-50 to-white text-emerald-700",
  amber: "from-amber-50 to-white text-amber-700",
  red: "from-red-50 to-white text-red-700",
  slate: "from-slate-50 to-white text-slate-700"
};

export function KpiCard({ label, value, hint, tone = "slate" }: KpiCardProps) {
  return (
    <div className={cn("rounded-2xl border border-slate-200 bg-gradient-to-br p-4 shadow-card", tones[tone])}>
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold tracking-tight">{value}</div>
      {hint && <div className="mt-1 truncate text-xs text-slate-500">{hint}</div>}
    </div>
  );
}
