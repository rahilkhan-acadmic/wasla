"use client";

import { useState } from "react";
import { predictDemo, PredictResponse } from "../lib/api";

// Hardcoded rather than fetched -- these are a fixed, known-good subset of
// the tickers bundled in data/sample_companies.json. No new backend
// endpoint needed just to list them. They are synthetic companies, not real
// listings; PR 2 of the redesign replaces this with the NSE ticker list.
const DEMO_TICKERS = ["SYN027", "SYN029", "SYN065", "SYN094"];

export default function DemoTickerPicker({ onResult }: { onResult: (r: PredictResponse | null) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);

  async function handlePick(ticker: string) {
    setLoading(ticker);
    setError(null);
    try {
      onResult(await predictDemo(ticker));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
      onResult(null);
    } finally {
      setLoading(null);
    }
  }

  return (
    <section className="card">
      <h2>Try a sample company</h2>
      <p className="card-subtitle">Synthetic demo companies, scored from data bundled with the model.</p>
      <div className="demo-tickers">
        {DEMO_TICKERS.map((ticker) => (
          <button key={ticker} onClick={() => handlePick(ticker)} disabled={loading === ticker}>
            {loading === ticker ? "Scoring..." : ticker}
          </button>
        ))}
      </div>
      {error && <p className="error-note">{error}</p>}
    </section>
  );
}
