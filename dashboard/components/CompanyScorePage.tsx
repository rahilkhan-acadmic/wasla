"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CompaniesResponse,
  CompanyFinancials,
  CompanySummary,
  LookupResponse,
  PredictResponse,
  getCompanies,
  getCompany,
  lookupTicker,
} from "../lib/api";
import { FormValues, OPTIONAL_FIELDS, REQUIRED_FIELDS } from "../lib/financials";
import ScoreForm from "./ScoreForm";
import TickerCombobox from "./TickerCombobox";
import DemoTickerPicker from "./DemoTickerPicker";
import FinancialsChart from "./FinancialsChart";
import ResultCard from "./ResultCard";

const LOOKUP_DEBOUNCE_MS = 700;
const TICKER_RE = /^[A-Za-z0-9][A-Za-z0-9&-]{1,19}(\.[A-Za-z]{1,3})?$/;

const FIELD_LABELS: Record<string, string> = Object.fromEntries([...REQUIRED_FIELDS, ...OPTIONAL_FIELDS]);

function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

function toFormValues(c: CompanyFinancials): FormValues {
  const v: FormValues = {};
  for (const [key] of [...REQUIRED_FIELDS, ...OPTIONAL_FIELDS]) {
    const n = c.financials[key];
    if (n !== null && n !== undefined) v[key] = String(n);
  }
  return v;
}

type LookupState =
  | { kind: "idle" }
  | { kind: "searching"; query: string }
  | { kind: "prompt"; data: LookupResponse }
  | { kind: "notfound"; query: string }
  | { kind: "error"; message: string };

