"use client";
import Link from "next/link";
import { OverviewOperations } from "@/components/overview-operations";
import { singaporeTime } from "@/lib/format";
import { useQuery } from "@tanstack/react-query";
import { api, Ingredient, InventoryLot, Plan, Run } from "@/lib/api";
import {
  ErrorNotice,
  PageHeading,
  Placeholder,
  Status,
  useServiceDate,
} from "@/components/workspace";

export default function Overview() {
  const { day } = useServiceDate();
  const ingredients = useQuery({
    queryKey: ["ingredients"],
    queryFn: ({ signal }) => api<Ingredient[]>("/ingredients", { signal }),
  });
  const lots = useQuery({
    queryKey: ["inventory"],
    queryFn: ({ signal }) => api<InventoryLot[]>("/inventory", { signal }),
  });
  const plans = useQuery({
    queryKey: ["plans"],
    queryFn: ({ signal }) => api<Plan[]>("/plan-history", { signal }),
  });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: ({ signal }) => api<Run[]>("/runs", { signal }),
    refetchInterval: (q) =>
      q.state.data?.some((r) => ["QUEUED", "RUNNING"].includes(r.status))
        ? 5000
        : false,
  });
  const active = plans.data?.find((p) =>
    ["APPROVED", "PENDING_APPROVAL"].includes(p.status),
  );
  const errors = [ingredients, lots, plans, runs].filter((q) => q.error);
  return (
    <>
      <PageHeading
        eyebrow="YOUR DAY, IN ORDER"
        title="A clearer view of the kitchen."
        description={`Service overview · ${day} · historical demonstration date`}
      >
        <Link href="/workspace/daily" className="button button-primary">
          Complete daily update →
        </Link>
      </PageHeading>
      {errors.map((q, i) => (
        <ErrorNotice key={i} error={q.error!} retry={() => q.refetch()} />
      ))}
      <div className="stat-strip">
        <div>
          <strong>{ingredients.data?.length ?? "—"}</strong>
          <span>Ingredients in your kitchen</span>
        </div>
        <div>
          <strong>
            {lots.data?.filter((l) => l.expiry_date === day).length ?? "—"}
          </strong>
          <span>Lots reaching expiry today</span>
        </div>
        <div>
          <strong>
            {plans.data?.filter((p) => p.status === "PENDING_APPROVAL")
              .length ?? "—"}
          </strong>
          <span>Plans awaiting your review</span>
        </div>
      </div>
      <div className="two-columns">
        <section className="panel">
          <header className="panel-head">
            <h2>Your purchase plan</h2>
            <Link href="/workspace/recommendations">View all →</Link>
          </header>
          {plans.isPending ? (
            <p className="empty-state" role="status">
              Loading recommendations…
            </p>
          ) : plans.error ? (
            <p className="empty-state">
              Recommendations unavailable. Retry the connection above.
            </p>
          ) : active ? (
            <div className="panel-body">
              <Status value={active.status} />
              <h3>Purchase plan · version {active.version}</h3>
              <p>{active.lines.length} ingredient allocations</p>
              <p>Total expected cost: S$ {active.total_expected_cost}</p>
              {active.calculation_mode === "DEVELOPMENT_FIXTURE" && (
                <p className="notice">
                  Development calculation — not a connected engine result.
                </p>
              )}
              <Link
                className="button button-secondary"
                href="/workspace/recommendations"
              >
                Review recommendation
              </Link>
            </div>
          ) : (
            <div className="empty-state">
              <h3>No current recommendation.</h3>
              <p>
                Your next completed assessment will appear here. Approval and
                actual purchasing are separate steps.
              </p>
            </div>
          )}
        </section>
        <section className="panel">
          <header className="panel-head">
            <h2>Recent assessments</h2>
            <Link href="/workspace/activity">Open activity →</Link>
          </header>
          <div className="panel-body">
            {runs.isPending ? (
              <p role="status">Loading assessments…</p>
            ) : runs.error ? (
              <p className="quiet">Assessment history unavailable.</p>
            ) : runs.data?.length ? (
              runs.data
                .slice()
                .sort((a, b) => b.created_at.localeCompare(a.created_at))
                .slice(0, 3)
                .map((r) => (
                  <div key={r.id} style={{ marginBottom: 20 }}>
                    <Status value={r.status} />
                    <p>{r.trigger.replaceAll("_", " ").toLowerCase()}</p>
                    <small>{singaporeTime(r.as_of)}</small>
                  </div>
                ))
            ) : (
              <p className="quiet">No assessments recorded yet.</p>
            )}
          </div>
        </section>
      </div>
      <OverviewOperations />
      <Placeholder title="A view of what’s ahead">
        Projected shortages and demand will appear here when the forecast and
        inventory evidence are connected. Physical counts and estimates remain
        available in Inventory.
      </Placeholder>
      <section className="panel">
        <header className="panel-head">
          <h2>Keep the day moving</h2>
        </header>
        <div className="panel-body form-actions">
          <Link className="button button-secondary" href="/workspace/inventory">
            Inspect inventory
          </Link>
          <Link
            className="button button-secondary"
            href="/workspace/deliveries"
          >
            Track deliveries
          </Link>
          <Link className="button button-secondary" href="/workspace/suppliers">
            Report a supplier change
          </Link>
        </div>
      </section>
    </>
  );
}
