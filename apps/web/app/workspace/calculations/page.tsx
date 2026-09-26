"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Run } from "@/lib/api";
import { readCalculationResult } from "@/lib/calculation-results";
import { CalculationResults } from "@/components/calculation-results";
import { ErrorNotice, PageHeading } from "@/components/workspace";
import { humanize, singaporeTime } from "@/lib/format";

export default function CalculationsPage() {
  const [run, setRun] = useState("");
  const runs = useQuery({ queryKey: ["runs"], queryFn: ({ signal }) => api<Run[]>("/runs", { signal }) });
  const output = useQuery({ queryKey: ["manager-calculation-results", run], enabled: !!run,
    queryFn: async ({ signal }) => readCalculationResult(await api<unknown>(`/manager/runs/${encodeURIComponent(run)}/calculation-results`, { signal }), run) });
  return <>
    <PageHeading eyebrow="STOCK & SALES" title="Forecast & projections" description="Inspect the demand and stock calculations frozen for a particular assessment. No calculation is rerun here." />
    <section className="panel calculation-display"><div className="panel-body">
      <label className="field-label">Assessment<select value={run} onChange={e => setRun(e.target.value)} disabled={runs.isPending}><option value="">Choose an assessment</option>{runs.data?.map(r => <option key={r.id} value={r.id}>{singaporeTime(r.as_of)} · {humanize(r.trigger)} · {humanize(r.status)} · {r.id.slice(0, 8)}</option>)}</select></label>
      {runs.isPending && <p role="status">Loading assessments…</p>}
      {runs.error && <ErrorNotice error={runs.error} />}
      {runs.isSuccess && !runs.data.length && <p>No assessments recorded yet. Request one in Activity.</p>}
      {!run && <p>Select the exact assessment you want to inspect. Results are never silently replaced with a newer calculation.</p>}
      {!!run && output.isPending && <p role="status">Loading stored calculation…</p>}
      {output.error && <><ErrorNotice error={output.error} /><button className="button button-secondary" onClick={() => output.refetch()}>Retry stored result</button></>}
      {!!run && !output.error && !output.isPending && output.data && <CalculationResults key={run} result={output.data} />}
    </div></section>
  </>;
}
