import { PredictResponse } from "../lib/api";
import ZScoreGauge from "./ZScoreGauge";

// Same 0.33 / 0.66 cut-offs as before, named the way the Market Overview
// pie will name them (Low / Moderate / High risk).
function probabilityBand(p: number): { key: "low" | "medium" | "high"; label: string; icon: string } {
  if (p < 0.33) return { key: "low", label: "Low risk", icon: "✓" };
  if (p < 0.66) return { key: "medium", label: "Moderate risk", icon: "!" };
  return { key: "high", label: "High risk", icon: "✕" };
}

export default function ResultCard({ result, stale = false }: { result: PredictResponse; stale?: boolean }) {
  const band = probabilityBand(result.probability_distressed);

  return (
    <section className={`card result-card ${stale ? "result-stale" : ""}`} aria-live="polite">
      <h2>Result — {result.ticker}</h2>
      {stale && (
        <p className="notice notice-info">
          The figures have changed since this score. Press <strong>Score</strong> to update it.
        </p>
      )}

      <div className="hero">
        <div className="hero-figure">{(result.probability_distressed * 100).toFixed(1)}%</div>
        <div className="hero-caption">probability of financial distress</div>
        <div className={`risk-label risk-${band.key}`}>
          <span className="zone-icon" aria-hidden="true">
            {band.icon}
          </span>
          {band.label}
        </div>
      </div>

      <div className="gauges">
        <ZScoreGauge variant="z" score={result.z_score} zone={result.z_score_zone} />
        <ZScoreGauge variant="z2" score={result.z_double_prime} zone={result.z_double_prime_zone} />
      </div>

      <div className="chips">
        <span className={`chip ${result.cash_burning ? "chip-warn" : ""}`}>
          {result.cash_burning ? "Loss-making (EBIT below zero)" : "EBIT positive"}
        </span>
      </div>

      <p className="muted-note">
        A screening signal, not a credit rating. News sentiment is not used yet (always 0.0), and the model has seen
        few Indian companies, so treat scores for Indian tickers with extra caution.
      </p>
    </section>
  );
}
