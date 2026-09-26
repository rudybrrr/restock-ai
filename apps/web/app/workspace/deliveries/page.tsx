"use client";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { PurchasingSteps } from "@/components/purchasing-steps";
import { useQuery } from "@tanstack/react-query";
import { api, Ingredient, NamedRecord } from "@/lib/api";
import { Delivery } from "@/lib/operations-types";
import { singaporeTime, localSingapore } from "@/lib/format";
import {
  ErrorNotice,
  PageHeading,
  Status,
  TabDescription,
  useServiceDate,
} from "@/components/workspace";
import { PurchaseForm, DeliveryAction } from "@/components/delivery-forms";
import { ChangeHistory } from "@/components/change-events";
export default function DeliveriesPage() {
  const view = useSearchParams().get("view");
  return <DeliveriesContent key={view} receiving={view === "receive"} />;
}
function DeliveriesContent({ receiving }: { receiving: boolean }) {
  const { day } = useServiceDate();
  const [create, setCreate] = useState(false);
  const [filter, setFilter] = useState(receiving ? "Outstanding" : "All");
  const [arrivalDay, setArrivalDay] = useState("");
  const [action, setAction] = useState<{
    delivery: Delivery;
    mode: "receive" | "update";
  } | null>(null);
  const q = useQuery({
    queryKey: ["deliveries"],
    queryFn: ({ signal }) => api<Delivery[]>("/deliveries", { signal }),
  });
  const ingredients = useQuery({
    queryKey: ["ingredients"],
    queryFn: ({ signal }) => api<Ingredient[]>("/ingredients", { signal }),
  });
  const suppliers = useQuery({
    queryKey: ["suppliers"],
    queryFn: ({ signal }) => api<NamedRecord[]>("/suppliers", { signal }),
  });
  return (
    <>
      <PageHeading
        eyebrow="ACTUAL PURCHASES & DELIVERIES"
        title="Purchases & deliveries"
        description="Track actual purchases, arrivals and receipts."
      >
        <button
          className="button button-primary"
          onClick={() => setCreate(!create)}
        >
          {create ? "Close purchase form" : "Record actual purchase"}
        </button>
      </PageHeading>
      <PurchasingSteps receiving={filter === "Outstanding" || action?.mode === "receive"} />
      <Suspense fallback={<p role="status">Loading purchase form…</p>}>
        <PurchaseForm
          day={day}
          requestedOpen={create}
          onClose={() => setCreate(false)}
        />
      </Suspense>
      <p className="compact-note">Purchases are expected supply. Only a receipt adds inventory.</p>
      <div className="tabs" role="tablist" aria-label="Delivery filter">
        {["All", "Outstanding", "Closed"].map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={filter === t}
            onClick={() => setFilter(t)}
          >
            {t}
          </button>
        ))}
      </div>
      <TabDescription tab={filter} />
      <label className="field-label">
        Expected arrival date (optional)
        <input
          type="date"
          value={arrivalDay}
          onChange={(event) => setArrivalDay(event.target.value)}
        />
      </label>
      {action && (
        <DeliveryAction
          key={`${action.delivery.id}-${action.mode}`}
          day={day}
          delivery={action.delivery}
          mode={action.mode}
          onClose={() => setAction(null)}
        />
      )}{" "}
      {q.error ? (
        <ErrorNotice error={q.error} retry={() => q.refetch()} />
      ) : q.isPending ? (
        <p role="status">Loading deliveries…</p>
      ) : (
        <section className="panel">
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Ingredient / supplier</th>
                  <th>Expected arrival</th>
                  <th>Ordered</th>
                  <th>Received</th>
                  <th>Outstanding</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {q.data
                  ?.filter(
                    (delivery) =>
                      !arrivalDay ||
                      localSingapore(delivery.expected_at).startsWith(
                        arrivalDay,
                      ),
                  )
                  ?.filter(
                    (d) =>
                      filter === "All" ||
                      (filter === "Outstanding"
                        ? Number(d.outstanding_quantity) > 0
                        : Number(d.outstanding_quantity) === 0),
                  )
                  .slice()
                  .reverse()
                  .map((d) => (
                    <tr key={d.id}>
                      <td>
                        {ingredients.data?.find((i) => i.id === d.ingredient_id)
                          ?.name ?? d.ingredient_id}
                        <small>
                          {suppliers.data?.find((s) => s.id === d.supplier_id)
                            ?.name ?? d.supplier_id}
                        </small>
                        <Status value={d.source_validation} />
                        <ChangeHistory deliveryId={d.id} />
                        <details>
                          <summary>Receipt history</summary>
                          {d.receipts.length ? (
                            d.receipts.map((r) => (
                              <p className="quiet" key={r.id}>
                                {r.quantity} · {singaporeTime(r.received_at)} ·
                                lot {r.lot_id} · expiry {r.expiry_date}
                              </p>
                            ))
                          ) : (
                            <p className="quiet">No receipts recorded.</p>
                          )}
                          <small>Delivery: {d.id}</small>
                          <small>Ordered: {singaporeTime(d.ordered_at)}</small>
                          <small>Expected expiry: {d.expected_expiry_date ?? "Not recorded"}</small>
                          <small>Cancelled: {d.cancelled_quantity}</small>
                        </details>
                      </td>
                      <td>{singaporeTime(d.expected_at)}</td>
                      <td>{d.expected_quantity}</td>
                      <td>{d.received_quantity}</td>
                      <td>
                        {d.outstanding_quantity}
                        <small>
                          {
                            ingredients.data?.find(
                              (i) => i.id === d.ingredient_id,
                            )?.unit
                          }
                        </small>
                      </td>
                      <td>
                        <div className="form-actions" style={{ margin: 0 }}>
                          <button
                            className="button button-secondary"
                            disabled={Number(d.outstanding_quantity) === 0}
                            onClick={() =>
                              setAction({ delivery: d, mode: "receive" })
                            }
                          >
                            Receive
                          </button>
                          <button
                            className="button button-secondary"
                            disabled={Number(d.outstanding_quantity) === 0}
                            onClick={() =>
                              setAction({ delivery: d, mode: "update" })
                            }
                          >
                            Update
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          {q.data?.length === 0 && (
            <div className="empty-state">
              <h3>No purchases recorded yet.</h3>
              <p>
                Once you arrange an order with a supplier, record it here.
                Approval alone does not create an incoming delivery.
              </p>
            </div>
          )}
          {!!q.data?.length && !q.data.some(d => (!arrivalDay || localSingapore(d.expected_at).startsWith(arrivalDay)) && (filter === "All" || (filter === "Outstanding" ? Number(d.outstanding_quantity) > 0 : Number(d.outstanding_quantity) === 0))) && <p className="empty-state">No deliveries match these filters. Choose All or clear the arrival date.</p>}
        </section>
      )}
    </>
  );
}
