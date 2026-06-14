import { useLocation, useNavigate } from "react-router-dom";
import type { TickerData } from "../types/Dashboard";
import { PATHS } from "../routes/paths";
import "../styles/TickerDetails.css";
import CommentCard from "../components/CommentCard";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../components/ui/tabs";
import StatCard from "../components/StatCard";

export default function TickerDetails() {
  const { state } = useLocation();
  const ticker: TickerData = state?.ticker;
  const navigate = useNavigate();

  if (!ticker) {
    navigate(PATHS.dashboard);
  }

  return (
    <>
      <div className="ticker-details-container">
        <div className="ticker-main-details-container">
          <div className="ticker-main-details">
            <img
              src={ticker.logoUrl}
              alt={ticker.logoFallback}
              onError={(e) => {
                if (ticker.logoFallback) {
                  e.currentTarget.src = ticker.logoFallback;
                } else {
                  e.currentTarget.style.display = "none";
                }
              }}
              width={100}
              height={100}
              className="ticker-logo"
            />
          </div>
          <div className="ticker-heading">
            <h1 className="text-2xl font-bold">{ticker.stockName}</h1>
            <p className="text-sm text-slate-500">{ticker.name}</p>
          </div>
          <div className="ticker-price">
            <h1 className="text-2xl font-bold">${ticker.price}</h1>
            <h2 className="scroll-m-20 text-center text-lg font-semibold tracking-tight">
              <span
                className={
                  ticker.changePercent >= 0 ? "text-green-500" : "text-red-500"
                }
              >
                {ticker.changePercent >= 0 ? "▲" : "▼"}{" "}
                {Math.abs(ticker.changePercent)}%
              </span>
            </h2>
          </div>
        </div>
        <div className="ticker-description">{ticker.description}</div>
        <Tabs
          defaultValue="sentiment"
          className="w-full flex flex-col justify-center my-6"
        >
          <TabsList>
            <TabsTrigger value="sentiment">Sentiment</TabsTrigger>
            <TabsTrigger value="news">News</TabsTrigger>
            <TabsTrigger value="company">Stock Details</TabsTrigger>
            <TabsTrigger value="financials">Financials</TabsTrigger>
          </TabsList>
          <TabsContent value="sentiment" className="w-full">
            <SentimentTab ticker={ticker} />
          </TabsContent>
          <TabsContent value="news">
            <div>This is the news tab</div>
          </TabsContent>
          <TabsContent value="company">
            <StockDetailsTab ticker={ticker} />
          </TabsContent>
          <TabsContent value="financials">
            <FinancialsTab ticker={ticker} />
          </TabsContent>
        </Tabs>
      </div>
    </>
  );
}

const SentimentTab = ({ ticker }: { ticker: TickerData }) => {
  return (
    <div className="ticker-sentiment-container-wrapper">
      <div className="ticker-sentiment-details">
        <StatCard label="Mentions" value={ticker.mentions} />
        <StatCard label="Avg Sentiment" value={ticker.averageSentiment} />
        <StatCard label="Final Score" value={ticker.finalScore} />
      </div>
      <div className="ticker-sentiment-contexts">
        <div className="comment-grid">
          {ticker.topContexts.map((context) => (
            <CommentCard
              key={context.text}
              comment={context.text}
              score={context.score}
              sentiment={context.sentiment}
            />
          ))}
        </div>
      </div>
    </div>
  );
};

const StockDetailsTab = ({ ticker }: { ticker: TickerData }) => {
  return (
    <div className="ticker-stock-details-container">
      <StatCard label="Name" value={ticker.name} />
      <StatCard label="Symbol" value={ticker.symbol} />
      <StatCard label="Industry" value={ticker.industry} />
      <StatCard label="Sector" value={ticker.sector} />
      <StatCard label="Country" value={ticker.country} />
      <StatCard label="City" value={`${ticker.city}, ${ticker.state}`} />
      <StatCard label="Exchange" value={ticker.exchange} />
      {ticker.website && (
        <StatCard
          label="Website"
          value={
            <a
              href={ticker.website}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-500 hover:underline text-sm"
            >
              {ticker.website.replace("https://", "")}
            </a>
          }
        />
      )}
    </div>
  );
};

const FinancialsTab = ({ ticker }: { ticker: TickerData }) => {
  const formatNumber = (num: number) => {
    if (num >= 1_000_000_000) return `$${(num / 1_000_000_000).toFixed(2)}B`;
    if (num >= 1_000_000) return `$${(num / 1_000_000).toFixed(2)}M`;
    if (num >= 1_000) return `${(num / 1_000).toFixed(1)}K`;
    return num.toString();
  };

  return (
    <div className="ticker-financials-container">
      <StatCard label="Price" value={`$${ticker.price}`} />
      <StatCard
        label="Change"
        value={
          <span
            className={
              ticker.changePercent >= 0 ? "text-green-500" : "text-red-500"
            }
          >
            {ticker.changePercent >= 0 ? "▲" : "▼"}{" "}
            {Math.abs(ticker.changePercent)}%
          </span>
        }
      />
      <StatCard label="Market Cap" value={formatNumber(ticker.marketCap)} />
      <StatCard label="Volume" value={formatNumber(ticker.volume)} />
      <StatCard label="52W High" value={`$${ticker.fiftyTwoWeekHigh}`} />
      <StatCard label="52W Low" value={`$${ticker.fiftyTwoWeekLow}`} />
      {ticker.analystTarget > 0 && (
        <StatCard label="Analyst Target" value={`$${ticker.analystTarget}`} />
      )}
      {ticker.analystRecommendation !== "none" && (
        <StatCard
          label="Analyst Recommendation"
          value={ticker.analystRecommendation.toUpperCase()}
        />
      )}
      <StatCard label="Exchange" value={ticker.exchange} />
      <StatCard label="Currency" value={ticker.currency} />
    </div>
  );
};
