"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CompaniesResponse,
  CompanyFinancials,
  CompanySummary,
  SearchResult,
  getCompanies,
  getCompany,
  lookupTicker,
  searchCompanies,
} from "../lib/api";
import { FormValues, OPTIONAL_FIELDS, REQUIRED_FIELDS } from "../lib/financials";
import ScoreForm from "./ScoreForm";
import TickerCombobox from "./TickerCombobox";
import DemoTickerPicker from "./DemoTickerPicker";
import FinancialsChart from "./FinancialsChart";
import ResultCard from "./ResultCard";
import MarketStatusCard from "./MarketStatusCard";
import { buildRequest, requestSignature, useScorer } from "../lib/useScorer";

const SEARCH_DEBOUNCE_MS = 400;
// Backend search starts at 3 characters (ticker matching; name matching
// from 5 -- see src/market_data.py). Below that the index list filters
// locally, with no request.
const MIN_SEARCH_CHARS = 3;
const QUERY_RE = /^[A-Za-z0-9][A-Za-z0-9 &.\-']{2,39}$/;
const MAX_LOCAL_OPTIONS = 50;

function asResult(c: CompanySummary): SearchResult {
  return {
    symbol: c.symbol,
    yahoo_ticker: `${c.symbol}.NS`,
    name: c.name,
    exchange: "NSE",
    industry: c.industry,
    in_index: true,
    has_financials: c.has_financials,
  };
}

/** 1-2 typed characters: rank index members locally (symbol first). */
function localMatches(companies: CompanySummary[], text: string): SearchResult[] {
  const q = text.trim().toUpperCase();
  if (!q) return companies.slice(0, MAX_LOCAL_OPTIONS).map(asResult);
  return companies
    .filter((c) => c.symbol.startsWith(q))
    .slice(0, MAX_LOCAL_OPTIONS)
    .map(asResult);
}

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

type SearchState =
  | { kind: "idle" }
  | { kind: "searching"; query: string }
  | { kind: "done"; query: string; results: SearchResult[]; onlineOk: boolean }
  | { kind: "error"; query: string; message: string };

// Split view: inputs on the left, chart and result on the right. Stacks to
// one column on narrow screens (see .split in globals.css).
export default function CompanyScorePage({
  onCrumbChange,
  initialSymbol = null,
}: {
  onCrumbChange: (c: string | null) => void;
  // From #/score/<SYMBOL>, e.g. a click in Market Overview's table.
  initialSymbol?: string | null;
}) {
  const [ticker, setTicker] = useState("");
  const [values, setValues] = useState<FormValues>({});
  const [headlines, setHeadlines] = useState("");
  const scorer = useScorer();
  const { result } = scorer;
  // Set by an auto-fill: score as soon as the filled values have rendered.
  const autoScorePending = useRef(false);

  const [list, setList] = useState<CompaniesResponse | null>(null);
  const [listError, setListError] = useState(false);
  const [filled, setFilled] = useState<{ company: CompanyFinancials; edited: boolean } | null>(null);
  const [loadingCompany, setLoadingCompany] = useState<string | null>(null);
  const [search, setSearch] = useState<SearchState>({ kind: "idle" });
  const [notice, setNotice] = useState<{ kind: "info" | "error"; text: React.ReactNode } | null>(null);

  // Only text the user typed is searched; picking an option sets this to
  // null so a selection never triggers a second, redundant search.
  const [typedQuery, setTypedQuery] = useState<string | null>(null);
  const searchSeq = useRef(0);
  // The single-match auto-fill fires once per company, not on every
  // further keystroke that still matches only it.
  const autoFilledFor = useRef<string | null>(null);
  const [closeList, setCloseList] = useState(0);

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
    autoScorePending.current = true;
  }, []);

  const request = buildRequest(ticker, values, headlines);
  const unchanged = !!request && !!result && requestSignature(request) === scorer.scoredSignature;
  // A result is on screen but the inputs have moved on since it was scored.
  const resultStale = !!result && scorer.scoredSignature !== null && !unchanged;

  // Score right after an auto-fill, once its values are in state. Skipped
  // when the source lacked a required figure: the user fills it in, then
  // presses Score.
  useEffect(() => {
    if (!autoScorePending.current) return;
    autoScorePending.current = false;
    if (request) void scorer.score(request);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values, ticker]);

  /** Load an option's latest figures into the form (then auto-score). */
  async function handleSelect(r: SearchResult, how: "picked" | "only-match" = "picked") {
    setTicker(r.symbol);
    setTypedQuery(null);
    setSearch({ kind: "idle" });
    setNotice(null);
    setCloseList((n) => n + 1);
    setLoadingCompany(r.name || r.symbol);
    try {
      if (r.in_index) {
        applyFill(await getCompany(r.symbol));
      } else {
        const found = await lookupTicker(r.yahoo_ticker);
        if (!found.found || !found.company) {
          setNotice({
            kind: "info",
            text: <>No financial statements available online for {r.name}. Enter the figures manually.</>,
          });
          return;
        }
        applyFill(found.company);
      }
      if (how === "only-match") {
        setNotice({ kind: "info", text: <>Only one match, <strong>{r.name}</strong>: its figures are filled in.</> });
      }
    } catch (err) {
      setNotice({ kind: "error", text: err instanceof Error ? err.message : "Could not load company data" });
    } finally {
      setLoadingCompany(null);
    }
  }

  function handleTyped(text: string) {
    setTicker(text);
    setTypedQuery(text);
    setNotice(null);
    if (text.trim().length < MIN_SEARCH_CHARS) {
      setSearch({ kind: "idle" });
      autoFilledFor.current = null;
    }
  }

  // Arriving via #/score/<SYMBOL>: load that company as if picked from the list.
  const openedSymbol = useRef<string | null>(null);
  useEffect(() => {
    const sym = initialSymbol?.trim().toUpperCase();
    if (!sym || openedSymbol.current === sym) return;
    openedSymbol.current = sym;
    const known = list?.companies.find((c) => c.symbol === sym);
    void handleSelect(
      known ? asResult(known) : { symbol: sym, yahoo_ticker: `${sym}.NS`, name: sym, exchange: "NSE",
        industry: null, in_index: true, has_financials: true }
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSymbol]);

  // Debounced backend search: ticker from 3 characters, name from 5.
  // Exactly one result is loaded straight into the form.
  useEffect(() => {
    const q = typedQuery?.trim().replace(/\s+/g, " ") ?? "";
    if (q.length < MIN_SEARCH_CHARS || !QUERY_RE.test(q)) return;
    const seq = ++searchSeq.current;
    const timer = setTimeout(async () => {
      setSearch({ kind: "searching", query: q });
      try {
        const r = await searchCompanies(q);
        if (seq !== searchSeq.current) return; // a newer keystroke won
        setSearch({ kind: "done", query: q, results: r.results, onlineOk: r.online_ok });
        if (r.results.length === 1 && autoFilledFor.current !== r.results[0].yahoo_ticker) {
          autoFilledFor.current = r.results[0].yahoo_ticker;
          void handleSelect(r.results[0], "only-match");
        }
      } catch (err) {
        if (seq !== searchSeq.current) return;
        setSearch({ kind: "error", query: q, message: err instanceof Error ? err.message : "Search failed" });
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typedQuery]);

  const typedLen = typedQuery?.trim().length ?? 0;
  const options: SearchResult[] =
    typedQuery !== null && typedLen >= MIN_SEARCH_CHARS
      ? search.kind === "done"
        ? search.results
        : []
      : localMatches(list?.companies ?? [], typedQuery ?? "");
  const listStatus: React.ReactNode =
    typedQuery === null || typedLen < MIN_SEARCH_CHARS
      ? null
      : search.kind === "searching" || search.kind === "idle"
        ? "Searching…"
        : search.kind === "error"
          ? `Search failed: ${search.message}`
          : search.results.length === 0
            ? `No companies found for “${search.query}”.`
            : !search.onlineOk
              ? "Online search unavailable; showing index matches only."
              : null;

  const listHint = listError ? (
    "Company list unavailable right now; you can still search any ticker or name."
  ) : list && !list.available ? (
    "The NSE company list is being prepared (first weekly refresh). You can still search any ticker or name."
  ) : list?.available ? (
    <>
      {list.companies.length} companies from the {list.index}, refreshed {formatDate(list.generated_at)}.
    </>
  ) : (
    "Loading company list…"
  );

  const noticeEl: React.ReactNode = loadingCompany ? (
    <p className="notice notice-info">Loading {loadingCompany}’s latest figures…</p>
  ) : notice ? (
    <p className={`notice notice-${notice.kind}`}>{notice.text}</p>
  ) : null;

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
      {filled.company.note && <p className="source-missing">{filled.company.note}</p>}
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
          tickerField={
            <TickerCombobox
              value={ticker}
              onChange={handleTyped}
              onSelect={(r) => void handleSelect(r)}
              options={options}
              status={listStatus}
              hint={listHint}
              closeSignal={closeList}
            />
          }
          notice={
            <>
              {noticeEl}
              {sourceNote}
            </>
          }
          values={values}
          currency={filled?.company.currency ?? null}
          onValuesChange={(v) => {
            setValues(v);
            if (filled && !filled.edited) setFilled({ ...filled, edited: true });
          }}
          headlines={headlines}
          onHeadlinesChange={setHeadlines}
          canScore={!!request}
          unchanged={unchanged}
          loading={scorer.loading}
          error={scorer.error}
          onScore={() => void scorer.score(request)}
          onClear={() => {
            setTicker("");
            setValues({});
            setHeadlines("");
            scorer.reset();
            autoScorePending.current = false;
            setFilled(null);
            setTypedQuery(null);
            setSearch({ kind: "idle" });
            setNotice(null);
            autoFilledFor.current = null;
          }}
        />
        <DemoTickerPicker onResult={scorer.showExternal} />
      </div>
      <div className="split-right">
        <FinancialsChart
          // Title the chart after the company whose figures are shown.
          ticker={filled ? filled.company.symbol : ticker}
          values={values}
          currency={filled?.company.currency ?? null}
          asOf={filled ? formatDate(filled.company.as_of) : null}
        />
        {result && <ResultCard result={result} stale={resultStale} />}
      </div>
      <div className="split-market">
        <MarketStatusCard result={result} />
      </div>
    </div>
  );
}
