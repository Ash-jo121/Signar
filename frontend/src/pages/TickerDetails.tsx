import { useLocation, useNavigate, useParams } from "react-router-dom";
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

export default function TickerDetails() {
  const { symbol } = useParams();
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
            <h1 className="scroll-m-20 text-center text-2xl font-extrabold tracking-tight text-balance">
              {ticker.stockName}
            </h1>
            <h2 className="scroll-m-20 text-center text-lg font-semibold tracking-tight">
              {ticker.name}
            </h2>
          </div>
          <div className="ticker-price">
            <h1 className="scroll-m-20 text-center text-2xl font-extrabold tracking-tight text-balance">
              {ticker.price}$
            </h1>
            <h2 className="scroll-m-20 text-center text-lg font-semibold tracking-tight">
              {ticker.changePercent} %{" "}
              <span className="text-green-500">&#9652;</span>
            </h2>
          </div>
        </div>
        <div className="ticker-description">{ticker.description}</div>
        <Tabs
          defaultValue="sentiment"
          className="w-full flex flex-col justify-center my-20"
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
      <div className="ticker-sentiment-container">Stock Sentiment</div>
      <div className="ticker-sentiment-details">
        <div> Mentions: {ticker.mentions}</div>
        <div> Average Sentiment: {ticker.averageSentiment}</div>
        <div>
          {" "}
          Final Score: <SentimentScore score={ticker.finalScore} />
        </div>
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
      <div>Name: {ticker.name}</div>
      <div>Symbol: {ticker.symbol}</div>
      <div>Industry: {ticker.industry}</div>
      <div>Sector: {ticker.sector}</div>
      <div>Country: {ticker.country}</div>
      <div>
        Website:{" "}
        <a href={ticker.website} target="_blank" rel="noopener noreferrer">
          {ticker.website}
        </a>
      </div>
      <div>City: {ticker.city}</div>
      <div>State: {ticker.state}</div>
      <div>Zip: {ticker.zip}</div>
      <div>Phone: {ticker.phone}</div>
      <div>Email: {ticker.email}</div>
      <div>CEO: {ticker.ceo}</div>
      <div>Founded: {ticker.founded}</div>
      <div>Employees: {ticker.employees}</div>
    </div>
  );
};

const FinancialsTab = ({ ticker }: { ticker: TickerData }) => {
  return (
    <div className="ticker-financials-container">
      <div>Price: {ticker.price}</div>
      <div>Change Percent: {ticker.changePercent}</div>
      <div>Market Cap: {ticker.marketCap}</div>
      <div>52 Week High: {ticker.fiftyTwoWeekHigh}</div>
      <div>52 Week Low: {ticker.fiftyTwoWeekLow}</div>
      <div>Volume: {ticker.volume}</div>
      <div>Analyst Target: {ticker.analystTarget}</div>
      <div>Recommendation: {ticker.recommendation}</div>
      <div>Exchange: {ticker.exchange}</div>
      <div>Currency: {ticker.currency}</div>
    </div>
  );
};

const SentimentScore = ({ score }: { score: number }) => {
  const color = score > 0.1 ? "#22c55e" : score < -0.1 ? "#ef4444" : "#94a3b8";
  return (
    <span style={{ color }}>
      {score > 0 ? "+" : score < 0 ? "-" : ""}
      {score}
    </span>
  );
};
