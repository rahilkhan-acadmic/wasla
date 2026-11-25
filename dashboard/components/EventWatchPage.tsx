"use client";

import { useEffect, useMemo, useState } from "react";
import {
  EventIndexStats,
  EventType,
  EventTypeCard,
  EventWatchResponse,
  IndexId,
  UpcomingEvent,
  getEventWatch,
} from "../lib/api";
import CollapsibleCard from "./CollapsibleCard";

// Event Watch: upcoming scheduled macro events (RBI policy, US Fed, Union
// Budget) and, for each, what the past says: how far Nifty usually moved,
// how the strategy rule's trades turned out (win / loss), and a confidence
// score built from visible components. Data: GET /events/watch
// (src/event_watch.py), from the daily-data study in
// doc/event-breakout-strategy.md §6a. Research, not investment advice.

const TYPES: EventType[] = ["rbi_mpc", "fomc", "union_budget"];
const INDEXES: { id: IndexId; label: string }[] = [
  { id: "NIFTY50", label: "Nifty 50" },
  { id: "NIFTYBANK", label: "Nifty Bank" },
];

const pct = (x: number | null | undefined, digits = 2) =>
  x === null || x === undefined ? "—" : `${(x * 100).toFixed(digits)}%`;
const signed = (x: number) => `${x > 0 ? "+" : ""}${(x * 100).toFixed(2)}%`;

function istTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function countdown(iso: string, now: number): string {
  const ms = new Date(iso).getTime() - now;
  if (ms <= 0) return "released";
  const h = Math.floor(ms / 3_600_000);
  const d = Math.floor(h / 24);
  return d >= 1 ? `in ${d} d ${h % 24} h` : `in ${h} h ${Math.floor((ms % 3_600_000) / 60_000)} min`;
}

