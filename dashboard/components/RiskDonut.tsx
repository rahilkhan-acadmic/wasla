import { RiskBand } from "../lib/api";
import StatusDonut from "./StatusDonut";

// The model's three risk bands as a donut (Market Overview, Company Score's
// market column). Bands are states, so they wear the reserved status colours.

export const BAND_META: Record<RiskBand, { label: string; icon: string; colorVar: string; tone: string }> = {
  low: { label: "Low risk", icon: "✓", colorVar: "var(--status-good)", tone: "risk-low" },
  moderate: { label: "Moderate risk", icon: "!", colorVar: "var(--status-warning)", tone: "risk-medium" },
  high: { label: "High risk", icon: "✕", colorVar: "var(--status-critical)", tone: "risk-high" },
};

const ORDER: RiskBand[] = ["low", "moderate", "high"];

export default function RiskDonut({
  bands,
  thresholds,
  selected = null,
  onSelect,
  highlight = null,
  highlightLabel,
  size,
}: {
  bands: Record<RiskBand, number>;
  thresholds: { moderate: number; high: number };
  selected?: RiskBand | null;
  onSelect?: (b: RiskBand | null) => void;
  highlight?: RiskBand | null;
  highlightLabel?: string;
  size?: number;
}) {
  const p = (x: number) => Math.round(x * 100);
  const range: Record<RiskBand, string> = {
    low: `below ${p(thresholds.moderate)}%`,
    moderate: `${p(thresholds.moderate)}–${p(thresholds.high)}%`,
    high: `${p(thresholds.high)}% and above`,
  };
  return (
    <StatusDonut
      size={size}
      centerLabel="scored"
      segments={ORDER.map((b) => ({
        key: b,
        label: BAND_META[b].label,
        icon: BAND_META[b].icon,
        colorVar: BAND_META[b].colorVar,
        toneClass: BAND_META[b].tone,
        count: bands[b],
        note: range[b],
      }))}
      selected={selected}
      onSelect={onSelect ? (k) => onSelect(k as RiskBand | null) : undefined}
      highlight={highlight}
      highlightLabel={highlightLabel}
    />
  );
}
