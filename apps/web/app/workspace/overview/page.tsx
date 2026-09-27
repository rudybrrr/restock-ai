"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { OverviewAttention } from "@/components/overview-attention";
import { api, Ingredient, InventoryLot, Plan } from "@/lib/api";
import type { DailyHistory, Delivery } from "@/lib/operations-types";
import { localSingapore } from "@/lib/format";
import { ErrorNotice, PageHeading, Status, useServiceDate } from "@/components/workspace";

export default function Overview() {
  const { day } = useServiceDate();
  const ingredients = useQuery({ queryKey: ["ingredients"], queryFn: ({ signal }) => api<Ingredient[]>("/ingredients", { signal }) });
  const lots = useQuery({ queryKey: ["inventory"], queryFn: ({ signal }) => api<InventoryLot[]>("/inventory", { signal }) });
  const plans = useQuery({ queryKey: ["plans"], queryFn: ({ signal }) => api<Plan[]>("/plan-history", { signal }), refetchInterval: 5000 });
  const deliveries = useQuery({ queryKey: ["deliveries"], queryFn: ({ signal }) => api<Delivery[]>("/deliveries", { signal }) });
  const daily = useQuery({ queryKey: ["daily", day], queryFn: ({ signal }) => api<DailyHistory>(`/daily-updates/${day}`, { signal }) });
  const expiring = lots.data?.filter(l => l.expiry_date === day);
  const incoming = deliveries.data?.filter(d => Number(d.outstanding_quantity) > 0 && localSingapore(d.expected_at).slice(0, 10) <= day);
  return <>
    <PageHeading eyebrow="YOUR DAY, IN ORDER" title="Today" description={`What needs attention for service on ${day}. Start with the next action below.`} />
    <OverviewAttention />
    {[ingredients, lots, plans, deliveries, daily].filter(q => q.error).map((q, i) => <ErrorNotice key={i} error={q.error!} retry={() => q.refetch()} />)}
    <div className="stat-strip">
      <div><strong>{ingredients.data?.length ?? "—"}</strong><span>Ingredients tracked</span></div>
      <div><strong>{plans.data?.filter(p => p.status === "PENDING_APPROVAL").length ?? "—"}</strong><span>Recommendations awaiting approval</span></div>
      <div><strong>{incoming?.length ?? "—"}</strong><span>Deliveries due by this service date</span></div>
    </div>
    <div className="two-columns today-focus">
      <section className="panel"><header className="panel-head"><h2>Needs attention</h2></header><div className="panel-body">
        <p className="quiet">These are record checks, not a certification that stock is sufficient.</p>
        <ul className="task-list">
          <li><div><strong>Expiring batches</strong><p>{expiring === undefined ? "Not checked yet." : `${expiring.length} batches reach their expiry date today. Disposal is not automatically recorded as waste.`}</p></div>{!!expiring?.length && <Link href="/workspace/inventory">Inspect batches →</Link>}</li>
          <li><div><strong>Expected arrivals</strong><p>{incoming === undefined ? "Not checked yet." : incoming.length ? "Check whether due stock arrived, or record a delay or shortfall." : "No outstanding deliveries are due by the selected date."}</p></div>{!!incoming?.length && <Link href="/workspace/deliveries?view=receive">Check arrivals →</Link>}</li>
          <li><div><strong>Closing records</strong><p>{daily.data === undefined ? "Not checked yet." : daily.data.revisions.length ? "A closing update is submitted. Corrections remain available in Daily operations." : daily.data.draft ? "A draft is saved. Submit it when service has finished." : "Closing counts and final sales have not been submitted. Submit only after service finishes."}</p></div>{daily.data && !daily.data.revisions.length && <Link href="/workspace/daily">Complete closing update →</Link>}</li>
        </ul>
      </div></section>
      <section className="panel"><header className="panel-head"><h2>At a glance</h2></header><div className="panel-body">
        <dl className="day-summary"><div><dt>Service date</dt><dd>{day} · Singapore time</dd></div><div><dt>Closing update</dt><dd>{daily.data ? <Status value={daily.data.revisions.length ? "Submitted" : daily.data.draft ? "Draft" : "Not submitted"} /> : "Unavailable"}</dd></div><div><dt>Stock records</dt><dd>{lots.data?.length ?? "Unknown"} received batches. Counts and sales-based estimates are separate views under Daily operations.</dd></div></dl>
        <details className="record-details"><summary>New to ReStock?</summary><ol className="first-day-guide"><li><strong>During service:</strong> check stock and record complete sales intervals in Daily operations.</li><li><strong>When buying:</strong> review and approve the exact recommendation in Purchasing; arrange and record purchases separately.</li><li><strong>At closing:</strong> submit final sales and physical counts in Daily operations.</li></ol><p>Activity is your history. Settings contains suppliers, promotions and restaurant reference data.</p></details>
      </div></section>
    </div>
  </>;
}
