"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { humanize, singaporeTime } from "@/lib/format";
import { ErrorNotice } from "./workspace";

type Result = {
  material_change: boolean | null;
  complete: boolean;
  inventory_feasible: boolean | null;
  findings: { code: string; source: string }[];
  required_follow_up: string[];
  evidence_refs: string[];
  as_of: string;
  known_at: string;
  captured_state_revision: string;
  sales?: {
    dish_id: string;
    expected: string | null;
    observed: string | null;
    deviation: string | null;
    threshold: string | null;
    adequate_exposure: boolean | null;
    material: boolean | null;
  }[];
  missing_intervals?: [string, string][];
  first_risk_at?: string | null;
  safety_breaches?: { ingredient_id: string; at: string; deficit: string }[];
  assessed_lot_ids?: string[];
  assessed_ingredient_ids?: string[];
  affected_ids?: string[];
  threshold_policy_version?: string;
  limitations?: string[];
};
type Assessment = {
  result_reference: string | null;
  completed_at: string | null;
  result: Result | null;
};
const truth = (value: boolean | null) =>
  value === null ? "Unknown" : value ? "Yes" : "No";

function SavedAssessment({
  runId,
  kind,
  active,
}: {
  runId: string;
  kind: "sales-materiality" | "inventory-adjustment";
  active: boolean;
}) {
  const query = useQuery({
    queryKey: ["change-assessment", runId, kind],
    queryFn: ({ signal }) =>
      api<Assessment | null>(
        `/manager/runs/${encodeURIComponent(runId)}/${kind}`,
        { signal },
      ),
    refetchInterval: active ? 5000 : false,
  });
  const result = query.data?.result;
  return (
    <section className="evidence-display">
      <h3>
        {kind === "sales-materiality"
          ? "Sales change assessment"
          : "Stock correction assessment"}
      </h3>
      {query.error ? (
        <ErrorNotice error={query.error} retry={() => query.refetch()} />
      ) : query.isPending ? (
        <p role="status">Loading assessment…</p>
      ) : !result ? (
        <p>
          {query.data
            ? "Calculation requested; result has not been recorded."
            : "No assessment recorded for this run."}
        </p>
      ) : (
        <>
          <p>
            {!result.complete
              ? "Assessment incomplete. The effect on the plan remains unresolved."
              : result.material_change === null
                ? "Assessment recorded; material change is unknown."
                : result.material_change
                  ? "A material change was recorded. Review the assessment outcome and any revised recommendation."
                  : "The completed assessment found no material change within its assessed scope."}
          </p>
          <dl>
            <dt>Inventory feasible</dt>
            <dd>{truth(result.inventory_feasible)}</dd>
            <dt>Assessed through</dt>
            <dd>{singaporeTime(result.as_of)}</dd>
            <dt>Information available by</dt>
            <dd>{singaporeTime(result.known_at)}</dd>
            <dt>State revision</dt>
            <dd>{result.captured_state_revision}</dd>
          </dl>
          {result.threshold_policy_version && (
            <p>Threshold policy: {result.threshold_policy_version}</p>
          )}
          {result.sales && (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Dish</th>
                    <th>Expected</th>
                    <th>Observed</th>
                    <th>Deviation</th>
                    <th>Threshold</th>
                    <th>Enough sales exposure</th>
                    <th>Material change</th>
                  </tr>
                </thead>
                <tbody>
                  {result.sales.map((dish) => (
                    <tr key={dish.dish_id}>
                      <td>{dish.dish_id}</td>
                      <td>{dish.expected ?? "Unknown"}</td>
                      <td>{dish.observed ?? "Unknown"}</td>
                      <td>{dish.deviation ?? "Unknown"}</td>
                      <td>{dish.threshold ?? "Unknown"}</td>
                      <td>{truth(dish.adequate_exposure)}</td>
                      <td>{truth(dish.material)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {result.assessed_lot_ids && (
            <p>Assessed lots: {result.assessed_lot_ids.join(", ") || "None"}</p>
          )}
          {result.assessed_ingredient_ids && (
            <p>
              Assessed ingredients:{" "}
              {result.assessed_ingredient_ids.join(", ") || "None"}
            </p>
          )}
          {result.affected_ids && (
            <p>
              Affected items:{" "}
              {result.affected_ids.join(", ") || "None reported"}
            </p>
          )}
          {result.first_risk_at && (
            <p>First projected risk: {singaporeTime(result.first_risk_at)}</p>
          )}
          {!!result.missing_intervals?.length && (
            <>
              <h4>Missing sales intervals</h4>
              <ul>
                {result.missing_intervals.map(([start, end]) => (
                  <li key={`${start}-${end}`}>
                    {singaporeTime(start)} – {singaporeTime(end)}
                  </li>
                ))}
              </ul>
            </>
          )}
          {!!result.safety_breaches?.length && (
            <>
              <h4>Safety-stock breaches</h4>
              <ul>
                {result.safety_breaches.map((breach, index) => (
                  <li key={index}>
                    {breach.ingredient_id}: deficit {breach.deficit} at{" "}
                    {singaporeTime(breach.at)}
                  </li>
                ))}
              </ul>
            </>
          )}
          {!!result.findings.length && (
            <>
              <h4>Findings</h4>
              <ul>
                {result.findings.map((finding, index) => (
                  <li key={index}>
                    {humanize(finding.code)} · {finding.source}
                  </li>
                ))}
              </ul>
            </>
          )}
          {!!result.required_follow_up.length && (
            <>
              <h4>Required follow-up</h4>
              <ul>
                {result.required_follow_up.map((item) => (
                  <li key={item}>{humanize(item)}</li>
                ))}
              </ul>
            </>
          )}
          {result.limitations?.map((item) => (
            <p key={item}>{item}</p>
          ))}
          <details>
            <summary>Recorded evidence</summary>
            <p>{query.data?.result_reference}</p>
            {result.evidence_refs.map((reference) => (
              <p key={reference}>{reference}</p>
            ))}
          </details>
        </>
      )}
    </section>
  );
}

export function ChangeAssessments({
  runId,
  active = false,
}: {
  runId: string;
  active?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>Sales and stock-correction assessments</summary>
      {open && (
        <>
          <SavedAssessment
            runId={runId}
            kind="sales-materiality"
            active={active}
          />
          <SavedAssessment
            runId={runId}
            kind="inventory-adjustment"
            active={active}
          />
        </>
      )}
    </details>
  );
}
