"use client";

import { useState } from "react";
import { predictDemo, PredictResponse } from "../lib/api";
import ResultCard from "./ResultCard";

// Hardcoded rather than fetched -- these are a fixed, known-good subset of
// the tickers bundled in data/sample_companies.json. No new backend
// endpoint needed just to list them.
const DEMO_TICKERS = ["SYN027", "SYN029", "SYN065", "SYN094"];

export default function DemoTickerPicker() {
  const [result, setResult] = useState<PredictResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);

  async function handlePick(ticker: string) {
    setLoading(ticker);
    setError(null);
    try {
      const response = await predictDemo(ticker);
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
      setResult(null);
    } finally {
      setLoading(null);
    }
  }

  return (
    <section>
      <h2>Try a demo ticker</h2>
      <div className="demo-tickers">
        {DEMO_TICKERS.map((ticker) => (
          <button key={ticker} onClick={() => handlePick(ticker)} disabled={loading === ticker}>
            {loading === ticker ? "Scoring..." : ticker}
          </button>
        ))}
      </div>

      {error && <p className="error-note">{error}</p>}
      {result && <ResultCard result={result} />}
    </section>
  );
}
