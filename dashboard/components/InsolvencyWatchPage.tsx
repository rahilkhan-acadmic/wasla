"use client";

import { useMemo, useState } from "react";
import data from "../data/insolvency_cases.json";

// Facts only: hand-curated, sourced cases (dashboard/data/insolvency_cases.json,
// validated by tests/test_insolvency_data.py). Deliberately shows no model
// scores -- several of these companies are in the model's training labels,
// and a score for a company the model learned from isn't a prediction.

type Outcome = "acquired" | "liquidated" | "ongoing";

interface Case {
  id: string;
  company: string;
  industry: string;
  rbi_first_list: boolean;
  admitted: string;
  outcome: Outcome;
  outcome_event: string;
  outcome_date: string | null;
  acquirer: string | null;
  recovery_pct: number | null;
  recovery_note: string | null;
  summary: string;
  in_training_labels: boolean;
  sources: { label: string; url: string }[];
}

const CASES = data.cases as Case[];
const AS_OF = data.status_as_of;

const OUTCOME_META: Record<Outcome, { label: string; colorVar: string; blurb: string }> = {
  acquired: { label: "Acquired", colorVar: "var(--series-1)", blurb: "sold to a new owner under a resolution plan" },
  liquidated: { label: "Liquidated", colorVar: "var(--series-2)", blurb: "wound up and its assets sold" },
  ongoing: { label: "Ongoing", colorVar: "var(--series-3)", blurb: "no completed resolution yet" },
};
const OUTCOME_ORDER: Outcome[] = ["acquired", "liquidated", "ongoing"];

/** "YYYY-MM-DD" or "YYYY-MM" (first of month) -> UTC ms. */
function toMs(d: string): number {
  const [y, m, day] = d.split("-").map(Number);
  return Date.UTC(y, (m ?? 1) - 1, day ?? 1);
}

