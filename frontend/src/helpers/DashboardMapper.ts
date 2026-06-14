import type {
  Context,
  DashboardApiResponse,
  DashboardData,
  FloatDataQuality,
  JsonObject,
  MarketData,
  MarketSession,
  PriceUpdateStatus,
  RankingReason,
  RiskLevel,
  Sentiment,
  Source,
  ThesisConfirmation,
  TickerData,
} from "../types/Dashboard";

type RawObject = Record<string, unknown>;

const objectValue = (value: unknown): RawObject =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as RawObject)
    : {};

const arrayValue = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const stringValue = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value : fallback;
const numberValue = (value: unknown, fallback = 0): number =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;
const nullableNumber = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const nullableString = (value: unknown): string | null =>
  typeof value === "string" ? value : null;
const booleanValue = (value: unknown): boolean => value === true;
const stringArray = (value: unknown): string[] =>
  arrayValue(value).filter((item): item is string => typeof item === "string");

const numberRecord = (value: unknown): Record<string, number> =>
  Object.fromEntries(
    Object.entries(objectValue(value)).filter(
      (entry): entry is [string, number] =>
        typeof entry[1] === "number" && Number.isFinite(entry[1]),
    ),
  );

const mapContext = (value: unknown): Context => {
  const context = objectValue(value);
  return {
    text: stringValue(context.text),
    sentiment: stringValue(context.sentiment, "neutral") as Sentiment,
    score: numberValue(context.score),
    source: stringValue(context.source, "post") as Source,
    subreddit: stringValue(context.subreddit),
    author: stringValue(context.author),
  };
};

const mapMarketData = (value: unknown): MarketData => {
  const market = objectValue(value);
  return {
    price: numberValue(market.price),
    previousClose: numberValue(market.previous_close),
    open: numberValue(market.open),
    high: numberValue(market.high),
    low: numberValue(market.low),
    volumeToday: numberValue(market.volume_today),
    averageVolume10d: numberValue(market.avg_volume_10d),
    averageVolume30d: numberValue(market.avg_volume_30d),
    dollarVolume: numberValue(market.dollar_volume),
    relativeVolume10d: numberValue(market.relative_volume_10d),
    relativeVolume30d: numberValue(market.relative_volume_30d),
    priceChange1dPct: nullableNumber(market.price_change_1d_pct),
    priceChange3dPct: nullableNumber(market.price_change_3d_pct),
    priceChange7dPct: nullableNumber(market.price_change_7d_pct),
    gapPct: nullableNumber(market.gap_pct),
    intradayRangePct: nullableNumber(market.intraday_range_pct),
    distanceFrom20DmaPct: nullableNumber(market.distance_from_20dma_pct),
    dataTimestamp: stringValue(market.data_timestamp),
    marketSession: stringValue(market.market_session, "closed") as MarketSession,
    marketSessionPhase: nullableString(market.market_session_phase),
    signalDate: stringValue(market.signal_date),
    marketDataAsOf: stringValue(market.market_data_as_of),
  };
};

export const mapThesisConfirmation = (value: unknown): ThesisConfirmation => {
  const confirmation = objectValue(value);
  return {
    ticker: stringValue(confirmation.ticker),
    confirmationState: stringValue(confirmation.confirmation_state),
    confirmationScore: numberValue(confirmation.confirmation_score),
    windowDays: numberValue(confirmation.window_days),
    daysSeen: numberValue(confirmation.days_seen),
    daysClearingGates: numberValue(confirmation.days_clearing_gates),
    uniqueAuthorsLatest: numberValue(confirmation.unique_authors_latest),
    uniqueAuthorsMax: numberValue(confirmation.unique_authors_max),
    authorTrend: stringValue(confirmation.author_trend),
    mentionsTrend: stringValue(confirmation.mentions_trend),
    priceStatus: stringValue(confirmation.price_status),
    thesisEvolution: stringValue(confirmation.thesis_evolution),
    stateReason: stringValue(confirmation.state_reason),
  };
};

const mapRankingReason = (value: unknown): RankingReason => {
  const reason = objectValue(value);
  return {
    positive: stringArray(reason.positive),
    negative: stringArray(reason.negative),
  };
};

