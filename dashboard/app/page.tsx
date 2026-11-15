"use client";

import { useState } from "react";
import AppShell from "../components/AppShell";
import CompanyScorePage from "../components/CompanyScorePage";
import ComingSoonPage from "../components/ComingSoonPage";
import ModelInfoPage from "../components/ModelInfoPage";
import { useHashRoute } from "../lib/routes";

export default function Page() {
  const route = useHashRoute();
  const [crumb, setCrumb] = useState<string | null>(null);

  return (
    <AppShell route={route} extraCrumb={route === "score" ? crumb : null}>
      {route === "score" && <CompanyScorePage onCrumbChange={setCrumb} />}
      {route === "market" && <ComingSoonPage page="market" />}
      {route === "insolvency" && <ComingSoonPage page="insolvency" />}
      {route === "model" && <ModelInfoPage />}
    </AppShell>
  );
}
