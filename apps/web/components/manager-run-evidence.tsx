"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  api,
  ManagerApprovalAttempt,
  ManagerRunEvidence,
  ManagerTimelineEntry,
} from "@/lib/api";
import { humanize, singaporeTime } from "@/lib/format";
import { ErrorNotice, Status } from "./workspace";

function isManagerEvidence(value: unknown): value is ManagerRunEvidence {
  return !!value && typeof value === "object" && "run_id" in value;
}

function refs(entry: ManagerTimelineEntry) {
  return entry.evidence_refs.map((ref) => ref.reference_id).join(", ");
}

function ApprovalAttempt({ attempt }: { attempt: ManagerApprovalAttempt }) {
  return (
    <li>
      <strong>{humanize(attempt.status)}</strong> ·{" "}
      {singaporeTime(attempt.timestamp)} · {attempt.actor}
      <br />
      <span>{attempt.summary}</span>
      {attempt.reason_codes.length > 0 && (
        <small>Reason: {attempt.reason_codes.map(humanize).join(", ")}</small>
      )}
    </li>
  );
}

export function ManagerEvidencePanel({
  runId,
  compact = false,
}: {
  runId: string;
  compact?: boolean;
}) {
  const evidence = useQuery({
    queryKey: ["manager-run-evidence", runId],
    queryFn: ({ signal }) =>
      api<ManagerRunEvidence>(
        "/manager/runs/" + encodeURIComponent(runId) + "/evidence",
        { signal },
      ),
    refetchInterval: (query) =>
      query.state.data &&
      ["QUEUED", "RUNNING"].includes(query.state.data.run_status)
        ? 5000
        : false,
  });

  if (evidence.error) {
    return (
      <ErrorNotice error={evidence.error} retry={() => evidence.refetch()} />
    );
  }
  if (evidence.isPending)
    return <p role="status">Loading structured evidence…</p>;
  if (!isManagerEvidence(evidence.data)) {
    return (
      <p className="quiet">
        Structured manager evidence is not available for this assessment.
      </p>
    );
  }

  const value = evidence.data;
  const visibleTimeline = compact
    ? value.timeline.filter((entry) =>
        ["TRIGGER_EVENT", "RUN_COMPLETED", "PLAN_TRANSITIONED"].includes(
          entry.kind,
        ),
      )
    : value.timeline;

  return (
    <section
      className="evidence-display"
      aria-label="Structured manager evidence"
    >
      <header className="panel-head">
        <div>
          <h3>Assessment summary</h3>
          <p className="quiet">
            Persisted facts for run {value.run_id}; private prompts and working
            notes are excluded.
          </p>
        </div>
        <Status value={value.run_status} />
      </header>

      <dl>
        <dt>What prompted this assessment?</dt>
        <dd>{humanize(value.routing.trigger_type ?? value.trigger)}</dd>
        <dt>What did ReStock conclude?</dt>
        <dd>
          {["QUEUED", "RUNNING"].includes(value.run_status)
            ? "No conclusion yet."
            : (value.decision.summary ??
              (value.decision.outcome
                ? humanize(value.decision.outcome)
                : "No decision was recorded."))}
        </dd>
        <dt>What should I do next?</dt>
        <dd>
          {value.run_status === "QUEUED"
            ? "Wait for processing. If the request stays queued, check that the assessment worker is running."
            : value.run_status === "RUNNING"
              ? "Wait for the recorded result before making a decision."
              : value.run_status === "FAILED"
                ? "Review the failure and missing inputs, then retry the assessment."
                : value.approval.status === "REJECTED"
                  ? "This recommendation was rejected. Request a reassessment if you need a new recommendation."
                  : value.active_plan &&
                      ["INVALIDATED", "SUPERSEDED"].includes(
                        value.active_plan.status,
                      )
                    ? "This version is no longer actionable. Review the latest recommendation before deciding."
                    : value.approval.required
                      ? "Review the exact recommendation version before approving. Approval does not place an order."
                      : value.decision.outcome === "KEEP_CURRENT_PLAN"
                        ? "Review the retained plan and any recorded limitations. No additional purchase is implied."
                        : value.approval.status === "APPROVED"
                          ? "Arrange purchases separately and record what you actually ordered."
                          : "Review the recorded decision, reasons and evidence gaps before acting."}
        </dd>
      </dl>
      <Link href={`/workspace/activity/${encodeURIComponent(runId)}`}>
        Open this assessment →
      </Link>

      <dl>
        <dt>Plan / version / status</dt>
        <dd>
          {value.active_plan
            ? value.active_plan.plan_id +
              " · v" +
              value.active_plan.version +
              " · " +
              humanize(value.active_plan.status)
            : "No plan version recorded"}
        </dd>
        <dt>Approval</dt>
        <dd>
          {value.approval.required
            ? "Pending approval for version " + value.approval.plan_version
            : humanize(value.approval.status)}
          {value.approval.stale_attempts.length > 0 &&
            " · " +
              value.approval.stale_attempts.length +
              " stale attempt" +
              (value.approval.stale_attempts.length === 1 ? "" : "s")}
        </dd>
        <dt>Final decision</dt>
        <dd>
          {value.decision.outcome
            ? humanize(value.decision.outcome)
            : "Not recorded"}
          {value.decision.reason_codes.length > 0 &&
            " · " + value.decision.reason_codes.map(humanize).join(", ")}
        </dd>
      </dl>

      {!compact && value.plan_history.length > 0 && (
        <details className="record-details">
          <summary>Plan history ({value.plan_history.length})</summary>
          <ul className="evidence-list">
            {value.plan_history.map((plan) => (
              <li key={plan.id}>
                <strong>
                  {plan.plan_id} · version {plan.version}
                </strong>
                <span>
                  {humanize(plan.status)} · {plan.line_count} lines · S
                  {plan.total_expected_cost}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <details className="record-details">
        <summary>
          Coordinator routing · {value.routing.specialist_calls} specialist
          calls · {value.routing.tool_call_count} tool calls
        </summary>
        <dl className="evidence-list">
          <div>
            <dt>Trigger</dt>
            <dd>{humanize(value.routing.trigger_type ?? value.trigger)}</dd>
          </div>
          <div>
            <dt>Specialists</dt>
            <dd>
              {value.routing.specialists.length
                ? value.routing.specialists.map(humanize).join(", ")
                : "None recorded"}
            </dd>
          </div>
          <div>
            <dt>Tools</dt>
            <dd>
              {value.routing.tool_calls.length
                ? value.routing.tool_calls.map(humanize).join(", ")
                : "None recorded"}
            </dd>
          </div>
          <div>
            <dt>Retries</dt>
            <dd>{value.routing.retries}</dd>
          </div>
        </dl>
      </details>

      {!compact && value.validation.length > 0 && (
        <details className="record-details">
          <summary>Validation ({value.validation.length})</summary>
          <ul className="evidence-list">
            {value.validation.map((item) => (
              <li key={item.id}>
                <strong>
                  {item.succeeded === true
                    ? "Passed"
                    : item.succeeded === false
                      ? "Failed"
                      : "Recorded"}
                </strong>
                <span>{item.summary}</span>
                {item.evidence_refs.length > 0 && (
                  <small>
                    Evidence:{" "}
                    {item.evidence_refs
                      .map((ref) => ref.reference_id)
                      .join(", ")}
                  </small>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}

      {!compact &&
        (value.approval.latest_attempt ||
          value.approval.stale_attempts.length > 0) && (
          <details className="record-details">
            <summary>Approval attempts</summary>
            <ul className="evidence-list">
              {value.approval.latest_attempt && (
                <ApprovalAttempt attempt={value.approval.latest_attempt} />
              )}
              {value.approval.stale_attempts.map((attempt) => (
                <ApprovalAttempt key={attempt.id} attempt={attempt} />
              ))}
            </ul>
          </details>
        )}

      {!compact && (
        <details className="record-details">
          <summary>Event and audit timeline ({visibleTimeline.length})</summary>
          <ol className="evidence-list">
            {visibleTimeline.map((entry) => (
              <li key={entry.id}>
                <strong>{humanize(entry.kind)}</strong>
                <span>
                  {singaporeTime(entry.timestamp)} · {entry.actor}
                  {entry.specialist ? " · " + humanize(entry.specialist) : ""}
                  {entry.tool_name ? " · " + humanize(entry.tool_name) : ""}
                </span>
                <span>{entry.summary}</span>
                {refs(entry) && <small>Evidence: {refs(entry)}</small>}
              </li>
            ))}
          </ol>
        </details>
      )}

      {value.evaluation && (
        <p className="notice">Evaluation: {value.evaluation.summary}</p>
      )}
      {value.gaps.length > 0 && (
        <details className="record-details">
          <summary>Evidence gaps ({value.gaps.length})</summary>
          <ul className="evidence-list">
            {value.gaps.map((gap) => (
              <li key={gap.code}>
                <strong>{humanize(gap.code)}</strong>
                <span>{gap.message}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
