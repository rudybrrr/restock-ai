import { Run } from "@/lib/api";
import Link from "next/link";
import { singaporeTime } from "@/lib/format";
import { ProcurementEvidence } from "./procurement-evidence";
import { ManagerEvidencePanel } from "./manager-run-evidence";
import { ChangeAssessments } from "./change-assessments";
import { AssessmentProgress } from "./assessment-progress";

const explanations: Record<string, string> = {
  CALCULATION_INCOMPLETE:
    "The approved calculation could not establish a supported purchase recommendation. Review the recorded findings and required follow-up; no new purchase is authorized by this result.",
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
  const contingency = snapshot?.post_purchase_contingency_result;
  const validation = contingency?.independent_validation ?? snapshot?.decision_engine_artifacts?.validation;
  const search = contingency?.numerical_result ?? snapshot?.decision_engine_artifacts?.search_result;
  return (
    <section className="evidence-display" aria-label="Assessment evidence">
      <AssessmentProgress status={run.status} />
      {run.status === "SUCCEEDED" && run.outcome && (
        <div className="notice decision-brief" aria-label="Assessment outcome">
          <p className="eyebrow">RECORDED ASSESSMENT OUTCOME</p>
          <h3>{run.outcome === "KEEP_CURRENT_PLAN"
            ? "No additional purchase recommended."
            : run.outcome === "REVISE_PLAN"
              ? "A new recommendation is ready to review."
              : run.outcome === "ESCALATE"
                ? "Manager review needed. No new purchase authorized."
                : "Review the recorded decision."}</h3>
          <p>{run.outcome === "KEEP_CURRENT_PLAN"
            ? "The assessment retains the current plan within its assessed scope. Existing purchases stay unchanged; this is not a new approval."
            : run.outcome === "REVISE_PLAN"
              ? "Review the exact version, its purchase scope and costs. Approval and recording an actual purchase remain separate steps."
              : run.outcome === "ESCALATE"
                ? "A change may be material even when the calculation cannot support a safe recommendation. This result is not a finding that stock is sufficient. Review the evidence and follow-up before acting."
                : "Use the evidence below to decide what to do next."}</p>
          {run.outcome === "REVISE_PLAN" && run.plan_version_id && (
            <Link className="button button-primary" href={`/workspace/recommendations?version=${encodeURIComponent(run.plan_version_id)}`}>Review recommendation →</Link>
          )}
          {run.outcome === "KEEP_CURRENT_PLAN" && <Link href="/workspace/deliveries">Review recorded purchases →</Link>}
        </div>
      )}
      {code && explanations[code] && !["KEEP_CURRENT_PLAN", "REVISE_PLAN", "REQUEST_HUMAN_APPROVAL"].includes(code) && <p>{explanations[code]}</p>}
      {(validation || contingency) && <section className="calculation-checks" aria-label="Stored calculation checks">
        <h3>Calculated and checked</h3>
        <dl className="evidence-list"><div><dt>Assessment scope</dt><dd>{contingency ? "Bounded post-purchase contingency · additional purchases only" : "Captured procurement domain"}</dd></div><div><dt>Independent validation</dt><dd>{validation?.complete === true && validation.feasible === true ? "Complete · candidate feasible within its captured scope" : "No complete feasible candidate validation recorded"}</dd></div></dl>
        {contingency && <><p>{contingency.complete ? "Post-purchase assessment complete within the approved case." : "Post-purchase assessment incomplete; review its findings."} Existing commitments remain fixed.</p>{contingency.findings.length > 0 && <ul>{contingency.findings.map(code => <li key={code}>{code.replaceAll("_", " ").toLowerCase()}</li>)}</ul>}</>}
        <p className="quiet">These are stored Backend/engine checks, not a new calculation or a guarantee outside the approved domain.</p>
      </section>}
      <ManagerEvidencePanel runId={run.id} />
      {search && <details className="record-details"><summary>Stored procurement search evidence</summary><dl className="evidence-list"><div><dt>Search outcome</dt><dd>{search.status?.replaceAll("_", " ") ?? "Not recorded"}</dd></div><div><dt>Complete approved-domain search</dt><dd>{search.search_complete === true ? "Complete within the captured domain" : search.search_complete === false ? "Incomplete — not a certified optimum" : "Not recorded"}</dd></div><div><dt>Optimal in captured domain</dt><dd>{search.optimal_in_domain === true ? "Recorded by the engine; captured domain only" : search.optimal_in_domain === false ? "Not established" : "Not recorded"}</dd></div><div><dt>Candidates evaluated / domain size</dt><dd>{search.evaluated ?? "Not recorded"} / {search.domain_size ?? "Not recorded"}</dd></div><div><dt>Work used</dt><dd>{search.work_used ?? "Not recorded"}</dd></div></dl><p className="quiet">Search completeness is separate from candidate feasibility. Missing evidence is not a successful search, and this does not certify general intraday or 21-day optimisation.</p></details>}
      <details className="record-details">
        <summary>Captured inputs and procurement evidence</summary>
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
            {run.completed_at
              ? singaporeTime(run.completed_at)
              : "Not completed"}
          </dd>
        </dl>
        <p className="quiet">
          Captured inputs do not prove a successful forecast or complete
          optimisation. Outcomes above are the backend’s recorded assessment,
          not an independent certification.
        </p>
        {snapshot?.procurement_contract && (
          <ProcurementEvidence runId={run.id} />
        )}
      </details>
      <ChangeAssessments
        runId={run.id}
        active={run.status === "QUEUED" || run.status === "RUNNING"}
        initiallyOpen={run.trigger === "SALES_UPDATED"}
      />
    </section>
  );
}
