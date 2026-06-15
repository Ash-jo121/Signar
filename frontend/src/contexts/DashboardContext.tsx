import { useEffect, useMemo, useState, type ReactNode } from "react";
import { TICKERS_API_URL } from "@/constants/Api";
import { EMPTY_DASHBOARD } from "@/constants/Header";
import { DashboardContext } from "@/contexts/useDashboardContext";
import { mapDashboardData } from "@/helpers/DashboardMapper";
import type { DashboardData, MarketState, TickerData } from "@/types/Dashboard";

const uniqueTickers = (...groups: TickerData[][]) => {
  const seen = new Set<string>();
  return groups.flat().filter((ticker) => {
    if (seen.has(ticker.stockName)) return false;
    seen.add(ticker.stockName);
    return true;
  });
};

const getEasternMarketState = (
  now: Date,
  runDate: string,
  runSession: string,
): MarketState => {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      weekday: "short",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(now)
      .map((part) => [part.type, part.value]),
  );
  const easternDate = `${parts.year}-${parts.month}-${parts.day}`;
  const minutes = Number(parts.hour) * 60 + Number(parts.minute);
  const isWeekday = !["Sat", "Sun"].includes(parts.weekday);
  const isCurrentTradingDay = runSession === "open" && runDate === easternDate;

  return isCurrentTradingDay && isWeekday && minutes >= 9 * 60 + 30 && minutes < 16 * 60
    ? "open"
    : "closed";
};

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [dashboard, setDashboard] = useState<DashboardData>(EMPTY_DASHBOARD);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [currentTime, setCurrentTime] = useState(() => new Date());

  useEffect(() => {
    const controller = new AbortController();

    fetch(TICKERS_API_URL, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Dashboard API returned ${response.status}`);
        return response.json();
      })
      .then((payload: unknown) => setDashboard(mapDashboardData(payload)))
      .catch((fetchError: unknown) => {
        if (fetchError instanceof DOMException && fetchError.name === "AbortError") return;
        setError(fetchError instanceof Error ? fetchError.message : "Unable to load signals");
      })
      .finally(() => setLoading(false));

    return () => controller.abort();
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setCurrentTime(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  const allTickers = useMemo(
    () =>
      uniqueTickers(
        dashboard.bestTradeCandidates,
        dashboard.radarWatchlist,
        dashboard.avoidHighRisk,
        dashboard.nearMissCandidates,
      ),
    [dashboard],
  );

  const liveMarketState = getEasternMarketState(
    currentTime,
    dashboard.runDate,
    dashboard.marketSession,
  );

  const value = useMemo(
    () => ({
      dashboard,
      allTickers,
      liveMarketState,
      search,
      setSearch,
      loading,
      error,
    }),
    [allTickers, dashboard, error, liveMarketState, loading, search],
  );

  return <DashboardContext.Provider value={value}>{children}</DashboardContext.Provider>;
}
