"use client";

import { useEffect, useMemo, useState } from "react";
import {
  MarketOverviewResponse,
  OverviewCompany,
  RiskBand,
  UNIVERSES,
  Universe,
  getMarketOverview,
} from "../lib/api";
import { routeHref } from "../lib/routes";
import CollapsibleCard from "./CollapsibleCard";
import RiskDonut, { BAND_META } from "./RiskDonut";

type SortKey = "probability" | "name" | "industry" | "z";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

// The index switcher is a pair of links, so the choice lives in the URL
// (#/market, #/market/us) and survives a reload or a shared link.
function UniverseSwitch({ current }: { current: Universe }) {
  return (
    <nav className="segmented" aria-label="Index">
      {UNIVERSES.map((u) => (
        <a
          key={u.id}
          href={routeHref("market", u.id === "nse" ? undefined : u.id)}
          aria-current={u.id === current ? "page" : undefined}
          className="segmented-link"
        >
          {u.short}
        </a>
      ))}
    </nav>
  );
}

// Who the model has and hasn't seen, per index -- stated next to the scores.
const CAVEAT: Record<Universe, string> = {
  nse: "A screening signal, not a credit rating: the model has seen few Indian companies.",
  us: "A screening signal, not a credit rating: the model's US training data is a few dozen EDGAR filers.",
};

