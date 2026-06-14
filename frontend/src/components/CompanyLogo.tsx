import { useState } from "react";
import { Building2 } from "lucide-react";
import "../styles/CompanyLogo.css";

interface CompanyLogoProps {
  ticker: string;
  companyName?: string;
  logoUrl?: string;
  fallbackUrl?: string;
  size?: "small" | "large";
}

export default function CompanyLogo({
  ticker,
  companyName,
  logoUrl,
  fallbackUrl,
  size = "small",
}: CompanyLogoProps) {
  const sources = [logoUrl, fallbackUrl].filter(
    (source, index, all): source is string =>
      Boolean(source) && all.indexOf(source) === index,
  );
  const [sourceIndex, setSourceIndex] = useState(0);

  const source = sources[sourceIndex];
  const initials = ticker.trim().slice(0, 2).toUpperCase() || "?";
  const label = companyName || ticker || "Company";

  return (
    <span className={`company-logo company-logo-${size}`} aria-label={`${label} logo`}>
      {source ? (
        <img
          src={source}
          alt=""
          onError={() => setSourceIndex((current) => current + 1)}
        />
      ) : (
        <span className="company-logo-default" aria-hidden="true">
          <Building2 />
          <strong>{initials}</strong>
        </span>
      )}
    </span>
  );
}
