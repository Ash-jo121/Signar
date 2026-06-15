import { Radar, Search } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { useDashboardContext } from "@/contexts/useDashboardContext";
import { PATHS } from "@/routes/paths";

const formatDate = (value: string) => {
  if (!value) return "Latest signal run";
  const date = new Date(`${value}T12:00:00`);
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
};

export default function Header() {
  const { dashboard, allTickers, liveMarketState, search, setSearch } =
    useDashboardContext();
  const location = useLocation();
  const navigate = useNavigate();

  const updateSearch = (value: string) => {
    setSearch(value);
    if (location.pathname !== PATHS.dashboard) navigate(PATHS.dashboard);
  };

  const matchingTickerCount = search
    ? allTickers.filter((ticker) =>
        [ticker.stockName, ticker.name, ticker.shortName, ticker.sector, ticker.industry].some(
          (value) => value.toLowerCase().includes(search.toLowerCase()),
        ),
      ).length
    : allTickers.length;

  return (
    <header className="signar-header">
      <button
        type="button"
        className="brand-lockup"
        aria-label="Go to Signar dashboard"
        onClick={() => navigate(PATHS.dashboard)}
      >
        <span className="brand-mark">
          <Radar size={25} strokeWidth={2.1} />
          <span className="brand-pulse" />
        </span>
        <span>
          <strong>Signar</strong>
          <small>ThreadRadar intelligence</small>
        </span>
      </button>

      <label className="ticker-search">
        <Search size={19} />
        <input
          value={search}
          onChange={(event) => updateSearch(event.target.value)}
          placeholder="Search tickers, companies, sectors, or setups"
        />
        {search && <kbd>{matchingTickerCount} found</kbd>}
      </label>

      <div className="run-status">
        <span>
          {formatDate(dashboard.runDate)} {"\u00b7"} {allTickers.length} tracked
        </span>
        <strong
          className={`market-pill ${liveMarketState}`}
          title="Live U.S. regular market hours, 9:30 AM-4:00 PM ET"
        >
          <span />
          Market {liveMarketState}
        </strong>
      </div>
    </header>
  );
}
