import { useEffect, useState } from "react";
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  BarChart3,
  Building2,
  ExternalLink,
  FileText,
  MessageSquareText,
  Newspaper,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import CompanyLogo from "../components/CompanyLogo";
import { API_BASE_URL } from "@/constants/Api";
import { useDashboardContext } from "@/contexts/useDashboardContext";
import { mapTickerHistory } from "@/helpers/DashboardMapper";
import { PATHS } from "../routes/paths";
import type { Context, TickerData, TickerHistoryPoint } from "../types/Dashboard";
import "../styles/TickerDetails.css";

type DetailTab = "sentiment" | "news" | "company" | "financials";
type MovementMetric = "price" | "sentiment" | "score" | "mentions";

interface Series {
  label: string;
  value: number;
}

interface HistoryResult {
  ticker: string;
  startDate: string;
  history: TickerHistoryPoint[];
  error: string;
}

const money = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: value < 10 ? 2 : 0,
    maximumFractionDigits: value < 10 ? 4 : 0,
  }).format(value);

const compactNumber = (value: number) =>
  new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(value);

const titleCase = (value: string) =>
  value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const signalLabel = (ticker: TickerData) => {
  if (ticker.tradeGatePassed || ticker.tradeAction === "candidate") return "Candidate";
  if (ticker.threadradarTradeStatus === "avoid" || ticker.tradeAction === "avoid") {
    return "Avoid";
  }
  return "Watch";
};

const validSeries = (items: Series[]) =>
  items.filter((item) => Number.isFinite(item.value));

const historySeries = (
  history: TickerHistoryPoint[],
  select: (point: TickerHistoryPoint) => number | null,
) =>
  validSeries(
    history.flatMap((point) => {
      const value = select(point);
      if (value === null) return [];
      return [
        {
          label: new Intl.DateTimeFormat("en-US", {
            month: "short",
            day: "numeric",
            timeZone: "UTC",
          }).format(new Date(`${point.date}T00:00:00Z`)),
          value,
        },
      ];
    }),
  );

