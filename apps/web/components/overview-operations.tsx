"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import {
  DailyHistory,
  Delivery,
  EventRecord,
  OrderCycle,
  Promotion,
} from "@/lib/operations-types";
import { singaporeTime, humanize } from "@/lib/format";
import { ErrorNotice, Status, useServiceDate } from "./workspace";
export function OverviewOperations() {
  const { day } = useServiceDate();
  const daily = useQuery({
    queryKey: ["daily", day],
    queryFn: ({ signal }) =>
      api<DailyHistory>(`/daily-updates/${day}`, { signal }),
  });
  const deliveries = useQuery({
    queryKey: ["deliveries"],
    queryFn: ({ signal }) => api<Delivery[]>("/deliveries", { signal }),
  });
  const cycles = useQuery({
    queryKey: ["cycles", day],
    queryFn: ({ signal }) =>
      api<OrderCycle[]>(`/order-cycles?start=${day}&end=${day}`, { signal }),
  });
  const events = useQuery({
    queryKey: ["events"],
    queryFn: ({ signal }) => api<EventRecord[]>("/events", { signal }),
  });
  const promotions = useQuery({
    queryKey: ["promotions"],
    queryFn: ({ signal }) => api<Promotion[]>("/promotions", { signal }),
  });
  const relevantPromotions = promotions.data?.filter(p => p.active && p.end_date >= day)
    .sort((a, b) => a.start_date.localeCompare(b.start_date));
  return (
    <>
      <div className="two-columns">
        <section className="panel">
          <header className="panel-head">
            <h2>Daily closing & ordering</h2>
            <Link href="/workspace/daily">Open daily update →</Link>
          </header>
          <div className="panel-body">
            {daily.error ? (
              <ErrorNotice error={daily.error} retry={() => daily.refetch()} />
            ) : daily.isPending ? (
              <p role="status">Loading closing status…</p>
            ) : (
              <>
                <Status
                  value={
                    daily.data.revisions.length
                      ? "Submitted"
                      : daily.data.draft
                        ? "Draft"
                        : "Not submitted"
                  }
                />
                <p className="quiet">
                  {day}
                  {daily.data.revisions.length
                    ? ` · revision ${daily.data.revisions.at(-1)?.revision}`
                    : " · closing count still to submit"}
                </p>
              </>
            )}
            {cycles.error ? (
              <ErrorNotice
                error={cycles.error}
                retry={() => cycles.refetch()}
              />
            ) : (
              cycles.data?.map((c) => (
                <p key={c.ingredient_id}>
                  {c.ingredient_id} <Status value={c.status} />
                </p>
              ))
            )}
            {cycles.data?.length === 0 && (
              <p className="quiet">No ordering occasions today.</p>
            )}
            <Link className="text-link" href="/workspace/suppliers">
              Manage ordering occasions →
            </Link>
          </div>
        </section>
        <section className="panel">
          <header className="panel-head">
            <h2>On the way</h2>
            <Link href="/workspace/deliveries">View deliveries →</Link>
          </header>
          <div className="panel-body">
            {deliveries.error ? (
              <ErrorNotice
                error={deliveries.error}
                retry={() => deliveries.refetch()}
              />
            ) : deliveries.isPending ? (
              <p role="status">Loading deliveries…</p>
            ) : deliveries.data.filter(
                (d) => Number(d.outstanding_quantity) > 0,
              ).length ? (
              deliveries.data
                .filter((d) => Number(d.outstanding_quantity) > 0)
                .slice(0, 4)
                .map((d) => (
                  <div key={d.id} className="record-details">
                    <strong>{d.ingredient_id}</strong>
                    <p>
                      {d.outstanding_quantity} outstanding · {d.supplier_id}
                    </p>
                    <small>Expected {singaporeTime(d.expected_at)}</small>
                  </div>
                ))
            ) : (
              <p className="quiet">No outstanding deliveries recorded.</p>
            )}
          </div>
        </section>
      </div>
      <section className="panel">
        <header className="panel-head"><h2>Active & upcoming promotions</h2><Link href="/workspace/suppliers">Manage promotions →</Link></header>
        <div className="panel-body">
          {promotions.error ? <ErrorNotice error={promotions.error} retry={() => promotions.refetch()} />
            : promotions.isPending ? <p role="status">Loading promotions…</p>
              : relevantPromotions?.length ? relevantPromotions.slice(0, 4).map(p => <div key={p.id} className="record-details"><strong>{p.name}</strong><p><Status value={p.start_date > day ? "Upcoming" : "Active"} /> · {p.start_date} – {p.end_date}</p><small>Configured demand multiplier: {p.demand_multiplier} · revision {p.revision}. This is an input, not a certified demand forecast.</small></div>)
                : <p className="quiet">No active or upcoming promotions for the selected date.</p>}
        </div>
      </section>
      <section className="panel">
        <header className="panel-head">
          <h2>Latest changes</h2>
          <Link href="/workspace/activity">View timeline →</Link>
        </header>
        <div className="panel-body">
          {events.error ? (
            <ErrorNotice error={events.error} retry={() => events.refetch()} />
          ) : events.isPending ? <p role="status">Loading recent changes…</p> : (
            events.data
              ?.slice(-4)
              .reverse()
              .map((e) => (
                <p key={e.id}>
                  {humanize(e.type)}{" "}
                  <small className="quiet">
                    · {singaporeTime(e.timestamp)}
                  </small>
                </p>
              ))
          )}
          {events.data?.length === 0 && (
            <p className="quiet">No changes recorded yet.</p>
          )}
        </div>
      </section>
    </>
  );
}
