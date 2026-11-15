"use client";

import { useState } from "react";
import AppShell from "../components/AppShell";
import CompanyScorePage from "../components/CompanyScorePage";
import InsolvencyWatchPage from "../components/InsolvencyWatchPage";
import MarketOverviewPage from "../components/MarketOverviewPage";
import ModelInfoPage from "../components/ModelInfoPage";
import { isUniverse } from "../lib/api";
import { useHashRoute } from "../lib/routes";

export default function Page() {
  const { route, param, sub } = useHashRoute();
  const [crumb, setCrumb] = useState<string | null>(null);

  return (
    <AppShell route={route} extraCrumb={route === "score" ? crumb : null}>
      {route === "score" && (
        <CompanyScorePage
          onCrumbChange={setCrumb}
          initialSymbol={param}
          initialUniverse={isUniverse(sub) ? sub : "nse"}
        />
      )}
      {route === "market" && <MarketOverviewPage universe={isUniverse(param) ? param : "nse"} />}
      {route === "insolvency" && <InsolvencyWatchPage />}
      {route === "model" && <ModelInfoPage />}
    </AppShell>
  );
}
