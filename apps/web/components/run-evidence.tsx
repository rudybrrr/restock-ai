import { Run } from "@/lib/api";
import { singaporeTime } from "@/lib/format";
import { ProcurementEvidence } from "./procurement-evidence";
import { ManagerEvidencePanel } from "./manager-run-evidence";

const explanations: Record<string, string> = {
  MISSING_REQUIRED_DATA:
    "Required inputs are missing. A purchasing conclusion cannot be drawn from this assessment.",
  NO_FEASIBLE_SUPPLIER:
    "No feasible supplier option was reported for the assessed requirements.",
  UNRESOLVED_SHORTAGE:
    "The assessment could not resolve a projected shortage. Manager review is needed.",
  POLICY_VIOLATION:
    "The result did not satisfy the purchasing policy. Review the recorded reason before acting.",
  TOOL_FAILURE:
    "A calculation or tool failed. This is not evidence that no purchase is needed.",
  KEEP_CURRENT_PLAN:
    "The assessment recorded that the current recommendation should be retained.",
  REQUEST_HUMAN_APPROVAL:
    "Review the exact recommendation version before approving. Approval does not place a purchase.",
  REVISE_PLAN:
    "The assessment recorded a revision to the purchasing recommendation.",
};

export function RunEvidence({ run }: { run: Run }) {
  const snapshot = run.snapshot;
  const code = run.escalation_reason ?? run.failure_reason ?? run.outcome;
  const missing = snapshot?.missing_offer_history;
  return (
    <section className="evidence-display" aria-label="Assessment evidence">
      {code && explanations[code] && <p>{explanations[code]}</p>}
      <dl>
        <dt>Operational cutoff</dt>
        <dd>{singaporeTime(run.as_of)}</dd>
        <dt>Knowledge cutoff</dt>
        <dd>
          {snapshot?.known_at
            ? singaporeTime(snapshot.known_at)
            : "Not captured"}
        </dd>
        <dt>Input revision</dt>
        <dd>{run.input_revision ?? "Not available"}</dd>
        <dt>Frozen procurement inputs</dt>
        <dd>
          {snapshot?.procurement_contract
            ? `Captured at state revision ${snapshot.procurement_contract.captured_state_revision}`
            : run.status === "QUEUED"
              ? "Awaiting agent claim and capture"
              : (snapshot?.procurement_contract_unavailable_reason ??
                "No frozen first-slice contract recorded")}
        </dd>
        <dt>Missing supplier-offer history</dt>
        <dd>
          {missing
            ? missing.length
              ? missing.join(", ")
              : "None reported"
            : "Not captured"}
        </dd>
        <dt>Completed</dt>
        <dd>
          {run.completed_at ? singaporeTime(run.completed_at) : "Not completed"}
        </dd>
      </dl>
      <p className="quiet">
        Captured inputs do not prove a successful forecast or complete
        optimisation. Outcomes above are the backend’s recorded assessment, not
        an independent certification.
      </p>
      {snapshot?.procurement_contract && <ProcurementEvidence runId={run.id} />}
      <ManagerEvidencePanel runId={run.id} />
    </section>
  );
}
