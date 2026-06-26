import { CheckCircle2, XCircle } from "lucide-react";
import { cn } from "../../lib/utils";

type ToastProps = {
  message: string;
  type?: "success" | "error" | "info";
};

export function Toast({ message, type = "info" }: ToastProps) {
  return (
    <div
      className={cn(
        "fixed bottom-5 right-5 z-50 flex items-center gap-3 rounded-2xl border bg-white px-4 py-3 text-sm shadow-soft",
        type === "success" && "border-emerald-100 text-emerald-800",
        type === "error" && "border-red-100 text-red-800",
        type === "info" && "border-slate-200 text-slate-800"
      )}
    >
      {type === "error" ? <XCircle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
      {message}
    </div>
  );
}
