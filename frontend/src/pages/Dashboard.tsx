import { useEffect, useState } from "react";
import type { TickerData } from "../types/Dashboard";
import "../styles/Dashboard.css";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../components/ui/table";
import { dashboardMapper } from "../helpers/DashboardMapper";
import { PATHS } from "../routes/paths";
import { useNavigate } from "react-router-dom";

const API_URL = "http://localhost:8000/api/tickers";

export default function Dashboard() {
  const navigate = useNavigate();
  const [tickerData, setTickerData] = useState<TickerData[]>([]);
  const fetchData = async () => {
    const response = await fetch(API_URL);
    const data = await response.json();
    setTickerData(dashboardMapper(data));
  };

  useEffect(() => {
    fetchData();
  }, []);

  return (
    <div className="main-dashboard">
      <h1 className="scroll-m-20 text-center text-4xl font-extrabold tracking-tight text-balance">
        Welcome to ThreadRadar
      </h1>
      <h2 className="scroll-m-20 text-2xl font-semibold tracking-tight">
        Top 10 penny stocks
      </h2>
      <Table>
        <TableCaption>A list of all top stock picks</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[100px]">Stock</TableHead>
            <TableHead className="w-[300px]">Name</TableHead>
            <TableHead className="w-[100px]">Price ($)</TableHead>
            <TableHead className="w-[100px]">Mentions</TableHead>
            <TableHead className="w-[200px]">Average Sentiment</TableHead>
            <TableHead className="w-[100px]">Final Score</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {tickerData.map((item) => (
            <TableRow
              key={item.stockName}
              className="cursor-pointer"
              onClick={() =>
                navigate(PATHS.ticker(item.stockName), {
                  state: { ticker: item },
                })
              }
            >
              <TableCell className="font-medium">{item.stockName}</TableCell>
              <TableCell>
                {item.name === "" ? item.shortName : item.name}
              </TableCell>
              <TableCell>{item.price}</TableCell>
              <TableCell>{item.mentions}</TableCell>
              <TableCell>{item.averageSentiment}</TableCell>
              <TableCell>{item.finalScore}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
