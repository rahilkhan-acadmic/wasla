"use client";

import { FormValues, REQUIRED_FIELDS, formatCompact, formatFull, parseValue } from "../lib/financials";

// Horizontal bars for the figures the user has entered, redrawn as they type.
// One series, so no legend box -- the title names it. Values can be negative
// (retained earnings, EBIT), so bars grow from a shared zero baseline and
// negatives take the opposite pole of the diverging pair. A colour legend
// appears only when a negative value is actually on screen.
export default function FinancialsChart({
  ticker,
  values,
  currency = null,
  asOf = null,
}: {
  ticker: string;
  values: FormValues;
  currency?: string | null;
  asOf?: string | null;
}) {
  const rows = REQUIRED_FIELDS.map(([key, label]) => ({ key, label, value: parseValue(values[key]) }));
  const entered = rows.filter((r) => r.value !== null) as { key: string; label: string; value: number }[];

  const title = ticker ? `${ticker.toUpperCase()} — reported financials` : "Reported financials";
  const subtitle = [asOf && `FY ending ${asOf}`, currency].filter(Boolean).join(" · ");
  const fmt = (n: number) => formatCompact(n, currency);

  if (entered.length === 0) {
    return (
      <section className="card chart-card">
        <h2>{title}</h2>
        <p className="empty-state">Enter figures in the form to see them charted here.</p>
      </section>
    );
  }

  const lo = Math.min(0, ...entered.map((r) => r.value));
  const hi = Math.max(0, ...entered.map((r) => r.value));
  const span = hi - lo || 1;
  const zeroPct = ((0 - lo) / span) * 100;
  const hasNegative = lo < 0;

  return (
    <section className="card chart-card">
      <h2>{title}</h2>
      {subtitle && <p className="card-subtitle">{subtitle}</p>}
      {hasNegative && (
        <div className="legend" aria-hidden="true">
          <span className="legend-item">
            <span className="swatch swatch-positive" /> Positive
          </span>
          <span className="legend-item">
            <span className="swatch swatch-negative" /> Negative
          </span>
        </div>
      )}

      <div className="hbar-chart" role="img" aria-label={`Bar chart of ${entered.length} reported figures. Values are listed in the table below.`}>
        {rows.map((r) => {
          if (r.value === null) {
            return (
              <div className="hbar-row hbar-row-missing" key={r.key}>
                <span className="hbar-label">{r.label}</span>
                <span className="hbar-track" />
                <span className="hbar-value muted">—</span>
              </div>
            );
          }
          const valuePct = ((r.value - lo) / span) * 100;
          const left = Math.min(zeroPct, valuePct);
          const width = Math.abs(valuePct - zeroPct);
          const negative = r.value < 0;
          return (
            <div className="hbar-row" key={r.key} title={`${r.label}: ${formatFull(r.value)}`}>
              <span className="hbar-label">{r.label}</span>
              <span className="hbar-track">
                <span className="hbar-zero" style={{ left: `${zeroPct}%` }} />
                <span
                  className={`hbar-bar ${negative ? "hbar-bar-negative" : ""}`}
                  // Keep a hairline of a bar visible for tiny non-zero values.
                  style={{ left: `${left}%`, width: `max(${width}%, ${r.value === 0 ? 0 : 2}px)` }}
                />
              </span>
              <span className="hbar-value">{fmt(r.value)}</span>
            </div>
          );
        })}
      </div>

      <details className="table-view">
        <summary>Show as table</summary>
        <table>
          <thead>
            <tr>
              <th scope="col">Figure</th>
              <th scope="col" className="num">
                Value
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <th scope="row">{r.label}</th>
                <td className="num">{r.value === null ? "—" : formatFull(r.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}
