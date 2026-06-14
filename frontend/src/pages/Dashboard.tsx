import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowDown,
  ArrowUp,
  BarChart3,
  ChevronDown,
  ExternalLink,
  Radar,
  Search,
  ShieldAlert,
  Sparkles,
  TrendingUp,
  Users,
  WalletCards,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import CompanyLogo from "../components/CompanyLogo";
import { mapDashboardData } from "../helpers/DashboardMapper";
import { PATHS } from "../routes/paths";
import type { DashboardData, TickerData } from "../types/Dashboard";
import "../styles/Dashboard.css";

const API_URL = "http://localhost:8000/api/tickers";

type DashboardTab = "trade" | "radar" | "risk" | "all";
type SortKey = "ticker" | "price" | "mentions" | "sentiment" | "radar";
type SortDirection = "asc" | "desc";

const PAPER_PORTFOLIO = {
  totalCapital: 10_000,
  cashAvailable: 7_240.5,
  invested: 2_759.5,
  totalPnl: 342.2,
  todayPnl: 84.3,
  positions: [
    { ticker: "OTLK", change: 7.9 },
    { ticker: "MWC", change: 6.5 },
    { ticker: "RENY", change: 3.2 },
  ],
};

const EMPTY_DASHBOARD: DashboardData = {
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

const money = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  }).format(value);

const compactNumber = (value: number) =>
  new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);

const formatDate = (value: string) => {
  if (!value) return "Latest signal run";
  const date = new Date(`${value}T12:00:00`);
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
};

const uniqueTickers = (...groups: TickerData[][]) => {
  const seen = new Set<string>();
  return groups.flat().filter((ticker) => {
    if (seen.has(ticker.stockName)) return false;
    seen.add(ticker.stockName);
    return true;
  });
};

const signalLabel = (ticker: TickerData) => {
  if (ticker.tradeGatePassed || ticker.tradeAction === "candidate") return "Candidate";
  if (ticker.riskLevel === "high" || ticker.riskLevel === "extreme") return "High risk";
  if (ticker.threadradarTradeStatus === "avoid" || ticker.tradeAction === "avoid") {
    return "Avoid";
  }
  return "Watch";
};

const sentimentLabel = (sentiment: number) => {
  if (sentiment >= 0.2) return "Bullish";
  if (sentiment <= -0.2) return "Bearish";
  return "Neutral";
};

const sentimentTone = (sentiment: number) => {
  if (sentiment >= 0.2) return "positive";
  if (sentiment <= -0.2) return "negative";
  return "neutral";
};

const signalTone = (ticker: TickerData) => {
  const label = signalLabel(ticker);
  if (label === "Candidate") return "candidate";
  if (label === "Avoid" || label === "High risk") return "avoid";
  return "watch";
};