// Split view: inputs on the left, chart and result on the right. Stacks to
// one column on narrow screens (see .split in globals.css).
export default function CompanyScorePage({ onCrumbChange }: { onCrumbChange: (c: string | null) => void }) {
  const [ticker, setTicker] = useState("");
  const [values, setValues] = useState<FormValues>({});
  const [result, setResult] = useState<PredictResponse | null>(null);

  const [list, setList] = useState<CompaniesResponse | null>(null);
  const [listError, setListError] = useState(false);
  const [filled, setFilled] = useState<{ company: CompanyFinancials; edited: boolean } | null>(null);
  const [loadingCompany, setLoadingCompany] = useState<string | null>(null);
  const [lookup, setLookup] = useState<LookupState>({ kind: "idle" });

  // Only text the user typed is searched; picking from the list sets this to
  // null so a selection never triggers a second, redundant lookup.
  const [typedQuery, setTypedQuery] = useState<string | null>(null);
  const declined = useRef(new Set<string>());
  const lookupSeq = useRef(0);

  useEffect(() => {
    onCrumbChange(result ? result.ticker : null);
  }, [result, onCrumbChange]);
  useEffect(() => () => onCrumbChange(null), [onCrumbChange]);

  useEffect(() => {
    let cancelled = false;
    getCompanies()
      .then((r) => !cancelled && setList(r))
      .catch(() => !cancelled && setListError(true));
    return () => {
      cancelled = true;
    };
  }, []);

  const applyFill = useCallback((c: CompanyFinancials) => {
    setValues(toFormValues(c));
    setFilled({ company: c, edited: false });
    setResult(null);
  }, []);

  async function handleSelect(c: CompanySummary) {
    setTicker(c.symbol);
    setTypedQuery(null);
    setLookup({ kind: "idle" });
    setLoadingCompany(c.symbol);
    try {
      applyFill(await getCompany(c.symbol));
    } catch (err) {
      setLookup({ kind: "error", message: err instanceof Error ? err.message : "Could not load company data" });
    } finally {
      setLoadingCompany(null);
    }
  }

  function handleTyped(text: string) {
    setTicker(text);
    setTypedQuery(text);
    if (lookup.kind !== "idle") setLookup({ kind: "idle" });
  }

  // Debounced background search for a typed ticker.
  useEffect(() => {
    const q = typedQuery?.trim().toUpperCase() ?? "";
    if (!q || !TICKER_RE.test(q) || declined.current.has(q)) return;
    if (filled && filled.company.symbol === q) return;
    const seq = ++lookupSeq.current;
    const timer = setTimeout(async () => {
      setLookup({ kind: "searching", query: q });
      try {
        const r = await lookupTicker(q);
        if (seq !== lookupSeq.current) return; // a newer keystroke won
        setLookup(r.found && r.company ? { kind: "prompt", data: r } : { kind: "notfound", query: q });
      } catch (err) {
        if (seq !== lookupSeq.current) return;
        setLookup({ kind: "error", message: err instanceof Error ? err.message : "Search failed" });
      }
    }, LOOKUP_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [typedQuery, filled]);

  const listHint = listError ? (
    "Company list unavailable right now; you can still type any ticker."
  ) : list && !list.available ? (
    "The NSE company list is being prepared (first weekly refresh). You can still type any ticker."
  ) : list?.available ? (
    <>
      {list.companies.length} companies from the {list.index}, refreshed {formatDate(list.generated_at)}.
    </>
  ) : (
    "Loading company list…"
  );

  let notice: React.ReactNode = null;
  if (loadingCompany) {
    notice = <p className="notice notice-info">Loading {loadingCompany}’s latest figures…</p>;
  } else if (lookup.kind === "searching") {
    notice = <p className="notice notice-info">Searching online for {lookup.query}…</p>;
  } else if (lookup.kind === "prompt" && lookup.data.company) {
    const c = lookup.data.company;
    notice = (
      <div className="notice notice-prompt" role="alert">
        <p>
          <strong>Data available</strong> for {c.name} ({c.yahoo_ticker})
          {c.as_of && <>, financial year ending {formatDate(c.as_of)}</>}. Do you want to autopopulate the fields?
        </p>
        <div className="notice-actions">
          <button
            type="button"
            className="button-primary"
            onClick={() => {
              applyFill(c);
              setLookup({ kind: "idle" });
              setTypedQuery(null);
            }}
          >
            Yes, fill in
          </button>
          <button
            type="button"
            onClick={() => {
              declined.current.add(lookup.data.query);
              setLookup({ kind: "idle" });
            }}
          >
            No
          </button>
        </div>
      </div>
    );
  } else if (lookup.kind === "notfound") {
    notice = (
      <p className="notice notice-info">No online data found for {lookup.query}. Enter the figures manually.</p>
    );
  } else if (lookup.kind === "error") {
    notice = <p className="notice notice-error">{lookup.message}</p>;
  }

  // The ticker box no longer names the company the figures came from.
  const typed = ticker.trim().toUpperCase();
  const stale = !!filled && typed !== filled.company.symbol && typed !== filled.company.yahoo_ticker;

  const sourceNote = filled && (
    <div className="source-note">
      {stale && (
        <p className="source-missing">
          These figures are still {filled.company.name}’s, not {typed || "the ticker above"}. Pick or confirm a
          company to replace them, or press Clear.
        </p>
      )}
      <p>
        <strong>{filled.company.name}</strong> ({filled.company.yahoo_ticker})
        {filled.company.as_of && <> · FY ending {formatDate(filled.company.as_of)}</>}
        {filled.company.currency && <> · {filled.company.currency}</>} · Yahoo Finance,{" "}
        {filled.company.source === "snapshot"
          ? `weekly snapshot of ${formatDate(filled.company.fetched_at)}`
          : "fetched just now"}
        {filled.edited && <> · edited by you</>}
      </p>
      {filled.company.missing.length > 0 && (
        <p className="source-missing">
          Not available from the source, please enter:{" "}
          {filled.company.missing.map((m) => FIELD_LABELS[m] ?? m).join(", ")}.
        </p>
      )}
    </div>
  );

  return (
    <div className="split">
      <div className="split-left">
        <ScoreForm
          ticker={ticker}
          tickerField={
            <TickerCombobox
              value={ticker}
              onChange={handleTyped}
              onSelect={handleSelect}
              companies={list?.companies ?? []}
              hint={listHint}
            />
          }
          notice={
            <>
              {notice}
              {sourceNote}
            </>
          }
          values={values}
          currency={filled?.company.currency ?? null}
          onValuesChange={(v) => {
            setValues(v);
            if (filled && !filled.edited) setFilled({ ...filled, edited: true });
          }}
          onResult={setResult}
          onClear={() => {
            setTicker("");
            setValues({});
            setResult(null);
            setFilled(null);
            setTypedQuery(null);
            setLookup({ kind: "idle" });
          }}
        />
        <DemoTickerPicker onResult={setResult} />
      </div>
      <div className="split-right">
        <FinancialsChart
          // Title the chart after the company whose figures are shown.
          ticker={filled ? filled.company.symbol : ticker}
          values={values}
          currency={filled?.company.currency ?? null}
          asOf={filled ? formatDate(filled.company.as_of) : null}
        />
        {result && <ResultCard result={result} />}
      </div>
    </div>
  );
}
