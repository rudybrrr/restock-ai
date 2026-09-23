"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, Run } from "@/lib/api";
import { ErrorNotice, PageHeading, Status } from "./workspace";
import { RunEvidence } from "./run-evidence";
import { ReassessAction } from "./reassess-action";
export function AssessmentDetail({ id }: { id: string }) {
  const query = useQuery({
    queryKey: ["run", id],
    queryFn: ({ signal }) =>
      api<Run>(`/runs/${encodeURIComponent(id)}`, { signal }),
    refetchInterval: (query) =>
      query.state.data &&
      ["QUEUED", "RUNNING"].includes(query.state.data.status)
        ? 5000
        : false,
  });
  return (
    <>
      <PageHeading
        eyebrow="ASSESSMENT"
        title="Review this assessment."
        description={id}
      />
      <Link href="/workspace/activity">← All activity</Link>
      {query.error ? (
        <ErrorNotice error={query.error} retry={() => query.refetch()} />
      ) : query.isPending ? (
        <p role="status">Loading assessment…</p>
      ) : (
        <section className="panel">
          <div className="panel-body">
            <Status value={query.data.status} />
            <p>{query.data.outcome ?? "No outcome recorded"}</p>
            <p>{query.data.escalation_reason ?? query.data.failure_reason}</p>
            <RunEvidence run={query.data} />
            {query.data.status === "FAILED" && (
              <ReassessAction runId={id} at={query.data.as_of} />
            )}
            {query.data.plan_version_id && (
              <Link
                href={`/workspace/recommendations?version=${encodeURIComponent(query.data.plan_version_id)}`}
              >
                Open exact recommendation →
              </Link>
            )}
          </div>
        </section>
      )}
    </>
  );
}
