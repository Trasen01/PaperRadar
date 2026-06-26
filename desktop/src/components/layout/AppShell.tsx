import { ComponentType, ReactNode } from "react";
import { Activity, SatelliteDish } from "lucide-react";
import type { AppPage } from "../../app/App";
import { cn } from "../../lib/utils";

type NavigationItem = {
  id: AppPage;
  label: string;
  icon: ComponentType<{ className?: string }>;
};

type AppShellProps = {
  activePage: AppPage;
  navigation: NavigationItem[];
  onNavigate: (page: AppPage) => void;
  children: ReactNode;
};

export function AppShell({ activePage, navigation, onNavigate, children }: AppShellProps) {
  return (
    <div className="flex h-screen min-w-[1180px] overflow-hidden bg-slate-50/80">
      <aside className="flex w-[260px] shrink-0 flex-col border-r border-slate-200/80 bg-white/78 px-4 py-5 shadow-[inset_-1px_0_0_rgba(255,255,255,0.7)] backdrop-blur-xl">
        <div className="mb-8 flex items-center gap-3 px-2">
          <div className="grid h-11 w-11 place-items-center rounded-2xl bg-blue-600 text-white shadow-soft">
            <SatelliteDish className="h-6 w-6" />
          </div>
          <div>
            <div className="text-[17px] font-semibold tracking-tight text-slate-950">PaperRadar</div>
            <div className="text-sm text-slate-500">文献雷达</div>
          </div>
        </div>

        <nav className="space-y-1.5">
          {navigation.map((item) => {
            const Icon = item.icon;
            const active = activePage === item.id;
            return (
              <button
                key={item.id}
                className={cn(
                  "group relative flex h-11 w-full items-center gap-3 rounded-xl px-3 text-left text-sm font-medium outline-none transition",
                  active ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-100/80 hover:text-slate-950"
                )}
                onClick={() => onNavigate(item.id)}
              >
                <span className={cn("absolute left-0 h-6 w-1 rounded-full transition", active ? "bg-blue-600 opacity-100" : "bg-transparent opacity-0")} />
                <Icon className={cn("h-4.5 w-4.5", active ? "text-blue-700" : "text-slate-500")} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="mt-auto rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-800">
            <Activity className="h-4 w-4 text-emerald-600" />
            本地模式
          </div>
          <p className="text-xs leading-5 text-slate-500">采用关键词命中机制，结合研究方向筛选本地与在线文献。</p>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="flex-1 overflow-auto px-7 py-6">{children}</div>
      </main>
    </div>
  );
}
