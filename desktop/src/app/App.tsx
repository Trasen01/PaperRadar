import { useMemo, useState } from "react";
import { History, LibraryBig, Radar } from "lucide-react";
import { AppShell } from "../components/layout/AppShell";
import { TodayDiscovery } from "../pages/TodayDiscovery";
import { HistoryResearch } from "../pages/HistoryResearch";
import { ResearchProfiles } from "../pages/ResearchProfiles";

export type AppPage = "today" | "history" | "profiles";

export function App() {
  const [page, setPage] = useState<AppPage>("today");

  const navigation = useMemo(
    () => [
      { id: "today" as const, label: "今日发现", icon: Radar },
      { id: "history" as const, label: "历史调研", icon: History },
      { id: "profiles" as const, label: "研究方向", icon: LibraryBig }
    ],
    []
  );

  return (
    <AppShell activePage={page} navigation={navigation} onNavigate={setPage}>
      <div className={page === "today" ? "block" : "hidden"}><TodayDiscovery /></div>
      <div className={page === "history" ? "block" : "hidden"}><HistoryResearch /></div>
      <div className={page === "profiles" ? "block" : "hidden"}><ResearchProfiles /></div>
    </AppShell>
  );
}
