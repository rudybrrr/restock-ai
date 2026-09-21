"use client";
import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { EventRecord } from "@/lib/operations-types";
import { humanize, singaporeTime } from "@/lib/format";
import { ErrorNotice } from "./workspace";

export function EventAssessments({ eventId }: { eventId: string }) {
  const query = useQuery({
    queryKey: ["event-assessments", eventId],
    queryFn: ({ signal }) =>
      api<{ run_id: string }[]>(
        `/manager/events/${encodeURIComponent(eventId)}/assessments`,
        { signal },
      ),
  });
  return (
    <div>
      {query.error ? (
        <ErrorNotice error={query.error} retry={() => query.refetch()} />
      ) : query.isPending ? (
        <p role="status">Loading linked assessments…</p>
      ) : query.data?.length ? (
        query.data.map((link) => (
          <p key={link.run_id}>
            <Link
              href={`/workspace/activity/${encodeURIComponent(link.run_id)}`}
            >
              Open assessment {link.run_id} →
            </Link>
          </p>
        ))
      ) : (
        <p className="quiet">No assessment linked to this event.</p>
      )}
    </div>
  );
}

type Adjustment = {
  lot_id: string;
  ingredient_id: string;
  unit: string;
  previous_quantity: string | null;
  corrected_quantity: string;
  delta: string | null;
};
export function CorrectionDetails({ event }: { event: EventRecord }) {
  const adjustments = event.payload.adjustments as Adjustment[] | undefined;
  return (
    <section className="evidence-display">
      <p>
        Effective{" "}
        {typeof event.payload.effective_at === "string"
          ? singaporeTime(event.payload.effective_at)
          : "time not recorded"}{" "}
        · recorded by {event.source}
      </p>
      <p>
        Revision {String(event.payload.revision_id ?? "Unknown")} replaces{" "}
        {String(event.payload.replaces_revision_id ?? "Unknown")}
      </p>
      {Array.isArray(adjustments) ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Ingredient / lot</th>
                <th>Previous count</th>
                <th>Corrected count</th>
                <th>Difference</th>
              </tr>
            </thead>
            <tbody>
              {adjustments.map((line) => (
                <tr key={line.lot_id}>
                  <td>
                    {line.ingredient_id}
                    <small>{line.lot_id}</small>
                  </td>
                  <td>{line.previous_quantity ?? "New observation"}</td>
                  <td>
                    {line.corrected_quantity} {line.unit}
                  </td>
                  <td>
                    {line.delta === null
                      ? "No earlier count"
                      : `${line.delta} ${line.unit}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>Detailed quantity changes were not recorded for this event.</p>
      )}
      <EventAssessments eventId={event.id} />
    </section>
  );
}

export function ChangeHistory({
  day,
  deliveryId,
}: {
  day?: string;
  deliveryId?: string;
}) {
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: ["events"],
    queryFn: ({ signal }) => api<EventRecord[]>("/events", { signal }),
    enabled: open,
  });
  const events = query.data?.filter((event) =>
    deliveryId
      ? ["DELIVERY_DELAYED", "DELIVERY_SHORT", "DELIVERY_CANCELLED"].includes(
          event.type,
        ) &&
        (event.payload.delivery as { id?: string } | undefined)?.id ===
          deliveryId
      : event.type === "INVENTORY_ADJUSTED" && event.payload.day === day,
  );
  return (
    <details
      className="record-details"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        {deliveryId
          ? "Delivery disruptions & assessments"
          : "Stock correction history"}
      </summary>
      {open &&
        (query.error ? (
          <ErrorNotice error={query.error} retry={() => query.refetch()} />
        ) : query.isPending ? (
          <p role="status">Loading changes…</p>
        ) : events?.length ? (
          events
            .slice()
            .reverse()
            .map((event) => (
              <section key={event.id}>
                <h3>
                  {humanize(event.type)} · {singaporeTime(event.timestamp)}
                </h3>
                {deliveryId ? (
                  <>
                    <DeliveryDisruption event={event} />
                    <EventAssessments eventId={event.id} />
                  </>
                ) : (
                  <CorrectionDetails event={event} />
                )}
              </section>
            ))
        ) : (
          <p>No changes recorded.</p>
        ))}
    </details>
  );
}

export function DeliveryDisruption({ event }: { event: EventRecord }) {
  const delivery = event.payload.delivery as
    | {
        expected_at?: string;
        expected_quantity?: string;
        outstanding_quantity?: string;
        cancelled_quantity?: string;
      }
    | undefined;
  return (
    <p>
      {humanize(event.type)} · recorded by {event.source}
      {delivery?.expected_at &&
        ` · expected arrival ${singaporeTime(delivery.expected_at)}`}
      {delivery?.expected_quantity !== undefined &&
        ` · expected ${delivery.expected_quantity}`}
      {delivery?.outstanding_quantity !== undefined &&
        ` · outstanding ${delivery.outstanding_quantity}`}
      {delivery?.cancelled_quantity !== undefined &&
        ` · cancelled ${delivery.cancelled_quantity}`}
    </p>
  );
}
