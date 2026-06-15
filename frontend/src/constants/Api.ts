export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ||
  (import.meta.env.DEV
    ? "http://localhost:8000"
    : "https://signar-production.up.railway.app")
).replace(/\/$/, "");

export const TICKERS_API_URL = `${API_BASE_URL}/api/tickers`;