function formatDay(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

// --- Probable movement: one dot per past event-day move, on a shared axis,
// against the band that holds 80% of ordinary days. One series, so no
// legend box; the caption names the band.
function MoveStrip({ stats }: { stats: EventIndexStats }) {
  const m = stats.movement;
  const max = Math.max(0.02, ...m.each.map((e) => Math.abs(e.ret))) * 1.1;
  const W = 320;
  const H = 46;
  const PAD = 6; // keeps edge dots and axis labels inside the box
  const x = (v: number) => PAD + ((v + max) / (2 * max)) * (W - 2 * PAD);
  const band = m.baseline_abs_ret_p80;
  const ticks = [-max, -max / 2, 0, max / 2, max].map((t) => Math.round(t * 1000) / 1000);
  return (
    <figure className="ew-chart">
      <svg
        viewBox={`0 0 ${W} ${H + 16}`}
        role="img"
        aria-label={`${m.n} past event days: Nifty moves from ${signed(Math.min(...m.each.map((e) => e.ret)))} to ${signed(Math.max(...m.each.map((e) => e.ret)))}; shaded band holds 80% of ordinary days (±${pct(band)}).`}
      >
        <rect x={x(-band)} y={4} width={x(band) - x(-band)} height={H - 8} className="ew-band" />
        <line x1={x(0)} x2={x(0)} y1={2} y2={H - 2} className="ew-zero" />
        {m.each.map((e, i) => (
          <circle
            key={e.event}
            cx={x(e.ret)}
            cy={10 + ((i * 7) % (H - 20))}
            r={4.5}
            className="ew-dot"
          >
            <title>{`${e.event.replace(/^[a-z_]+-/, "")}: ${signed(e.ret)} (range ${pct(e.range)})`}</title>
          </circle>
        ))}
        {ticks.map((t, i) => (
          <text
            key={t}
            x={x(t)}
            y={H + 12}
            textAnchor={i === 0 ? "start" : i === ticks.length - 1 ? "end" : "middle"}
            className="ew-tick"
          >
            {t === 0 ? "0" : `${t > 0 ? "+" : ""}${(t * 100).toFixed(1)}%`}
          </text>
        ))}
      </svg>
      <figcaption className="ew-caption">
        Each dot is one past event day's close-to-close move. Shaded: where 80% of ordinary days fall (±{pct(band)}).
      </figcaption>
    </figure>
  );
}

// --- Strategy record: one square per past trade, oldest first. Win/loss are
// states, so they wear the reserved status colours, with ✓/✕ in the legend
// and the count in text (colour never carries the meaning alone).
function TradeStrip({ stats }: { stats: EventIndexStats }) {
  const r = stats.record;
  return (
    <div className="ew-trades">
      <div className="ew-squares" role="img" aria-label={`${r.wins} wins and ${r.losses} losses, oldest first`}>
        {r.each.map((t) => (
          <span key={t.event} className={`ew-sq ${t.return > 0 ? "ew-win" : "ew-loss"}`} title={`${formatDay(t.date)}: ${signed(t.return)}`} />
        ))}
      </div>
      <div className="ew-legend">
        <span className="zone-label risk-low">
          <span className="zone-icon" aria-hidden="true">✓</span>
          {r.wins} wins
        </span>
        <span className="zone-label risk-high">
          <span className="zone-icon" aria-hidden="true">✕</span>
          {r.losses} losses
        </span>
        <span className="muted-cell">oldest → newest</span>
      </div>
    </div>
  );
}

const COMPONENT_HELP: Record<string, string> = {
  evidence: "Enough past cases (full at 30)",
  edge: "Win rate above ordinary days",
  significance: "Unlikely to be luck (bootstrap)",
  stability: "Held in both halves of history",
};

function Confidence({ stats }: { stats: EventIndexStats }) {
  const c = stats.confidence;
  return (
    <div className="ew-confidence">
      <div className="ew-score">
        <span className="stat-value">{c.score}</span>
        <span className="ew-score-of">/100</span>
        <span className={`chip ew-label-${c.label}`}>{c.label} confidence</span>
      </div>
      <p className="ew-verdict">{c.verdict}</p>
      <ul className="ew-components">
        {Object.entries(c.components).map(([k, v]) => (
          <li key={k} title={COMPONENT_HELP[k]}>
            <span className="ew-comp-name">{k}</span>
            <span className="ew-comp-track" aria-hidden="true">
              <span className="ew-comp-fill" style={{ width: `${Math.round(v * 100)}%` }} />
            </span>
            <span className="ew-comp-val">{v.toFixed(2)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TypePanel({ card, index }: { card: EventTypeCard; index: IndexId }) {
  const stats = card.by_index[index];
  if (!stats) return <p className="muted-note">No data for this index.</p>;
  const m = stats.movement;
  const r = stats.record;
  return (
    <div className="ew-grid">
      <section className="ew-block">
        <h3>Probable movement</h3>
        <p className="ew-big">
          ±{pct(m.abs_ret_p50)} <span className="muted-cell">median</span>
        </p>
        <p className="card-subtitle">
          80% of past {card.label} days moved less than ±{pct(m.abs_ret_p80)} (ordinary days: median ±
          {pct(m.baseline_abs_ret_p50)}, 80% within ±{pct(m.baseline_abs_ret_p80)}). Up {m.up} times, down {m.down}.
          Typical intraday range {pct(m.range_p50)}.
        </p>
        <MoveStrip stats={stats} />
      </section>
      <section className="ew-block">
        <h3>Strategy record</h3>
        <p className="card-subtitle">{card.rule}</p>
        <TradeStrip stats={stats} />
        <p className="card-subtitle">
          Win rate {pct(r.win_rate, 0)} (ordinary days {pct(r.baseline.win_rate, 0)}), average trade{" "}
          {r.avg_return === null ? "—" : signed(r.avg_return)} after {(r.cost_per_trade * 10000).toFixed(0)} bp costs,
          worst {r.worst === null ? "—" : signed(r.worst)}. Daily-data version of the rule; the intraday version needs
          intraday data.
        </p>
      </section>
      <section className="ew-block">
        <h3>Confidence</h3>
        <Confidence stats={stats} />
      </section>
      {card.vix && (
        <section className="ew-block">
          <h3>Volatility</h3>
          <p className="card-subtitle">
            India VIX usually <strong>{card.vix.mean_vix_change_on_day < 0 ? "falls" : "rises"}</strong>{" "}
            {pct(Math.abs(card.vix.mean_vix_change_on_day), 1)} on the day (ordinary days{" "}
            {signed(card.vix.baseline_mean_vix_change)}), after {signed(card.vix.mean_vix_change_3d_before)} over the 3
            days before. Options bought into the event tend to lose that volatility premium.
          </p>
          <p className="muted-note">{card.nse_note}</p>
        </section>
      )}
    </div>
  );
}

function UpcomingCard({ ev, card, index, now }: { ev: UpcomingEvent; card: EventTypeCard; index: IndexId; now: number }) {
  return (
    <section className="card ew-upcoming">
      <div className="overview-title">
        <h2>
          {ev.label} <span className="muted-cell">· {istTime(ev.release_ist)} IST</span>
        </h2>
        <span className="chip">{countdown(ev.release_ist, now)}</span>
      </div>
      <p className="card-subtitle">
        {ev.second_stage_ist ? <>Press conference {istTime(ev.second_stage_ist)} IST. </> : null}
        Nifty reacts in the session of {formatDay(ev.nse_session)}.{" "}
        <a href={ev.source} target="_blank" rel="noopener noreferrer">
          Schedule source
        </a>
      </p>
      <TypePanel card={card} index={index} />
    </section>
  );
}

export default function EventWatchPage() {
  const [data, setData] = useState<EventWatchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState<IndexId>("NIFTY50");
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let cancelled = false;
    getEventWatch()
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : "Could not load Event Watch"));
    const t = setInterval(() => setNow(Date.now()), 60_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  const history = useMemo(() => {
    if (!data) return [];
    const stats = (t: EventType) => data.cards[t].by_index[index];
    return TYPES.flatMap((t) => {
      const s = stats(t);
      if (!s) return [];
      const trades = new Map(s.record.each.map((x) => [x.event, x.return]));
      return s.movement.each.map((m) => ({ ...m, type: data.cards[t].label, trade: trades.get(m.event) }));
    }).sort((a, b) => b.date.localeCompare(a.date));
  }, [data, index]);

  if (error)
    return (
      <section className="card">
        <h2>Event Watch</h2>
        <p className="error-note">{error}</p>
      </section>
    );
  if (!data)
    return (
      <section className="card">
        <h2>Event Watch</h2>
        <p className="muted-note">Loading…</p>
      </section>
    );

  const switcher = (
    <div className="segmented" role="group" aria-label="Index">
      {INDEXES.map((i) => (
        <button key={i.id} type="button" aria-pressed={index === i.id} onClick={() => setIndex(i.id)}>
          {i.label}
        </button>
      ))}
    </div>
  );

  return (
    <div className="overview">
      <section className="card overview-head">
        <div className="overview-title">
          <h2>Event Watch</h2>
          {switcher}
        </div>
        <p className="card-subtitle">
          Scheduled events that move Indian markets (RBI policy, US Fed, Union Budget), with what happened around the
          past {TYPES.reduce((n, t) => n + (data.cards[t].by_index[index]?.movement.n ?? 0), 0)} of them (
          {formatDay(data.study_span[0])} – {formatDay(data.study_span[1])}). {data.disclaimer}
        </p>
        {data.latest_vix && (
          <p className="muted-note">
            India VIX {data.latest_vix.close.toFixed(2)} on {formatDay(data.latest_vix.date)}: higher than{" "}
            {Math.round(data.latest_vix.percentile_5y * 100)}% of the last 5 years’ closes.
          </p>
        )}
      </section>

      {data.upcoming.length === 0 ? (
        <section className="card">
          <p className="muted-note">No scheduled events in the next 60 days (calendar as of {formatDay(data.calendar_as_of)}).</p>
        </section>
      ) : (
        data.upcoming.map((ev) => <UpcomingCard key={ev.id} ev={ev} card={data.cards[ev.type]} index={index} now={now} />)
      )}

      {TYPES.map((t) => (
        <CollapsibleCard key={t} title={`${data.cards[t].label}: all past events`} storageKey={`events-type-${t}`} defaultOpen={false}>
          <TypePanel card={data.cards[t]} index={index} />
        </CollapsibleCard>
      ))}

      <CollapsibleCard title={`Event history (${history.length})`} storageKey="events-history" defaultOpen={false}>
        <div className="table-scroll">
          <table className="data-table compact">
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">Event</th>
                <th scope="col" className="num">Move</th>
                <th scope="col" className="num">Range</th>
                <th scope="col">Strategy trade</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={`${h.event}-${index}`}>
                  <td>{formatDay(h.date)}</td>
                  <td>{h.type}</td>
                  <td className="num">{signed(h.ret)}</td>
                  <td className="num">{pct(h.range)}</td>
                  <td>
                    {h.trade === undefined ? (
                      <span className="muted-cell">no trade</span>
                    ) : (
                      <span className={`zone-label ${h.trade > 0 ? "risk-low" : "risk-high"}`}>
                        <span className="zone-icon" aria-hidden="true">
                          {h.trade > 0 ? "✓" : "✕"}
                        </span>
                        {signed(h.trade)}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleCard>
    </div>
  );
}
