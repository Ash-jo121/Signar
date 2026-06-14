export type Nullable<T> = T | null;
export type JsonObject = Record<string, unknown>;

export type MarketSession = "open" | "closed";
export type PriceUpdateStatus = "eligible" | "skipped_market_closed";
export type Sentiment = "positive" | "neutral" | "negative";
export type Source = "post" | "comment";
export type RiskLevel = "low" | "medium" | "high" | "extreme";
export type FloatDataQuality =
  | "reported"
  | "estimated"
  | "upper_bound"
  | "missing";
export type MarketState = "open" | "closed";

export interface RunMetadata {
  runDate: string;
  marketSession: MarketSession;
  marketSessionPhase: Nullable<string>;
  marketClosedReason: Nullable<string>;
  priceUpdateStatus: PriceUpdateStatus;
  eligibleForBacktest: boolean;
  nextTradingSessionSignal: boolean;
  scoringVersion?: string;
}

export interface DashboardData extends RunMetadata {
  runMetadata: RunMetadata;
  bestTradeCandidates: TickerData[];
  radarWatchlist: TickerData[];
  avoidHighRisk: TickerData[];
  nearMissCandidates: TickerData[];
  multiDayConfirmation: ThesisConfirmation[];
  confirmedWatchlist: ThesisConfirmation[];
}

export interface DashboardApiResponse {
  run_date?: string;
  market_session?: MarketSession;
  market_session_phase?: Nullable<string>;
  market_closed_reason?: Nullable<string>;
  price_update_status?: PriceUpdateStatus;
  eligible_for_backtest?: boolean;
  next_trading_session_signal?: boolean;
  scoring_version?: string;
  run_metadata?: Record<string, unknown>;
  best_trade_candidates?: Record<string, unknown>[];
  radar_watchlist?: Record<string, unknown>[];
  avoid_high_risk?: Record<string, unknown>[];
  near_miss_candidates?: Record<string, unknown>[];
  multi_day_confirmation?: Record<string, unknown>[];
  confirmed_watchlist?: Record<string, unknown>[];
}

export interface Context {
  text: string;
  sentiment: Sentiment;
  score: number;
  source: Source;
  subreddit: string;
  author: string;
}

export interface MarketData {
  price: number;
  previousClose: number;
  open: number;
  high: number;
  low: number;
  volumeToday: number;
  averageVolume10d: number;
  averageVolume30d: number;
  dollarVolume: number;
  relativeVolume10d: number;
  relativeVolume30d: number;
  priceChange1dPct: Nullable<number>;
  priceChange3dPct: Nullable<number>;
  priceChange7dPct: Nullable<number>;
  gapPct: Nullable<number>;
  intradayRangePct: Nullable<number>;
  distanceFrom20DmaPct: Nullable<number>;
  dataTimestamp: string;
  marketSession: MarketSession;
  marketSessionPhase: Nullable<string>;
  signalDate: string;
  marketDataAsOf: string;
}

export interface ThesisConfirmation {
  ticker: string;
  confirmationState: string;
  confirmationScore: number;
  windowDays: number;
  daysSeen: number;
  daysClearingGates: number;
  uniqueAuthorsLatest: number;
  uniqueAuthorsMax: number;
  authorTrend: string;
  mentionsTrend: string;
  priceStatus: string;
  thesisEvolution: string;
  stateReason: string;
}

export interface RankingReason {
  positive: string[];
  negative: string[];
}

export interface TickerData {
  stockName: string;
  symbol: string;
  name: string;
  shortName: string;
  description: string;
  sector: string;
  industry: string;
  website: string;
  logoUrl: string;
  logoFallback: string;
  exchange: string;
  currency: string;
  country: string;
  city: string;
  state: string;
  zip: string;
  phone: string;
  email: string;
  ceo: string;
  founded: number;
  employees: number;

  mentions: number;
  averageSentiment: number;
  finalScore: number;
  baseFinalScore: number;
  rawFinalScore: number;
  signalScore: number;
  radarScore: number;
  tradeScore: number;
  preCatalystTradeScore: Nullable<number>;
  topContexts: Context[];

  modFlagged: boolean;
  modFlagType: Nullable<string>;
  modFlagScore: number;
  engagementRatio: number;
  uniqueAuthors: number;
  topAuthorMentions: number;
  topAuthorShare: number;
  promotionRiskScore: number;
  promotionTermsCount: number;
  unrealisticTargetCount: number;
  subredditsMentioningTicker: number;
  subredditMentions: Record<string, number>;

