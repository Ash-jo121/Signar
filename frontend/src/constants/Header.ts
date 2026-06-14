import type { DashboardData } from "@/types/Dashboard";

export const EMPTY_DASHBOARD: DashboardData = {
  runDate: "",
  marketSession: "closed",
  marketSessionPhase: null,
  marketClosedReason: null,
  priceUpdateStatus: "skipped_market_closed",
  eligibleForBacktest: false,
  nextTradingSessionSignal: false,
  runMetadata: {
    runDate: "",
    marketSession: "closed",
    marketSessionPhase: null,
    marketClosedReason: null,
    priceUpdateStatus: "skipped_market_closed",
    eligibleForBacktest: false,
    nextTradingSessionSignal: false,
  },
  bestTradeCandidates: [],
  radarWatchlist: [],
  avoidHighRisk: [],
  nearMissCandidates: [],
  multiDayConfirmation: [],
  confirmedWatchlist: [],
};
