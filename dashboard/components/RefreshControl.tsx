"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshStatus, Universe, getRefreshStatus, startRefresh } from "../lib/api";

// "Refresh now" for an index's market data, next to when it was collected.
// The job runs in the background (NSE ~12 min, S&P 500 ~30 min as 4 parts);
// while it runs this polls its status and, when it finishes, asks the page
// to reload. Sunday's scheduled run shows up here the same way.

const POLL_MS = 20_000;

function time(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function RefreshControl({ universe, onFinished }: { universe: Universe; onFinished: () => void }) {
  const [status, setStatus] = useState<RefreshStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const wasRunning = useRef(false);

  const load = useCallback(async () => {
    try {
      const s = await getRefreshStatus(universe);
      setStatus(s);
      setError(null);
      if (wasRunning.current && s.state === "done") onFinished();
      wasRunning.current = s.state === "running";
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read the refresh status");
    }
  }, [universe, onFinished]);

  useEffect(() => {
    wasRunning.current = false;
    setStatus(null);
    void load();
  }, [load]);

  const running = status?.state === "running";
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(t);
  }, [running, load]);

  async function refresh() {
    setStarting(true);
    setError(null);
    try {
      const s = await startRefresh(universe);
      setStatus(s);
      wasRunning.current = s.state === "running";
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the refresh");
    } finally {
      setStarting(false);
    }
  }

  const minutes = status?.expected_minutes;
  let note: React.ReactNode = "Refreshes automatically every Sunday.";
  if (status?.state === "running") {
    note = (
      <>
        Refreshing{status.trigger === "scheduled" ? " (weekly run)" : ""}: started {time(status.started_at)}
        {status.progress ? `, ${status.progress}` : ""}. Usually takes about {minutes} minutes; this page updates
        when it’s done.
      </>
    );
  } else if (status?.state === "failed") {
    note = <span className="error-note">Last refresh failed: {status.error ?? "unknown error"}</span>;
  } else if (status?.state === "stale") {
    note = "The last refresh stopped without finishing. You can start a new one.";
  } else if (status?.state === "done" && status.finished_at) {
    note = (
      <>
        Last refresh finished {new Date(status.finished_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}
        {status.trigger === "manual" ? " (manual)" : ""}. Refreshes automatically every Sunday.
      </>
    );
  }

  return (
    <div className="refresh-control">
      <button
        type="button"
        className="refresh-button"
        onClick={refresh}
        disabled={!status || running || starting}
        aria-describedby={`refresh-note-${universe}`}
      >
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" className={running || starting ? "spin" : undefined}>
          <path
            d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v3h-3"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        {running ? "Refreshing…" : starting ? "Starting…" : `Refresh now${minutes ? ` (~${minutes} min)` : ""}`}
      </button>
      <span id={`refresh-note-${universe}`} className="refresh-note" aria-live="polite">
        {error ? <span className="error-note">{error}</span> : note}
      </span>
    </div>
  );
}
