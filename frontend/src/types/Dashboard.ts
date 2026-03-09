export interface TickerData {
  stockName: string;
  mentions: number;
  averageSentiment: number;
  finalScore: number;
  topContexts: TopContext[];
  price: number;
  changePercent: number;
  marketCap: number;
  fiftyTwoWeekHigh: number;
  fiftyTwoWeekLow: number;
  volume: number;
  analystTarget: number;
  recommendation: string;
  sector: string;
  description: string;
  name: string;
  symbol: string;
  shortName: string;
  industry: string;
  website: string;
  logoUrl: string;
  exchange: string;
  currency: string;
  country: string;
  city: string;
  state: string;
  zip: string;
  phone: string;
  email: string;
  ceo: string;
  founded: number;
  employees: number;
  tags: string[];
  similar: string[];
  related: string[];
  stats: any;
  financials: any;
  news: any;
  events: any;
  earnings: any;
  dividends: any;
  splits: any;
  stockSplits: any;
  stockDividends: any;
  logoFallback: string;
}

export interface TopContext {
  text: string;
  sentiment: number;
  score: number;
}
