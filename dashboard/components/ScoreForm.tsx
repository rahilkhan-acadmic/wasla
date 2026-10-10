"use client";

import { useState } from "react";
import { predict, PredictResponse } from "../lib/api";
import ResultCard from "./ResultCard";

const REQUIRED_FIELDS = [
  ["total_assets", "Total assets"],
  ["total_liabilities", "Total liabilities"],
  ["current_assets", "Current assets"],
  ["current_liabilities", "Current liabilities"],
  ["retained_earnings", "Retained earnings"],
  ["ebit", "EBIT"],
  ["sales", "Sales"],
] as const;

const OPTIONAL_FIELDS = [
  ["market_value_equity", "Market value of equity"],
  ["book_value_equity", "Book value of equity"],
] as const;

type FormState = Record<string, string>;

export default function ScoreForm() {
  const [ticker, setTicker] = useState("");
  const [headlines, setHeadlines] = useState("");
  const [values, setValues] = useState<FormState>({});
  const [result, setResult] = useState<PredictResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const missingRequired = !ticker || REQUIRED_FIELDS.some(([key]) => values[key] === undefined || values[key] === "");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (missingRequired) return;
    setLoading(true);
    setError(null);
    try {
      const financials: Record<string, number> = {};
      for (const [key] of [...REQUIRED_FIELDS, ...OPTIONAL_FIELDS]) {
        if (values[key] !== undefined && values[key] !== "") {
          financials[key] = Number(values[key]);
        }
      }
      const response = await predict({
        ticker,
        financials: financials as any,
        headlines: headlines
          .split("\n")
          .map((h) => h.trim())
          .filter(Boolean),
      });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  function handleClear() {
    setTicker("");
    setHeadlines("");
    setValues({});
    setResult(null);
    setError(null);
  }

  return (
    <section>
      <h2>Score a company</h2>
      <form onSubmit={handleSubmit}>
        <label>
          Ticker
          <input value={ticker} onChange={(e) => setTicker(e.target.value)} required />
        </label>

        {REQUIRED_FIELDS.map(([key, label]) => (
          <label key={key}>
            {label}
            <input
              type="number"
              step="any"
              value={values[key] ?? ""}
              onChange={(e) => setValues({ ...values, [key]: e.target.value })}
              required
            />
          </label>
        ))}

        {OPTIONAL_FIELDS.map(([key, label]) => (
          <label key={key}>
            {label} (optional)
            <input
              type="number"
              step="any"
              value={values[key] ?? ""}
              onChange={(e) => setValues({ ...values, [key]: e.target.value })}
            />
          </label>
        ))}

        <label>
          Headlines (optional, one per line -- has no effect on the score yet, see note below)
          <textarea value={headlines} onChange={(e) => setHeadlines(e.target.value)} rows={3} />
        </label>

        <div className="form-actions">
          <button type="submit" disabled={missingRequired || loading}>
            {loading ? "Scoring..." : "Score"}
          </button>
          <button type="button" onClick={handleClear}>
            Clear
          </button>
        </div>
      </form>

      {error && <p className="error-note">{error}</p>}
      {result && <ResultCard result={result} />}
    </section>
  );
}