export default function Dashboard() {
  const navigate = useNavigate();
  const [dashboard, setDashboard] = useState<DashboardData>(EMPTY_DASHBOARD);
  const [activeTab, setActiveTab] = useState<DashboardTab>("all");
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [sortKey, setSortKey] = useState<SortKey>("radar");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();

    fetch(API_URL, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Dashboard API returned ${response.status}`);
        return response.json();
      })
      .then((payload: unknown) => {
        const mapped = mapDashboardData(payload);
        setDashboard(mapped);
        const firstTicker =
          mapped.bestTradeCandidates[0]?.stockName ?? mapped.radarWatchlist[0]?.stockName;
        if (firstTicker) setExpanded(new Set([firstTicker]));
      })
      .catch((fetchError: unknown) => {
        if (fetchError instanceof DOMException && fetchError.name === "AbortError") return;
        setError(fetchError instanceof Error ? fetchError.message : "Unable to load signals");
      })
      .finally(() => setLoading(false));

    return () => controller.abort();
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

  const tabs = useMemo(
    () => [
      { id: "trade" as const, label: "Trade Candidates", count: dashboard.bestTradeCandidates.length },
      { id: "radar" as const, label: "Radar", count: dashboard.radarWatchlist.length },
      { id: "risk" as const, label: "High Risk", count: dashboard.avoidHighRisk.length },
      { id: "all" as const, label: "All", count: allTickers.length },
    ],
    [allTickers.length, dashboard],
  );

  const displayedTickers = useMemo(() => {
    const source =
      activeTab === "trade"
        ? dashboard.bestTradeCandidates
        : activeTab === "radar"
          ? dashboard.radarWatchlist
          : activeTab === "risk"
            ? dashboard.avoidHighRisk
            : allTickers;

    const query = search.trim().toLowerCase();
    const filtered = query
      ? source.filter((ticker) =>
          [
            ticker.stockName,
            ticker.name,
            ticker.shortName,
            ticker.sector,
            ticker.industry,
            ticker.setupType,
            ticker.catalystType,
          ].some((value) => value.toLowerCase().includes(query)),
        )
      : source;

    const direction = sortDirection === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      if (sortKey === "ticker") return a.stockName.localeCompare(b.stockName) * direction;
      const values = {
        price: [a.price, b.price],
        mentions: [a.mentions, b.mentions],
        sentiment: [a.averageSentiment, b.averageSentiment],
        radar: [a.radarScore, b.radarScore],
      };
      const [left, right] = values[sortKey];
      return (left - right) * direction;
    });
  }, [activeTab, allTickers, dashboard, search, sortDirection, sortKey]);

  const topRadar = [...allTickers].sort((a, b) => b.radarScore - a.radarScore)[0];
  const mostMentioned = [...allTickers].sort((a, b) => b.mentions - a.mentions)[0];
  const avgSentiment =
    allTickers.length > 0
      ? allTickers.reduce((sum, ticker) => sum + ticker.averageSentiment, 0) /
        allTickers.length
      : 0;
  const bullishCount = allTickers.filter((ticker) => ticker.averageSentiment >= 0.2).length;
  const bearishCount = allTickers.filter((ticker) => ticker.averageSentiment <= -0.2).length;

  const changeSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    setSortDirection(key === "ticker" ? "asc" : "desc");
  };

  const toggleExpanded = (ticker: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(ticker)) next.delete(ticker);
      else next.add(ticker);
      return next;
    });
  };

  return (
    <main className="signar-dashboard">
      <header className="signar-header">
        <div className="brand-lockup" aria-label="Signar">
          <div className="brand-mark">
            <Radar size={25} strokeWidth={2.1} />
            <span className="brand-pulse" />
          </div>
          <div>
            <strong>Signar</strong>
            <span>ThreadRadar intelligence</span>
          </div>
        </div>

        <label className="ticker-search">
          <Search size={19} />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search tickers, companies, sectors, or setups"
          />
          {search && <kbd>{displayedTickers.length} found</kbd>}
        </label>

        <div className="run-status">
          <span>
            {formatDate(dashboard.runDate)} · {allTickers.length} tracked
          </span>
          <strong className={`market-pill ${dashboard.marketSession}`}>
            <span />
            Market {dashboard.marketSession}
          </strong>
        </div>
      </header>

      <div className="dashboard-canvas">
        <section className="paper-strip" aria-label="Demo paper trading portfolio">
          <div className="paper-title">
            <span className="paper-accent" />
            <WalletCards size={20} />
            <div>
              <span>Demo paper trading</span>
              <strong>Portfolio</strong>
            </div>
          </div>
          <PaperMetric label="Total capital" value={money(PAPER_PORTFOLIO.totalCapital)} />
          <PaperMetric
            label="Cash available"
            value={money(PAPER_PORTFOLIO.cashAvailable)}
            detail="72% free"
          />
          <PaperMetric
            label="Invested"
            value={money(PAPER_PORTFOLIO.invested)}
            detail="3 positions"
          />
          <PaperMetric
            label="Total P&L"
            value={money(PAPER_PORTFOLIO.totalPnl)}
            detail="+3.42%"
            positive
          />
          <PaperMetric
            label="Today's P&L"
            value={money(PAPER_PORTFOLIO.todayPnl)}
            detail="+0.84%"
            positive
          />
          <div className="open-positions">
            <span>Open positions</span>
            <div>
              {PAPER_PORTFOLIO.positions.map((position) => (
                <strong key={position.ticker}>
                  {position.ticker}
                  <small>+{position.change}%</small>
                </strong>
              ))}
            </div>
          </div>
        </section>

        <section className="summary-grid" aria-label="Signal summary">
          <SummaryCard
            icon={<Activity size={18} />}
            label="Tickers tracked"
            value={String(allTickers.length)}
            detail={`${dashboard.radarWatchlist.length} radar · ${dashboard.avoidHighRisk.length} high-risk`}
          />
          <SummaryCard
            icon={<BarChart3 size={18} />}
            label="Top radar score"
            value={topRadar ? topRadar.radarScore.toFixed(3) : "—"}
            detail={topRadar ? `${topRadar.stockName} · best signal today` : "No active signal"}
          />
          <SummaryCard
            icon={<Users size={18} />}
            label="Most mentioned"
            value={mostMentioned?.stockName ?? "—"}
            detail={
              mostMentioned ? `${mostMentioned.mentions.toFixed(1)} weighted mentions` : "No mentions"
            }
          />
          <SummaryCard
            icon={<TrendingUp size={18} />}
            label="Avg sentiment"
            value={avgSentiment.toFixed(2)}
            detail={`${bullishCount} bullish · ${bearishCount} bearish`}
          />
        </section>

        <section className="signal-section">
          <div className="signal-toolbar">
            <div className="signal-tabs" role="tablist" aria-label="Signal cohorts">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  className={activeTab === tab.id ? "active" : ""}
                  onClick={() => setActiveTab(tab.id)}
                  role="tab"
                  aria-selected={activeTab === tab.id}
                >
                  {tab.label} <span>{tab.count}</span>
                </button>
              ))}
            </div>
            <span className="table-hint">Select a row to inspect the signal</span>
          </div>

          <div className="signal-table-shell">
            <div className="signal-table-header">
              <span>#</span>
              <SortButton label="Ticker" sortKey="ticker" activeKey={sortKey} onSort={changeSort} />
              <span>Company</span>
              <SortButton label="Price" sortKey="price" activeKey={sortKey} onSort={changeSort} />
              <SortButton
                label="Mentions"
                sortKey="mentions"
                activeKey={sortKey}
                onSort={changeSort}
              />
              <SortButton
                label="Sentiment"
                sortKey="sentiment"
                activeKey={sortKey}
                onSort={changeSort}
              />
              <SortButton
                label="Radar score"
                sortKey="radar"
                activeKey={sortKey}
                onSort={changeSort}
              />
              <span>Signal</span>
              <span />
            </div>

            {loading && (
              <div className="dashboard-message">
                <Radar className="spin-slow" size={27} />
                Loading the latest ThreadRadar signals…
              </div>
            )}
            {!loading && error && (
              <div className="dashboard-message error">
                <ShieldAlert size={25} />
                <div>
                  <strong>Could not load the dashboard</strong>
                  <span>{error}</span>
                </div>
              </div>
            )}
            {!loading && !error && displayedTickers.length === 0 && (
              <div className="dashboard-message">
                <Search size={25} />
                No signals match this view.
              </div>
            )}

            {!loading &&
              !error &&
              displayedTickers.map((ticker, index) => (
                <SignalRow
                  key={ticker.stockName}
                  ticker={ticker}
                  rank={index + 1}
                  open={expanded.has(ticker.stockName)}
                  onToggle={() => toggleExpanded(ticker.stockName)}
                  onView={() =>
                    navigate(PATHS.ticker(ticker.stockName), {
                      state: { ticker },
                    })
                  }
                />
              ))}
          </div>
        </section>
      </div>
    </main>
  );
}

function PaperMetric({
  label,
  value,
  detail,
  positive = false,
}: {
  label: string;
  value: string;
  detail?: string;
  positive?: boolean;
}) {
  return (
    <div className={`paper-metric ${positive ? "positive" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </div>
  );
}

function SummaryCard({
  icon,
  label,
  value,
  detail,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <article className="summary-card">
      <div className="summary-card-label">
        {icon}
        <span>{label}</span>
      </div>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}

function SortButton({
  label,
  sortKey,
  activeKey,
  onSort,
}: {
  label: string;
  sortKey: SortKey;
  activeKey: SortKey;
  onSort: (key: SortKey) => void;
}) {
  return (
    <button
      type="button"
      className={activeKey === sortKey ? "active" : ""}
      onClick={() => onSort(sortKey)}
    >
      {label}
      <ChevronDown size={13} />
    </button>
  );
}

function SignalRow({
  ticker,
  rank,
  open,
  onToggle,
  onView,
}: {
  ticker: TickerData;
  rank: number;
  open: boolean;
  onToggle: () => void;
  onView: () => void;
}) {
  const sentiment = sentimentTone(ticker.averageSentiment);
  const tone = signalTone(ticker);
  const positiveReasons = ticker.rankingReason.positive;
  const negativeReasons =
    ticker.rankingReason.negative.length > 0 ? ticker.rankingReason.negative : ticker.failedReasons;
  const primaryContext = ticker.topContexts[0];
  const scoreWidth = `${Math.min(100, Math.max(4, ticker.radarScore * 100))}%`;

  return (
    <article className={`signal-row ${open ? "expanded" : ""}`}>
      <button
        type="button"
        className="signal-row-summary"
        onClick={onToggle}
        aria-expanded={open}
      >
        <span className="rank">{rank}</span>
        <span className="ticker-cell">
          <CompanyLogo
            ticker={ticker.stockName}
            companyName={ticker.name}
            logoUrl={ticker.logoUrl}
            fallbackUrl={ticker.logoFallback}
          />
          <strong>{ticker.stockName}</strong>
        </span>
        <span className="company-cell">
          <strong>{ticker.name || ticker.shortName || "Unknown company"}</strong>
          <small>{[ticker.sector, ticker.industry].filter(Boolean).join(" · ") || ticker.setupType}</small>
        </span>
        <span className="price-cell">
          <strong>{money(ticker.price)}</strong>
          <small className={ticker.changePercent >= 0 ? "gain" : "loss"}>
            {ticker.changePercent >= 0 ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
            {Math.abs(ticker.changePercent).toFixed(1)}%
          </small>
        </span>
        <span className="mentions-cell">
          <strong>{ticker.mentions.toFixed(1)}</strong>
          <small>
            <span style={{ width: `${Math.min(100, ticker.mentions * 2.5)}%` }} />
          </small>
        </span>
        <span className={`sentiment-pill ${sentiment}`}>
          {sentimentLabel(ticker.averageSentiment)}
          <small>{ticker.averageSentiment.toFixed(2)}</small>
        </span>
        <span className="score-cell">
          <strong>{ticker.radarScore.toFixed(3)}</strong>
          <small>
            <span style={{ width: scoreWidth }} />
          </small>
        </span>
        <span className={`signal-pill ${tone}`}>{signalLabel(ticker)}</span>
        <ChevronDown className="row-chevron" size={18} />
      </button>

      {open && (
        <div className="signal-row-details">
          <div className="reddit-signal">
            <div className="detail-heading">
              <Sparkles size={15} />
              Top Reddit signal
            </div>
            <blockquote>
              “{primaryContext?.text || ticker.catalystReasoning || ticker.tradeReason}”
            </blockquote>
            <div className="subreddit-list">
              {Object.keys(ticker.subredditMentions).map((subreddit) => (
                <span key={subreddit}>r/{subreddit}</span>
              ))}
            </div>
          </div>

          <div className="signal-analysis">
            <div className="detail-heading">
              <BarChart3 size={15} />
              Signal analysis
            </div>
            <div className="reason-columns">
              <ReasonList title="Positives" tone="positive" reasons={positiveReasons} />
              <ReasonList title="Concerns" tone="negative" reasons={negativeReasons} />
            </div>
            <div className="signal-facts">
              <span>
                Risk: <strong className={`risk-${ticker.riskLevel}`}>{ticker.riskLevel}</strong>{" "}
                ({ticker.riskScore.toFixed(1)})
              </span>
              <span>
                Velocity: <strong>{ticker.mentionVelocityLabel || "unknown"}</strong>
              </span>
              <span>
                Authors: <strong>{ticker.uniqueAuthors}</strong>
              </span>
              <span>
                Volume: <strong>{compactNumber(ticker.volume)}</strong>
              </span>
            </div>
            <button type="button" className="view-signal" onClick={onView}>
              Open signal details <ExternalLink size={14} />
            </button>
          </div>
        </div>
      )}
    </article>
  );
}

function ReasonList({
  title,
  tone,
  reasons,
}: {
  title: string;
  tone: "positive" | "negative";
  reasons: string[];
}) {
  return (
    <div className={`reason-list ${tone}`}>
      <strong>{tone === "positive" ? "✓" : "×"} {title}</strong>
      {reasons.slice(0, 4).map((reason) => (
        <span key={reason}>· {reason.replaceAll("_", " ")}</span>
      ))}
      {reasons.length === 0 && <span>· none flagged</span>}
    </div>
  );
}
