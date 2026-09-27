"use client";
import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, Ingredient, InventoryLot } from "@/lib/api";
import { sumDecimals } from "@/lib/decimal";
import { ErrorNotice, Status, useServiceDate } from "./workspace";

export function StockComparison() {
  const { day } = useServiceDate();
  return <StockDay key={day} day={day} />;
}
function StockDay({ day }: { day: string }) {
  const [time, setTime] = useState("08:00");
  const path = `/inventory/estimated?as_of=${encodeURIComponent(`${day}T${time}:00+08:00`)}`;
  const ingredients = useQuery({ queryKey: ["ingredients"], queryFn: ({ signal }) => api<Ingredient[]>("/ingredients", { signal }) });
  const physical = useQuery({ queryKey: ["inventory"], queryFn: ({ signal }) => api<InventoryLot[]>("/inventory", { signal }) });
  const estimates = useQuery({ queryKey: ["inventory", path], queryFn: ({ signal }) => api<InventoryLot[]>(path, { signal }), enabled: !!time });
  const queries = [ingredients, physical, estimates];
  return <section className="panel" aria-label="Stock comparison">
    <header className="panel-head"><h2>Counted and estimated stock</h2><Link href="/workspace/inventory">Inspect lots →</Link></header>
    <div className="panel-body"><label className="field-label">Estimate through (Singapore · {day})<input type="time" required value={time} onChange={e => { if (e.target.value) setTime(e.target.value); }} /></label><p className="compact-note">Counts may include expired lots. Estimates use reported activity; check coverage below.</p><details className="reading-note"><summary>How these quantities differ</summary><p>Counts are latest observations per batch, which may have different timestamps. Usable estimates account for later receipts, reported sales and expiry through the selected time. Neither a missing estimate nor incomplete sales coverage establishes zero stock or stock sufficiency.</p></details></div>
    {queries.some(q => q.error) ? <div className="panel-body">{queries.filter(q => q.error).map((q, i) => <ErrorNotice key={i} error={q.error!} retry={() => q.refetch()} />)}</div> : queries.some(q => q.isPending) ? <p className="empty-state" role="status">Loading stock comparison…</p> : <div className="table-scroll"><table><thead><tr><th>Ingredient</th><th>Latest recorded counts</th><th>Usable estimate · {time}</th><th>Sales coverage after count</th></tr></thead><tbody>{ingredients.data?.map(i => {
      const counts = physical.data?.filter(l => l.ingredient_id === i.id) ?? [];
      const estimated = estimates.data?.filter(l => l.ingredient_id === i.id) ?? [];
      return <tr key={i.id}><td>{i.name}</td><td>{counts.length ? `${sumDecimals(counts.map(l => l.quantity))} ${i.unit}` : "No observation"}</td><td>{estimated.length ? `${sumDecimals(estimated.filter(l => l.status !== "EXPIRED").map(l => l.quantity))} ${i.unit}` : "No estimate"}</td><td><Status value={!estimated.length ? "Unknown" : estimated.every(l => l.coverage_complete === true) ? "Complete" : "Incomplete"} />{estimated.some(l => Number(l.unallocated_consumption ?? "0") > 0) && <small>Uncovered ingredient use recorded</small>}</td></tr>;
    })}</tbody></table>{ingredients.data?.length === 0 && <p className="empty-state">No ingredient catalogue available for comparison.</p>}</div>}
  </section>;
}
