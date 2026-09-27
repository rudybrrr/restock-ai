"use client";
import { useEffect, useId, useRef } from "react";
import { Offer } from "@/lib/operations-types";
import { localSingapore, singaporeTime } from "@/lib/format";
import { moneyOrUnavailable } from "@/lib/plan-cost";

export function SupplierTerms({ offer, supplier, ingredient, onClose }: {
  offer: Offer; supplier: string; ingredient: string; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    return () => element.close();
  }, []);
  const dates = new Map<string, string[]>();
  for (const arrival of [...new Set(offer.feasible_delivery_at ?? [])].sort()) {
    const date = localSingapore(arrival).slice(0, 10);
    dates.set(date, [...(dates.get(date) ?? []), arrival]);
  }
  return <dialog ref={dialog} className="supplier-terms-dialog" aria-labelledby={titleId} onClose={onClose}
    onClick={event => {
      if (event.target !== event.currentTarget) return;
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) event.currentTarget.close();
    }}>
    <header className="terms-header"><div><p className="eyebrow">SUPPLIER TERMS</p><h2 id={titleId}>{supplier} · {ingredient}</h2></div><button className="icon-button" aria-label="Close supplier terms" onClick={() => dialog.current?.close()}>✕</button></header>
    <div className="terms-body">
      <dl className="terms-facts">
        <div><dt>Lead time</dt><dd>{offer.lead_time_minutes === null ? "Unknown" : `${offer.lead_time_minutes} minutes`}</dd></div>
        <div><dt>Order cutoff</dt><dd>{offer.order_cutoff.kind === "LOCAL_TIME" ? `${offer.order_cutoff.local_time ?? "Unknown"} · Singapore` : offer.order_cutoff.kind.replaceAll("_", " ").toLowerCase()}</dd></div>
        <div><dt>Shelf life on arrival</dt><dd>{offer.shelf_life_days_on_arrival === null ? "Unknown" : `${offer.shelf_life_days_on_arrival} days`}</dd></div>
        <div><dt>Delivery fee</dt><dd>{moneyOrUnavailable(offer.delivery_fee_sgd)}</dd></div>
        <div><dt>Emergency fee</dt><dd>{moneyOrUnavailable(offer.emergency_fee_sgd)}</dd></div>
        <div><dt>Observed</dt><dd>{singaporeTime(offer.observed_at)}</dd></div>
      </dl>
      <h3>Arrival opportunities</h3>
      <p className="quiet">Singapore time · reported supplier slots, not reserved deliveries.</p>
      {offer.feasible_delivery_at === null ? <p>Arrival availability unknown.</p> : !dates.size ? <p>No feasible arrivals reported.</p> :
        <div className="arrival-schedule" tabIndex={0} aria-label="Reported arrival schedule">{[...dates].map(([date, arrivals]) => <div className="arrival-day" key={date}><strong>{new Intl.DateTimeFormat("en-SG", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Singapore" }).format(new Date(`${date}T00:00:00+08:00`))}</strong><div>{arrivals.map(arrival => <span key={arrival}>{new Intl.DateTimeFormat("en-SG", { hour: "numeric", minute: "2-digit", timeZone: "Asia/Singapore" }).format(new Date(arrival))}</span>)}</div></div>)}</div>}
    </div>
  </dialog>;
}
