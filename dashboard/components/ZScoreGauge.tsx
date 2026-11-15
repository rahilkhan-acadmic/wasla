// A meter for one Altman score against its three zones. Zone colours are the
// reserved status colours, and the current zone is always also named in text
// with an icon -- colour never carries the meaning alone.
//
// Thresholds mirror src/altman_zscore.py classify_zone().

type Variant = "z" | "z2";

const VARIANTS: Record<Variant, { name: string; grey: number; safe: number }> = {
  z: { name: "Altman Z-Score", grey: 1.81, safe: 2.99 },
  z2: { name: "Altman Z″-Score", grey: 1.1, safe: 2.6 },
};

// Fixed display range; scores outside it pin to the edge with an arrow.
const MIN = -2;
const MAX = 6;

const ZONE_TEXT: Record<string, { label: string; icon: string }> = {
  distress: { label: "Distress zone", icon: "✕" },
  grey: { label: "Grey zone", icon: "!" },
  safe: { label: "Safe zone", icon: "✓" },
};

function pct(v: number) {
  return ((Math.min(MAX, Math.max(MIN, v)) - MIN) / (MAX - MIN)) * 100;
}

export default function ZScoreGauge({ variant, score, zone }: { variant: Variant; score: number; zone: string }) {
  const v = VARIANTS[variant];
  const zt = ZONE_TEXT[zone] ?? { label: zone, icon: "•" };
  const offLow = score < MIN;
  const offHigh = score > MAX;

  return (
    <div className="gauge">
      <div className="gauge-head">
        <span className="gauge-name">{v.name}</span>
        <span className="gauge-score">
          {offLow && "◀ "}
          {score.toFixed(2)}
          {offHigh && " ▶"}
        </span>
      </div>

      <div
        className="gauge-track"
        role="meter"
        aria-label={v.name}
        aria-valuemin={MIN}
        aria-valuemax={MAX}
        aria-valuenow={Math.min(MAX, Math.max(MIN, score))}
        aria-valuetext={`${score.toFixed(2)}, ${zt.label}`}
      >
        <span className="gauge-zone gauge-zone-distress" style={{ left: 0, width: `${pct(v.grey)}%` }} />
        <span
          className="gauge-zone gauge-zone-grey"
          style={{ left: `${pct(v.grey)}%`, width: `${pct(v.safe) - pct(v.grey)}%` }}
        />
        <span className="gauge-zone gauge-zone-safe" style={{ left: `${pct(v.safe)}%`, right: 0 }} />
        <span className="gauge-marker" style={{ left: `${pct(score)}%` }} />
      </div>

      <div className="gauge-scale" aria-hidden="true">
        <span style={{ left: `${pct(v.grey)}%` }}>{v.grey}</span>
        <span style={{ left: `${pct(v.safe)}%` }}>{v.safe}</span>
      </div>

      <div className={`zone-label zone-${zone}`}>
        <span className="zone-icon" aria-hidden="true">
          {zt.icon}
        </span>
        {zt.label}
      </div>
    </div>
  );
}
