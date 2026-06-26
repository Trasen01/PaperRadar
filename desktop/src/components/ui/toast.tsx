import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import { cn } from "../../lib/utils";

type ToastProps = {
  message: string;
  type?: "success" | "error" | "warning" | "info";
};

export function Toast({ message, type = "info" }: ToastProps) {
  const Icon = type === "success" ? CheckCircle2 : type === "error" ? XCircle : type === "warning" ? AlertTriangle : Info;
  return (
    <div
      className={cn(
        "fixed bottom-5 right-5 z-50 flex max-w-[420px] items-start gap-3 rounded-2xl border bg-white px-4 py-3 text-sm shadow-soft",
        type === "success" && "border-emerald-100 text-emerald-800",
        type === "error" && "border-red-100 text-red-800",
        type === "warning" && "border-amber-100 text-amber-800",
        type === "info" && "border-blue-100 text-blue-800"
      )}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <span className="leading-5">{message}</span>
    </div>
  );
}