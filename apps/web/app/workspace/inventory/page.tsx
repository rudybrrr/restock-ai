"use client";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { InventorySummary } from "@/components/inventory-summary";
import { useQuery } from "@tanstack/react-query";
import { api, Ingredient, InventoryLot, NamedRecord } from "@/lib/api";
import { Delivery } from "@/lib/operations-types";
import {
  ErrorNotice,
  PageHeading,
  Status,
  TabDescription,
  useServiceDate,
} from "@/components/workspace";

type Recipe = { menu_item_id: string; ingredient_id: string; quantity: string };
export default function Inventory() {
  return <Suspense fallback={<p role="status">Loading inventory…</p>}><InventoryRoute /></Suspense>;
}
function InventoryRoute() {
  const view = useSearchParams().get("view");
  return <InventoryContent key={view} initialTab={view === "menu" ? "Menu & recipes" : view === "schedules" ? "Ordering schedules" : "Physical counts"} />;
}
function InventoryContent({ initialTab }: { initialTab: string }) {
  const { day } = useServiceDate();
  const [tab, setTab] = useState(initialTab);
  const referenceView = ["Menu & recipes", "Ordering schedules"].includes(initialTab);
  const [time, setTime] = useState("08:00");
  const [search, setSearch] = useState("");
  const ingredients = useQuery({
    queryKey: ["ingredients"],
    queryFn: ({ signal }) => api<Ingredient[]>("/ingredients", { signal }),
  });
  const path =
    tab === "Estimates"
      ? `/inventory/estimated?as_of=${encodeURIComponent(`${day}T${time}:00+08:00`)}`
      : "/inventory";
  const lots = useQuery({
    queryKey: ["inventory", path],
    queryFn: ({ signal }) => api<InventoryLot[]>(path, { signal }),
    enabled: ["Physical counts", "Estimates"].includes(tab),
  });
  const menu = useQuery({
    queryKey: ["menu"],
    queryFn: ({ signal }) => api<NamedRecord[]>("/menu-items", { signal }),
    enabled: tab === "Menu & recipes",
  });
  const recipes = useQuery({
    queryKey: ["recipes"],
    queryFn: ({ signal }) => api<Recipe[]>("/recipes", { signal }),
    enabled: tab === "Menu & recipes",
  });
  const deliveries = useQuery({ queryKey: ["deliveries"], queryFn: ({ signal }) => api<Delivery[]>("/deliveries", { signal }), enabled: tab === "Physical counts" });
  const names = Object.fromEntries(
    (ingredients.data ?? []).map((i) => [i.id, i.name]),
  );
  return (
    <>
      <PageHeading
        eyebrow={referenceView ? "RESTAURANT SETTINGS" : "STOCK & SALES"}
        title={referenceView ? initialTab : "Inventory"}
        description={tab === "Menu & recipes" ? "Inspect dishes and ingredient quantities per portion. Recipes are read-only." : tab === "Ordering schedules" ? "See each ingredient’s interval and starting date. Manage occasion decisions under Suppliers & promotions." : "Compare recorded counts with sales-based estimates."}
      />
      {!referenceView && <div className="tabs" role="tablist" aria-label="Inventory views">
        {[
          "Physical counts",
          "Estimates",
        ].map((t) => (
          <button
            role="tab"
            aria-selected={tab === t}
            key={t}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>}
      {!referenceView && <TabDescription tab={tab} />}
      {ingredients.error && (
        <ErrorNotice
          error={ingredients.error}
          retry={() => ingredients.refetch()}
        />
      )}{" "}
      {tab === "Menu & recipes" ? (
        <>
          {menu.error && (
            <ErrorNotice error={menu.error} retry={() => menu.refetch()} />
          )}{" "}
          {recipes.error && (
            <ErrorNotice
              error={recipes.error}
              retry={() => recipes.refetch()}
            />
          )}{" "}
          {(menu.isPending || recipes.isPending) && <p role="status">Loading menu and recipes…</p>}
          {menu.data?.length === 0 && <p className="empty-state">No menu items recorded.</p>}
          {menu.data?.map((d) => (
            <section className="panel" key={d.id}>
              <header className="panel-head">
                <h2>{d.name}</h2>
                <span className="quiet">Per portion</span>
              </header>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Ingredient</th>
                      <th>Quantity</th>
                      <th>Unit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recipes.data
                      ?.filter((r) => r.menu_item_id === d.id)
                      .map((r) => (
                        <tr key={r.ingredient_id}>
                          <td>{names[r.ingredient_id] ?? r.ingredient_id}</td>
                          <td>{r.quantity}</td>
                          <td>
                            {
                              ingredients.data?.find(
                                (i) => i.id === r.ingredient_id,
                              )?.unit
                            }
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </>
      ) : tab === "Ordering schedules" ? (
        <section className="panel">
          <header className="panel-head">
            <h2>Ingredient schedules</h2>
          </header>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Ingredient</th>
                  <th>Interval</th>
                  <th>Starting date</th>
                </tr>
              </thead>
              <tbody>
                {ingredients.data?.map((i) => (
                  <tr key={i.id}>
                    <td>{i.name}</td>
                    <td>Every {i.interval_days} days</td>
                    <td>{i.starting_date}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="panel-body">
            <p className="quiet">
              Schedules indicate occasions to order; a purchase is not
              automatically required.
            </p>
            <Link href="/workspace/suppliers">Manage ordering occasions →</Link>
          </div>
        </section>
      ) : (
        <>
          {lots.data && ingredients.data && (
            <InventorySummary
              lots={lots.data}
              ingredients={ingredients.data}
              estimated={tab === "Estimates"}
            />
          )}
          <div
            className="form-actions"
            style={{ marginBottom: 22, marginTop: 0 }}
          >
            <label>
              <span className="quiet">Find an ingredient </span>
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search ingredients"
              />
            </label>
            {tab === "Estimates" && (
              <label>
                <span className="quiet">As of (Singapore) </span>
                <input
                  type="time"
                  required
                  value={time}
                  onChange={(e) => {
                    if (e.target.value) setTime(e.target.value);
                  }}
                />
              </label>
            )}
          </div>
          {lots.error ? (
            <ErrorNotice error={lots.error} retry={() => lots.refetch()} />
          ) : (
            <section className="panel">
              <header className="panel-head">
                <h2>
                  {tab === "Estimates"
                    ? `Estimated at ${time} · ${day}`
                    : "Latest physical observations"}
                </h2>
                <span className="quiet">Batch-level detail</span>
              </header>
              {lots.isPending ? (
                <p className="empty-state" role="status">
                  Loading inventory…
                </p>
              ) : (
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Ingredient / lot</th>
                        <th>Quantity</th>
                        <th>Expiry</th>
                        <th>Last count</th>
                        <th>
                          {tab === "Estimates"
                            ? "Coverage"
                            : "As of selected day"}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {lots.data
                        ?.filter((l) =>
                          (names[l.ingredient_id] ?? l.ingredient_id)
                            .toLowerCase()
                            .includes(search.toLowerCase()),
                        )
                        .map((l) => (
                          <tr key={l.id}>
                            <td>
                              {names[l.ingredient_id] ?? l.ingredient_id}
                              <small>{l.id}</small>
                              {tab === "Physical counts" && <small>{deliveries.data?.some(d => d.receipts.some(r => r.lot_id === l.id)) ? "Created by a recorded delivery receipt" : deliveries.error || deliveries.isPending ? "Receipt provenance unavailable" : "No delivery receipt link recorded"}</small>}
                            </td>
                            <td>
                              {l.quantity}{" "}
                              <small>
                                {l.unit} · {l.provenance.toLowerCase()}
                              </small>
                            </td>
                            <td>
                              {l.expiry_date}
                              {l.expiry_date < day && (
                                <small>Expired by selected date</small>
                              )}
                            </td>
                            <td>
                              {new Date(l.counted_at).toLocaleString("en-SG", {
                                timeZone: "Asia/Singapore",
                                dateStyle: "medium",
                                timeStyle: "short",
                              })}
                            </td>
                            <td>
                              {tab === "Estimates" ? (
                                <>
                                  <Status
                                    value={
                                      l.coverage_complete
                                        ? "Complete"
                                        : "Incomplete"
                                    }
                                  />
                                  {l.unallocated_consumption &&
                                    Number(l.unallocated_consumption) > 0 && (
                                      <small>
                                        Uncovered ingredient use:{" "}
                                        {l.unallocated_consumption} {l.unit}{" "}
                                        (not additive across lots)
                                      </small>
                                    )}
                                </>
                              ) : (
                                <Status
                                  value={
                                    l.expiry_date < day
                                      ? "EXPIRED"
                                      : l.expiry_date === day
                                        ? "Expires today"
                                        : "Within expiry"
                                  }
                                />
                              )}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                  {lots.data?.length === 0 && (
                    <p className="empty-state">
                      No inventory lots have been recorded.
                    </p>
                  )}
                  {!!lots.data?.length && !lots.data.some(l => (names[l.ingredient_id] ?? l.ingredient_id).toLowerCase().includes(search.toLowerCase())) && <p className="empty-state">No lots match this ingredient. Try a different search.</p>}
                </div>
              )}
            </section>
          )}
        </>
      )}
      <p className="quiet">
        FEFO uses earlier-expiring eligible lots first, then earlier receipt
        time, then ascending lot ID. Only arrived, unexpired lots are eligible.
        Stock remains usable through its expiry date in Singapore time.
        Unexplained differences are not recorded waste.
      </p>
    </>
  );
}
