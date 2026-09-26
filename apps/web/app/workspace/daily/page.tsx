"use client";
import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Ingredient, InventoryLot, NamedRecord } from "@/lib/api";
import { DailyHistory, DailyRevision, Draft } from "@/lib/operations-types";
import { localSingapore, singaporeTime, timestamp } from "@/lib/format";
import {
  ErrorNotice,
  PageHeading,
  Status,
  TabDescription,
  useServiceDate,
} from "@/components/workspace";
import { SalesEntry } from "@/components/sales-entry";
import { ChangeHistory } from "@/components/change-events";

export default function DailyPage() {
  return <Suspense fallback={<p role="status">Loading daily operations…</p>}><DailyContent /></Suspense>;
}
function DailyContent() {
  const params = useSearchParams();
  const view = params.get("view");
  return <DailyTabs key={view} initialTab={view === "sales" ? "Sales intervals" : "Closing update"} />;
}
function DailyTabs({ initialTab }: { initialTab: string }) {
  const { day } = useServiceDate();
  const [tab, setTab] = useState(initialTab);
  return (
    <>
      <PageHeading
        eyebrow="DAILY OPERATIONS"
        title={tab === "Sales intervals" ? "Report sales" : "Closing update"}
        description={`Physical counts and final dish sales · ${day} · Singapore time`}
      />
      <div className="tabs" role="tablist" aria-label="Daily operations">
        {["Closing update", "Sales intervals"].map((t) => (
          <button
            role="tab"
            key={t}
            aria-selected={t === tab}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>
      <TabDescription tab={tab} />
      {tab === "Closing update" ? (
        <>
          <DailyEditor key={day} day={day} />
          <ChangeHistory key={`corrections-${day}`} day={day} />
        </>
      ) : (
        <SalesEntry key={day} day={day} />
      )}
    </>
  );
}
function DailyEditor({ day }: { day: string }) {
  const cache = useQueryClient();
  const history = useQuery({
    queryKey: ["daily", day],
    queryFn: ({ signal }) =>
      api<DailyHistory>(`/daily-updates/${day}`, { signal }),
  });
  const lots = useQuery({
    queryKey: ["inventory"],
    queryFn: ({ signal }) => api<InventoryLot[]>("/inventory", { signal }),
  });
  const menu = useQuery({
    queryKey: ["menu"],
    queryFn: ({ signal }) => api<NamedRecord[]>("/menu-items", { signal }),
  });
  const ingredients = useQuery({
    queryKey: ["ingredients"],
    queryFn: ({ signal }) => api<Ingredient[]>("/ingredients", { signal }),
  });
  const [edited, setEdited] = useState<Draft | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [message, setMessage] = useState("");
  const [confirm, setConfirm] = useState(false);
  const latest = history.data?.revisions.at(-1);
  const draft = edited ??
    history.data?.draft ??
    latest ?? { cutoff: `${day}T22:00:00+08:00`, counts: {}, sales: {} };
  function change(patch: Partial<Draft>) {
    setEdited({ ...draft, ...patch });
    setMessage("");
    setConfirm(false);
  }
  async function save(submit: boolean) {
    if (pending) return;
    if (!validEntries || (submit && !complete)) {
      setError(
        new Error(
          "Enter non-negative quantities (up to three decimal places) and whole-number sales. Complete every field before submitting.",
        ),
      );
      return;
    }
    setPending(true);
    setError(null);
    setMessage("");
    try {
      await api(`/daily-updates/${day}/draft`, {
        method: "POST",
        body: {
          cutoff: draft.cutoff,
          counts: draft.counts,
          sales: draft.sales,
        },
      });
      if (submit) {
        await api<DailyRevision>(`/daily-updates/${day}/submit`, {
          method: "POST",
        });
        setMessage(
          "Closing update submitted. Assessment requested; follow its progress in Activity.",
        );
      } else
        setMessage("Draft saved. No assessment is requested until submission.");
      setEdited(null);
      setConfirm(false);
      await cache.invalidateQueries();
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Unable to save update."));
    } finally {
      setPending(false);
    }
  }
  const relevant =
    lots.data?.filter(
      (l) =>
        new Date(l.received_at) <= new Date(draft.cutoff) &&
        (l.expiry_date >= day || l.id in draft.counts),
    ) ?? [];
  const validEntries =
    Number.isFinite(Date.parse(draft.cutoff)) &&
    Object.values(draft.counts).every((value) =>
      /^\d+(\.\d{1,3})?$/.test(value),
    ) &&
    Object.values(draft.sales).every(
      (value) => Number.isSafeInteger(value) && value >= 0,
    );
  const complete =
    validEntries &&
    relevant.every((l) => l.id in draft.counts) &&
    (menu.data?.every((d) => d.id in draft.sales) ?? false);
  const errors = [history, lots, menu, ingredients].filter((q) => q.error);
  if (errors.length)
    return (
      <>
        {errors.map((q, i) => (
          <ErrorNotice key={i} error={q.error!} retry={() => q.refetch()} />
        ))}
      </>
    );
  if ([history, lots, menu, ingredients].some((q) => q.isPending))
    return <p role="status">Loading closing records…</p>;
  return (
    <>
      {latest && (
        <div className="notice">
          Revision {latest.revision} submitted by {latest.actor}. Editing
          creates a correction with the original cutoff.
        </div>
      )}
      <label className="field-label">
        Closing cutoff (Singapore)
        <input
          type="datetime-local"
          required
          value={localSingapore(draft.cutoff)}
          disabled={!!latest || pending}
          onChange={(e) => {
            if (e.target.value) change({ cutoff: timestamp(e.target.value) });
          }}
        />
      </label>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save(false);
        }}
      >
        <fieldset disabled={pending} style={{ border: 0, padding: 0 }}>
          <div className="two-columns" style={{ marginTop: 24 }}>
            <section className="panel">
              <header className="panel-head">
                <h2>Count each batch</h2>
                <span className="quiet">Enter what is physically left</span>
              </header>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Ingredient / batch</th>
                      <th>Closing quantity</th>
                    </tr>
                  </thead>
                  <tbody>
                    {relevant.map((l) => (
                      <tr key={l.id}>
                        <td>
                          {ingredients.data?.find(
                            (i) => i.id === l.ingredient_id,
                          )?.name ?? l.ingredient_id}
                          <small>
                            {l.id} · expiry {l.expiry_date}
                          </small>
                        </td>
                        <td>
                          <input
                            aria-label={`Closing quantity for ${l.id}`}
                            type="number"
                            min="0"
                            step="0.001"
                            value={draft.counts[l.id] ?? ""}
                            placeholder="Not entered"
                            onChange={(e) => {
                              const counts = { ...draft.counts };
                              if (e.target.value === "") delete counts[l.id];
                              else counts[l.id] = e.target.value;
                              change({ counts });
                            }}
                            style={{ width: 110 }}
                          />{" "}
                          {l.unit}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
            <section className="panel">
              <header className="panel-head">
                <h2>Final dish sales</h2>
              </header>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Dish</th>
                      <th>Portions sold</th>
                    </tr>
                  </thead>
                  <tbody>
                    {menu.data?.map((d) => (
                      <tr key={d.id}>
                        <td>{d.name}</td>
                        <td>
                          <input
                            aria-label={`Final sales for ${d.name}`}
                            type="number"
                            min="0"
                            step="1"
                            placeholder="Not entered"
                            value={draft.sales[d.id] ?? ""}
                            onChange={(e) => {
                              const sales = { ...draft.sales };
                              if (e.target.value === "") delete sales[d.id];
                              else sales[d.id] = Number(e.target.value);
                              change({ sales });
                            }}
                            style={{ width: 110 }}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
          <p className="quiet">
            Blank means not entered. Enter 0 explicitly when nothing remains or
            no portions were sold. Closing counts are authoritative and will not
            have today’s sales deducted again.
          </p>
          {error && <ErrorNotice error={error} />}{" "}
          {message && (
            <p className="notice" role="status">
              {message}
            </p>
          )}
          <div className="form-actions">
            <button type="submit" className="button button-secondary">
              {pending ? "Saving…" : "Save draft"}
            </button>
            <button
              type="button"
              disabled={!complete || pending}
              className="button button-primary"
              onClick={() => setConfirm(true)}
            >
              Review submission
            </button>
          </div>
          {confirm && (
            <div className="notice">
              <strong>Submit closing update for {day}?</strong>
              <p>
                This records a physical observation and requests an assessment.
              </p>
              <div className="form-actions">
                <button
                  type="button"
                  className="button button-primary"
                  onClick={() => save(true)}
                >
                  Confirm submission
                </button>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => setConfirm(false)}
                >
                  Keep editing
                </button>
              </div>
            </div>
          )}
        </fieldset>
      </form>
      {message && <p><Link href="/workspace/activity">Review assessments and submission activity →</Link></p>}
      <section className="panel">
        <header className="panel-head">
          <h2>Submission history & reconciliation</h2>
        </header>
        <div className="panel-body">
          {history.data?.revisions.length ? (
            history.data.revisions
              .slice()
              .reverse()
              .map((r) => (
                <details key={r.id} className="record-details">
                  <summary>
                    Revision {r.revision} · {singaporeTime(r.recorded_at)} ·{" "}
                    {r.actor}
                  </summary>
                  {r.reconciliation ? (
                    <>
                      <Status value={r.reconciliation.status} />
                      <div className="table-scroll">
                        <table>
                          <thead>
                            <tr>
                              <th>Dish</th>
                              <th>Daily</th>
                              <th>Intervals</th>
                              <th>Difference</th>
                            </tr>
                          </thead>
                          <tbody>
                            {r.reconciliation.dishes.map((d) => (
                              <tr key={d.menu_item_id}>
                                <td>
                                  {menu.data?.find(
                                    (m) => m.id === d.menu_item_id,
                                  )?.name ?? d.menu_item_id}
                                </td>
                                <td>{d.daily_total}</td>
                                <td>{d.batch_total}</td>
                                <td>{d.difference ?? "Coverage incomplete"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <p className="quiet">
                        Coverage: {singaporeTime(r.reconciliation.period_start)}{" "}
                        to {singaporeTime(r.reconciliation.period_end)}
                      </p>
                    </>
                  ) : (
                    <p>No reconciliation evidence recorded.</p>
                  )}
                </details>
              ))
          ) : (
            <p className="quiet">No closing update submitted for this day.</p>
          )}
        </div>
      </section>
    </>
  );
}
