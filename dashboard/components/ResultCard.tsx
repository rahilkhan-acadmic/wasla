import { PredictResponse } from "../lib/api";

function probabilityBand(p: number): "low" | "medium" | "high" {
  if (p < 0.33) return "low";
  if (p < 0.66) return "medium";
  return "high";
}

export default function ResultCard({ result }: { result: PredictResponse }) {
  const band = probabilityBand(result.probability_distressed);

  return (
    <div className="result-card">
      <h3>{result.ticker}</h3>

      <div className={`probability probability-${band}`}>
        {(result.probability_distressed * 100).toFixed(1)}%
        <span className="probability-label">probability of distress</span>
      </div>

      <div className="chips">
        <span className="chip">
          Z-Score {result.z_score.toFixed(2)} &middot; {result.z_score_zone}
        </span>
        <span className="chip">
          Z&Prime; {result.z_double_prime.toFixed(2)} &middot; {result.z_double_prime_zone}
        </span>
        <span className={`chip ${result.cash_burning ? "chip-warn" : ""}`}>
          {result.cash_burning ? "Burning cash" : "Not burning cash"}
        </span>
      </div>

      <p className="muted-note">
        News sentiment: {result.news_sentiment.toFixed(3)} (not yet implemented --
        this field is currently always 0.0 for every company; see project README).
      </p>
    </div>
  );
}
