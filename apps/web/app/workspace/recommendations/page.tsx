"use client";
import { ReassessAction } from "@/components/reassess-action";
import Link from "next/link";
import { ProcurementEvidence } from "@/components/procurement-evidence";
import { ManagerEvidencePanel } from "@/components/manager-run-evidence";
import { PurchaseContext } from "@/components/purchase-context";
import { PurchasingSteps } from "@/components/purchasing-steps";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, Ingredient, NamedRecord, Plan, PlanLine } from "@/lib/api";
import { singaporeTime } from "@/lib/format";
import { moneyOrUnavailable, planCostSummary } from "@/lib/plan-cost";
import {
  ErrorNotice,
  PageHeading,
  Status,
  TabDescription,
} from "@/components/workspace";
type StoredLine = PlanLine & {
  id: string;
  linked_quantity: string;
  uncommitted_quantity: string;
};
export default function Recommendations() {
  return (
    <Suspense fallback={<p role="status">Loading recommendation…</p>}>
      <RecommendationsContent />
    </Suspense>
  );
}
function RecommendationsContent() {
  const params = useSearchParams();
  const requested = params.get("version") ?? "";
  return <RecommendationView key={requested} requested={requested} />;
}
function RecommendationView({ requested }: { requested: string }) {
  const q = useQuery({
    queryKey: ["plans"],
    queryFn: ({ signal }) => api<Plan[]>("/plan-history", { signal }),
    refetchInterval: 5000,
  });
  const [selection, setSelected] = useState<string | null>(null);
  const selected = selection ?? requested;
  const exact = useQuery({
    queryKey: ["plan", selected],
    queryFn: ({ signal }) =>
      api<Plan>(`/plans/${encodeURIComponent(selected)}`, { signal }),
    enabled: !!selected,
    refetchInterval: 5000,
  });
  const [tab, setTab] = useState("Purchase plans");
  const active = q.data?.find((p) =>
    ["APPROVED", "PENDING_APPROVAL"].includes(p.status),
  );
  const plan = selected
    ? exact.data
    : (active ??
      q.data
        ?.slice()
        .sort((a, b) => b.created_at.localeCompare(a.created_at))[0]);
  return (
    <>
      <PageHeading
        eyebrow="PURCHASE RECOMMENDATIONS"
        title="Review purchase recommendation"
        description="Review quantities, arrivals and costs. Approval does not place an order."
      >
        <Link href="/workspace/activity" className="button button-secondary">
          Request assessment →
        </Link>
      </PageHeading>
      <div className="tabs" role="tablist" aria-label="Recommendation views">
        {["Purchase plans", "Policy"].map((t) => (
          <button
            role="tab"
            aria-selected={tab === t}
            key={t}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>
      <TabDescription tab={tab} />
      {tab === "Policy" ? (
        <ProcurementEvidence />
      ) : selected && exact.error ? (
        <ErrorNotice error={exact.error} retry={() => exact.refetch()} />
      ) : selected && exact.isPending ? (
        <p role="status">Loading the requested plan version…</p>
      ) : !selected && q.error ? (
        <ErrorNotice error={q.error} retry={() => q.refetch()} />
      ) : !selected && q.isPending ? (
        <p role="status">Loading recommendations…</p>
      ) : !plan ? (
        <section className="panel">
          <div className="empty-state">
            <h3>No recommendation yet.</h3>
            <p>
              A completed, feasible assessment creates a plan here. Missing
              data, incomplete calculations, and no-purchase outcomes do not
              create fictitious purchase lines.
            </p>
          </div>
        </section>
      ) : (
        <>
          <label className="field-label">
            Plan history
            <select
              value={plan.id}
              onChange={(e) => setSelected(e.target.value)}
            >
              {selected && plan && !q.data?.some((p) => p.id === plan.id) && (
                <option value={plan.id}>
                  Requested version {plan.version} · {plan.id}
                </option>
              )}
              {q.data
                ?.slice()
                .sort((a, b) => b.created_at.localeCompare(a.created_at))
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    Version {p.version} · {p.status.replaceAll("_", " ")} ·{" "}
                    {singaporeTime(p.created_at)} · {p.plan_id.slice(0, 8)}
                  </option>
                ))}
            </select>
          </label>
          <PlanDetail key={plan.id} plan={plan} />
          {q.data && q.data.length > 1 && (
            <PlanComparison selected={plan} plans={q.data} />
          )}
        </>
      )}
    </>
  );
}
function PlanDetail({ plan }: { plan: Plan }) {
  const cache = useQueryClient();
  const ingredients = useQuery({
    queryKey: ["ingredients"],
    queryFn: ({ signal }) => api<Ingredient[]>("/ingredients", { signal }),
  });
  const suppliers = useQuery({
    queryKey: ["suppliers"],
    queryFn: ({ signal }) => api<NamedRecord[]>("/suppliers", { signal }),
  });
  const lines = useQuery({
    queryKey: ["plan-lines", plan.id],
    queryFn: ({ signal }) =>
      api<StoredLine[]>(`/plans/${encodeURIComponent(plan.id)}/lines`, {
        signal,
      }),
  });
  const [decision, setDecision] = useState<"APPROVED" | "REJECTED" | null>(
    null,
  );
  const [instructions, setInstructions] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [success, setSuccess] = useState("");
  const [stale, setStale] = useState(false);
  const contingency = plan.calculation_mode === "CONTINGENCY_ENGINE";
  const cashOnly = plan.cost_scope === "NEW_PURCHASE_CASH_ONLY";
  const costRows: [string, string | null][] = cashOnly
    ? [
        ["New purchase acquisition", plan.total_purchase_cost],
        ["New purchase delivery", plan.delivery_cost],
        ["New purchase emergency fee", plan.emergency_penalty],
        ["New purchase cash total", plan.new_purchase_cash_cost],
      ]
    : [
        ["Purchase cost", plan.total_purchase_cost],
        ["Delivery cost", plan.delivery_cost],
        ["Expected waste cost", plan.expected_waste_cost],
        ["Expected stockout cost", plan.expected_stockout_cost],
        ["Emergency penalty", plan.emergency_penalty],
        ["Total expected cost", plan.total_expected_cost],
      ];
  async function confirm() {
    if (!decision || pending || stale || plan.status !== "PENDING_APPROVAL") return;
    setPending(true);
    setError(null);
    try {
      await api(`/plans/${encodeURIComponent(plan.id)}/decision`, {
        method: "POST",
        body: {
          plan_id: plan.plan_id,
          plan_version: plan.version,
          decision,
          instructions: instructions || null,
        },
      });
      setSuccess(
        decision === "APPROVED"
          ? "This version is approved. Record an actual purchase after you arrange it with the supplier."
          : "This version was rejected. No replacement was requested automatically. You can request a new assessment below.",
      );
      setDecision(null);
      await cache.invalidateQueries();
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Decision failed."));
      if (e instanceof ApiError && e.code === "PLAN_VERSION_STALE") {
        setStale(true);
        setDecision(null);
        await cache.invalidateQueries();
      }
    } finally {
      setPending(false);
    }
  }
  return (
    <>
      <PurchasingSteps plan={plan} />
      <section className="panel" style={{ marginTop: 24 }}>
        <header className="panel-head">
          <div>
            <h2>Purchase plan · version {plan.version}</h2>
            <p className="quiet">Created {singaporeTime(plan.created_at)}</p>
          </div>
          <Status value={plan.status} />
        </header>
        <div className="panel-body decision-brief" aria-label="Recommendation summary">
          <p className="eyebrow">{contingency ? "ADDITIONAL PURCHASE ONLY" : "PURCHASE RECOMMENDATION"}</p>
          <p>{contingency
            ? "Additional quantities only. Existing purchases stay unchanged."
            : "Approval applies only to this version. Arrange and record purchases separately."}</p>
          <strong>{planCostSummary(plan).label}: {moneyOrUnavailable(planCostSummary(plan).value)}</strong>
          {plan.status === "PENDING_APPROVAL" && !stale && <p>Awaiting your approval · version {plan.version}</p>}
        </div>
        {plan.calculation_mode === "DEVELOPMENT_FIXTURE" && (
          <div className="notice" style={{ margin: 20 }}>
            Development fixture. This result does not demonstrate the real
            engine’s feasibility or contingency calculation.
          </div>
        )}
        <p className="mobile-table-hint">Scroll the table sideways for arrival dates and purchasing details →</p>
        <div id="purchase-lines" className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Ingredient</th>
                <th>Supplier</th>
                <th>Quantity</th>
                <th>Unit price</th>
                <th>Arrival (Singapore)</th>
                <th>Purchase type / expiry</th>
                <th>Purchasing</th>
              </tr>
            </thead>
            <tbody>
              {(
                lines.data ??
                plan.lines.map((l) => ({
                  ...l,
                  id: null,
                  linked_quantity: null,
                  uncommitted_quantity: null,
                }))
              ).map((l, i) => (
                <tr key={l.id ?? i}>
                  <td>
                    {ingredients.data?.find((x) => x.id === l.ingredient_id)
                      ?.name ?? l.ingredient_id}
                  </td>
                  <td>
                    {suppliers.data?.find((x) => x.id === l.supplier_id)
                      ?.name ?? l.supplier_id}
                  </td>
                  <td>
                    {l.quantity}{" "}
                    {
                      ingredients.data?.find((x) => x.id === l.ingredient_id)
                        ?.unit
                    }
                  </td>
                  <td>S$ {l.unit_price}</td>
                  <td>{singaporeTime(l.arrival_at)}</td>
                  <td>{l.kind ? l.kind.toLowerCase() : "Not recorded"}<small>Expiry: {l.expiry_date ?? "Not recorded"}</small></td>
                  <td>
                    {l.uncommitted_quantity !== null ? (
                      <>
                        <small>Linked: {String(l.linked_quantity)}</small>
                        <small>
                          Uncommitted: {String(l.uncommitted_quantity)}
                        </small>
                        {plan.status === "APPROVED" &&
                          Number(l.uncommitted_quantity) > 0 && (
                            <Link
                              href={`/workspace/deliveries?plan=${encodeURIComponent(plan.id)}&line=${encodeURIComponent(String(l.id))}`}
                            >
                              Record purchase →
                            </Link>
                          )}
                      </>
                    ) : (
                      <span className="quiet">
                        Allocation detail unavailable
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {lines.error && (
          <ErrorNotice error={lines.error} retry={() => lines.refetch()} />
        )}
        <div className="panel-body">
          {contingency && <PurchaseContext runId={plan.run_id} />}
          <div className="cost-ledger">
            {costRows.map(([label, value]) => (
              <div key={label}>
                <span>{label}</span>
                <strong>{moneyOrUnavailable(value)}</strong>
              </div>
            ))}
          </div>
          <p className="quiet">
            {cashOnly
              ? "New purchase cash only. Waste and stockout economics are not included."
              : "Stored calculation output. Expected cost may differ from immediate cash."}
          </p>
          {error && (
            <ErrorNotice
              error={error}
              retry={stale ? undefined : () => cache.invalidateQueries({ queryKey: ["plans"] })}
            />
          )}{" "}
          {stale && (
            <div className="notice" role="status">
              <h3>Approval not saved. This version is out of date.</h3>
              <p>No purchase was placed. Review the latest recommendation and assessment before deciding again.</p>
              <div className="form-actions">
                <Link className="button button-secondary" href="/workspace/recommendations">Review latest recommendation</Link>
                <Link href="/workspace/activity">View recent assessments →</Link>
              </div>
            </div>
          )}
          {success && (
            <p role="status" className="notice">
              {success}
            </p>
          )}
          {plan.status === "REJECTED" && (
            <ReassessAction
              key={plan.id}
              runId={plan.run_id}
              at={plan.created_at}
            />
          )}
          {["INVALIDATED", "SUPERSEDED"].includes(plan.status) && (
            <p className="notice">
              This version is no longer actionable. Select the latest
              recommendation before making a decision.
            </p>
          )}
          {plan.status === "PENDING_APPROVAL" && !stale && (
            <div id="plan-decision" className="form-actions">
              <button
                disabled={pending}
                className="button button-primary"
                onClick={() => setDecision("APPROVED")}
              >
                Approve version {plan.version}
              </button>
              <button
                disabled={pending}
                className="button button-secondary"
                onClick={() => setDecision("REJECTED")}
              >
                Reject with instructions
              </button>
            </div>
          )}
          {decision && plan.status === "PENDING_APPROVAL" && !stale && (
            <section className="notice">
              <h3>
                {decision === "APPROVED" ? "Approve" : "Reject"} version{" "}
                {plan.version}?
              </h3>
              <p>
                This decision applies only to this version. Approval does not
                place a supplier order or add inventory.
              </p>
              <label className="field-label">
                Instructions (optional)
                <textarea
                  maxLength={1000}
                  value={instructions}
                  onChange={(e) => setInstructions(e.target.value)}
                />
              </label>
              <div className="form-actions">
                <button
                  disabled={pending}
                  className="button button-primary"
                  onClick={confirm}
                >
                  {pending ? "Saving decision…" : "Confirm decision"}
                </button>
                <button
                  disabled={pending}
                  className="button button-secondary"
                  onClick={() => setDecision(null)}
                >
                  Cancel
                </button>
              </div>
            </section>
          )}
          {plan.status === "APPROVED" && <p className="scope-note">Use “Record purchase” on the approved lines above after arranging the order. Linked and uncommitted quantities help prevent recording the allocation twice.</p>}
          <details className="record-details"><summary>Why this recommendation?</summary><ManagerEvidencePanel runId={plan.run_id} compact /></details>
          <details className="record-details">
            <summary>Calculation references</summary>
            <dl className="evidence-list">
              {[
                ["Plan", plan.plan_id],
                ["Version record", plan.id],
                ["Forecast", plan.forecast_id],
                ["Inventory snapshot", plan.inventory_snapshot_id],
                ["Assessment", plan.run_id],
                ["Calculation mode", plan.calculation_mode],
              ].map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
            <Link
              href={`/workspace/activity/${encodeURIComponent(plan.run_id)}`}
            >
              View assessment and existing-purchase evidence →
            </Link>
          </details>
        </div>
      </section>
    </>
  );
}
function PlanComparison({
  selected,
  plans,
}: {
  selected: Plan;
  plans: Plan[];
}) {
  const prior = plans
    .filter(
      (p) => p.plan_id === selected.plan_id && p.version < selected.version,
    )
    .sort((a, b) => b.version - a.version)[0];
  if (!prior) return null;
  return (
    <section className="panel">
      <header className="panel-head">
        <h2>Compared with version {prior.version}</h2>
      </header>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Measure</th>
              <th>Version {prior.version}</th>
              <th>Version {selected.version}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Line count</td>
              <td>{prior.lines.length}</td>
              <td>{selected.lines.length}</td>
            </tr>
            <tr>
              <td>Cost basis</td>
              <td>
                {planCostSummary(prior).label}: {moneyOrUnavailable(planCostSummary(prior).value)}
              </td>
              <td>
                {planCostSummary(selected).label}: {moneyOrUnavailable(planCostSummary(selected).value)}
              </td>
            </tr>
            <tr>
              <td>Status</td>
              <td>
                <Status value={prior.status} />
              </td>
              <td>
                <Status value={selected.status} />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="panel-body">
        <h3>Ingredient allocations by version</h3>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Ingredient / supplier</th>
                <th>Version</th>
                <th>Quantity</th>
                <th>Arrival</th>
              </tr>
            </thead>
            <tbody>
              {[prior, selected].flatMap((p) =>
                p.lines.map((l, i) => (
                  <tr key={`${p.id}-${i}`}>
                    <td>
                      {l.ingredient_id} / {l.supplier_id}
                    </td>
                    <td>{p.version}</td>
                    <td>{l.quantity}</td>
                    <td>{singaporeTime(l.arrival_at)}</td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
