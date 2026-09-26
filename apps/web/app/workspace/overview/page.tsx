"use client";
import { useState } from "react";
import Link from "next/link";
import { OverviewOperations } from "@/components/overview-operations";
import { OverviewAttention } from "@/components/overview-attention";
import { QuickStart } from "@/components/quick-start";
import { StockComparison } from "@/components/stock-comparison";
import { ManagerEvidencePanel } from "@/components/manager-run-evidence";
import { singaporeTime } from "@/lib/format";
import { moneyOrUnavailable, planCostSummary } from "@/lib/plan-cost";
import { useQuery } from "@tanstack/react-query";
import { api, Ingredient, InventoryLot, Plan, Run } from "@/lib/api";
import {
  ErrorNotice,
  PageHeading,
  Status,
  TabDescription,
  useServiceDate,
} from "@/components/workspace";

export default function Overview() {
  const [tab, setTab] = useState("Summary");
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
    refetchInterval: 5000,
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
        title="Today"
        description={`Service overview · ${day} · historical demonstration date`}
      >
        <Link href="/workspace/daily" className="button button-secondary">
          Complete daily update →
        </Link>
      </PageHeading>
      {errors.map((q, i) => (
        <ErrorNotice key={i} error={q.error!} retry={() => q.refetch()} />
      ))}
      <OverviewAttention />
      <div className="tabs" role="tablist" aria-label="Today views">
        {["Summary", "Daily operations", "Stock overview"].map(t => <button key={t} id={`today-${t.replaceAll(" ", "-")}`} role="tab" aria-selected={tab === t} aria-controls="today-panel" onClick={() => setTab(t)}>{t}</button>)}
      </div>
      <TabDescription tab={tab} />
      <div id="today-panel" role="tabpanel" aria-labelledby={`today-${tab.replaceAll(" ", "-")}`}>
      {tab === "Summary" && <div className="overview-summary">
      <QuickStart />
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
              <p>{active.lines.length} ingredients · {active.calculation_mode === "CONTINGENCY_ENGINE" ? "Additional purchases" : "Purchase recommendation"}</p>
              <p>
                {planCostSummary(active).label}: {moneyOrUnavailable(planCostSummary(active).value)}
              </p>
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
              <details className="record-details"><summary>Why this recommendation?</summary><ManagerEvidencePanel runId={active.run_id} compact /></details>
            </div>
          ) : (
            <div className="empty-state">
              <h3>No current recommendation.</h3>
              <p>
                Request an assessment to get started.
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
                  <div key={r.id} className="assessment-row">
                    <Status value={r.status} />
                    <p>{r.trigger.replaceAll("_", " ").toLowerCase()}</p>
                    <small>{singaporeTime(r.as_of)}</small>
                    <p className="quiet">{r.outcome ? r.outcome.replaceAll("_", " ").toLowerCase() : "Conclusion not yet recorded"}</p>
                    <Link href={`/workspace/activity/${encodeURIComponent(r.id)}`}>Review assessment →</Link>
                  </div>
                ))
            ) : (
              <p className="quiet">No assessments recorded yet.</p>
            )}
          </div>
        </section>
      </div>
      </div>}
      {tab === "Daily operations" && <OverviewOperations />}
      {tab === "Stock overview" && <StockComparison />}
      <nav className="quick-links" aria-label="Quick actions">
          <Link href="/workspace/inventory">
            Inspect inventory
          </Link>
          <Link
            href="/workspace/deliveries"
          >
            Track deliveries
          </Link>
          <Link href="/workspace/suppliers">
            Report a supplier change
          </Link>
      </nav>
      </div>
    </>
  );
}
