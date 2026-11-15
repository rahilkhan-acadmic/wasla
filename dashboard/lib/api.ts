// Thin fetch wrappers around the distress-model-api Lambda Function URL.
// NEXT_PUBLIC_API_BASE_URL is baked in at build time (static export has no
// server to read env vars at request time) -- set it when running `next build`,
// e.g. NEXT_PUBLIC_API_BASE_URL=https://xxxx.lambda-url.ap-south-1.on.aws npm run build

import { getIdToken } from "./auth";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export interface Financials {
  total_assets: number;
  total_liabilities: number;
  current_assets: number;
  current_liabilities: number;
  retained_earnings: number;
  ebit: number;
  sales: number;
  market_value_equity?: number;
  book_value_equity?: number;
}

export interface PredictRequest {
  ticker: string;
  financials: Financials;
  headlines: string[];
}

export interface PredictResponse {
  ticker: string;
  probability_distressed: number;
  z_score: number;
  z_score_zone: string;
  z_double_prime: number;
  z_double_prime_zone: string;
  news_sentiment: number;
  cash_burning: boolean;
}

export interface ModelInfoResponse {
  registry_configured: boolean;
  version: string | null;
  promoted_at: string | null;
  s3_key: string | null;
}

export interface HealthResponse {
  status: string;
  model_version: string | null;
  registry_configured: boolean;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const idToken = getIdToken();
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "content-type": "application/json",
      ...(idToken ? { authorization: `Bearer ${idToken}` } : {}),
    },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`${path} failed: ${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

export function predict(body: PredictRequest): Promise<PredictResponse> {
  return request<PredictResponse>("/predict", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function predictDemo(ticker: string): Promise<PredictResponse> {
  return request<PredictResponse>(`/predict/demo/${encodeURIComponent(ticker)}`, {
    method: "POST",
  });
}

export function getModelInfo(): Promise<ModelInfoResponse> {
  return request<ModelInfoResponse>("/model/info");
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

// --- Market data (index snapshots + custom-ticker lookup) ---

/** nse = Nifty LargeMidcap 250, us = S&P 500 (see src/market_data.py). */
export type Universe = "nse" | "us";

export const UNIVERSES: { id: Universe; label: string; short: string }[] = [
  { id: "nse", label: "NSE · Nifty LargeMidcap 250", short: "NSE 250" },
  { id: "us", label: "US · S&P 500", short: "S&P 500" },
];

export function isUniverse(x: string | null | undefined): x is Universe {
  return x === "nse" || x === "us";
}

function universeQuery(u: Universe | undefined, sep: "?" | "&" = "?"): string {
  return u && u !== "nse" ? `${sep}universe=${u}` : "";
}

export interface CompanySummary {
  symbol: string;
  name: string;
  industry: string | null;
  has_financials: boolean;
  as_of: string | null;
}

export interface CompaniesResponse {
  index: string;
  available: boolean;
  generated_at: string | null;
  data_source: string | null;
  companies: CompanySummary[];
}

export interface CompanyFinancials {
  symbol: string;
  yahoo_ticker: string;
  name: string;
  industry: string | null;
  as_of: string | null;
  currency: string | null;
  source: "snapshot" | "live";
  fetched_at: string | null;
  financials: Partial<Record<keyof Financials, number | null>>;
  missing: string[];
  complete: boolean;
  note?: string | null;
}

export interface LookupResponse {
  query: string;
  found: boolean;
  in_index: boolean;
  company: CompanyFinancials | null;
}

export function getCompanies(universe?: Universe): Promise<CompaniesResponse> {
  return request<CompaniesResponse>(`/companies${universeQuery(universe)}`);
}

export function getCompany(symbol: string, universe?: Universe): Promise<CompanyFinancials> {
  return request<CompanyFinancials>(`/companies/${encodeURIComponent(symbol)}${universeQuery(universe)}`);
}

export function lookupTicker(ticker: string): Promise<LookupResponse> {
  return request<LookupResponse>(`/lookup/${encodeURIComponent(ticker)}`);
}

// --- Market overview (all constituents scored with the current model) ---

export type RiskBand = "low" | "moderate" | "high";

export interface OverviewCompany {
  symbol: string;
  name: string;
  industry: string | null;
  as_of: string | null;
  probability_distressed: number;
  band: RiskBand;
  z_score: number;
  z_score_zone: string;
  z_double_prime: number;
  z_double_prime_zone: string;
  loss_making: boolean;
}

export interface UnscoredCompany {
  symbol: string;
  name: string;
  industry: string | null;
  category: "not_applicable" | "missing_data" | "error";
  reason: string;
}

export interface MarketOverviewResponse {
  index: string;
  universe: Universe;
  available: boolean;
  snapshot_generated_at: string | null;
  model_version: string | null;
  thresholds: { moderate: number; high: number };
  total: number;
  scored: number;
  bands: Record<RiskBand, number>;
  loss_making: number;
  ebit_known: number;
  companies: OverviewCompany[];
  unscored: UnscoredCompany[];
}

export function getMarketOverview(universe: Universe = "nse"): Promise<MarketOverviewResponse> {
  return request<MarketOverviewResponse>(`/market/overview${universeQuery(universe)}`);
}

// --- Manual market-data refresh ---

export type RefreshState = "idle" | "running" | "done" | "failed" | "stale";

export interface RefreshStatus {
  universe: Universe;
  index: string;
  state: RefreshState;
  trigger: string | null;
  started_at: string | null;
  finished_at: string | null;
  progress: string | null;
  error: string | null;
  snapshot_generated_at: string | null;
  expected_minutes: number;
}

export function getRefreshStatus(universe: Universe): Promise<RefreshStatus> {
  return request<RefreshStatus>(`/market/refresh?universe=${universe}`);
}

/** Start a refresh. A run already in progress (409) is not an error here:
 * its status is returned, so the page simply shows it. */
export async function startRefresh(universe: Universe): Promise<RefreshStatus> {
  const idToken = getIdToken();
  const res = await fetch(`${API_BASE_URL}/market/refresh?universe=${universe}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(idToken ? { authorization: `Bearer ${idToken}` } : {}),
    },
  });
  if (res.status === 409) {
    const body = await res.json();
    return body.detail.status as RefreshStatus;
  }
  if (!res.ok) throw new Error(`Refresh failed to start: ${res.status} ${await res.text()}`);
  return res.json() as Promise<RefreshStatus>;
}

// --- Company search (ticker 3+ chars, name 5+ chars; index + Yahoo) ---

export interface SearchResult {
  symbol: string;
  yahoo_ticker: string;
  name: string;
  exchange: string | null;
  industry: string | null;
  in_index: boolean;
  has_financials: boolean | null;
  // Which index the company is in, when it is in one.
  universe?: Universe | null;
  index_label?: string | null; // e.g. "LargeMidcap 250", "S&P 500"
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  online_ok: boolean;
}

export function searchCompanies(q: string): Promise<SearchResponse> {
  return request<SearchResponse>(`/search?q=${encodeURIComponent(q)}`);
}
