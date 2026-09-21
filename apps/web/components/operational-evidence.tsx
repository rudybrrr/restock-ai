import { Delivery } from "@/lib/operations-types";
import { humanize, singaporeTime } from "@/lib/format";

export type ActivitySemantics = {
  version: string;
  baseline_history_mode: string;
  intraday_sales_mode: string;
  closing_sales_mode: string;
  reconciliation_mode: string;
};
export type CommitmentProjection = {
  complete: boolean;
  as_of: string;
  known_at: string;
  captured_state_revision: string;
  findings: { code: string; source: string }[];
  supplies: {
    delivery: Delivery;
    expiry_date: string | null;
    projected_lot_id: string | null;
    expiry_evidence: {
      reference: string;
      available_at: string;
      captured_revision: string;
    } | null;
  }[];
};
const rules: Record<string, string> = {
  VERSIONED_FORECAST_INPUT_IMMUTABLE:
    "Historical forecast inputs stay fixed for the captured version.",
  INVENTORY_ESTIMATE_AND_REASSESSMENT_ONLY:
    "Intraday sales update estimated stock and request reassessment.",
  LATEST_DAILY_REVISION_AUTHORITATIVE:
    "The latest submitted daily sales revision supplies the authoritative closing totals.",
  COMPARE_NEVER_ADD:
    "Closing totals are compared with intraday reports for reconciliation; the two are never added together.",
};
export function OperationalEvidence({
  semantics,
  commitments,
  runId,
}: {
  semantics?: ActivitySemantics | null;
  commitments?: CommitmentProjection | null;
  runId?: string;
}) {
  return (
    <>
      <h3>How sales feed this forecast</h3>
      {semantics ? (
        <>
          <p className="quiet">Recorded rules: {semantics.version}</p>
          <ul>
            {[
              semantics.baseline_history_mode,
              semantics.intraday_sales_mode,
              semantics.closing_sales_mode,
              semantics.reconciliation_mode,
            ].map((rule) => (
              <li key={rule}>{rules[rule] ?? humanize(rule)}</li>
            ))}
          </ul>
        </>
      ) : (
        <p>Activity rules were not captured in this record.</p>
      )}
      {runId && (
        <>
          <h3>Purchases already accounted for</h3>
          {!commitments ? (
            <p>Existing-purchase evidence was not captured for this run.</p>
          ) : (
            <>
              <p>
                Recorded as of {singaporeTime(commitments.as_of)}, using
                information available by {singaporeTime(commitments.known_at)}.
                These are purchases already arranged; only their outstanding
                quantities provide future supply.
              </p>
              <p>
                {commitments.complete
                  ? "Commitment evidence is complete."
                  : "Commitment evidence is incomplete; review the missing information below."}
              </p>
              {commitments.findings.map((finding, index) => (
                <p key={index}>
                  {humanize(finding.code)} · {finding.source}
                </p>
              ))}
              {commitments.supplies.length ? (
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Ingredient / supplier</th>
                        <th>Expected</th>
                        <th>Received</th>
                        <th>Cancelled</th>
                        <th>Outstanding</th>
                        <th>Arrival</th>
                        <th>Expected expiry</th>
                        <th>Evidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {commitments.supplies.map((supply) => (
                        <tr key={supply.delivery.id}>
                          <td>
                            {supply.delivery.ingredient_id}
                            <small>{supply.delivery.supplier_id}</small>
                          </td>
                          <td>{supply.delivery.expected_quantity}</td>
                          <td>{supply.delivery.received_quantity}</td>
                          <td>{supply.delivery.cancelled_quantity}</td>
                          <td>{supply.delivery.outstanding_quantity}</td>
                          <td>{singaporeTime(supply.delivery.expected_at)}</td>
                          <td>{supply.expiry_date ?? "Unknown"}</td>
                          <td>
                            <details>
                              <summary>Purchase evidence</summary>
                              <p>Delivery {supply.delivery.id}</p>
                              <p>
                                Projected lot:{" "}
                                {supply.projected_lot_id ?? "Not available"}
                              </p>
                              <p>
                                Expiry source:{" "}
                                {supply.expiry_evidence?.reference ??
                                  "Not available"}
                              </p>
                            </details>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p>
                  No existing purchases were included in this run’s captured
                  evidence.
                </p>
              )}
            </>
          )}
        </>
      )}
    </>
  );
}
