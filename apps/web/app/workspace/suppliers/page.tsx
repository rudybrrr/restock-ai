"use client";
import { useState } from "react";
import { SupplierTerms } from "@/components/supplier-terms";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Ingredient, NamedRecord } from "@/lib/api";
import { Offer, Promotion, OrderCycle } from "@/lib/operations-types";
import { timestamp } from "@/lib/format";
import {
  ErrorNotice,
  PageHeading,
  Status,
  TabDescription,
  useServiceDate,
} from "@/components/workspace";
export default function SuppliersPage() {
  const { day } = useServiceDate();
  const cache = useQueryClient();
  const [tab, setTab] = useState("Supplier offers");
  const [editing, setEditing] = useState<Offer | null>(null);
  const [terms, setTerms] = useState<Offer | null>(null);
  const [promotion, setPromotion] = useState<Promotion | null | undefined>(
    undefined,
  );
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [message, setMessage] = useState("");
  const [filter, setFilter] = useState("");
  const suppliers = useQuery({
    queryKey: ["suppliers"],
    queryFn: ({ signal }) => api<NamedRecord[]>("/suppliers", { signal }),
  });
  const ingredients = useQuery({
    queryKey: ["ingredients"],
    queryFn: ({ signal }) => api<Ingredient[]>("/ingredients", { signal }),
  });
  const offers = useQuery({
    queryKey: ["offers"],
    queryFn: ({ signal }) => api<Offer[]>("/supplier-offers", { signal }),
  });
  const menu = useQuery({
    queryKey: ["menu"],
    queryFn: ({ signal }) => api<NamedRecord[]>("/menu-items", { signal }),
  });
  const promotions = useQuery({
    queryKey: ["promotions"],
    queryFn: ({ signal }) => api<Promotion[]>("/promotions", { signal }),
    enabled: tab === "Promotions",
  });
  const cycles = useQuery({
    queryKey: ["cycles", day],
    queryFn: ({ signal }) =>
      api<OrderCycle[]>(`/order-cycles?start=${day}&end=${day}`, { signal }),
    enabled: tab === "Ordering occasions",
  });
  const holidays = useQuery({
    queryKey: ["holidays"],
    queryFn: ({ signal }) =>
      api<{ date: string; name: string; source_url: string }[]>("/holidays", {
        signal,
      }),
    enabled: tab === "Holidays",
  });
  async function mutate(path: string, method: string, body: unknown) {
    if (pending) return;
    setPending(true);
    setError(null);
    setMessage("");
    try {
      await api(path, { method, body });
      setMessage(
        "Change recorded. Review Activity for any resulting assessment.",
      );
      await cache.invalidateQueries();
      setEditing(null);
      setPromotion(undefined);
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Unable to save change."));
    } finally {
      setPending(false);
    }
  }
  return (
    <>
      <PageHeading
        eyebrow="RESTAURANT CONTEXT"
        title="Suppliers & promotions"
        description="Approved suppliers, promotions, ordering occasions, and holiday context."
      />
      <div
        className="tabs"
        role="tablist"
        aria-label="Restaurant context views"
      >
        {[
          "Supplier offers",
          "Promotions",
          "Ordering occasions",
          "Holidays",
        ].map((t) => (
          <button
            role="tab"
            key={t}
            aria-selected={tab === t}
            onClick={() => {
              setTab(t);
              setError(null);
              setMessage("");
            }}
          >
            {t}
          </button>
        ))}
      </div>
      <TabDescription tab={tab} />
      {error && <ErrorNotice error={error} />}{" "}
      {message && (
        <p role="status" className="notice">
          {message}
        </p>
      )}
      {(suppliers.error || ingredients.error || menu.error) && <ErrorNotice error={suppliers.error ?? ingredients.error ?? menu.error!} retry={() => { void suppliers.refetch(); void ingredients.refetch(); void menu.refetch(); }} />}
      {tab === "Supplier offers" && offers.isPending && <p role="status">Loading supplier offers…</p>}
      {tab === "Promotions" && promotions.isPending && <p role="status">Loading promotions…</p>}
      {tab === "Ordering occasions" && cycles.isPending && <p role="status">Loading ordering occasions…</p>}
      {tab === "Holidays" && holidays.isPending && <p role="status">Loading holiday context…</p>}
      {tab === "Supplier offers" && offers.data?.length === 0 && <p className="empty-state">No supplier offers recorded.</p>}
      {tab === "Supplier offers" && !!offers.data?.length && !offers.data.some(o => !filter || o.ingredient_id === filter) && <p className="empty-state">No supplier offers match this ingredient.</p>}
      {tab === "Holidays" && holidays.data?.length === 0 && <p className="empty-state">No holiday dates recorded.</p>}
      {tab === "Supplier offers" ? (
        <>
          <label className="field-label">
            Filter by ingredient
            <select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">All ingredients</option>
              {ingredients.data?.map((i) => (
                <option value={i.id} key={i.id}>
                  {i.name}
                </option>
              ))}
            </select>
          </label>
          {editing && (
            <form
              key={editing.id}
              className="panel"
              style={{ marginTop: 24 }}
              onSubmit={(e) => {
                e.preventDefault();
                const f = new FormData(e.currentTarget);
                const body: Record<string, unknown> = {
                  effective_at: timestamp(String(f.get("effective"))),
                };
                for (const key of [
                  "unit_price",
                  "available_quantity",
                  "recent_on_time_rate",
                  "current_status",
                ])
                  if (f.get(key) !== "") body[key] = f.get(key);
                mutate(
                  `/supplier-offers/${encodeURIComponent(editing.id)}`,
                  "PATCH",
                  body,
                );
              }}
            >
              <header className="panel-head">
                <h2>
                  Update {editing.ingredient_id} · {editing.supplier_id}
                </h2>
              </header>
              <fieldset
                disabled={pending}
                className="panel-body"
                style={{ border: 0 }}
              >
                <p className="quiet">
                  Leave a field blank to preserve its current value.
                </p>
                <div className="form-grid">
                  <label>
                    Unit price (SGD)
                    <input
                      name="unit_price"
                      type="number"
                      min="0"
                      step="0.01"
                      placeholder={editing.unit_price ?? "Unknown"}
                    />
                  </label>
                  <label>
                    Available quantity
                    <input
                      name="available_quantity"
                      type="number"
                      min="0"
                      step="0.001"
                      placeholder={editing.available_quantity ?? "Unknown"}
                    />
                  </label>
                  <label>
                    Recent on-time rate (0–1)
                    <input
                      name="recent_on_time_rate"
                      type="number"
                      min="0"
                      max="1"
                      step="0.001"
                      placeholder={editing.recent_on_time_rate ?? "Unknown"}
                    />
                  </label>
                  <label>
                    Status
                    <select name="current_status">
                      <option value="">Keep current status</option>
                      <option>AVAILABLE</option>
                      <option>UNAVAILABLE</option>
                      <option>UNKNOWN</option>
                    </select>
                  </label>
                  <label>
                    Effective at (Singapore)
                    <input
                      type="datetime-local"
                      required
                      name="effective"
                      defaultValue={`${day}T08:00`}
                    />
                  </label>
                </div>
                <div className="form-actions">
                  <button className="button button-primary">
                    Save supplier change
                  </button>
                  <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => setEditing(null)}
                  >
                    Cancel
                  </button>
                </div>
              </fieldset>
            </form>
          )}
          {offers.error ? (
            <ErrorNotice error={offers.error} retry={() => offers.refetch()} />
          ) : (
            <section className="panel" style={{ marginTop: 24 }}>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Supplier / ingredient</th>
                      <th>Unit price</th>
                      <th>Available</th>
                      <th>MOQ / pack</th>
                      <th>Status / context</th>
                      <th>Terms</th>
                    </tr>
                  </thead>
                  <tbody>
                    {offers.data
                      ?.filter((o) => !filter || o.ingredient_id === filter)
                      .map((o) => (
                        <tr key={o.id}>
                          <td>
                            {suppliers.data?.find((s) => s.id === o.supplier_id)
                              ?.name ?? o.supplier_id}
                            <small>
                              {ingredients.data?.find(
                                (i) => i.id === o.ingredient_id,
                              )?.name ?? o.ingredient_id}
                            </small>
                          </td>
                          <td>
                            {o.unit_price === null
                              ? "Unknown"
                              : `S$ ${o.unit_price}`}
                          </td>
                          <td>{o.available_quantity ?? "Unknown"}</td>
                          <td>
                            {o.moq ?? "Unknown"} / {o.pack_size ?? "Unknown"}
                          </td>
                          <td>
                            <Status value={o.current_status} />
                            <small>
                              On-time rate: {o.recent_on_time_rate ?? "Unknown"}
                            </small>
                          </td>
                          <td>
                            <button className="terms-link" onClick={() => setTerms(o)}>View terms</button>
                            <button
                              className="button button-secondary"
                              onClick={() => setEditing(o)}
                            >
                              Update
                            </button>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      ) : tab === "Promotions" ? (
        <>
          <button
            className="button button-primary"
            onClick={() => setPromotion(null)}
          >
            Add promotion
          </button>
          {promotion !== undefined && (
            <form
              className="panel"
              style={{ marginTop: 24 }}
              key={promotion?.id ?? "new"}
              onSubmit={(e) => {
                e.preventDefault();
                const f = new FormData(e.currentTarget);
                if (
                  f.getAll("dishes").length === 0 ||
                  String(f.get("end")) < String(f.get("start"))
                ) {
                  setError(
                    new Error(
                      "Choose at least one dish and an end date on or after the start date.",
                    ),
                  );
                  return;
                }
                mutate(
                  `/promotions/${encodeURIComponent(String(f.get("id")))}`,
                  "PUT",
                  {
                    revision: (promotion?.revision ?? 0) + 1,
                    name: f.get("name"),
                    start_date: f.get("start"),
                    end_date: f.get("end"),
                    menu_item_ids: f.getAll("dishes"),
                    demand_multiplier: f.get("multiplier"),
                    active: f.get("active") === "on",
                    effective_at: timestamp(String(f.get("effective"))),
                  },
                );
              }}
            >
              <fieldset
                disabled={pending}
                className="panel-body"
                style={{ border: 0 }}
              >
                <div className="form-grid">
                  <label>
                    Promotion identifier
                    <input
                      required
                      name="id"
                      defaultValue={promotion?.id ?? ""}
                      readOnly={!!promotion}
                    />
                  </label>
                  <label>
                    Name
                    <input
                      required
                      maxLength={100}
                      name="name"
                      defaultValue={promotion?.name ?? ""}
                    />
                  </label>
                  <label>
                    Start date
                    <input
                      required
                      type="date"
                      name="start"
                      defaultValue={promotion?.start_date ?? day}
                    />
                  </label>
                  <label>
                    End date
                    <input
                      required
                      type="date"
                      name="end"
                      defaultValue={promotion?.end_date ?? day}
                    />
                  </label>
                  <label>
                    Declared demand multiplier
                    <input
                      type="number"
                      min="0.001"
                      max="10"
                      step="0.001"
                      required
                      name="multiplier"
                      defaultValue={promotion?.demand_multiplier ?? ""}
                    />
                    <small>Explicit assumption; not measured demand.</small>
                  </label>
                  <label>
                    Effective at (Singapore)
                    <input
                      required
                      type="datetime-local"
                      name="effective"
                      defaultValue={`${day}T08:00`}
                    />
                  </label>
                  <label>
                    Active
                    <input
                      type="checkbox"
                      name="active"
                      defaultChecked={promotion?.active ?? true}
                    />
                  </label>
                </div>
                <fieldset style={{ marginTop: 20 }}>
                  <legend>Affected dishes (select at least one)</legend>
                  {menu.data?.map((m) => (
                    <label key={m.id} style={{ display: "block" }}>
                      <input
                        type="checkbox"
                        name="dishes"
                        value={m.id}
                        defaultChecked={promotion?.menu_item_ids.includes(m.id)}
                      />{" "}
                      {m.name}
                    </label>
                  ))}
                </fieldset>
                <div className="form-actions">
                  <button disabled={pending} className="button button-primary">
                    Save promotion revision
                  </button>
                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => setPromotion(undefined)}
                  >
                    Cancel
                  </button>
                </div>
              </fieldset>
            </form>
          )}
          {promotions.error ? (
            <ErrorNotice
              error={promotions.error}
              retry={() => promotions.refetch()}
            />
          ) : (
            promotions.data?.map((p) => (
              <section className="panel" key={p.id} style={{ marginTop: 20 }}>
                <header className="panel-head">
                  <h2>{p.name}</h2>
                  <Status value={p.active ? "Active" : "Inactive"} />
                </header>
                <div className="panel-body">
                  <p>
                    {p.start_date} – {p.end_date} · revision {p.revision}
                  </p>
                  <p>
                    {p.menu_item_ids
                      .map(
                        (id) => menu.data?.find((m) => m.id === id)?.name ?? id,
                      )
                      .join(", ")}
                  </p>
                  <p className="quiet">
                    Declared multiplier: {p.demand_multiplier}
                  </p>
                  <button
                    className="button button-secondary"
                    onClick={() => setPromotion(p)}
                  >
                    Edit promotion
                  </button>
                </div>
              </section>
            ))
          )}
        </>
      ) : tab === "Ordering occasions" ? (
        <>
          <p className="quiet">
            Occasions on {day}. Marking ordered does not record a purchase or
            create a delivery.
          </p>
          {cycles.error ? (
            <ErrorNotice error={cycles.error} retry={() => cycles.refetch()} />
          ) : (
            <section className="panel">
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Ingredient</th>
                      <th>Schedule date</th>
                      <th>Status</th>
                      <th>Decision</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cycles.data?.map((c) => (
                      <tr key={c.ingredient_id}>
                        <td>
                          {ingredients.data?.find(
                            (i) => i.id === c.ingredient_id,
                          )?.name ?? c.ingredient_id}
                        </td>
                        <td>{c.scheduled_date}</td>
                        <td>
                          <Status value={c.status} />
                        </td>
                        <td>
                          <form
                            onSubmit={(e) => {
                              e.preventDefault();
                              const f = new FormData(e.currentTarget);
                              mutate(
                                `/order-cycles/${encodeURIComponent(c.ingredient_id)}/${c.scheduled_date}/decision`,
                                "POST",
                                {
                                  status: f.get("status"),
                                  note: f.get("note") || null,
                                  effective_at: timestamp(
                                    String(f.get("effective")),
                                  ),
                                },
                              );
                            }}
                          >
                            <select
                              name="status"
                              aria-label={`Decision for ${c.ingredient_id}`}
                            >
                              <option>ORDERED</option>
                              <option>SKIPPED</option>
                            </select>
                            <input
                              name="note"
                              aria-label="Decision note"
                              maxLength={500}
                              placeholder="Optional note"
                            />
                            <input
                              name="effective"
                              aria-label="Decision effective time in Singapore"
                              required
                              type="datetime-local"
                              defaultValue={`${day}T08:00`}
                            />
                            <button
                              disabled={pending}
                              className="button button-secondary"
                            >
                              Record decision
                            </button>
                          </form>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {cycles.data?.length === 0 && (
                  <p className="empty-state">
                    No scheduled ordering occasions on this date.
                  </p>
                )}
              </div>
            </section>
          )}
        </>
      ) : holidays.error ? (
        <ErrorNotice error={holidays.error} retry={() => holidays.refetch()} />
      ) : (
        <section className="panel">
          <header className="panel-head">
            <h2>Singapore public holidays</h2>
          </header>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Holiday</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {holidays.data?.map((h) => (
                  <tr key={`${h.date}-${h.name}`}>
                    <td>{h.date}</td>
                    <td>{h.name}</td>
                    <td>
                      <a href={h.source_url} target="_blank" rel="noreferrer">
                        View source ↗
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="panel-body quiet">
            A holiday alone does not imply closure or increased demand.
          </p>
        </section>
      )}
      {terms && <SupplierTerms offer={terms}
        supplier={suppliers.data?.find(s => s.id === terms.supplier_id)?.name ?? terms.supplier_id}
        ingredient={ingredients.data?.find(i => i.id === terms.ingredient_id)?.name ?? terms.ingredient_id}
        onClose={() => setTerms(null)} />}
    </>
  );
}
