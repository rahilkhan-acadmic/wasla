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
  { id: "market", label: "Market Overview", comingSoon: true },
  { id: "insolvency", label: "Insolvency Watch", comingSoon: true },
  { id: "model", label: "Model Info" },
];

export const DEFAULT_ROUTE: RouteId = "score";

function parseHash(hash: string): RouteId {
  const id = hash.replace(/^#\/?/, "").split("/")[0];
  return ROUTES.some((r) => r.id === id) ? (id as RouteId) : DEFAULT_ROUTE;
}

export function routeHref(id: RouteId): string {
  return `#/${id}`;
}

export function useHashRoute(): RouteId {
  const [route, setRoute] = useState<RouteId>(DEFAULT_ROUTE);

  useEffect(() => {
    const sync = () => setRoute(parseHash(window.location.hash));
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  return route;
}
