"use client";
import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Ingredient, NamedRecord, PlanLine } from "@/lib/api";
import { Delivery } from "@/lib/operations-types";
import { localSingapore, timestamp } from "@/lib/format";
import { ErrorNotice } from "./workspace";
type Allocation = PlanLine & { id: string; uncommitted_quantity: string };
export function PurchaseForm({
  day,
  requestedOpen,
  onClose,
}: {
  day: string;
  requestedOpen: boolean;
  onClose: () => void;
}) {
  const cache = useQueryClient();
  const params = useSearchParams();
  const router = useRouter();
  const link =
    params.get("plan") && params.get("line")
      ? { plan: params.get("plan")!, line: params.get("line")! }
      : null;
  const [dismissed, setDismissed] = useState(false);
  const open =
    requestedOpen || ((!!link || params.get("manual") === "1") && !dismissed);
  const allocations = useQuery({
    queryKey: ["plan-lines", link?.plan],
    queryFn: ({ signal }) =>
      api<Allocation[]>(`/plans/${encodeURIComponent(link!.plan)}/lines`, {
        signal,
      }),
    enabled: !!link && open,
  });
  const allocation = allocations.data?.find((l) => l.id === link?.line);
  const ingredients = useQuery({
    queryKey: ["ingredients"],
    queryFn: ({ signal }) => api<Ingredient[]>("/ingredients", { signal }),
    enabled: open,
  });
  const suppliers = useQuery({
    queryKey: ["suppliers"],
    queryFn: ({ signal }) => api<NamedRecord[]>("/suppliers", { signal }),
    enabled: open,
  });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [success, setSuccess] = useState("");
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (pending) return;
    const f = new FormData(e.currentTarget);
    setPending(true);
    setError(null);
    try {
      await api("/deliveries", {
        method: "POST",
        body: {
          supplier_id: allocation?.supplier_id ?? f.get("supplier"),
          ingredient_id: allocation?.ingredient_id ?? f.get("ingredient"),
          kind: f.get("kind"),
          expected_quantity: f.get("quantity"),
          ordered_at: timestamp(String(f.get("ordered"))),
          expected_at: timestamp(String(f.get("arrival"))),
          source_plan_line_id: allocation?.id ?? null,
          cycle_date: f.get("cycle") || null,
        },
      });
      setSuccess(
        "Actual purchase recorded. The quantity is expected supply until a receipt is recorded.",
      );
      await cache.invalidateQueries();
      setDismissed(true);
      onClose();
    } catch (e) {
      setError(
        e instanceof Error ? e : new Error("Purchase recording failed."),
      );
    } finally {
      setPending(false);
    }
  }
  if (!open)
    return success ? (
      <p role="status" className="notice">
        {success}
      </p>
    ) : null;
  return (
    <form className="panel" onSubmit={submit}>
      <header className="panel-head">
        <h2>
          {link ? "Record approved allocation" : "Record a manual purchase"}
        </h2>
        <button
          type="button"
          className="button button-secondary"
          disabled={pending}
          onClick={() => {
            setDismissed(true);
            onClose();
          }}
        >
          Close
        </button>
      </header>
      {link && (
        <button
          type="button"
          className="button button-secondary"
          disabled={pending}
          onClick={() => router.replace("/workspace/deliveries?manual=1")}
        >
          Record an unlinked manual purchase instead
        </button>
      )}
      <fieldset
        className="panel-body"
        style={{ border: 0 }}
        disabled={
          pending ||
          ingredients.isPending ||
          suppliers.isPending ||
          !!ingredients.error ||
          !!suppliers.error ||
          (!!link && !allocation)
        }
      >
        <p className="quiet">
          Only record purchases already arranged with a supplier. A manual
          deviation is kept separate from approved allocation provenance.
        </p>
        {allocations.error && (
          <ErrorNotice
            error={allocations.error}
            retry={() => allocations.refetch()}
          />
        )}{" "}
        {ingredients.error && <ErrorNotice error={ingredients.error} />}{" "}
        {suppliers.error && <ErrorNotice error={suppliers.error} />}{" "}
        {link && allocations.data && !allocation && (
          <p role="alert">The requested recommendation line is unavailable.</p>
        )}
        <div className="form-grid">
          <label>
            Supplier
            <select
              name="supplier"
              required
              key={allocation?.supplier_id ?? "manual"}
              defaultValue={allocation?.supplier_id ?? ""}
              disabled={!!allocation}
            >
              <option value="">Choose supplier</option>
              {suppliers.data?.map((s) => (
                <option value={s.id} key={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Ingredient
            <select
              name="ingredient"
              required
              key={allocation?.ingredient_id ?? "manual"}
              defaultValue={allocation?.ingredient_id ?? ""}
              disabled={!!allocation}
            >
              <option value="">Choose ingredient</option>
              {ingredients.data?.map((i) => (
                <option value={i.id} key={i.id}>
                  {i.name} ({i.unit})
                </option>
              ))}
            </select>
          </label>
          <label>
            Quantity
            <input
              name="quantity"
              required
              type="number"
              min="0.001"
              max={allocation?.uncommitted_quantity}
              step="0.001"
            />
            {allocation && (
              <small>
                Uncommitted allocation: {allocation.uncommitted_quantity}
              </small>
            )}
          </label>
          <label>
            Purchase type
            <select name="kind">
              <option>NORMAL</option>
              <option>EMERGENCY</option>
            </select>
          </label>
          <label>
            Ordered at (Singapore)
            <input
              type="datetime-local"
              name="ordered"
              required
              defaultValue={`${day}T08:00`}
            />
          </label>
          <label>
            Expected arrival (Singapore)
            <input
              type="datetime-local"
              name="arrival"
              required
              key={allocation?.arrival_at ?? day}
              defaultValue={
                allocation
                  ? localSingapore(allocation.arrival_at)
                  : `${day}T10:00`
              }
            />
          </label>
          <label>
            Ordering cycle date (optional)
            <input type="date" name="cycle" />
          </label>
        </div>
        {error && <ErrorNotice error={error} />}
        <div className="form-actions">
          <button className="button button-primary" type="submit">
            {pending ? "Recording…" : "Record actual purchase"}
          </button>
        </div>
      </fieldset>
    </form>
  );
}
export function DeliveryAction({
  delivery,
  mode,
  day,
  onClose,
}: {
  delivery: Delivery;
  mode: "receive" | "update";
  day: string;
  onClose: () => void;
}) {
  const cache = useQueryClient();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [message, setMessage] = useState("");
  const [requestId] = useState(
    () => `receipt-${globalThis.crypto.randomUUID()}`,
  );
  const [closing, setClosing] = useState<{ day: string; quantity: string }[]>(
    [],
  );
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (pending) return;
    const f = new FormData(e.currentTarget);
    if (
      mode === "receive" &&
      new Set(closing.map((entry) => entry.day)).size !== closing.length
    ) {
      setError(new Error("Use only one closing-count correction per day."));
      return;
    }
    if (
      mode === "receive" &&
      String(f.get("expiry")) < String(f.get("effective")).slice(0, 10)
    ) {
      setError(new Error("The expiry date cannot be before the receipt date."));
      return;
    }
    setPending(true);
    setError(null);
    const body =
      mode === "receive"
        ? {
            request_id: requestId,
            quantity: f.get("quantity"),
            received_at: timestamp(String(f.get("effective"))),
            expiry_date: f.get("expiry"),
            remainder: f.get("remainder"),
            closing_counts: Object.fromEntries(
              closing.filter((c) => c.day).map((c) => [c.day, c.quantity]),
            ),
          }
        : {
            expected_quantity: f.get("quantity"),
            expected_at: timestamp(String(f.get("arrival"))),
            effective_at: timestamp(String(f.get("effective"))),
            cancel_remainder: f.get("cancel") === "on",
          };
    try {
      await api(
        `/deliveries/${encodeURIComponent(delivery.id)}/${mode === "receive" ? "receive" : "update"}`,
        { method: "POST", body },
      );
      setMessage(
        mode === "receive"
          ? "Receipt recorded and inventory updated."
          : "Delivery expectations updated.",
      );
      await cache.invalidateQueries();
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Delivery action failed."));
    } finally {
      setPending(false);
    }
  }
  return (
    <form className="panel" onSubmit={submit}>
      <header className="panel-head">
        <h2>
          {mode === "receive"
            ? "Receive delivery"
            : "Update delivery expectations"}
        </h2>
        <button
          className="button button-secondary"
          type="button"
          disabled={pending}
          onClick={onClose}
        >
          Close
        </button>
      </header>
      <fieldset
        className="panel-body"
        style={{ border: 0 }}
        disabled={pending || !!message}
      >
        <p className="quiet">
          {delivery.ingredient_id} · {delivery.supplier_id} · Outstanding:{" "}
          {delivery.outstanding_quantity}
        </p>
        <div className="form-grid">
          <label>
            {mode === "receive" ? "Quantity received" : "New expected total"}
            <input
              name="quantity"
              type="number"
              min="0.001"
              max={
                mode === "receive" ? delivery.outstanding_quantity : undefined
              }
              step="0.001"
              required
              defaultValue={
                mode === "receive" ? "" : delivery.expected_quantity
              }
            />
          </label>
          <label>
            {mode === "receive" ? "Received at" : "Change effective at"}{" "}
            (Singapore)
            <input
              name="effective"
              type="datetime-local"
              required
              defaultValue={`${day}T10:00`}
            />
          </label>
          {mode === "receive" ? (
            <>
              <label>
                Actual expiry date
                <input type="date" name="expiry" required />
              </label>
              <label>
                Unreceived remainder
                <select name="remainder">
                  <option value="EXPECTED">Still expected</option>
                  <option value="CANCELLED">Cancel remainder</option>
                </select>
              </label>
            </>
          ) : (
            <>
              <label>
                Expected arrival (Singapore)
                <input
                  name="arrival"
                  required
                  type="datetime-local"
                  defaultValue={localSingapore(delivery.expected_at)}
                />
              </label>
              <label>
                <span>Cancel outstanding remainder</span>
                <input name="cancel" type="checkbox" />
                <small>Cancellation closes the remaining commitment.</small>
              </label>
            </>
          )}
        </div>
        {mode === "receive" && (
          <details className="record-details">
            <summary>Late receipt: closing-count corrections</summary>
            <p className="quiet">
              For a receipt entered after a closing update, provide the new
              lot’s physical closing quantity for every affected submitted day.
            </p>
            {closing.map((c, i) => (
              <div className="form-actions" key={i}>
                <label>
                  Closing day
                  <input
                    type="date"
                    required
                    value={c.day}
                    onChange={(e) =>
                      setClosing(
                        closing.map((x, j) =>
                          j === i ? { ...x, day: e.target.value } : x,
                        ),
                      )
                    }
                  />
                </label>
                <label>
                  Quantity remaining
                  <input
                    type="number"
                    min="0"
                    step="0.001"
                    required
                    value={c.quantity}
                    onChange={(e) =>
                      setClosing(
                        closing.map((x, j) =>
                          j === i ? { ...x, quantity: e.target.value } : x,
                        ),
                      )
                    }
                  />
                </label>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => setClosing(closing.filter((_, j) => j !== i))}
                >
                  Remove
                </button>
              </div>
            ))}
            <button
              type="button"
              className="button button-secondary"
              onClick={() =>
                setClosing([...closing, { day: "", quantity: "" }])
              }
            >
              Add closing correction
            </button>
          </details>
        )}
        {error && <ErrorNotice error={error} />}
        <div className="form-actions">
          <button className="button button-primary" type="submit">
            {pending
              ? "Saving…"
              : mode === "receive"
                ? "Confirm receipt"
                : "Confirm delivery update"}
          </button>
        </div>
      </fieldset>
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
    </form>
  );
}
