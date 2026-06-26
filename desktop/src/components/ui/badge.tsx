import { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";

type BadgeVariant = "blue" | "green" | "amber" | "red" | "slate" | "purple";

const variants: Record<BadgeVariant, string> = {
  blue: "bg-blue-50 text-blue-700 ring-blue-100",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-100",
  amber: "bg-amber-50 text-amber-700 ring-amber-100",
  red: "bg-red-50 text-red-700 ring-red-100",
  slate: "bg-slate-100 text-slate-700 ring-slate-200",
  purple: "bg-violet-50 text-violet-700 ring-violet-100"
};

type BadgeProps = HTMLAttributes<HTMLSpanElement> & {
  variant?: BadgeVariant;
};

export function Badge({ className, variant = "slate", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex min-h-[24px] min-w-[48px] items-center justify-center whitespace-nowrap rounded-full px-2.5 text-xs font-semibold ring-1",
        variants[variant],
        className
      )}
      {...props}
    />
  );
}
