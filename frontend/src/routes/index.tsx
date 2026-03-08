import { createBrowserRouter } from "react-router-dom";
import TickerDetails from "../pages/TickerDetails";
import NotFound from "../pages/NotFound";
import Dashboard from "../pages/Dashboard";
import Layout from "../pages/Layout";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: "ticker/:symbol", element: <TickerDetails /> },
    ],
  },
  {
    path: "*",
    element: <NotFound />,
  },
]);
