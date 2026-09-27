"use client";
import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, NamedRecord } from "@/lib/api";
import { EventRecord, SalesBatch } from "@/lib/operations-types";
import { timestamp, localSingapore } from "@/lib/format";
import { ErrorNotice, Status } from "./workspace";
export function SalesEntry({ day }: { day: string }) {
  const cache = useQueryClient();
  const menu = useQuery({
    queryKey: ["menu"],
    queryFn: ({ signal }) => api<NamedRecord[]>("/menu-items", { signal }),
  });
  const events = useQuery({
    queryKey: ["events"],
    queryFn: ({ signal }) => api<EventRecord[]>("/events", { signal }),
  });
  const [source, setSource] = useState("simulator");
  const [batchId, setBatchId] = useState("");
  const [start, setStart] = useState(`${day}T08:00`);
  const [end, setEnd] = useState(`${day}T08:30`);
  const [sales, setSales] = useState<Record<string, number>>({});
  const [replaces, setReplaces] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [success, setSuccess] = useState("");
  const batches = (events.data ?? [])
    .filter((e) => e.type === "SALES_UPDATED")
    .map((e) => e.payload.batch as SalesBatch)
    .filter(Boolean);
  const replaced = new Set(batches.map((b) => b.replaces_id).filter(Boolean));
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (pending) return;
    setSuccess("");
    if (Date.parse(timestamp(end)) <= Date.parse(timestamp(start))) {
      setError(new Error("The interval end must be later than its start."));
      return;
    }
    setPending(true);
    setError(null);
    try {
      const result = await api<SalesBatch>("/sales-batches", {
        method: "POST",
        body: {
          source,
          batch_id: batchId,
          period_start: timestamp(start),
          period_end: timestamp(end),
          sales,
          replaces_id: replaces,
        },
      });
      setSuccess(
        `Batch ${result.batch_id}, revision ${result.revision}, accepted.`,
      );
      await cache.invalidateQueries();
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Sales submission failed."));
    } finally {
      setPending(false);
    }
  }
  function edit(b: SalesBatch) {
    setSource(b.source);
    setBatchId(b.batch_id);
    setStart(localSingapore(b.period_start));
    setEnd(localSingapore(b.period_end));
    setSales(b.sales);
    setReplaces(b.id);
    setSuccess("");
  }
  return (
    <>
      <p className="compact-note">Submit complete interval reports. Omitted dishes count as zero; partial reports are not supported.</p>
      {menu.error && (
        <ErrorNotice error={menu.error} retry={() => menu.refetch()} />
      )}
      <form onSubmit={submit} className="panel">
        <header className="panel-head">
          <h2>
            {replaces ? "Correct a sales interval" : "Record a sales interval"}
          </h2>
        </header>
        <fieldset
          disabled={pending || menu.isPending || !!menu.error}
          className="panel-body"
          style={{ border: 0 }}
        >
          <div className="form-grid">
            <label>
              Source
              <input
                required
                value={source}
                disabled={!!replaces}
                onChange={(e) => setSource(e.target.value)}
              />
            </label>
            <label>
              Batch identity
              <input
                required
                maxLength={128}
                disabled={!!replaces}
                value={batchId}
                onChange={(e) => setBatchId(e.target.value)}
                placeholder="Unique report identifier"
              />
            </label>
            <label>
              Interval start (Singapore)
              <input
                type="datetime-local"
                required
                disabled={!!replaces}
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
            <label>
              Interval end (Singapore)
              <input
                type="datetime-local"
                min={start}
                required
                disabled={!!replaces}
                value={end}
                onChange={(e) => setEnd(e.target.value)}
              />
            </label>
            {menu.data?.map((m) => (
              <label key={m.id}>
                {m.name}
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={sales[m.id] ?? ""}
                  placeholder="Omitted = 0"
                  onChange={(e) => {
                    const next = { ...sales };
                    if (e.target.value === "") delete next[m.id];
                    else next[m.id] = Number(e.target.value);
                    setSales(next);
                  }}
                />
              </label>
            ))}
          </div>
          {error && <ErrorNotice error={error} />}{" "}
          {success && (
            <p className="notice" role="status">
              {success}
              {" "}<Link href="/workspace/sales">Follow reported sales and assessment →</Link>
            </p>
          )}
          <div className="form-actions">
            <button type="submit" className="button button-primary">
              {pending ? "Submitting…" : "Submit complete report"}
            </button>
            {replaces && (
              <button
                type="button"
                className="button button-secondary"
                onClick={() => {
                  setReplaces(null);
                  setBatchId("");
                  setSales({});
                }}
              >
                New report
              </button>
            )}
          </div>
        </fieldset>
      </form>
      <section className="panel">
        <header className="panel-head">
          <h2>Recorded intervals</h2>
        </header>
        {events.error ? (
          <ErrorNotice error={events.error} retry={() => events.refetch()} />
        ) : events.isPending ? <p className="empty-state" role="status">Loading recorded intervals…</p> : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Source / identity</th>
                  <th>Interval (Singapore)</th>
                  <th>Revision</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {batches
                  .filter((b) => localSingapore(b.period_start).startsWith(day))
                  .slice()
                  .reverse()
                  .map((b) => (
                    <tr key={b.id}>
                      <td>
                        {b.batch_id}
                        <small>{b.source}</small>
                      </td>
                      <td>
                        {localSingapore(b.period_start)} –{" "}
                        {localSingapore(b.period_end)}
                      </td>
                      <td>
                        {b.revision}{" "}
                        <Status
                          value={replaced.has(b.id) ? "Replaced" : "Active"}
                        />
                      </td>
                      <td>
                        <button
                          className="button button-secondary"
                          disabled={replaced.has(b.id) || pending}
                          onClick={() => edit(b)}
                        >
                          Correct
                        </button>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
            {!batches.some(b => localSingapore(b.period_start).startsWith(day)) && <p className="empty-state">No sales intervals recorded for {day}. Submit an explicit zero-sales interval to establish coverage when appropriate.</p>}
          </div>
        )}
      </section>
    </>
  );
}
