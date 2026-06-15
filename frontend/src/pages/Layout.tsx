import { Outlet } from "react-router-dom";
import Header from "@/components/Header";
import { DashboardProvider } from "@/contexts/DashboardContext";
import "../styles/Layout.css";

export default function Layout() {
  return (
    <DashboardProvider>
      <Header />
      <Outlet />
    </DashboardProvider>
  );
}