export const mapTicker = (value: unknown): TickerData => {
  const item = objectValue(value);
  const thesis = item.thesis_confirmation;

  return {
    stockName: stringValue(item.ticker),
    symbol: stringValue(item.symbol, stringValue(item.ticker)),
    name: stringValue(item.name),
    shortName: stringValue(item.short_name),
    description: stringValue(item.description),
    sector: stringValue(item.sector),
    industry: stringValue(item.industry),
    website: stringValue(item.website),
    logoUrl: stringValue(item.logo_url),
    logoFallback: stringValue(item.logo_fallback),
    exchange: stringValue(item.exchange),
    currency: stringValue(item.currency),
    country: stringValue(item.country),
    city: stringValue(item.city),
    state: stringValue(item.state),
    zip: stringValue(item.zip),
    phone: stringValue(item.phone),
    email: stringValue(item.email),
    ceo: stringValue(item.ceo),
    founded: numberValue(item.founded),
    employees: numberValue(item.num_employees),

    mentions: numberValue(item.mentions),
    averageSentiment: numberValue(item.avg_sentiment),
    finalScore: numberValue(item.final_score),
    baseFinalScore: numberValue(item.base_final_score),
    rawFinalScore: numberValue(item.raw_final_score),
    signalScore: numberValue(item.signal_score),
    radarScore: numberValue(item.radar_score),
    tradeScore: numberValue(item.trade_score),
    preCatalystTradeScore: nullableNumber(item.pre_catalyst_trade_score),
    topContexts: arrayValue(item.top_contexts).map(mapContext),

    modFlagged: booleanValue(item.mod_flagged),
    modFlagType: nullableString(item.mod_flag_type),
    modFlagScore: numberValue(item.mod_flag_score),
    engagementRatio: numberValue(item.engagement_ratio),
    uniqueAuthors: numberValue(item.unique_authors),
    topAuthorMentions: numberValue(item.top_author_mentions),
    topAuthorShare: numberValue(item.top_author_share),
    promotionRiskScore: numberValue(item.promotion_risk_score),
    promotionTermsCount: numberValue(item.promotion_terms_count),
    unrealisticTargetCount: numberValue(item.unrealistic_target_count),
    subredditsMentioningTicker: numberValue(item.subreddits_mentioning_ticker),
    subredditMentions: numberRecord(item.subreddit_mentions),

    price: numberValue(item.price),
    previousClose: numberValue(item.previous_close),
    openPrice: numberValue(item.open_price),
    highPrice: numberValue(item.high_price),
    lowPrice: numberValue(item.low_price),
    closePrice: numberValue(item.close_price),
    adjustedClose: numberValue(item.adjusted_close),
    changePercent: numberValue(item.change_percent),
    priceChange1d: nullableNumber(item.price_change_1d),
    priceChange3d: nullableNumber(item.price_change_3d),
    priceChange7d: nullableNumber(item.price_change_7d),
    volume: numberValue(item.volume),
    averageVolume: numberValue(item.average_volume),
    averageVolume10d: numberValue(item.avg_volume_10d),
    averageVolume30d: numberValue(item.avg_volume_30d),
    relativeVolume: nullableNumber(item.relative_volume),
    relativeVolume10d: nullableNumber(item.relative_volume_10d),
    relativeVolume30d: nullableNumber(item.relative_volume_30d),
    dollarVolume: numberValue(item.dollar_volume),
    volumeChangeVsAverage: nullableNumber(item.volume_change_vs_avg),
    gapPct: nullableNumber(item.gap_pct),
    intradayRangePct: nullableNumber(item.intraday_range_pct),
    distanceFrom20DmaPct: nullableNumber(item.distance_from_20dma_pct),
    marketDataAsOf: stringValue(item.market_data_as_of),
    marketDataSource: stringValue(item.market_data_source),
    marketDataTimestamp: stringValue(item.market_data_timestamp),
    marketData: mapMarketData(item.market_data),
    marketConfirmationStatus: stringValue(item.market_confirmation_status),

    marketCap: numberValue(item.market_cap),
    fiftyTwoWeekHigh: numberValue(item.fifty_two_week_high),
    fiftyTwoWeekLow: numberValue(item.fifty_two_week_low),
    analystTarget: numberValue(item.analyst_target),
    analystRecommendation: stringValue(item.analyst_recommendation, "none"),
    recommendation: nullableString(item.recommendation),
    sharesOutstanding: nullableNumber(item.shares_outstanding),
    insiderOwnershipPct: nullableNumber(item.insider_ownership_pct),
    floatShares: nullableNumber(item.float_shares),
    floatSharesEstimate: nullableNumber(item.float_shares_estimate),
    effectiveFloatShares: nullableNumber(item.effective_float_shares),
    floatSharesSource: stringValue(item.float_shares_source, "unavailable"),
    floatDataQuality: stringValue(item.float_data_quality, "missing") as FloatDataQuality,
    floatFilterStatus: stringValue(item.float_filter_status),
    floatDataTimestamp: nullableString(item.float_data_timestamp),

    firstSeenDate: stringValue(item.first_seen_date),
    firstSeenDatetime: stringValue(item.first_seen_datetime),
    daysSinceFirstSeen: numberValue(item.days_since_first_seen),
    daysTrending: numberValue(item.days_trending),
    mentionsToday: numberValue(item.mentions_today),
    mentionsYesterday: nullableNumber(item.mentions_yesterday),
    mentions3dAverage: numberValue(item.mentions_3d_avg),
    mentionAcceleration: numberValue(item.mention_acceleration),
    mentionVelocityLabel: stringValue(item.mention_velocity_label),
    mentionDeclining2d: booleanValue(item.mention_declining_2d),
    previousDayMentions: nullableNumber(item.previous_day_mentions),
    mentionChangePct: nullableNumber(item.mention_change_pct),
    historicalDaysSeen: numberValue(item.historical_days_seen),
    persistenceDaysSeen: numberValue(item.persistence_days_seen),

    riskScore: numberValue(item.risk_score),
    riskLevel: stringValue(item.risk_level, "low") as RiskLevel,
    setupType: stringValue(item.setup_type),
    threadradarSignal: stringValue(item.threadradar_signal),
    threadradarRecommendation: stringValue(item.threadradar_recommendation),
    threadradarTradeStatus: stringValue(item.threadradar_trade_status),
    threadradarRiskAction: stringValue(item.threadradar_risk_action),
    tradeAction: stringValue(item.trade_action),
    tradeReason: stringValue(item.trade_reason),
    tradeGatePassed: booleanValue(item.trade_gate_passed),
    independentTradeGatePassed: booleanValue(item.independent_trade_gate_passed),
    failedReasons: stringArray(item.failed_reasons),
    cohort: stringValue(item.cohort),
    rankingBucket: stringValue(item.ranking_bucket),
    rankingReason: mapRankingReason(item.ranking_reason),
    isNearMiss: booleanValue(item.is_near_miss),
    nearMissRank: nullableNumber(item.near_miss_rank),
    entryDecision: stringValue(item.entry_decision),
    noTradeDay: booleanValue(item.no_trade_day),

    hasCatalyst: booleanValue(item.has_catalyst),
    catalystType: stringValue(item.catalyst_type),
    catalystConfidence: numberValue(item.catalyst_confidence),
    catalystReasoning: stringValue(item.catalyst_reasoning),
    catalystMultiplierEligible: booleanValue(item.catalyst_multiplier_eligible),
    catalystHasConcreteEvent: booleanValue(item.catalyst_has_concrete_event),
    catalystGateReason: nullableString(item.catalyst_gate_reason),
    thesisConfirmation:
      thesis !== null && typeof thesis === "object" ? mapThesisConfirmation(thesis) : null,
    confirmationState: stringValue(item.confirmation_state),
    confirmationScore: numberValue(item.confirmation_score),

    vampireFlagged: booleanValue(item.vampire_flagged),
    vampireFlagType: nullableString(item.vampire_flag_type),
    vampireConfidence: numberValue(item.vampire_confidence),

    runDate: stringValue(item.run_date),
    marketSession: stringValue(item.market_session, "closed") as MarketSession,
    marketSessionPhase: nullableString(item.market_session_phase),
    priceUpdateStatus: stringValue(
      item.price_update_status,
      "skipped_market_closed",
    ) as PriceUpdateStatus,
    eligibleForBacktest: booleanValue(item.eligible_for_backtest),
    nextTradingSessionSignal: booleanValue(item.next_trading_session_signal),
    scoringVersion: stringValue(item.scoring_version),

    multipliers: {
      catalyst: numberValue(item.catalyst_multiplier, 1),
      crossSubreddit: numberValue(item.cross_subreddit_multiplier, 1),
      subreddit: numberValue(item.subreddit_multiplier, 1),
      userCredibility: numberValue(item.user_credibility_multiplier, 1),
      postQuality: numberValue(item.post_quality_multiplier, 1),
      socialConviction: numberValue(item.social_conviction_multiplier, 1),
      credibility: numberValue(item.credibility_multiplier, 1),
      evidenceQuality: numberValue(item.evidence_quality_multiplier, 1),
      timing: numberValue(item.timing_multiplier, 1),
      tickerMentionDensity: numberValue(item.ticker_mention_density_multiplier, 1),
      mentionSweetSpot: numberValue(item.mention_sweet_spot_multiplier, 1),
      sentimentTiming: numberValue(item.sentiment_timing_multiplier, 1),
      engagement: numberValue(item.engagement_multiplier, 1),
      antiChase: numberValue(item.anti_chase_multiplier, 1),
      persistence: numberValue(item.persistence_multiplier, 1),
      staleRepetition: numberValue(item.stale_repetition_multiplier, 1),
      vampire: numberValue(item.vampire_multiplier, 1),
      accountAge: numberValue(item.account_age_multiplier, 1),
      karma: numberValue(item.karma_multiplier, 1),
      authorDiversity: numberValue(item.author_diversity_multiplier, 1),
      authorConcentration: numberValue(item.author_concentration_multiplier, 1),
      combinedSignal: numberValue(item.combined_signal_multiplier, 1),
      volumeConfirmation: numberValue(item.volume_confirmation_multiplier, 1),
      liquidity: numberValue(item.liquidity_multiplier, 1),
      earlyness: numberValue(item.earlyness_multiplier, 1),
      setupTrade: numberValue(item.setup_trade_multiplier, 1),
      riskScore: numberValue(item.risk_score_multiplier, 1),
      freshness: numberValue(item.freshness_multiplier, 1),
      promotionTrade: numberValue(item.promotion_trade_multiplier, 1),
    },
    tags: stringArray(item.tags),
    similar: stringArray(item.similar),
    related: stringArray(item.related),
    stats: objectValue(item.stats) as JsonObject,
    financials: objectValue(item.financials) as JsonObject,
    news: arrayValue(item.news),
    events: arrayValue(item.events),
    earnings: objectValue(item.earnings) as JsonObject,
    dividends: objectValue(item.dividends) as JsonObject,
    splits: objectValue(item.splits) as JsonObject,
    stockSplits: objectValue(item.stock_splits) as JsonObject,
    stockDividends: objectValue(item.stock_dividends) as JsonObject,
  };
};