  price: number;
  previousClose: number;
  openPrice: number;
  highPrice: number;
  lowPrice: number;
  closePrice: number;
  adjustedClose: number;
  changePercent: number;
  priceChange1d: Nullable<number>;
  priceChange3d: Nullable<number>;
  priceChange7d: Nullable<number>;
  volume: number;
  averageVolume: number;
  averageVolume10d: number;
  averageVolume30d: number;
  relativeVolume: Nullable<number>;
  relativeVolume10d: Nullable<number>;
  relativeVolume30d: Nullable<number>;
  dollarVolume: number;
  volumeChangeVsAverage: Nullable<number>;
  gapPct: Nullable<number>;
  intradayRangePct: Nullable<number>;
  distanceFrom20DmaPct: Nullable<number>;
  marketDataAsOf: string;
  marketDataSource: string;
  marketDataTimestamp: string;
  marketData: MarketData;
  marketConfirmationStatus: string;

  marketCap: number;
  fiftyTwoWeekHigh: number;
  fiftyTwoWeekLow: number;
  analystTarget: number;
  analystRecommendation: string;
  recommendation: Nullable<string>;
  sharesOutstanding: Nullable<number>;
  insiderOwnershipPct: Nullable<number>;
  floatShares: Nullable<number>;
  floatSharesEstimate: Nullable<number>;
  effectiveFloatShares: Nullable<number>;
  floatSharesSource: string;
  floatDataQuality: FloatDataQuality;
  floatFilterStatus: string;
  floatDataTimestamp: Nullable<string>;

  firstSeenDate: string;
  firstSeenDatetime: string;
  daysSinceFirstSeen: number;
  daysTrending: number;
  mentionsToday: number;
  mentionsYesterday: Nullable<number>;
  mentions3dAverage: number;
  mentionAcceleration: number;
  mentionVelocityLabel: string;
  mentionDeclining2d: boolean;
  previousDayMentions: Nullable<number>;
  mentionChangePct: Nullable<number>;
  historicalDaysSeen: number;
  persistenceDaysSeen: number;

  riskScore: number;
  riskLevel: RiskLevel;
  setupType: string;
  threadradarSignal: string;
  threadradarRecommendation: string;
  threadradarTradeStatus: string;
  threadradarRiskAction: string;
  tradeAction: string;
  tradeReason: string;
  tradeGatePassed: boolean;
  independentTradeGatePassed: boolean;
  failedReasons: string[];
  cohort: string;
  rankingBucket: string;
  rankingReason: RankingReason;
  isNearMiss: boolean;
  nearMissRank: Nullable<number>;
  entryDecision: string;
  noTradeDay: boolean;

  hasCatalyst: boolean;
  catalystType: string;
  catalystConfidence: number;
  catalystReasoning: string;
  catalystMultiplierEligible: boolean;
  catalystHasConcreteEvent: boolean;
  catalystGateReason: Nullable<string>;
  thesisConfirmation: Nullable<ThesisConfirmation>;
  confirmationState: string;
  confirmationScore: number;

  vampireFlagged: boolean;
  vampireFlagType: Nullable<string>;
  vampireConfidence: number;

  runDate: string;
  marketSession: MarketSession;
  marketSessionPhase: Nullable<string>;
  priceUpdateStatus: PriceUpdateStatus;
  eligibleForBacktest: boolean;
  nextTradingSessionSignal: boolean;
  scoringVersion: string;

  multipliers: SignalMultipliers;
  tags: string[];
  similar: string[];
  related: string[];
  stats: JsonObject;
  financials: JsonObject;
  news: unknown[];
  events: unknown[];
  earnings: JsonObject;
  dividends: JsonObject;
  splits: JsonObject;
  stockSplits: JsonObject;
  stockDividends: JsonObject;
}

export interface SignalMultipliers {
  catalyst: number;
  crossSubreddit: number;
  subreddit: number;
  userCredibility: number;
  postQuality: number;
  socialConviction: number;
  credibility: number;
  evidenceQuality: number;
  timing: number;
  tickerMentionDensity: number;
  mentionSweetSpot: number;
  sentimentTiming: number;
  engagement: number;
  antiChase: number;
  persistence: number;
  staleRepetition: number;
  vampire: number;
  accountAge: number;
  karma: number;
  authorDiversity: number;
  authorConcentration: number;
  combinedSignal: number;
  volumeConfirmation: number;
  liquidity: number;
  earlyness: number;
  setupTrade: number;
  riskScore: number;
  freshness: number;
  promotionTrade: number;
}
