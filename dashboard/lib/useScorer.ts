"use client";

import { useCallback, useRef, useState } from "react";
import { predict, PredictRequest, PredictResponse } from "./api";
import { FormValues, OPTIONAL_FIELDS, REQUIRED_FIELDS, parseValue } from "./financials";

// One place that calls /predict for the Company Score page, so the same
// inputs are never scored twice:
//   * a request identical to the one behind the result on screen is skipped
//     ("unchanged") -- the Score button can't re-send it;
//   * an identical request already in flight is joined, not re-sent
//     (double-click, auto-score + click);
//   * if the inputs change while a request is in flight, the late response
//     for the old inputs is dropped rather than overwriting the newer one.
// Dedup lives here rather than in the HTTP verb: switching POST to PUT
// would only declare the call safe to repeat; the browser would still send
// every duplicate. Scoring has no side effects, so POST /predict stays.

export type ScoreOutcome = "scored" | "unchanged" | "joined" | "error" | "incomplete";

export function buildRequest(ticker: string, values: FormValues, headlinesText: string): PredictRequest | null {
  const t = ticker.trim();
  if (!t) return null;
  const financials: Record<string, number> = {};
  for (const [key] of REQUIRED_FIELDS) {
    const v = parseValue(values[key]);
    if (v === null) return null;
    financials[key] = v;
  }
  for (const [key] of OPTIONAL_FIELDS) {
    const v = parseValue(values[key]);
    if (v !== null) financials[key] = v;
  }
  const headlines = headlinesText
    .split("\n")
    .map((h) => h.trim())
    .filter(Boolean);
  return { ticker: t, financials: financials as unknown as PredictRequest["financials"], headlines };
}

/** Stable fingerprint: key order and "1e3" vs "1000" don't matter. */
export function requestSignature(req: PredictRequest): string {
  const fin = Object.entries(req.financials as unknown as Record<string, number>).sort(([a], [b]) =>
    a.localeCompare(b)
  );
  return JSON.stringify([req.ticker.toUpperCase(), fin, req.headlines]);
}

export function useScorer() {
  const [result, setResult] = useState<PredictResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Signature of the inputs behind `result` (null for demo results, which
  // don't come from the form).
  const [scoredSignature, setScoredSignature] = useState<string | null>(null);

  const inFlight = useRef<{ sig: string; promise: Promise<ScoreOutcome> } | null>(null);
  const latestSig = useRef<string | null>(null);

  const score = useCallback(
    (req: PredictRequest | null): Promise<ScoreOutcome> => {
      if (!req) return Promise.resolve("incomplete");
      const sig = requestSignature(req);
      if (sig === scoredSignature && result) return Promise.resolve("unchanged");
      if (inFlight.current?.sig === sig) {
        return inFlight.current.promise.then((o) => (o === "scored" ? "joined" : o));
      }

      latestSig.current = sig;
      setLoading(true);
      setError(null);
      const promise = predict(req)
        .then((r): ScoreOutcome => {
          if (latestSig.current !== sig) return "scored"; // superseded; newer request owns the UI
          setResult(r);
          setScoredSignature(sig);
          return "scored";
        })
        .catch((e): ScoreOutcome => {
          if (latestSig.current === sig) {
            setError(e instanceof Error ? e.message : "Request failed");
            setResult(null);
            setScoredSignature(null);
          }
          return "error";
        })
        .finally(() => {
          if (inFlight.current?.sig === sig) inFlight.current = null;
          if (latestSig.current === sig) setLoading(false);
        });
      inFlight.current = { sig, promise };
      return promise;
    },
    [scoredSignature, result]
  );

  const reset = useCallback(() => {
    latestSig.current = null;
    inFlight.current = null;
    setResult(null);
    setScoredSignature(null);
    setError(null);
    setLoading(false);
  }, []);

  return { result, error, loading, scoredSignature, score, reset };
}
