"use client";
import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Plan } from "@/lib/api";
import { readCalculationResult } from "@/lib/calculation-results";
import { CalculationResults } from "./calculation-results";
import { ManagerEvidencePanel } from "./manager-run-evidence";
import { ProcurementEvidence } from "./procurement-evidence";
import { ErrorNotice } from "./workspace";

function CapturedCalculation({ runId }: { runId: string }) {
  const result = useQuery({ queryKey: ["recommendation-calculation", runId], queryFn: async ({ signal }) => readCalculationResult(await api<unknown>(`/manager/runs/${encodeURIComponent(runId)}/calculation-results`, { signal }), runId),
    refetchInterval: q => q.state.data && ["QUEUED", "RUNNING"].includes(q.state.data.run_status) ? 2500 : false });
  if (result.error) return <ErrorNotice error={result.error} retry={() => result.refetch()} />;
  if (result.isPending) return <p role="status">Loading the calculation captured for this recommendation…</p>;
  return <CalculationResults result={result.data} embedded />;
}

export function RecommendationDetails({ plan }: { plan: Plan }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [view, setView] = useState<string | null>(null);
  return <>
    <div className="recommendation-support" aria-label="Recommendation supporting details"><span>Understand this version</span>{["Explanation & evidence", "Forecast & stock projection", "Policy & captured inputs"].map(label => <button key={label} type="button" className="text-action" onClick={() => { setView(label); dialog.current?.showModal(); }}>{label}</button>)}</div>
    <dialog ref={dialog} className="supplier-terms-dialog recommendation-drawer" onClose={() => setView(null)} aria-labelledby="recommendation-detail-title">
      <header className="terms-header"><div><p className="eyebrow">RECOMMENDATION · VERSION {plan.version}</p><h2 id="recommendation-detail-title">{view}</h2></div><button type="button" className="icon-button" aria-label="Close recommendation details" onClick={() => dialog.current?.close()}>✕</button></header>
      <div className="terms-body calculation-display"><p className="scope-note">Details belong to this exact assessment. Closing this panel returns to the same recommendation; approval remains on the main review screen.</p>
        {view === "Explanation & evidence" && <ManagerEvidencePanel runId={plan.run_id} embedded />}
        {view === "Forecast & stock projection" && <CapturedCalculation runId={plan.run_id} />}
        {view === "Policy & captured inputs" && <ProcurementEvidence runId={plan.run_id} />}
      </div>
    </dialog>
  </>;
}
