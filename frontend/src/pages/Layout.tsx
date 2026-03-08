import { Outlet } from "react-router-dom";
import "../styles/Layout.css";

export default function Layout() {
  return (
    <div className="layout-container">
      <Outlet />
    </div>
  );
}
