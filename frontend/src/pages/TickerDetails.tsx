import { useLocation, useNavigate, useParams } from "react-router-dom";
import type { TickerData } from "../types/Dashboard";
import { PATHS } from "../routes/paths";
import "../styles/TickerDetails.css";

export default function TickerDetails() {
  const { symbol } = useParams();
  const { state } = useLocation();
  const ticker: TickerData = state?.ticker;
  const navigate = useNavigate();

  if (!ticker) {
    navigate(PATHS.dashboard);
  }

  console.log(ticker);

  return (
    <>
      <div className="ticker-main-details-container">
        <div className="ticker-main-details">
          <img
            src={ticker.logoUrl}
            alt={ticker.stockName}
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
    </>
  );
}
