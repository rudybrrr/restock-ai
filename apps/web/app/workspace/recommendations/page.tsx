"use client";
import Link from "next/link";
import { ProcurementEvidence } from "@/components/procurement-evidence";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Ingredient, NamedRecord, Plan, PlanLine } from "@/lib/api";
import { singaporeTime } from "@/lib/format";
import {
  ErrorNotice,
  PageHeading,
  Placeholder,
  Status,
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
  });
  const [selection, setSelected] = useState<string | null>(null);
  const selected = selection ?? requested;
  const exact = useQuery({
    queryKey: ["plan", selected],
    queryFn: ({ signal }) =>
      api<Plan>(`/plans/${encodeURIComponent(selected)}`, { signal }),
    enabled: !!selected,
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
        title="A plan you can stand behind."
        description="Review quantities, timing, and costs. You approve the recommendation and arrange the actual purchase separately."
      >
        <Link href="/workspace/activity" className="button button-primary">
          Request assessment →
        </Link>
      </PageHeading>
      <div className="tabs" role="tablist" aria-label="Recommendation views">
        {["Purchase plans", "Forecast", "Policy"].map((t) => (
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
      {tab === "Forecast" ? (
        <>
          <ProcurementEvidence historyOnly />
          <Placeholder title="Demand and ingredient forecast">
            Daily dish forecasts, dated service intervals, and ingredient
            requirements will appear when persisted calculation artifacts are
            available.
          </Placeholder>
          <Placeholder title="Inventory projection & shortage evidence">
            Opening counts, outstanding deliveries, FEFO, expiry, and
            first-shortage evidence will be connected to the selected plan.
          </Placeholder>
        </>
      ) : tab === "Policy" ? (
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
  async function confirm() {
    if (!decision || pending) return;
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
          : "This version was rejected.",
      );
      setDecision(null);
      await cache.invalidateQueries();
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Decision failed."));
    } finally {
      setPending(false);
    }
  }
  return (
    <>
      <section className="panel" style={{ marginTop: 24 }}>
        <header className="panel-head">
          <div>
            <h2>Purchase plan · version {plan.version}</h2>
            <p className="quiet">Created {singaporeTime(plan.created_at)}</p>
          </div>
          <Status value={plan.status} />
        </header>
        {plan.calculation_mode === "DEVELOPMENT_FIXTURE" && (
          <div className="notice" style={{ margin: 20 }}>
            Development fixture. This result does not demonstrate the real
            engine’s feasibility or contingency calculation.
          </div>
        )}
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Ingredient</th>
                <th>Supplier</th>
                <th>Quantity</th>
                <th>Unit price</th>
                <th>Arrival (Singapore)</th>
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
          <div className="cost-ledger">
            {[
              ["Purchase cost", plan.total_purchase_cost],
              ["Delivery cost", plan.delivery_cost],
              ["Expected waste cost", plan.expected_waste_cost],
              ["Expected stockout cost", plan.expected_stockout_cost],
              ["Emergency penalty", plan.emergency_penalty],
              ["Total expected cost", plan.total_expected_cost],
            ].map(([label, value]) => (
              <div key={label}>
                <span>{label}</span>
                <strong>S$ {value ?? "Unavailable"}</strong>
              </div>
            ))}
          </div>
          <p className="quiet">
            Values are the stored calculation output. Total expected cost is not
            automatically the same as immediate cash. Shipment fee groups and
            the full economic ledger await their shared interface.
          </p>
          {error && (
            <ErrorNotice
              error={error}
              retry={() => cache.invalidateQueries({ queryKey: ["plans"] })}
            />
          )}{" "}
          {success && (
            <p role="status" className="notice">
              {success}
            </p>
          )}
          {plan.status === "PENDING_APPROVAL" && (
            <div className="form-actions">
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
          {decision && (
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
            <Link href={`/workspace/activity/${encodeURIComponent(plan.run_id)}`}>
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
              <td>Total expected cost</td>
              <td>S$ {prior.total_expected_cost}</td>
              <td>S$ {selected.total_expected_cost}</td>
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