const mapRunMetadata = (value: unknown) => {
  const metadata = objectValue(value);
  return {
    runDate: stringValue(metadata.run_date),
    marketSession: stringValue(metadata.market_session, "closed") as MarketSession,
    marketSessionPhase: nullableString(metadata.market_session_phase),
    marketClosedReason: nullableString(metadata.market_closed_reason),
    priceUpdateStatus: stringValue(
      metadata.price_update_status,
      "skipped_market_closed",
    ) as PriceUpdateStatus,
    eligibleForBacktest: booleanValue(metadata.eligible_for_backtest),
    nextTradingSessionSignal: booleanValue(metadata.next_trading_session_signal),
    scoringVersion: stringValue(metadata.scoring_version) || undefined,
  };
};

export const mapDashboardData = (value: unknown): DashboardData => {
  const data = objectValue(value) as DashboardApiResponse;
  const runMetadata = mapRunMetadata(data.run_metadata ?? data);

  return {
    ...runMetadata,
    runMetadata,
    bestTradeCandidates: arrayValue(data.best_trade_candidates).map(mapTicker),
    radarWatchlist: arrayValue(data.radar_watchlist).map(mapTicker),
    avoidHighRisk: arrayValue(data.avoid_high_risk).map(mapTicker),
    nearMissCandidates: arrayValue(data.near_miss_candidates).map(mapTicker),
    multiDayConfirmation: arrayValue(data.multi_day_confirmation).map(mapThesisConfirmation),
    confirmedWatchlist: arrayValue(data.confirmed_watchlist).map(mapThesisConfirmation),
  };
};

// Backwards-compatible list mapper for the current dashboard table. For a full
// API payload, trade candidates are preferred and the radar watchlist is the fallback.
export const dashboardMapper = (value: unknown): TickerData[] => {
  if (Array.isArray(value)) {
    return value.map(mapTicker);
  }

  const dashboard = mapDashboardData(value);
  return dashboard.bestTradeCandidates.length > 0
    ? dashboard.bestTradeCandidates
    : dashboard.radarWatchlist;
};