function formatDate(d: string | null): string {
  if (!d) return "—";
  const parts = d.split("-");
  const dt = new Date(toMs(d));
  return dt.toLocaleDateString("en-GB", {
    ...(parts.length === 3 ? { day: "numeric" } : {}),
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

function duration(fromMs: number, toMs_: number): string {
  const months = Math.max(0, Math.round((toMs_ - fromMs) / (1000 * 60 * 60 * 24 * 30.44)));
  if (months < 24) return `${months} mo`;
  return `${(months / 12).toFixed(1)} yr`;
}

export default function InsolvencyWatchPage() {
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [rbiOnly, setRbiOnly] = useState(false);

  const counts = useMemo(
    () => Object.fromEntries(OUTCOME_ORDER.map((o) => [o, CASES.filter((c) => c.outcome === o).length])) as Record<Outcome, number>,
    []
  );

  const visible = useMemo(
    () =>
      CASES.filter((c) => (!outcome || c.outcome === outcome) && (!rbiOnly || c.rbi_first_list)).sort(
        (a, b) => toMs(a.admitted) - toMs(b.admitted) || a.company.localeCompare(b.company)
      ),
    [outcome, rbiOnly]
  );

  return (
    <div className="overview">
      <section className="card overview-head">
        <h2>Insolvency Watch</h2>
        <p className="card-subtitle">
          Major listed Indian companies that entered the corporate insolvency resolution process (CIRP) under the
          Insolvency and Bankruptcy Code since 2017, and what happened next. Status as of {formatDate(AS_OF)}. Facts
          only: no model scores, because several of these companies are in the model’s training data.
        </p>
        <details className="method">
          <summary>How this list was built</summary>
          <p>{data.method}</p>
          <p>{data.training_data_note}</p>
        </details>
      </section>

      <div className="outcome-tiles">
        {OUTCOME_ORDER.map((o) => (
          <button
            key={o}
            type="button"
            className={`card stat-tile outcome-tile ${outcome === o ? "outcome-tile-active" : ""}`}
            aria-pressed={outcome === o}
            onClick={() => setOutcome(outcome === o ? null : o)}
          >
            <span className="stat-label">
              <span className="swatch" style={{ background: OUTCOME_META[o].colorVar }} aria-hidden="true" />{" "}
              {OUTCOME_META[o].label}
            </span>
            <span className="stat-value">{counts[o]}</span>
            <span className="stat-caption">{OUTCOME_META[o].blurb}</span>
          </button>
        ))}
      </div>

      <section className="card">
        <div className="table-toolbar">
          <h2>Time in insolvency</h2>
          <div className="filters">
            <label className="check">
              <input type="checkbox" checked={rbiOnly} onChange={(e) => setRbiOnly(e.target.checked)} /> RBI’s first 12
              referrals (2017, as reported) only
            </label>
            {outcome && (
              <span className="filter-chip">
                {OUTCOME_META[outcome].label}
                <button type="button" aria-label={`Remove ${OUTCOME_META[outcome].label} filter`} onClick={() => setOutcome(null)}>
                  ×
                </button>
              </span>
            )}
          </div>
        </div>
        <p className="card-subtitle">
          From admission to the deciding order (plan approval, completion or liquidation). Ongoing cases run to{" "}
          {formatDate(AS_OF)}.
        </p>
        <Timeline cases={visible} />
      </section>

      <section className="card">
        <h2>How much lenders got back</h2>
        <p className="card-subtitle">
          Share of financial creditors’ admitted claims recovered, as reported (approximate: reports differ on the
          base). Cases without a reliable figure are left out rather than estimated.
        </p>
        <RecoveryBars cases={visible.filter((c) => c.recovery_pct !== null)} />
      </section>

      <section className="card">
        <h2>Cases ({visible.length})</h2>
        <ul className="case-list">
          {visible.map((c) => (
            <li key={c.id} className="case">
              <div className="case-head">
                <div>
                  <div className="case-name">{c.company}</div>
                  <div className="company-name">{c.industry}</div>
                </div>
                <span className="outcome-badge">
                  <span className="swatch" style={{ background: OUTCOME_META[c.outcome].colorVar }} aria-hidden="true" />
                  {OUTCOME_META[c.outcome].label}
                </span>
              </div>
              <dl className="case-facts">
                <dt>Admitted</dt>
                <dd>{formatDate(c.admitted)}</dd>
                <dt>Outcome</dt>
                <dd>
                  {c.outcome_event}
                  {c.outcome_date && <> ({formatDate(c.outcome_date)})</>}
                </dd>
                {c.acquirer && (
                  <>
                    <dt>Acquirer</dt>
                    <dd>{c.acquirer}</dd>
                  </>
                )}
                {(c.recovery_pct !== null || c.recovery_note) && (
                  <>
                    <dt>Recovery</dt>
                    <dd>
                      {c.recovery_pct !== null && <strong>~{c.recovery_pct}%. </strong>}
                      {c.recovery_note}
                    </dd>
                  </>
                )}
              </dl>
              <p className="case-summary">{c.summary}</p>
              <div className="case-foot">
                {c.rbi_first_list && <span className="chip">RBI’s first 12</span>}
                {c.in_training_labels && (
                  <span className="chip" title="Also in data/sources/india_distress_labels.csv; no model score is shown">
                    In model training data
                  </span>
                )}
                <span className="sources">
                  Sources:{" "}
                  {c.sources.map((s, i) => (
                    <span key={s.url}>
                      {i > 0 && " · "}
                      <a href={s.url} target="_blank" rel="noopener noreferrer">
                        {s.label}
                      </a>
                    </span>
                  ))}
                </span>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function Timeline({ cases }: { cases: Case[] }) {
  if (cases.length === 0) return <p className="empty-state">No cases match these filters.</p>;
  const endAsOf = toMs(AS_OF);
  const start = Date.UTC(2017, 0, 1);
  const lastYear = new Date(endAsOf).getUTCFullYear() + 1;
  const end = Date.UTC(lastYear, 0, 1);
  const pct = (ms: number) => ((ms - start) / (end - start)) * 100;
  const years = Array.from({ length: lastYear - 2017 + 1 }, (_, i) => 2017 + i);

  return (
    <div className="timeline" role="img" aria-label="Timeline of each case from admission to outcome; details are in the case list below.">
      <div className="tl-axis" aria-hidden="true">
        <span className="tl-label-col" />
        <span className="tl-track">
          {years.map((y) => (
            <span key={y} className="tl-tick" style={{ left: `${pct(Date.UTC(y, 0, 1))}%` }}>
              {y < lastYear ? `’${String(y).slice(2)}` : ""}
            </span>
          ))}
        </span>
      </div>
      {cases.map((c) => {
        const from = toMs(c.admitted);
        const ongoing = c.outcome === "ongoing";
        const to = ongoing || !c.outcome_date ? endAsOf : toMs(c.outcome_date);
        const left = pct(from);
        const width = Math.max(pct(to) - left, 0.6);
        return (
          <div className="tl-row" key={c.id} title={`${c.company}: ${formatDate(c.admitted)} → ${ongoing ? "ongoing" : formatDate(c.outcome_date)} (${duration(from, to)})`}>
            <span className="tl-label-col">{c.company.replace(/ (Ltd|Limited)$/, "")}</span>
            <span className="tl-track">
              {years.map((y) => (
                <span key={y} className="tl-grid" style={{ left: `${pct(Date.UTC(y, 0, 1))}%` }} />
              ))}
              <span
                className={`tl-bar ${ongoing ? "tl-bar-ongoing" : ""}`}
                style={{ left: `${left}%`, width: `${width}%`, background: OUTCOME_META[c.outcome].colorVar }}
              />
              <span
                className="tl-dur"
                style={left + width > 82 ? { right: `${100 - left + 0.8}%` } : { left: `${left + width + 0.8}%` }}
              >
                {duration(from, to)}
                {ongoing ? "+" : ""}
              </span>
            </span>
          </div>
        );
      })}
      <div className="legend tl-legend">
        {OUTCOME_ORDER.map((o) => (
          <span className="legend-item" key={o}>
            <span className="swatch" style={{ background: OUTCOME_META[o].colorVar }} /> {OUTCOME_META[o].label}
          </span>
        ))}
      </div>
    </div>
  );
}

function RecoveryBars({ cases }: { cases: Case[] }) {
  if (cases.length === 0) return <p className="empty-state">No recovery figures for these filters.</p>;
  const rows = [...cases].sort((a, b) => (b.recovery_pct ?? 0) - (a.recovery_pct ?? 0));
  return (
    <div className="hbar-chart" role="img" aria-label="Recovery percentage by case; values are also listed in each case below.">
      {rows.map((c) => (
        <div className="hbar-row" key={c.id} title={c.recovery_note ?? undefined}>
          <span className="hbar-label">{c.company.replace(/ (Ltd|Limited)$/, "")}</span>
          <span className="hbar-track">
            <span className="hbar-zero" style={{ left: 0 }} />
            <span className="hbar-bar" style={{ left: 0, width: `${c.recovery_pct}%` }} />
          </span>
          <span className="hbar-value">~{c.recovery_pct}%</span>
        </div>
      ))}
    </div>
  );
}
