"use client";

import { useState } from "react";
import { predict, PredictResponse } from "../lib/api";
import { FormValues, OPTIONAL_FIELDS, REQUIRED_FIELDS, formatCompact, parseValue } from "../lib/financials";

// The form's values live in the parent (CompanyScorePage) so the financials
// chart beside it can redraw as the user types.
export default function ScoreForm({
  ticker,
  tickerField,
  notice,
  values,
  currency = null,
  onValuesChange,
  onResult,
  onClear,
}: {
  ticker: string;
  // The ticker input (a searchable combobox) and any auto-fill notice are
  // owned by CompanyScorePage, which knows about the NSE company list.
  tickerField: React.ReactNode;
  notice?: React.ReactNode;
  values: FormValues;
  currency?: string | null;
  onValuesChange: (v: FormValues) => void;
  onResult: (r: PredictResponse | null) => void;
  onClear: () => void;
}) {
  const [headlines, setHeadlines] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const missingRequired = !ticker || REQUIRED_FIELDS.some(([key]) => parseValue(values[key]) === null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (missingRequired) return;
    setLoading(true);
    setError(null);
    try {
      const financials: Record<string, number> = {};
      for (const [key] of [...REQUIRED_FIELDS, ...OPTIONAL_FIELDS]) {
        const v = parseValue(values[key]);
        if (v !== null) financials[key] = v;
      }
      const response = await predict({
        ticker,
        financials: financials as any,
        headlines: headlines
          .split("\n")
          .map((h) => h.trim())
          .filter(Boolean),
      });
      onResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
      onResult(null);
    } finally {
      setLoading(false);
    }
  }

  function handleClear() {
    setHeadlines("");
    setError(null);
    onClear();
  }

  return (
    <section className="card">
      <h2>Company Score</h2>
      <p className="card-subtitle">
        Pick a Nifty LargeMidcap 250 company to fill in its latest annual figures, or type any ticker. All figures
        must be in the same currency and unit.
      </p>
      <form onSubmit={handleSubmit}>
        {tickerField}
        {notice}

        <div className="field-grid">
          {REQUIRED_FIELDS.map(([key, label]) => (
            <label key={key}>
              {label}
              <input
                type="number"
                step="any"
                inputMode="decimal"
                value={values[key] ?? ""}
                onChange={(e) => onValuesChange({ ...values, [key]: e.target.value })}
                required
              />
              <ReadableValue raw={values[key]} currency={currency} />
            </label>
          ))}

          {OPTIONAL_FIELDS.map(([key, label]) => (
            <label key={key}>
              {label} <span className="optional">(optional)</span>
              <input
                type="number"
                step="any"
                inputMode="decimal"
                value={values[key] ?? ""}
                onChange={(e) => onValuesChange({ ...values, [key]: e.target.value })}
              />
              <ReadableValue raw={values[key]} currency={currency} />
            </label>
          ))}
        </div>

        <details className="headlines">
          <summary>Headlines (optional, no effect on the score yet)</summary>
          <label>
            One per line
            <textarea value={headlines} onChange={(e) => setHeadlines(e.target.value)} rows={3} />
          </label>
        </details>

        <div className="form-actions">
          <button type="submit" className="button-primary" disabled={missingRequired || loading}>
            {loading ? "Scoring..." : "Score"}
          </button>
          <button type="button" onClick={handleClear}>
            Clear
          </button>
        </div>
      </form>

      {error && <p className="error-note">{error}</p>}
    </section>
  );
}

// "17500000000000" is unreadable at a glance; show "₹17.5T" under it.
// Only for large values, where the compact form actually helps.
function ReadableValue({ raw, currency }: { raw: string | undefined; currency: string | null }) {
  const n = parseValue(raw);
  if (n === null || Math.abs(n) < 100_000) return <span className="value-hint" aria-hidden="true" />;
  return (
    <span className="value-hint" aria-hidden="true">
      ≈ {formatCompact(n, currency)}
    </span>
  );
}
