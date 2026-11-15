"use client";

import { useEffect, useMemo, useState } from "react";
import {
  MarketOverviewResponse,
  PredictResponse,
  RiskBand,
  UNIVERSES,
  Universe,
  getMarketOverview,
  isUniverse,
} from "../lib/api";
import { routeHref } from "../lib/routes";
import RiskDonut from "./RiskDonut";
import StatusDonut from "./StatusDonut";

// Company Score's third column: where the whole market stands, so a single
// company's score has context. Same data as Market Overview (every index
// company with complete figures, scored with the current model).

type View = "zone" | "risk";

// Altman's own zones for the classic Z-score (thresholds 1.81 / 2.99, see
// src/altman_zscore.py), in the status colours: distress red, grey yellow,
// safe green.
const ZONES = [
  { key: "safe", label: "Safe zone", icon: "✓", colorVar: "var(--status-good)", toneClass: "zone-safe", note: "Z above 2.99" },
  { key: "grey", label: "Grey zone", icon: "!", colorVar: "var(--status-warning)", toneClass: "zone-grey", note: "Z 1.81–2.99" },
  { key: "distress", label: "Distress zone", icon: "✕", colorVar: "var(--status-critical)", toneClass: "zone-distress", note: "Z below 1.81" },
];

function band(p: number, t: { moderate: number; high: number }): RiskBand {
  return p < t.moderate ? "low" : p < t.high ? "moderate" : "high";
}

export default function MarketStatusCard({
  result,
  companyUniverse = null,
}: {
  result: PredictResponse | null;
  // Market of the company loaded into the form, when known: the card
  // switches to it, and only marks the company in its own index.
  companyUniverse?: Universe | null;
}) {
  const [universe, setUniverse] = useState<Universe>("nse");
  const [byUniverse, setByUniverse] = useState<Partial<Record<Universe, MarketOverviewResponse>>>({});
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("zone");
  const data = byUniverse[universe] ?? null;

  useEffect(() => {
    if (companyUniverse) setUniverse(companyUniverse);
  }, [companyUniverse]);

  useEffect(() => {
    if (byUniverse[universe]) return; // loaded once per page view
    let cancelled = false;
    setError(null);
    getMarketOverview(universe)
      .then((d) => !cancelled && setByUniverse((m) => ({ ...m, [universe]: d })))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : "Could not load market data"));
    return () => {
      cancelled = true;
    };
  }, [universe, byUniverse]);

  // Don't mark an Indian company on the S&P 500 donut or vice versa;
  // manually typed figures (market unknown) are marked wherever shown.
  const marked = result && (!companyUniverse || companyUniverse === universe) ? result : null;

  const zoneCounts = useMemo(() => {
    const c: Record<string, number> = { safe: 0, grey: 0, distress: 0 };
    for (const co of data?.companies ?? []) c[co.z_score_zone] = (c[co.z_score_zone] ?? 0) + 1;
    return c;
  }, [data]);

  const notApplicable = data?.unscored.filter((u) => u.category === "not_applicable").length ?? 0;

  return (
    <section className="card market-status">
      <h2>Market status</h2>
      <label className="universe">
        <span className="sr-only">Universe</span>
        <select
          value={universe}
          onChange={(e) => isUniverse(e.target.value) && setUniverse(e.target.value)}
          aria-label="Universe"
        >
          {UNIVERSES.map((u) => (
            <option key={u.id} value={u.id}>
              {u.label}
            </option>
          ))}
        </select>
      </label>

      <div className="segmented" role="group" aria-label="Group companies by">
        <button type="button" aria-pressed={view === "zone"} onClick={() => setView("zone")}>
          Altman Z zone
        </button>
        <button type="button" aria-pressed={view === "risk"} onClick={() => setView("risk")}>
          Model risk
        </button>
      </div>

      {error && <p className="error-note">{error}</p>}
      {!error && !data && <p className="muted-note">Loading market…</p>}
      {data && !data.available && (
        <p className="muted-note">
          The {data.index} data hasn’t been collected yet; the weekly refresh runs on Sundays.
        </p>
      )}

      {data?.available &&
        (view === "zone" ? (
          <StatusDonut
            size={150}
            centerLabel="companies"
            segments={ZONES.map((z) => ({ ...z, count: zoneCounts[z.key] ?? 0 }))}
            highlight={marked?.z_score_zone ?? null}
            highlightLabel={marked ? marked.ticker : "this company"}
          />
        ) : (
          <RiskDonut
            size={150}
            bands={data.bands}
            thresholds={data.thresholds}
            highlight={marked ? band(marked.probability_distressed, data.thresholds) : null}
            highlightLabel={marked ? marked.ticker : undefined}
          />
        ))}

      {data?.available && (
        <p className="muted-note">
          {data.scored} of {data.total} companies with complete figures
          {notApplicable > 0 && (
            <>
              ; {notApplicable} {universe === "nse" ? "banks/NBFCs/insurers" : "banks/insurers"} excluded (model
              doesn’t apply)
            </>
          )}
          . Model {data.model_version ?? "—"}.{" "}
          {marked ? (
            <>
              <strong>{marked.ticker}</strong> is outlined in its {view === "zone" ? "zone" : "band"}.{" "}
            </>
          ) : result && companyUniverse ? (
            <>
              The company you scored is in the {UNIVERSES.find((u) => u.id === companyUniverse)?.short} market, so it
              isn’t marked here.{" "}
            </>
          ) : (
            "Score a company to see where it sits. "
          )}
          <a href={routeHref("market", universe === "nse" ? undefined : universe)}>Full market overview</a>
        </p>
      )}
    </section>
  );
}
