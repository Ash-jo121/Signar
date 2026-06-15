import { createContext, useContext, type Dispatch, type SetStateAction } from "react";
import type { DashboardData, MarketState, TickerData } from "@/types/Dashboard";

export interface DashboardContextValue {
  dashboard: DashboardData;
  allTickers: TickerData[];
  liveMarketState: MarketState;
  search: string;
  setSearch: Dispatch<SetStateAction<string>>;
  loading: boolean;
  error: string;
}

export const DashboardContext = createContext<DashboardContextValue | null>(null);

export function useDashboardContext() {
  const context = useContext(DashboardContext);
  if (!context) {
    throw new Error("useDashboardContext must be used inside DashboardProvider");
  }
  return context;
}
