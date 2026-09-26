"use client";
import { useState } from "react";
import Link from "next/link";
import { PageHeading } from "@/components/workspace";
import { EconomicsResultView, ForecastResultView, ProjectionResultView, WastePreparationForm } from "@/components/prepared-feature-views";

/** Intentionally absent from demo navigation; no guessed endpoint or sample data. */
export default function PreparationPage() {
  const [tab, setTab] = useState("Forecast results");
  return <>
    <PageHeading eyebrow="INTEGRATION PREPARATION · NOT A WORKING DEMO" title="Pending feature views" description="Frontend preparation for team review. These features are not connected or represented as complete." />
    <Link href="/workspace/overview">Return to the working workspace →</Link>
    <div className="tabs" role="tablist" aria-label="Prepared features">
      {["Forecast results", "Stock projections", "Waste entry", "Economic results"].map(t => <button role="tab" aria-selected={tab === t} aria-controls="preparation-panel" id={`preparation-${t.replaceAll(" ", "-")}`} key={t} onClick={() => setTab(t)}>{t}</button>)}
    </div>
    <div key={tab} id="preparation-panel" role="tabpanel" aria-labelledby={`preparation-${tab.replaceAll(" ", "-")}`} className="panel"><header className="panel-head"><h2>{tab}</h2></header><div className="panel-body">
      {tab === "Forecast results" && <ForecastResultView result={{ state: "not-connected" }} />}
      {tab === "Stock projections" && <ProjectionResultView result={{ state: "not-connected" }} />}
      {tab === "Waste entry" && <WastePreparationForm />}
      {tab === "Economic results" && <EconomicsResultView result={{ state: "not-connected" }} />}
    </div></div>
  </>;
}
