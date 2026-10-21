"use client";

import { useEffect, useState } from "react";
import { getHealth, getModelInfo, ModelInfoResponse } from "../lib/api";

export default function ModelStatusPanel() {
  const [info, setInfo] = useState<ModelInfoResponse | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getModelInfo(), getHealth()])
      .then(([modelInfo]) => {
        if (cancelled) return;
        if (!modelInfo.registry_configured) {
          setUnavailable(true);
          return;
        }
        setInfo(modelInfo);
      })
      .catch(() => {
        if (!cancelled) setUnavailable(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (unavailable) {
    return <div className="status-panel status-unavailable">Model status unavailable</div>;
  }

  if (!info) {
    return <div className="status-panel">Loading model status...</div>;
  }

  return (
    <div className="status-panel">
      <span className="status-dot status-dot-live" />
      Model version: {info.version ?? "unknown"}
      {info.promoted_at && (
        <>
          {" "}
          &middot; Last promoted: {new Date(info.promoted_at).toLocaleString()}
        </>
      )}
    </div>
  );
}
