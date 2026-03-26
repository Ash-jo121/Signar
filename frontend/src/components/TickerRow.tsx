import type { TickerData } from "../types/Dashboard";

export default function TickerRow({ tickerData }: { tickerData: TickerData }) {
  return (
    <tr>
      <td>{tickerData.stockName}</td>
      <td>{tickerData.price}</td>
      <td>{tickerData.mentions}</td>
      <td>{tickerData.averageSentiment}</td>
      <td>{tickerData.finalScore}</td>
    </tr>
  );
}
