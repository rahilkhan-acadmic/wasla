"use client";

import { useEffect, useState } from "react";
import { PredictResponse } from "../lib/api";
import { FormValues } from "../lib/financials";
import ScoreForm from "./ScoreForm";
import DemoTickerPicker from "./DemoTickerPicker";
import FinancialsChart from "./FinancialsChart";
import ResultCard from "./ResultCard";

// Split view: inputs on the left, chart and result on the right. Stacks to
// one column on narrow screens (see .split in globals.css).
export default function CompanyScorePage({ onCrumbChange }: { onCrumbChange: (c: string | null) => void }) {
  const [ticker, setTicker] = useState("");
  const [values, setValues] = useState<FormValues>({});
  const [result, setResult] = useState<PredictResponse | null>(null);

  // The breadcrumb's last item is the company that was actually scored.
  useEffect(() => {
    onCrumbChange(result ? result.ticker : null);
  }, [result, onCrumbChange]);

  useEffect(() => () => onCrumbChange(null), [onCrumbChange]);

  return (
    <div className="split">
      <div className="split-left">
        <ScoreForm
          ticker={ticker}
          onTickerChange={setTicker}
          values={values}
          onValuesChange={setValues}
          onResult={setResult}
          onClear={() => {
            setTicker("");
            setValues({});
            setResult(null);
          }}
        />
        <DemoTickerPicker onResult={setResult} />
      </div>
      <div className="split-right">
        <FinancialsChart ticker={ticker} values={values} />
        {result && <ResultCard result={result} />}
      </div>
    </div>
  );
}
