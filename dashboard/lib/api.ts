// Thin fetch wrappers around the distress-model-api Lambda Function URL.
// NEXT_PUBLIC_API_BASE_URL is baked in at build time (static export has no
// server to read env vars at request time) -- set it when running `next build`,
// e.g. NEXT_PUBLIC_API_BASE_URL=https://xxxx.lambda-url.ap-south-1.on.aws npm run build

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
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "content-type": "application/json" },
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
