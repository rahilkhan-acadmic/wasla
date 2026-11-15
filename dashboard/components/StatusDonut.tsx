// Part-to-whole donut for a small set of ordered states (risk bands,
// Altman zones). States wear the reserved status colours, and every slice is
// also named in the legend with an icon, count and share -- colour never
// carries the meaning alone. The legend doubles as the table view.
//
// Optional: onSelect makes slices and legend rows act as a filter;
// highlight marks one state (e.g. "the company you just scored") with a
// ring on its slice and a tag in the legend.

export interface DonutSegment {
  key: string;
  label: string;
  icon: string;
  colorVar: string;
  toneClass: string; // text/icon tone class, e.g. "risk-low"
  count: number;
  note?: string; // small second line, e.g. "below 33%"
}

const GAP = 2; // surface gap between slices, in px along the ring

export default function StatusDonut({
  segments,
  centerLabel,
  size = 180,
  selected = null,
  onSelect,
  highlight = null,
  highlightLabel = "this company",
}: {
  segments: DonutSegment[];
  centerLabel: string;
  size?: number;
  selected?: string | null;
  onSelect?: (key: string | null) => void;
  highlight?: string | null;
  highlightLabel?: string;
}) {
  const stroke = Math.round(size * 0.145);
  const r = (size - stroke) / 2 - 3; // leave room for the highlight ring
  const circ = 2 * Math.PI * r;
  const total = segments.reduce((n, s) => n + s.count, 0);
  const nonZero = segments.filter((s) => s.count > 0).length;

  let offset = 0;
  const slices = segments
    .filter((s) => s.count > 0)
    .map((s) => {
      const len = (s.count / total) * circ;
      const slice = { s, dash: Math.max(len - (nonZero > 1 ? GAP : 0), 0.5), offset };
      offset += len;
      return slice;
    });
  const pct = (n: number) => (total ? Math.round((n / total) * 100) : 0);
  const c = size / 2;

  return (
    <div className="donut-wrap">
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={segments.map((s) => `${s.label}: ${s.count}`).join(", ")}
        className="donut"
      >
        <circle cx={c} cy={c} r={r} fill="none" stroke="var(--hairline)" strokeWidth={stroke} />
        {slices.map(({ s, dash, offset: off }) => (
          <g key={s.key}>
            {highlight === s.key && (
              // Outline ring around the highlighted slice.
              <circle
                cx={c}
                cy={c}
                r={r}
                fill="none"
                stroke="var(--text)"
                strokeWidth={stroke + 6}
                strokeDasharray={`${dash} ${circ - dash}`}
                strokeDashoffset={-off}
                transform={`rotate(-90 ${c} ${c})`}
              />
            )}
            <circle
              cx={c}
              cy={c}
              r={r}
              fill="none"
              stroke={s.colorVar}
              strokeWidth={stroke}
              strokeDasharray={`${dash} ${circ - dash}`}
              strokeDashoffset={-off}
              transform={`rotate(-90 ${c} ${c})`}
              opacity={selected && selected !== s.key ? 0.3 : 1}
              className={onSelect ? "donut-slice" : undefined}
              onClick={onSelect ? () => onSelect(selected === s.key ? null : s.key) : undefined}
            >
              <title>{`${s.label}: ${s.count} (${pct(s.count)}%)`}</title>
            </circle>
          </g>
        ))}
        <text x="50%" y="47%" textAnchor="middle" className="donut-total">
          {total}
        </text>
        <text x="50%" y="60%" textAnchor="middle" className="donut-caption">
          {centerLabel}
        </text>
      </svg>

      <ul className="donut-legend">
        {segments.map((s) => {
          const row = (
            <>
              <span className={`zone-label ${s.toneClass}`}>
                <span className="zone-icon" aria-hidden="true">
                  {s.icon}
                </span>
                {s.label}
              </span>
              <span className="legend-count">{s.count}</span>
              <span className="legend-pct">{pct(s.count)}%</span>
              {(s.note || highlight === s.key) && (
                <span className="legend-range">
                  {s.note}
                  {highlight === s.key && <strong className="legend-you">{s.note ? " · " : ""}◀ {highlightLabel}</strong>}
                </span>
              )}
            </>
          );
          return (
            <li key={s.key}>
              {onSelect ? (
                <button
                  type="button"
                  className={`legend-row ${selected === s.key ? "legend-row-active" : ""}`}
                  aria-pressed={selected === s.key}
                  onClick={() => onSelect(selected === s.key ? null : s.key)}
                >
                  {row}
                </button>
              ) : (
                <div className={`legend-row ${highlight === s.key ? "legend-row-active" : ""}`}>{row}</div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
