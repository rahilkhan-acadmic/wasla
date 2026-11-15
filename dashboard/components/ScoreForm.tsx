"use client";

import { FormValues, OPTIONAL_FIELDS, REQUIRED_FIELDS, formatCompact, parseValue } from "../lib/financials";

// Presentational: the values, headlines and scoring state all live in
// CompanyScorePage (see lib/useScorer.ts), which also scores automatically
// after an auto-fill and never re-sends identical inputs.
export default function ScoreForm({
  tickerField,
  notice,
  values,
  currency = null,
  headlines,
  onHeadlinesChange,
  onValuesChange,
  canScore,
  unchanged,
  loading,
  error,
  onScore,
  onClear,
}: {
  // The ticker input (a searchable combobox) and any auto-fill notice are
  // owned by CompanyScorePage, which knows about the NSE company list.
  tickerField: React.ReactNode;
  notice?: React.ReactNode;
  values: FormValues;
  currency?: string | null;
  headlines: string;
  onHeadlinesChange: (h: string) => void;
  onValuesChange: (v: FormValues) => void;
  canScore: boolean; // ticker + every required figure present
  unchanged: boolean; // the result on screen is for exactly these inputs
  loading: boolean;
  error: string | null;
  onScore: () => void;
  onClear: () => void;
}) {
  return (
    <section className="card">
      <h2>Company Score</h2>
      <p className="card-subtitle">
        Pick a Nifty LargeMidcap 250 company to fill in its latest annual figures, or type any ticker. All figures
        must be in the same currency and unit.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onScore();
        }}
      >
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
            <textarea value={headlines} onChange={(e) => onHeadlinesChange(e.target.value)} rows={3} />
          </label>
        </details>

        <div className="form-actions">
          <button
            type="submit"
            className="button-primary"
            disabled={!canScore || loading || unchanged}
            title={unchanged ? "Already scored. Change a figure to score again." : undefined}
          >
            {loading ? "Scoring..." : unchanged ? "Scored ✓" : "Score"}
          </button>
          <button type="button" onClick={onClear}>
            Clear
          </button>
        </div>
        {unchanged && !loading && (
          <p className="muted-note">Scored with these figures. Change any figure to score again.</p>
        )}
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
