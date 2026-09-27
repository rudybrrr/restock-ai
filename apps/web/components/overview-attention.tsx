"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ClipboardCheck, FileCheck2, Truck, Activity } from "lucide-react";
import { api, Plan, Run } from "@/lib/api";
import { DailyHistory, Delivery } from "@/lib/operations-types";
import { localSingapore } from "@/lib/format";
import { useServiceDate } from "./workspace";

export function OverviewAttention() {
  const { day } = useServiceDate();
  const plans = useQuery({ queryKey: ["plans"], queryFn: ({ signal }) => api<Plan[]>("/plan-history", { signal }), refetchInterval: 5000 });
  const runs = useQuery({ queryKey: ["runs"], queryFn: ({ signal }) => api<Run[]>("/runs", { signal }), refetchInterval: 5000 });
  const daily = useQuery({ queryKey: ["daily", day], queryFn: ({ signal }) => api<DailyHistory>(`/daily-updates/${day}`, { signal }) });
  const deliveries = useQuery({ queryKey: ["deliveries"], queryFn: ({ signal }) => api<Delivery[]>("/deliveries", { signal }) });
  const queries = [plans, runs, daily, deliveries];
  const latest = runs.data?.filter(r => localSingapore(r.as_of).startsWith(day)).sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const activeRun = runs.data?.filter(r => ["QUEUED", "RUNNING"].includes(r.status)).sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const pendingPlan = plans.data?.filter(p => p.status === "PENDING_APPROVAL").sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const approved = plans.data?.filter(p => p.status === "APPROVED").sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const currentRecommendation = pendingPlan ?? approved;
  const incoming = deliveries.data?.filter(d => Number(d.outstanding_quantity) > 0 && localSingapore(d.expected_at).slice(0, 10) <= day).length ?? 0;
  let title = "Your records are up to date.", description = "Review stock, sales coverage and purchasing context before making operational decisions. This is not a stock-sufficiency certification.", href = "/workspace/inventory", action = "Inspect stock", Icon = ClipboardCheck, tone = "calm";
  if (queries.some(q => q.isPending)) {
    title = "Checking what needs your attention…";
    description = "Loading recommendations, assessments, deliveries and the selected day’s closing status.";
  } else if (queries.some(q => q.error)) {
    title = "Some records could not be checked.";
    description = "A complete next-action summary is unavailable. Review the connection notices below; missing records do not mean everything is clear.";
    action = "Review activity"; href = "/workspace/activity"; tone = "warning";
  } else if (activeRun) {
    title = activeRun.status === "RUNNING" ? "ReStock is assessing the latest facts." : "Your assessment is in the queue.";
    description = "Wait for the result. Existing purchases stay unchanged.";
    href = `/workspace/activity/${encodeURIComponent(activeRun.id)}`; action = "Follow assessment"; Icon = Activity;
  } else if (latest && (latest.status === "FAILED" || latest.outcome === "ESCALATE") && (!currentRecommendation || latest.created_at >= currentRecommendation.created_at)) {
    title = latest.status === "FAILED" ? "An assessment needs follow-up." : "A change needs your review.";
    description = "No supported new purchase recommendation was established by this assessment. Inspect its findings and required follow-up.";
    href = `/workspace/activity/${encodeURIComponent(latest.id)}`; action = "Review assessment"; Icon = Activity; tone = "warning";
  } else if (pendingPlan) {
    title = pendingPlan.calculation_mode === "CONTINGENCY_ENGINE" ? "An additional purchase is awaiting your decision." : "A purchase recommendation is ready.";
    description = `Review version ${pendingPlan.version}, quantities and costs. Approval does not place an order.`;
    href = `/workspace/recommendations?version=${encodeURIComponent(pendingPlan.id)}`; action = "Review recommendation"; Icon = FileCheck2;
  } else if (approved) {
    title = "Your recommendation is approved.";
    description = "Arrange purchases separately. Check linked quantities before recording an order.";
    href = `/workspace/recommendations?version=${encodeURIComponent(approved.id)}`; action = "Review purchasing allocations"; Icon = FileCheck2;
  } else if (incoming) {
    title = `${incoming} ${incoming === 1 ? "delivery needs" : "deliveries need"} a status check.`;
    description = "Expected arrival is on or before the selected service date. Record a receipt only after stock arrives, or report a delay or shortfall.";
    href = "/workspace/deliveries"; action = "Review deliveries"; Icon = Truck;
  } else if (!daily.data?.revisions.length) {
    title = daily.data?.draft ? "Finish your closing update." : "Keep today’s records complete.";
    description = "Submit closing counts and final sales. Report intraday sales separately.";
    href = "/workspace/daily"; action = "Open daily update";
  }
  return (
    <section className={`attention-panel attention-${tone}`} aria-label="Next action">
      <span className="attention-icon"><Icon size={24} strokeWidth={1.5} aria-hidden="true" /></span>
      <div><p className="eyebrow">NEXT ACTION</p><h2>{title}</h2><p>{description}</p></div>
      {!queries.some(q => q.isPending) && <Link className="button button-primary" href={href}>{action}<ArrowRight size={16} aria-hidden="true" /></Link>}
    </section>
  );
}
