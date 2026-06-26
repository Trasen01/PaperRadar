import { ReactNode } from "react";
import { FileSearch } from "lucide-react";
import { Button } from "./button";

type EmptyStateProps = {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
  secondaryActionLabel?: string;
  onSecondaryAction?: () => void;
  icon?: ReactNode;
};

export function EmptyState({ title, description, actionLabel, onAction, secondaryActionLabel, onSecondaryAction, icon }: EmptyStateProps) {
  return (
    <div className="grid min-h-[280px] place-items-center rounded-2xl border border-dashed border-slate-200 bg-slate-50/70 p-8 text-center">
      <div>
        <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-2xl bg-white text-blue-600 shadow-sm">
          {icon ?? <FileSearch className="h-6 w-6" />}
        </div>
        <h3 className="text-base font-semibold text-slate-950">{title}</h3>
        <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">{description}</p>
        <div className="mt-5 flex justify-center gap-2">
          {actionLabel && onAction && <Button variant="primary" onClick={onAction}>{actionLabel}</Button>}
          {secondaryActionLabel && onSecondaryAction && <Button variant="secondary" onClick={onSecondaryAction}>{secondaryActionLabel}</Button>}
        </div>
      </div>
    </div>
  );
}