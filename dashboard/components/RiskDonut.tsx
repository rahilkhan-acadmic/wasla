import { RiskBand } from "../lib/api";

// Part-to-whole of the three risk bands. Bands are states, so they wear the
// reserved status colours, and every slice is also named with an icon, count
// and share in the legend beside it -- colour never carries it alone. The
// legend doubles as the table view and as a filter for the company table.

export const BAND_META: Record<RiskBand, { label: string; icon: string; colorVar: string }> = {
  low: { label: "Low risk", icon: "✓", colorVar: "var(--status-good)" },
  moderate: { label: "Moderate risk", icon: "!", colorVar: "var(--status-warning)" },
  high: { label: "High risk", icon: "✕", colorVar: "var(--status-critical)" },
};

const ORDER: RiskBand[] = ["low", "moderate", "high"];
const SIZE = 180;
const STROKE = 26;
const R = (SIZE - STROKE) / 2;
const CIRC = 2 * Math.PI * R;
const GAP = 2; // surface gap between slices, in px along the ring

export default function RiskDonut({
  bands,
  thresholds,
  selected,
  onSelect,
}: {
  bands: Record<RiskBand, number>;
  thresholds: { moderate: number; high: number };
  selected: RiskBand | null;
  onSelect: (b: RiskBand | null) => void;
}) {
  const total = ORDER.reduce((n, b) => n + bands[b], 0);
  const nonZero = ORDER.filter((b) => bands[b] > 0).length;

  let offset = 0;
  const slices = ORDER.filter((b) => bands[b] > 0).map((b) => {
    const len = (bands[b] / total) * CIRC;
    const gap = nonZero > 1 ? GAP : 0;
    const slice = { band: b, dash: Math.max(len - gap, 0.5), offset };
    offset += len;
    return slice;
  });

  const pct = (n: number) => (total ? Math.round((n / total) * 100) : 0);
  const range: Record<RiskBand, string> = {
    low: `below ${Math.round(thresholds.moderate * 100)}%`,
    moderate: `${Math.round(thresholds.moderate * 100)}–${Math.round(thresholds.high * 100)}%`,
    high: `${Math.round(thresholds.high * 100)}% and above`,
  };

  return (
    <div className="donut-wrap">
      <svg
        width={SIZE}
        height={SIZE}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label={ORDER.map((b) => `${BAND_META[b].label}: ${bands[b]}`).join(", ")}
        className="donut"
      >
        <circle cx={SIZE / 2} cy={SIZE / 2} r={R} fill="none" stroke="var(--hairline)" strokeWidth={STROKE} />
        {slices.map((s) => (
          <circle
            key={s.band}
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={R}
            fill="none"
            stroke={BAND_META[s.band].colorVar}
            strokeWidth={STROKE}
            strokeDasharray={`${s.dash} ${CIRC - s.dash}`}
            // Start at 12 o'clock and run clockwise.
            strokeDashoffset={-s.offset}
            transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
            opacity={selected && selected !== s.band ? 0.3 : 1}
            className="donut-slice"
            onClick={() => onSelect(selected === s.band ? null : s.band)}
          >
            <title>{`${BAND_META[s.band].label}: ${bands[s.band]} (${pct(bands[s.band])}%)`}</title>
          </circle>
        ))}
        <text x="50%" y="47%" textAnchor="middle" className="donut-total">
          {total}
        </text>
        <text x="50%" y="60%" textAnchor="middle" className="donut-caption">
          scored
        </text>
      </svg>

      <ul className="donut-legend">
        {ORDER.map((b) => (
          <li key={b}>
            <button
              type="button"
              className={`legend-row ${selected === b ? "legend-row-active" : ""}`}
              aria-pressed={selected === b}
              onClick={() => onSelect(selected === b ? null : b)}
            >
              <span className={`zone-label risk-${b === "moderate" ? "medium" : b}`}>
                <span className="zone-icon" aria-hidden="true">
                  {BAND_META[b].icon}
                </span>
                {BAND_META[b].label}
              </span>
              <span className="legend-count">{bands[b]}</span>
              <span className="legend-pct">{pct(bands[b])}%</span>
              <span className="legend-range">{range[b]}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