export default function TickerDetails() {
  const { state } = useLocation();
  const { symbol } = useParams();
  const { allTickers, loading, dashboard } = useDashboardContext();
  const ticker: TickerData | undefined =
    state?.ticker ?? allTickers.find((item) => item.stockName === symbol?.toUpperCase());
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<DetailTab>("sentiment");
  const [movementMetric, setMovementMetric] = useState<MovementMetric>("price");
  const [historyResult, setHistoryResult] = useState<HistoryResult>({
    ticker: "",
    startDate: "2026-06-10",
    history: [],
    error: "",
  });

  useEffect(() => {
    if (!loading && !ticker) navigate(PATHS.dashboard, { replace: true });
  }, [loading, navigate, ticker]);

  useEffect(() => {
    if (!ticker) return;

    const controller = new AbortController();
    const requestedTicker = ticker.stockName;

    fetch(`${API_BASE_URL}/api/tickers/${requestedTicker}/history?days=30`, {
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error(`History API returned ${response.status}`);
        return response.json();
      })
      .then((payload: unknown) => {
        const mappedHistory = mapTickerHistory(payload);
        setHistoryResult({
          ticker: requestedTicker,
          startDate: mappedHistory.startDate,
          history: mappedHistory.history,
          error: "",
        });
      })
      .catch((fetchError: unknown) => {
        if (fetchError instanceof DOMException && fetchError.name === "AbortError") return;
        setHistoryResult({
          ticker: requestedTicker,
          startDate: "2026-06-10",
          history: [],
          error:
            fetchError instanceof Error && fetchError.message.includes("404")
              ? "History API is not deployed on Railway yet"
              : fetchError instanceof Error
                ? fetchError.message
                : "History unavailable",
        });
      });

    return () => controller.abort();
  }, [ticker]);

  const tickerSymbol = ticker?.stockName ?? "";
  const history = historyResult.ticker === tickerSymbol ? historyResult.history : [];
  const historyError =
    historyResult.ticker === tickerSymbol ? historyResult.error : "";
  const historyLoading = Boolean(tickerSymbol && historyResult.ticker !== tickerSymbol);
  const historyEmptyMessage = historyLoading
    ? "Loading history"
    : historyError || "No analysis recorded since Jun 10";

  const movementSeries = {
    price: historySeries(history, (point) => point.price),
    sentiment: historySeries(history, (point) => point.averageSentiment),
    score: historySeries(history, (point) => point.finalScore),
    mentions: historySeries(history, (point) => point.mentions),
  };

  if (!ticker) return null;

  const activeSeries = movementSeries[movementMetric];
  const metricCards: {
    id: MovementMetric;
    label: string;
    value: string;
    color: string;
  }[] = [
    { id: "price", label: "Price", value: money(ticker.price), color: "#0aa4e5" },
    {
      id: "sentiment",
      label: "Avg sentiment",
      value: ticker.averageSentiment.toFixed(3),
      color: "#16a554",
    },
    { id: "score", label: "Final score", value: ticker.finalScore.toFixed(3), color: "#dd8600" },
    { id: "mentions", label: "Mentions", value: ticker.mentions.toFixed(1), color: "#4b93c4" },
  ];

  return (
    <main className="ticker-detail-page">
      <div className="ticker-detail-canvas">
        <nav className="ticker-breadcrumb" aria-label="Breadcrumb">
          <button type="button" onClick={() => navigate(PATHS.dashboard)}>
            <ArrowLeft size={14} /> Signal feed
          </button>
          <span>/</span>
          <span>Ticker detail</span>
          <span>/</span>
          <strong>{ticker.stockName}</strong>
        </nav>

        <section className="ticker-hero">
          <div className="ticker-identity">
            <CompanyLogo
              ticker={ticker.stockName}
              companyName={ticker.name}
              logoUrl={ticker.logoUrl}
              fallbackUrl={ticker.logoFallback}
              size="large"
            />
            <div>
              <div className="ticker-symbol-line">
                <h1>{ticker.stockName}</h1>
                <span>{ticker.exchange}</span>
              </div>
              <h2>{ticker.name || ticker.shortName}</h2>
              <p>{[ticker.sector, ticker.industry].filter(Boolean).join(" / ")}</p>
            </div>
          </div>

          <div className="ticker-live-price">
            <strong>{money(ticker.price)}</strong>
            <span className={ticker.changePercent >= 0 ? "positive" : "negative"}>
              {ticker.changePercent >= 0 ? <ArrowUp size={17} /> : <ArrowDown size={17} />}
              {Math.abs(ticker.changePercent).toFixed(2)}%
            </span>
          </div>

          <div className="ticker-signal-badges">
            <SignalBadge label="Radar score" value={ticker.radarScore.toFixed(3)} tone="blue" />
            <SignalBadge label="Signal" value={signalLabel(ticker)} tone="blue" />
            <SignalBadge label="Risk" value={ticker.riskLevel} tone={`risk-${ticker.riskLevel}`} />
            <SignalBadge
              label="Velocity"
              value={`${ticker.mentionVelocityLabel || "unknown"} / ${ticker.daysTrending}d`}
              tone="soft"
            />
          </div>
        </section>

        <section className="ticker-about">
          <div className="section-eyebrow">
            <Building2 size={15} /> About {ticker.name || ticker.stockName}
          </div>
          <p>{ticker.description || "No company description is currently available."}</p>
        </section>

        <section className="movement-section">
          <div className="section-heading">
            <div>
              <h2>Signal Movement</h2>
              <p>Daily price and ThreadRadar analysis history since June 10, 2026</p>
            </div>
          </div>

          <div className="movement-card-grid">
            {metricCards.map((metric) => (
              <button
                key={metric.id}
                type="button"
                className={`movement-card ${movementMetric === metric.id ? "active" : ""}`}
                style={{ "--metric-color": metric.color } as React.CSSProperties}
                onClick={() => setMovementMetric(metric.id)}
              >
                <span>{metric.label}</span>
                <strong>{metric.value}</strong>
                <MiniChart
                  series={movementSeries[metric.id]}
                  color={metric.color}
                  emptyMessage={historyEmptyMessage}
                />
                <small>{movementMetric === metric.id ? "showing below" : "select to inspect"}</small>
              </button>
            ))}
          </div>

          <div className="movement-chart-panel">
            <div className="movement-chart-title">
              <span style={{ background: metricCards.find((item) => item.id === movementMetric)?.color }} />
              <strong>{titleCase(movementMetric)}</strong>
              <small>
                {historyLoading
                  ? "Loading history"
                  : historyError || `${activeSeries.at(-1)?.value.toFixed(3) ?? "No"} latest value`}
              </small>
            </div>
            <MainChart
              series={activeSeries}
              color={metricCards.find((item) => item.id === movementMetric)?.color ?? "#0aa4e5"}
              emptyMessage={historyEmptyMessage}
            />
          </div>
        </section>

        <section className="ticker-tabs-section">
          <div className="ticker-tabs" role="tablist">
            {(
              [
                ["sentiment", "Sentiment", MessageSquareText],
                ["news", "News", Newspaper],
                ["company", "Stock Details", Building2],
                ["financials", "Financials", BarChart3],
              ] as const
            ).map(([id, label, Icon]) => (
              <button
                type="button"
                key={id}
                className={activeTab === id ? "active" : ""}
                onClick={() => setActiveTab(id)}
              >
                <Icon size={15} /> {label}
              </button>
            ))}
          </div>

          {activeTab === "sentiment" && <SentimentTab ticker={ticker} />}
          {activeTab === "news" && <NewsTab ticker={ticker} />}
          {activeTab === "company" && <StockDetailsTab ticker={ticker} />}
          {activeTab === "financials" && <FinancialsTab ticker={ticker} />}
        </section>

        <footer className="ticker-footer">
          <span>
            Signar · ThreadRadar · {ticker.scoringVersion || "latest model"} · data as of{" "}
            {dashboard.runDate || ticker.runDate}
          </span>
          <span>Not financial advice. Always DYOR.</span>
        </footer>
      </div>
    </main>
  );
}

