"use client";

import { useEffect, useState } from "react";
import { getHealth, getModelInfo, HealthResponse, ModelInfoResponse } from "../lib/api";

export default function ModelInfoPage() {
  const [info, setInfo] = useState<ModelInfoResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getModelInfo(), getHealth()])
      .then(([i, h]) => {
        if (cancelled) return;
        setInfo(i);
        setHealth(h);
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Request failed"));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="card">
      <h2>Model Info</h2>
      {error && <p className="error-note">{error}</p>}
      {!error && !info && <p className="muted-note">Loading…</p>}
      {info && (
        <dl className="kv">
          <dt>API status</dt>
          <dd>{health?.status ?? "unknown"}</dd>
          <dt>Model version</dt>
          <dd>{info.version ?? "unknown"}</dd>
          <dt>Last promoted</dt>
          <dd>{info.promoted_at ? new Date(info.promoted_at).toLocaleString() : "—"}</dd>
          <dt>Registry</dt>
          <dd>{info.registry_configured ? "Configured" : "Not configured"}</dd>
        </dl>
      )}
      <p className="muted-note">
        Retrained weekly on public filings (US SEC EDGAR, plus smaller India, UK and China sets) and promoted only if
        it beats the current model on held-out data. Evaluation history will be shown here in a later release.
      </p>
    </section>
  );
}
