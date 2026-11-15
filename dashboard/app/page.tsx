"use client";

import { useState } from "react";
import AppShell from "../components/AppShell";
import CompanyScorePage from "../components/CompanyScorePage";
import InsolvencyWatchPage from "../components/InsolvencyWatchPage";
import MarketOverviewPage from "../components/MarketOverviewPage";
import ModelInfoPage from "../components/ModelInfoPage";
import { useHashRoute } from "../lib/routes";

export default function Page() {
  const { route, param } = useHashRoute();
  const [crumb, setCrumb] = useState<string | null>(null);

  return (
    <AppShell route={route} extraCrumb={route === "score" ? crumb : null}>
      {route === "score" && <CompanyScorePage onCrumbChange={setCrumb} initialSymbol={param} />}
      {route === "market" && <MarketOverviewPage />}
      {route === "insolvency" && <InsolvencyWatchPage />}
      {route === "model" && <ModelInfoPage />}
    </AppShell>
  );
}
