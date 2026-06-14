import type { DashboardData, MarketState, TickerData } from "@/types/Dashboard";
import { Radar, Search } from "lucide-react";
import { useState } from "react";

const formatDate = (value: string) => {
  if (!value) return "Latest signal run";
  const date = new Date(`${value}T12:00:00`);
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
};

export default function Header({
  dashboard,
  allTickers,
  liveMarketState,
}: {
  dashboard: DashboardData;
  allTickers: TickerData[];
  liveMarketState: MarketState;
}) {
  const [search, setSearch] = useState("");

  return (
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
        {/* {search && <kbd>{displayedTickers.length} found</kbd>} */}
      </label>

      <div className="run-status">
        <span>
          {formatDate(dashboard.runDate)} · {allTickers.length} tracked
        </span>
        <strong
          className={`market-pill ${liveMarketState}`}
          title="Live U.S. regular market hours, 9:30 AM–4:00 PM ET"
        >
          <span />
          Market {liveMarketState}
        </strong>
      </div>
    </header>
  );
}