export default function MarketOverviewPage({ universe = "nse" }: { universe?: Universe }) {
  const [data, setData] = useState<MarketOverviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [band, setBand] = useState<RiskBand | null>(null);
  const [industry, setIndustry] = useState("");
  const [query, setQuery] = useState("");
  const [lossOnly, setLossOnly] = useState(false);
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "probability", desc: true });

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    setBand(null);
    setIndustry("");
    setQuery("");
    setLossOnly(false);
    getMarketOverview(universe)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : "Could not load the overview"));
    return () => {
      cancelled = true;
    };
  }, [universe]);
  const scoreHref = (symbol: string) => routeHref("score", symbol, universe === "nse" ? undefined : universe);
  const financialsLabel = universe === "nse" ? "banks, NBFCs and insurers" : "banks and insurers";

  const industries = useMemo(
    () => Array.from(new Set((data?.companies ?? []).map((c) => c.industry).filter(Boolean) as string[])).sort(),
    [data]
  );

  const rows = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toUpperCase();
    const filtered = data.companies.filter(
      (c) =>
        (!band || c.band === band) &&
        (!industry || c.industry === industry) &&
        (!lossOnly || c.loss_making) &&
        (!q || c.symbol.includes(q) || c.name.toUpperCase().includes(q))
    );
    const dir = sort.desc ? -1 : 1;
    const cmp: Record<SortKey, (a: OverviewCompany, b: OverviewCompany) => number> = {
      probability: (a, b) => a.probability_distressed - b.probability_distressed,
      name: (a, b) => a.symbol.localeCompare(b.symbol),
      industry: (a, b) => (a.industry ?? "").localeCompare(b.industry ?? "") || a.symbol.localeCompare(b.symbol),
      z: (a, b) => a.z_score - b.z_score,
    };
    return [...filtered].sort((a, b) => dir * cmp[sort.key](a, b));
  }, [data, band, industry, query, lossOnly, sort]);

  if (error) {
    return (
      <section className="card">
        <div className="overview-title">
          <h2>Market Overview</h2>
          <UniverseSwitch current={universe} />
        </div>
        <p className="error-note">{error}</p>
      </section>
    );
  }
  if (!data) {
    return (
      <section className="card">
        <div className="overview-title">
          <h2>Market Overview</h2>
          <UniverseSwitch current={universe} />
        </div>
        <p className="muted-note">Scoring the index…</p>
      </section>
    );
  }
  if (!data.available) {
    return (
      <section className="card">
        <div className="overview-title">
          <h2>Market Overview</h2>
          <UniverseSwitch current={universe} />
        </div>
        <p>
          The {data.index} data hasn’t been collected yet. The weekly refresh runs on Sundays; check back after the
          next run.
        </p>
      </section>
    );
  }

  function header(key: SortKey, label: string, numeric = false, extraClass = "") {
    const active = sort.key === key;
    return (
      <th scope="col" className={`${numeric ? "num" : ""} ${extraClass}`.trim() || undefined} aria-sort={active ? (sort.desc ? "descending" : "ascending") : "none"}>
        <button
          type="button"
          className="sort-button"
          onClick={() => setSort({ key, desc: active ? !sort.desc : key === "probability" })}
        >
          {label}
          <span aria-hidden="true" className="sort-arrow">
            {active ? (sort.desc ? "▼" : "▲") : ""}
          </span>
        </button>
      </th>
    );
  }

  const filtersActive = band || industry || query || lossOnly;
  const notApplicable = data.unscored.filter((u) => u.category === "not_applicable").length;
  const unscoredGroups: [string, typeof data.unscored][] = [
    [`Model doesn’t apply (${financialsLabel})`, data.unscored.filter((u) => u.category === "not_applicable")],
    ["Missing or unusable figures", data.unscored.filter((u) => u.category !== "not_applicable")],
  ];

  return (
    <div className="overview">
      <section className="card overview-head">
        <div className="overview-title">
          <h2>Market Overview — {data.index}</h2>
          <UniverseSwitch current={universe} />
        </div>
        <p className="card-subtitle">
          {data.scored} of {data.total} companies scored with model {data.model_version ?? "—"}, from annual figures
          collected {formatDate(data.snapshot_generated_at)}. {CAVEAT[universe]}
        </p>
      </section>

      <div className="overview-grid">
        <CollapsibleCard title="Distress risk across the index" storageKey="market-risk">
          <p className="card-subtitle">Click a band to filter the table.</p>
          <RiskDonut bands={data.bands} thresholds={data.thresholds} selected={band} onSelect={setBand} />
        </CollapsibleCard>

        <div className="stat-stack">
          <section className="card stat-tile">
            <div className="stat-label">Loss-making</div>
            <div className="stat-value">{data.loss_making}</div>
            <div className="stat-caption">
              of {data.ebit_known} companies with known EBIT reported an operating loss (EBIT below zero) in their
              latest year.
            </div>
            <button type="button" className="link-button" aria-pressed={lossOnly} onClick={() => setLossOnly(!lossOnly)}>
              {lossOnly ? "Show all companies" : "Show only these"}
            </button>
          </section>
          <section className="card stat-tile">
            <div className="stat-label">Not scored</div>
            <div className="stat-value">{data.unscored.length}</div>
            <div className="stat-caption">
              {notApplicable > 0 && (
                <>
                  {notApplicable} {financialsLabel}, where this model doesn’t apply
                  {data.unscored.length - notApplicable > 0 ? "; " : "."}
                </>
              )}
              {data.unscored.length - notApplicable > 0 && (
                <>{data.unscored.length - notApplicable} with a figure missing from the data source.</>
              )}{" "}
              Listed below the table.
            </div>
          </section>
        </div>
      </div>

      <CollapsibleCard
        title="Companies"
        storageKey="market-companies"
        actions={
          <>
            <input
              type="search"
              placeholder="Search ticker or name"
              aria-label="Search ticker or name"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <select aria-label="Industry" value={industry} onChange={(e) => setIndustry(e.target.value)}>
              <option value="">All industries</option>
              {industries.map((i) => (
                <option key={i} value={i}>
                  {i}
                </option>
              ))}
            </select>
            {band && (
              <span className="filter-chip">
                {BAND_META[band].label}
                <button type="button" aria-label={`Remove ${BAND_META[band].label} filter`} onClick={() => setBand(null)}>
                  ×
                </button>
              </span>
            )}
            {filtersActive && (
              <button
                type="button"
                className="link-button"
                onClick={() => {
                  setBand(null);
                  setIndustry("");
                  setQuery("");
                  setLossOnly(false);
                }}
              >
                Clear filters
              </button>
            )}
          </>
        }
      >
        <p className="muted-note" aria-live="polite">
          Showing {rows.length} of {data.scored}. Open a company to see its figures and full score.
        </p>

        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                {header("name", "Company")}
                {header("industry", "Industry", false, "col-industry")}
                {header("probability", "Distress risk", true)}
                {header("z", "Altman Z", true)}
                <th scope="col" title="Operating result in the latest year">EBIT</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.symbol}>
                  <th scope="row">
                    <a href={scoreHref(c.symbol)} className="company-link">
                      <span className="opt-symbol">{c.symbol}</span>
                      <span className="company-name">{c.name}</span>
                    </a>
                  </th>
                  <td className="muted-cell col-industry">{c.industry ?? "—"}</td>
                  <td className="num">
                    <span className={`risk-cell risk-${c.band === "moderate" ? "medium" : c.band}`}>
                      <span className="zone-icon" aria-hidden="true">
                        {BAND_META[c.band].icon}
                      </span>
                      {(c.probability_distressed * 100).toFixed(1)}%
                      <span className="sr-only"> ({BAND_META[c.band].label})</span>
                    </span>
                  </td>
                  <td className="num">
                    {c.z_score.toFixed(2)} <span className="muted-cell">{c.z_score_zone}</span>
                  </td>
                  <td>{c.loss_making ? <span className="chip chip-warn">Loss</span> : <span className="muted-cell">Profit</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleCard>

      {data.unscored.length > 0 && (
        <CollapsibleCard title={`Not scored (${data.unscored.length})`} storageKey="market-unscored" defaultOpen={false}>
          <>
            {unscoredGroups
              .filter(([, list]) => list.length > 0)
              .map(([title, list]) => (
                <div key={title} className="unscored-group">
                  <h3>
                    {title} · {list.length}
                  </h3>
                  <table className="data-table compact">
                    <tbody>
                      {list.map((u) => (
                        <tr key={u.symbol}>
                          <th scope="row">
                            <a href={scoreHref(u.symbol)} className="company-link">
                              <span className="opt-symbol">{u.symbol}</span>
                              <span className="company-name">{u.name}</span>
                            </a>
                          </th>
                          <td className="muted-cell">
                            {u.category === "not_applicable" ? (u.industry ?? "Financials") : u.reason}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            {notApplicable > 0 && (
              <p className="muted-note">
                {financialsLabel.charAt(0).toUpperCase() + financialsLabel.slice(1)} present an unclassified balance
                sheet, with no split into current and
                non-current assets and liabilities. Altman-style ratios, which this model is built on, need that split,
                so these companies are left out rather than scored on made-up figures.
              </p>
            )}
          </>
        </CollapsibleCard>
      )}
    </div>
  );
}
