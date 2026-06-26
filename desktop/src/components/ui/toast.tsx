import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import { cn } from "../../lib/utils";
import { Button } from "./button";

type ToastProps = {
  message?: string;
  title?: string;
  description?: string;
  type?: "success" | "error" | "warning" | "info";
  actionLabel?: string;
  onAction?: () => void;
  secondaryActionLabel?: string;
  onSecondaryAction?: () => void;
};

export function Toast({ message, title, description, type = "info", actionLabel, onAction, secondaryActionLabel, onSecondaryAction }: ToastProps) {
  const Icon = type === "success" ? CheckCircle2 : type === "error" ? XCircle : type === "warning" ? AlertTriangle : Info;
  const body = description ?? message;

  return (
    <div
      className={cn(
        "fixed bottom-5 right-5 z-50 flex max-w-[440px] items-start gap-3 rounded-2xl border bg-white px-4 py-3 text-sm shadow-soft",
        type === "success" && "border-emerald-100 text-emerald-800",
        type === "error" && "border-red-100 text-red-800",
        type === "warning" && "border-amber-100 text-amber-800",
        type === "info" && "border-blue-100 text-blue-800"
      )}
      role="status"
      aria-live="polite"
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0">
        {title && <div className="font-semibold leading-5">{title}</div>}
        {body && <div className={cn("leading-5", title && "mt-0.5 text-slate-600")}>{body}</div>}
        {(actionLabel || secondaryActionLabel) && (
          <div className="mt-3 flex gap-2">
            {actionLabel && onAction && <Button size="sm" variant={type === "error" ? "danger" : "secondary"} onClick={onAction}>{actionLabel}</Button>}
            {secondaryActionLabel && onSecondaryAction && <Button size="sm" variant="ghost" onClick={onSecondaryAction}>{secondaryActionLabel}</Button>}
          </div>
        )}
      </div>
    </div>
  );
}