"use client";

// Hash-based page routing. The dashboard is a static export served from S3
// behind CloudFront with only a DefaultRootObject (no rewrite function), so
// a real path like /market would 403. Routes live after the hash instead:
// /#/score, /#/market, ... -- all served by the single index.html.

import { useEffect, useState } from "react";

export type RouteId = "score" | "market" | "insolvency" | "model";

export interface RouteDef {
  id: RouteId;
  label: string;
  // Pages planned in doc/PROGRESS_STATUS.md but not built yet. Shown in the
  // nav so the structure is visible, marked "Soon".
  comingSoon?: boolean;
}

export const ROUTES: RouteDef[] = [
  { id: "score", label: "Company Score" },
  { id: "market", label: "Market Overview" },
  { id: "insolvency", label: "Insolvency Watch" },
  { id: "model", label: "Model Info" },
];

export const DEFAULT_ROUTE: RouteId = "score";

export interface Location {
  route: RouteId;
  // Optional second segment, e.g. the ticker in #/score/RELIANCE.
  param: string | null;
}

function parseHash(hash: string): Location {
  const [id, param] = hash.replace(/^#\/?/, "").split("/");
  const route = ROUTES.some((r) => r.id === id) ? (id as RouteId) : DEFAULT_ROUTE;
  let decoded: string | null = null;
  try {
    decoded = param ? decodeURIComponent(param) : null;
  } catch {
    decoded = null; // malformed escape in a hand-edited URL
  }
  return { route, param: decoded };
}

export function routeHref(id: RouteId, param?: string): string {
  return param ? `#/${id}/${encodeURIComponent(param)}` : `#/${id}`;
}

export function useHashRoute(): Location {
  const [loc, setLoc] = useState<Location>({ route: DEFAULT_ROUTE, param: null });

  useEffect(() => {
    const sync = () => setLoc(parseHash(window.location.hash));
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  return loc;
}
