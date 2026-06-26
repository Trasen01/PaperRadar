import { ReactNode } from "react";

type PageHeaderProps = {
  title: string;
  description: string;
  actions?: ReactNode;
};

export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <header className="mb-5 flex items-start justify-between gap-5">
      <div>
        <h1 className="text-[28px] font-semibold tracking-tight text-slate-950">{title}</h1>
        <p className="mt-1 text-sm leading-6 text-slate-500">{description}</p>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  );
}