function SignalBadge({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: string;
}) {
  return (
    <div className={`ticker-signal-badge ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MiniChart({
  series,
  color,
  emptyMessage,
}: {
  series: Series[];
  color: string;
  emptyMessage: string;
}) {
  const points = chartPoints(series, 160, 48, 4);
  if (series.length === 0) return <div className="mini-chart-empty">{emptyMessage}</div>;
  return (
    <svg className="mini-chart" viewBox="0 0 160 48" aria-hidden="true">
      {series.length > 1 && (
        <polyline points={points} fill="none" stroke={color} strokeWidth="2.5" />
      )}
      {points.split(" ").map((point, index) => {
        const [x, y] = point.split(",");
        return <circle key={`${series[index].label}-${index}`} cx={x} cy={y} r="3" fill={color} />;
      })}
    </svg>
  );
}

function MainChart({
  series,
  color,
  emptyMessage,
}: {
  series: Series[];
  color: string;
  emptyMessage: string;
}) {
  const width = 1000;
  const height = 245;
  const padding = 36;
  const points = chartPoints(series, width, height, padding);

  if (series.length === 0) {
    return <div className="main-chart-empty">{emptyMessage}</div>;
  }

  return (
    <div className="main-chart-wrap">
      <svg className="main-chart" viewBox={`0 0 ${width} ${height}`} role="img">
        {[0.2, 0.5, 0.8].map((position) => (
          <line
            key={position}
            x1={padding}
            x2={width - padding}
            y1={height * position}
            y2={height * position}
            stroke="#dce8f3"
            strokeWidth="1"
          />
        ))}
        {series.length > 1 && <polyline points={points} fill="none" stroke={color} strokeWidth="3" />}
        {points.split(" ").map((point, index) => {
          const [x, y] = point.split(",");
          return <circle key={series[index]?.label} cx={x} cy={y} r="4" fill="#fff" stroke={color} strokeWidth="3" />;
        })}
      </svg>
      <div className="chart-labels">
        {[series[0], series[Math.floor((series.length - 1) / 2)], series.at(-1)].map(
          (item, index) => <span key={`${item?.label}-${index}`}>{item?.label}</span>,
        )}
      </div>
    </div>
  );
}

function chartPoints(series: Series[], width: number, height: number, padding: number) {
  if (series.length === 0) return "";
  const values = series.map((item) => item.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return series
    .map((item, index) => {
      const x =
        series.length === 1
          ? width / 2
          : padding + (index / (series.length - 1)) * (width - padding * 2);
      const y = height - padding - ((item.value - min) / range) * (height - padding * 2);
      return `${x},${y}`;
    })
    .join(" ");
}

function SentimentTab({ ticker }: { ticker: TickerData }) {
  return (
    <div className="tab-content">
      <div className="detail-stat-grid three">
        <DetailStat label="Mentions" value={ticker.mentions.toFixed(1)} tone="blue" />
        <DetailStat label="Avg sentiment" value={ticker.averageSentiment.toFixed(3)} tone="green" />
        <DetailStat label="Trade score" value={ticker.tradeScore.toFixed(3)} tone="orange" />
      </div>

      <div className="mentions-heading">
        <span>
          Top Reddit mentions · {ticker.uniqueAuthors} authors · {ticker.subredditsMentioningTicker} subreddits
        </span>
      </div>
      <div className="reddit-mention-grid">
        {ticker.topContexts.map((context) => (
          <RedditMention key={`${context.author}-${context.text}`} context={context} />
        ))}
      </div>

      <div className="analysis-callout-grid">
        <AnalysisList
          title="Positive signals"
          icon={<Sparkles size={15} />}
          items={ticker.rankingReason.positive}
          tone="positive"
        />
        <AnalysisList
          title="Concerns"
          icon={<ShieldCheck size={15} />}
          items={ticker.rankingReason.negative.length ? ticker.rankingReason.negative : ticker.failedReasons}
          tone="negative"
        />
      </div>
    </div>
  );
}

function RedditMention({ context }: { context: Context }) {
  return (
    <article className={`reddit-mention ${context.sentiment}`}>
      <div>
        <strong>u/{context.author || "unknown"}</strong>
        <span>r/{context.subreddit}</span>
      </div>
      <p>{context.text}</p>
      <footer>
        <span>
          Score <strong>{context.score >= 0 ? "+" : ""}{context.score.toFixed(3)}</strong>
        </span>
        <em>{context.sentiment}</em>
      </footer>
    </article>
  );
}

function AnalysisList({
  title,
  icon,
  items,
  tone,
}: {
  title: string;
  icon: React.ReactNode;
  items: string[];
  tone: "positive" | "negative";
}) {
  return (
    <article className={`analysis-callout ${tone}`}>
      <h3>{icon} {title}</h3>
      {items.slice(0, 5).map((item) => (
        <span key={item}>· {item.replaceAll("_", " ")}</span>
      ))}
      {items.length === 0 && <span>· none flagged</span>}
    </article>
  );
}

function NewsTab({ ticker }: { ticker: TickerData }) {
  const news = ticker.news.filter(
    (item): item is Record<string, unknown> => item !== null && typeof item === "object",
  );

  return (
    <div className="tab-content">
      {news.length === 0 ? (
        <div className="detail-empty-state">
          <Newspaper size={30} />
          <strong>No enriched news items in this signal run</strong>
          <p>Catalyst context from Reddit and verified event analysis remains available below.</p>
          <div className="catalyst-summary">
            <span>{titleCase(ticker.catalystType || "none")}</span>
            <p>{ticker.catalystReasoning || "No catalyst reasoning available."}</p>
          </div>
        </div>
      ) : (
        <div className="news-list">
          {news.map((item, index) => (
            <article key={String(item.uuid ?? item.title ?? index)}>
              <FileText size={18} />
              <div>
                <strong>{String(item.title ?? "Market update")}</strong>
                <span>{String(item.publisher ?? item.source ?? "Source unavailable")}</span>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function StockDetailsTab({ ticker }: { ticker: TickerData }) {
  return (
    <div className="tab-content">
      <div className="detail-stat-grid four">
        <DetailStat label="Name" value={ticker.name || ticker.shortName} />
        <DetailStat label="Symbol" value={ticker.symbol || ticker.stockName} />
        <DetailStat label="Industry" value={ticker.industry || "Unknown"} />
        <DetailStat label="Sector" value={ticker.sector || "Unknown"} />
        <DetailStat label="Country" value={ticker.country || "Unknown"} />
        <DetailStat label="City" value={[ticker.city, ticker.state].filter(Boolean).join(", ") || "Unknown"} />
        <DetailStat label="Exchange" value={ticker.exchange || "Unknown"} />
        <DetailStat
          label="Website"
          value={
            ticker.website ? (
              <a href={ticker.website} target="_blank" rel="noreferrer">
                {ticker.website.replace(/^https?:\/\//, "")} <ExternalLink size={13} />
              </a>
            ) : (
              "Unknown"
            )
          }
        />
      </div>
    </div>
  );
}

function FinancialsTab({ ticker }: { ticker: TickerData }) {
  return (
    <div className="tab-content">
      <div className="detail-stat-grid four">
        <DetailStat label="Price" value={money(ticker.price)} />
        <DetailStat
          label="Change"
          value={`${ticker.changePercent >= 0 ? "▲" : "▼"} ${Math.abs(ticker.changePercent).toFixed(2)}%`}
          tone={ticker.changePercent >= 0 ? "green" : "red"}
        />
        <DetailStat label="Market cap" value={compactNumber(ticker.marketCap)} />
        <DetailStat label="Volume" value={compactNumber(ticker.volume)} />
        <DetailStat label="52W high" value={money(ticker.fiftyTwoWeekHigh)} />
        <DetailStat label="52W low" value={money(ticker.fiftyTwoWeekLow)} />
        <DetailStat
          label="Effective float"
          value={ticker.effectiveFloatShares ? compactNumber(ticker.effectiveFloatShares) : "Unavailable"}
        />
        <DetailStat label="Dollar volume" value={money(ticker.dollarVolume)} />
        <DetailStat label="Relative volume" value={ticker.relativeVolume?.toFixed(2) ?? "Unavailable"} />
        <DetailStat label="Analyst target" value={ticker.analystTarget ? money(ticker.analystTarget) : "Unavailable"} />
        <DetailStat label="Exchange" value={ticker.exchange || "Unknown"} />
        <DetailStat label="Currency" value={ticker.currency || "Unknown"} />
      </div>
    </div>
  );
}

function DetailStat({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: React.ReactNode;
  tone?: string;
}) {
  return (
    <article className={`detail-stat ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}
