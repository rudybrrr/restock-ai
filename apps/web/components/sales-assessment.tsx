"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, Run } from "@/lib/api";
import { localSingapore, singaporeTime } from "@/lib/format";
import { ErrorNotice, Status } from "./workspace";
import { ChangeAssessments } from "./change-assessments";

export function SalesAssessment({ day }: { day: string }) {
  const query = useQuery({ queryKey: ["runs"], queryFn: ({ signal }) => api<Run[]>("/runs", { signal }), refetchInterval: 5000 });
  const run = query.data?.filter(r => r.trigger === "SALES_UPDATED" && localSingapore(r.as_of).startsWith(day)).sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  return <section className="panel" aria-label="Sales reassessment">
    <header className="panel-head"><div><h2>From sales change to decision</h2><p className="quiet">Latest sales-triggered assessment for {day}</p></div>{run && <Status value={run.status} />}</header>
    <div className="panel-body">
      {query.error ? <ErrorNotice error={query.error} retry={() => query.refetch()} /> : query.isPending ? <p role="status">Loading sales assessments…</p> : !run ? <p>No sales-triggered assessment recorded for this date. This does not certify that there is no material change.</p> : <>
        <h3>{["QUEUED", "RUNNING"].includes(run.status) ? "The sales change is being checked." : run.status === "FAILED" ? "The assessment needs follow-up." : run.outcome === "ESCALATE" ? "Change detected; purchasing needs review." : run.outcome === "REVISE_PLAN" ? "A revised recommendation is ready." : run.outcome === "KEEP_CURRENT_PLAN" ? "Current plan retained within the assessed scope." : "Review the recorded result."}</h3>
        {run.outcome === "ESCALATE" && <p>No new purchase is authorized. Review the findings; this result does not establish that stock is sufficient.</p>}
        <p className="quiet">Assessed through {singaporeTime(run.as_of)}{run.escalation_reason ? ` · ${run.escalation_reason.replaceAll("_", " ").toLowerCase()}` : ""}</p>
        <Link className="button button-secondary" href={`/workspace/activity/${encodeURIComponent(run.id)}`}>Review sales assessment →</Link>
        <ChangeAssessments key={run.id} runId={run.id} active={["QUEUED", "RUNNING"].includes(run.status)} />
      </>}
    </div>
  </section>;
}
