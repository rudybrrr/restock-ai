"use client";
import { useState } from "react";
import Link from "next/link";
import { useQueries, useQuery } from "@tanstack/react-query";
import { api, Ingredient, InventoryLot, NamedRecord } from "@/lib/api";
import { EventRecord, SalesBatch } from "@/lib/operations-types";
import { intervalSummary, recipeUsage } from "@/lib/intraday";
import { sumDecimals } from "@/lib/decimal";
import { singaporeTime } from "@/lib/format";
import {
  ErrorNotice,
  PageHeading,
  useServiceDate,
} from "@/components/workspace";

type Recipe = { menu_item_id: string; ingredient_id: string; quantity: string };

export default function Sales() {
  const { day } = useServiceDate();
  return <SalesDay key={day} day={day} />;
}

function SalesDay({ day }: { day: string }) {
  const [start, setStart] = useState("08:00");
  const [end, setEnd] = useState("21:00");
  const [refresh, setRefresh] = useState(true);
  const interval = refresh ? 10000 : false;
  const events = useQuery({
    queryKey: ["events"],
    queryFn: ({ signal }) => api<EventRecord[]>("/events", { signal }),
    refetchInterval: interval,
  });
  const ingredients = useQuery({
    queryKey: ["ingredients"],
    queryFn: ({ signal }) => api<Ingredient[]>("/ingredients", { signal }),
  });
  const menu = useQuery({
    queryKey: ["menu"],
    queryFn: ({ signal }) => api<NamedRecord[]>("/menu-items", { signal }),
  });
  const recipes = useQuery({
    queryKey: ["recipes"],
    queryFn: ({ signal }) => api<Recipe[]>("/recipes", { signal }),
  });
  const from = `${day}T${start}:00+08:00`,
    until = `${day}T${end}:00+08:00`;
  const valid = !!start && !!end && Date.parse(from) < Date.parse(until);
  const batches = (events.data ?? [])
    .filter((event) => event.type === "SALES_UPDATED")
    .map((event) => event.payload.batch as SalesBatch)
    .filter(Boolean);
  const summary = valid ? intervalSummary(batches, from, until) : null;
  const latest = summary?.included.reduce<string | null>(
    (last, batch) =>
      !last || Date.parse(batch.period_end) > Date.parse(last)
        ? batch.period_end
        : last,
    null,
  );
  const points = valid
    ? [...new Set([from, ...(latest ? [latest] : []), until])]
    : [];
  const estimates = useQueries({
    queries: points.map((at) => ({
      queryKey: ["inventory", "intraday", at],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api<InventoryLot[]>(
          `/inventory/estimated?as_of=${encodeURIComponent(at)}`,
          { signal },
        ),
      refetchInterval: interval,
    })),
  });
  const failures = [events, ingredients, menu, recipes].filter(
    (query) => query.error,
  );
  const loading = [events, ingredients, menu, recipes].some(
    (query) => query.isPending,
  );
  return (
    <>
      <PageHeading
        eyebrow="INTRADAY SALES"
        title="Follow the service day."
        description="Reported sales and backend stock estimates, with their timestamps and gaps kept visible."
      >
        <Link className="button button-secondary" href="/workspace/daily">
          Record or correct sales →
        </Link>
      </PageHeading>
      <div className="notice">
        Submitted or simulated sales—not a live POS connection. Refreshing
        retrieves recorded activity; it does not generate sales or trigger an
        assessment.
      </div>
      <section className="panel">
        <div className="panel-body form-grid">
          <label>
            Window start
            <input
              type="time"
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
          </label>
          <label>
            Window end
            <input
              type="time"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
            />
          </label>
          <label className="refresh-toggle">
            <input
              type="checkbox"
              checked={refresh}
              onChange={(e) => setRefresh(e.target.checked)}
            />{" "}
            Refresh every 10 seconds
          </label>
          <button
            className="button button-secondary"
            onClick={() => {
              void events.refetch();
              estimates.forEach((query) => void query.refetch());
            }}
          >
            Refresh now
          </button>
        </div>
      </section>
      {!valid && (
        <p role="alert">Choose an end time later than the start time.</p>
      )}
      {failures.map((query, index) => (
        <ErrorNotice
          key={index}
          error={query.error!}
          retry={() => query.refetch()}
        />
      ))}
      {loading && <p role="status">Loading reported sales…</p>}
      {!loading && !failures.length && summary && (
        <>
          <section className="panel">
            <header className="panel-head">
              <h2>Reported dish sales</h2>
              <span className="quiet">
                Latest included interval:{" "}
                {latest ? singaporeTime(latest) : "None"}
              </span>
            </header>
            <div className="panel-body">
              <p>
                {summary.included.length} active reports. Corrections replace
                previous revisions.
              </p>
              {summary.overlaps && (
                <p role="alert">
                  Overlapping intervals detected. Totals are withheld to avoid
                  double counting.
                </p>
              )}
              {!summary.overlaps && (
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Dish</th>
                        <th>Reported portions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {menu.data?.map((dish) => (
                        <tr key={dish.id}>
                          <td>{dish.name}</td>
                          <td>
                            {summary.included.length
                              ? (summary.totals[dish.id] ?? 0)
                              : "No reports"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="quiet">
                Totals cover only complete reports inside this window, not
                necessarily all sales. Zero means omitted or zero in those
                reports.
              </p>
              {summary.crossing.length > 0 && (
                <p>
                  {summary.crossing.length} boundary-crossing reports excluded;
                  quantities are not prorated.
                </p>
              )}
              <h3>Sales-report coverage</h3>
              {summary.gaps.length ? (
                <ul>
                  {summary.gaps.map((gap) => (
                    <li key={gap.start}>
                      {singaporeTime(gap.start)} – {singaporeTime(gap.end)}: no
                      complete report included
                    </li>
                  ))}
                </ul>
              ) : (
                <p>No gaps in the selected reporting window.</p>
              )}
              <p className="quiet">
                This window check is separate from the backend’s coverage check
                after each physical count.
              </p>
            </div>
          </section>
          <section className="panel">
            <header className="panel-head">
              <h2>Recipe-implied ingredient usage</h2>
            </header>
            <div className="panel-body">
              <p>
                Reported portions × current recipe quantities. This is not
                measured depletion, waste, or a substitute for the backend
                estimate.
              </p>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Ingredient</th>
                      <th>Calculated usage</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ingredients.data?.map((ingredient) => (
                      <tr key={ingredient.id}>
                        <td>{ingredient.name}</td>
                        <td>
                          {summary.overlaps || !summary.included.length
                            ? "Unavailable"
                            : sumDecimals(
                                (recipes.data ?? [])
                                  .filter(
                                    (recipe) =>
                                      recipe.ingredient_id === ingredient.id,
                                  )
                                  .map((recipe) =>
                                    recipeUsage(
                                      recipe.quantity,
                                      summary.totals[recipe.menu_item_id] ?? 0,
                                    ),
                                  ),
                              )}{" "}
                          {ingredient.unit}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
          <section className="panel">
            <header className="panel-head">
              <h2>Estimated-stock timeline</h2>
            </header>
            <div className="panel-body">
              <p>
                Backend estimates at the window start, latest included report,
                and window end. These are not future demand projections.
              </p>
              {estimates.map((query, index) => (
                <section key={points[index]}>
                  <h3>{singaporeTime(points[index])}</h3>
                  {query.error ? (
                    <ErrorNotice
                      error={query.error}
                      retry={() => query.refetch()}
                    />
                  ) : query.isPending ? (
                    <p role="status">Loading estimate…</p>
                  ) : !query.data?.length ? (
                    <p>No stock lots recorded at this cutoff.</p>
                  ) : (
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>Ingredient</th>
                            <th>Usable estimate</th>
                            <th>Coverage after count</th>
                          </tr>
                        </thead>
                        <tbody>
                          {ingredients.data?.map((ingredient) => {
                            const lots = query.data.filter(
                              (lot) => lot.ingredient_id === ingredient.id,
                            );
                            return (
                              <tr key={ingredient.id}>
                                <td>{ingredient.name}</td>
                                <td>
                                  {lots.length
                                    ? sumDecimals(
                                        lots
                                          .filter(
                                            (lot) => lot.status !== "EXPIRED",
                                          )
                                          .map((lot) => lot.quantity),
                                      )
                                    : "No lots"}{" "}
                                  {ingredient.unit}
                                </td>
                                <td>
                                  {!lots.length
                                    ? "Unknown"
                                    : lots.every(
                                          (lot) =>
                                            lot.coverage_complete === true,
                                        )
                                      ? "Complete"
                                      : "Incomplete"}
                                  {lots.some(
                                    (lot) =>
                                      Number(lot.unallocated_consumption ?? 0) >
                                      0,
                                  ) && " · uncovered consumption"}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              ))}
            </div>
          </section>
          <section className="panel">
            <header className="panel-head">
              <h2>Included report revisions</h2>
            </header>
            <div className="panel-body">
              {summary.included.length ? (
                summary.included.map((batch) => (
                  <p key={batch.id}>
                    {batch.source} · {batch.batch_id} · revision{" "}
                    {batch.revision} · {singaporeTime(batch.period_start)} –{" "}
                    {singaporeTime(batch.period_end)}
                    {batch.replaces_id && ` · corrects ${batch.replaces_id}`}
                  </p>
                ))
              ) : (
                <p>No complete reports in this window.</p>
              )}
            </div>
          </section>
        </>
      )}
    </>
  );
}
