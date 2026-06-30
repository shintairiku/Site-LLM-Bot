"use client";

import { createContext, useContext, useState, useCallback } from "react";
import type { AnalyticsData } from "./analytics";

export interface PromptRecord {
  id: string;
  content: string;
  note: string | null;
  created_by: string | null;
  created_at: string;
}

export interface DataSource {
  id: string;
  kind: "pdf" | "text" | "url";
  title: string;
  source_url: string | null;
  status: "processing" | "ready" | "error";
  bytes: number | null;
  chunk_count: number | null;
  created_by: string | null;
  created_at: string;
}

export interface AnalyticsAll {
  day: AnalyticsData;
  week: AnalyticsData;
  month: AnalyticsData;
}

interface DashboardContextValue {
  prompts: PromptRecord[];
  setPrompts: (records: PromptRecord[]) => void;
  dataSources: DataSource[];
  setDataSources: (sources: DataSource[]) => void;
  analytics: AnalyticsAll;
  refreshing: boolean;
  refresh: () => Promise<void>;
  /** 分析データのみを再取得する（分析画面のポーリング用）。 */
  refreshAnalytics: () => Promise<void>;
}

const DashboardContext = createContext<DashboardContextValue | null>(null);

export function useDashboard() {
  const ctx = useContext(DashboardContext);
  if (!ctx) throw new Error("useDashboard must be used within DashboardProvider");
  return ctx;
}

interface Props {
  initialPrompts: PromptRecord[];
  initialDataSources: DataSource[];
  initialAnalytics: AnalyticsAll;
  children: React.ReactNode;
}

export function DashboardProvider({
  initialPrompts,
  initialDataSources,
  initialAnalytics,
  children,
}: Props) {
  const [prompts, setPrompts] = useState<PromptRecord[]>(initialPrompts);
  const [dataSources, setDataSources] = useState<DataSource[]>(initialDataSources);
  const [analytics, setAnalytics] = useState<AnalyticsAll>(initialAnalytics);
  const [refreshing, setRefreshing] = useState(false);

  const refreshAnalytics = useCallback(async () => {
    const [dayRes, weekRes, monthRes] = await Promise.all([
      fetch("/api/analytics?period=day").then((r) => r.json()),
      fetch("/api/analytics?period=week").then((r) => r.json()),
      fetch("/api/analytics?period=month").then((r) => r.json()),
    ]);
    if (dayRes && weekRes && monthRes && !dayRes.error) {
      setAnalytics({ day: dayRes, week: weekRes, month: monthRes });
    }
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const [promptsRes, dataRes, dayRes, weekRes, monthRes] = await Promise.all([
        fetch("/api/prompt").then((r) => r.json()),
        fetch("/api/data-sources").then((r) => r.json()),
        fetch("/api/analytics?period=day").then((r) => r.json()),
        fetch("/api/analytics?period=week").then((r) => r.json()),
        fetch("/api/analytics?period=month").then((r) => r.json()),
      ]);
      if (Array.isArray(promptsRes)) setPrompts(promptsRes);
      if (Array.isArray(dataRes)) setDataSources(dataRes);
      if (dayRes && weekRes && monthRes && !dayRes.error) {
        setAnalytics({ day: dayRes, week: weekRes, month: monthRes });
      }
    } finally {
      setRefreshing(false);
    }
  }, []);

  return (
    <DashboardContext.Provider
      value={{
        prompts,
        setPrompts,
        dataSources,
        setDataSources,
        analytics,
        refreshing,
        refresh,
        refreshAnalytics,
      }}
    >
      {children}
    </DashboardContext.Provider>
  );
}
