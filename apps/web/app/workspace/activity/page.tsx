"use client";
import Link from "next/link";
import {
  CorrectionDetails,
  DeliveryDisruption,
  EventAssessments,
} from "@/components/change-events";
import { RunEvidence } from "@/components/run-evidence";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Run } from "@/lib/api";
import { EventRecord } from "@/lib/operations-types";
import { humanize, singaporeTime } from "@/lib/format";
import {
  ErrorNotice,
  PageHeading,
  Status,
  useServiceDate,
} from "@/components/workspace";
type Audit = {
  id: string;
  event_id: string;
  actor: string;
  action: string;
  timestamp: string;
};
export default function Activity() {
  const { day } = useServiceDate();
  const cache = useQueryClient();
  const [tab, setTab] = useState("Timeline");
  const [filter, setFilter] = useState("");
  const [time, setTime] = useState("08:00");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [message, setMessage] = useState("");
  const [requestedId, setRequestedId] = useState<string | null>(null);
  const events = useQuery({
    queryKey: ["events"],
    queryFn: ({ signal }) => api<EventRecord[]>("/events", { signal }),
  });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: ({ signal }) => api<Run[]>("/runs", { signal }),
    refetchInterval: (q) =>
      q.state.data?.some((r) => ["QUEUED", "RUNNING"].includes(r.status))
        ? 5000
        : false,
  });
  const audit = useQuery({
    queryKey: ["audit"],
    queryFn: ({ signal }) => api<Audit[]>("/audit", { signal }),
    enabled: tab === "Audit details",
  });
  async function request(path: string, body?: unknown) {
    setPending(true);
    setError(null);
    try {
      const result = await api<Run>(path, { method: "POST", body });
      setMessage(`Assessment ${result.id} is ${humanize(result.status)}.`);
      setRequestedId(result.id);
      await cache.invalidateQueries();
    } catch (e) {
      setError(
        e instanceof Error ? e : new Error("Assessment request failed."),
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <>
      <PageHeading
        eyebrow="ACTIVITY"
        title="Every change, in context."
        description="Follow the restaurant’s recorded changes, assessments, and manager decisions."
      />
      <section className="panel">
        <div className="panel-body form-actions" style={{ marginTop: 0 }}>
          <label className="field-label">
            Assess at (Singapore · {day})
            <input
              type="time"
              required
              value={time}
              onChange={(e) => {
                if (e.target.value) setTime(e.target.value);
              }}
            />
          </label>
          <button
            disabled={pending}
            className="button button-primary"
            onClick={() =>
              request("/assessments", { as_of: `${day}T${time}:00+08:00` })
            }
          >
            {pending ? "Requesting…" : "Reassess now"}
          </button>
        </div>
      </section>
      {error && <ErrorNotice error={error} />}{" "}
      {message && (
        <p role="status" className="notice">
          {message}
          {requestedId && (
            <>
              {" "}
              <Link
                href={`/workspace/activity/${encodeURIComponent(requestedId)}`}
              >
                Open requested assessment →
              </Link>
            </>
          )}
        </p>
      )}
      <div className="tabs" role="tablist" aria-label="Activity views">
        {["Timeline", "Assessments", "Audit details"].map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>
      {tab === "Timeline" ? (
        <>
          <label className="field-label">
            Filter activity
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Promotion, delivery, approval…"
            />
          </label>
          {events.error ? (
            <ErrorNotice error={events.error} retry={() => events.refetch()} />
          ) : events.isPending ? (
            <p role="status">Loading activity…</p>
          ) : (
            <section className="panel" style={{ marginTop: 24 }}>
              <div className="panel-body">
                {events.data
                  ?.filter((e) =>
                    humanize(e.type).includes(filter.toLowerCase()),
                  )
                  .slice()
                  .reverse()
                  .map((e) => (
                    <details key={e.id} className="record-details">
                      <summary>
                        <strong>{humanize(e.type)}</strong>
                        <small>
                          {singaporeTime(e.timestamp)} · recorded by {e.source}
                        </small>
                      </summary>
                      <p className="quiet">
                        Recorded time is shown above. Operational timestamps,
                        when supplied, appear in the event details.
                      </p>
                      <dl className="evidence-list">
                        {Object.entries(e.payload)
                          .filter(([, v]) => typeof v !== "object")
                          .map(([k, v]) => (
                            <div key={k}>
                              <dt>{humanize(k)}</dt>
                              <dd>{String(v ?? "Unavailable")}</dd>
                            </div>
                          ))}
                      </dl>
                      <p className="quiet">Event reference: {e.id}</p>
                      {e.type === "INVENTORY_ADJUSTED" && (
                        <CorrectionDetails event={e} />
                      )}
                      {[
                        "DELIVERY_DELAYED",
                        "DELIVERY_SHORT",
                        "DELIVERY_CANCELLED",
                      ].includes(e.type) && (
                        <>
                          <DeliveryDisruption event={e} />
                          <EventAssessments eventId={e.id} />
                        </>
                      )}
                      {e.type.startsWith("DELIVERY") ||
                      e.type === "EXTERNAL_ORDER_RECORDED" ? (
                        <Link href="/workspace/deliveries">
                          Open deliveries →
                        </Link>
                      ) : e.type.startsWith("PLAN") ? (
                        <Link href="/workspace/recommendations">
                          Open recommendations →
                        </Link>
                      ) : null}
                    </details>
                  ))}
                {events.data?.length === 0 && (
                  <p className="quiet">No events recorded yet.</p>
                )}
              </div>
            </section>
          )}
        </>
      ) : tab === "Assessments" ? (
        runs.error ? (
          <ErrorNotice error={runs.error} retry={() => runs.refetch()} />
        ) : (
          <section className="panel">
            <header className="panel-head">
              <h2>Assessment history</h2>
              <span className="quiet">Active runs refresh every 5 seconds</span>
            </header>
            <div className="panel-body">
              {runs.data
                ?.slice()
                .sort((a, b) => b.created_at.localeCompare(a.created_at))
                .map((r) => (
                  <details className="record-details" key={r.id}>
                    <summary>
                      <Status value={r.status} /> {humanize(r.trigger)}
                      <small>Operational time: {singaporeTime(r.as_of)}</small>
                    </summary>
                    <p>
                      Outcome:{" "}
                      {r.outcome ? humanize(r.outcome) : "Not available yet"}
                    </p>
                    {(r.escalation_reason || r.failure_reason) && (
                      <p className="notice">
                        {humanize(
                          r.escalation_reason ?? r.failure_reason ?? "",
                        )}
                      </p>
                    )}
                    <p className="quiet">Run reference: {r.id}</p>
                    <RunEvidence run={r} />
                    <div className="form-actions">
                      {r.plan_version_id && (
                        <Link
                          className="button button-secondary"
                          href={`/workspace/recommendations?version=${encodeURIComponent(r.plan_version_id)}`}
                        >
                          View recommendation
                        </Link>
                      )}
                      {r.status === "FAILED" && (
                        <button
                          disabled={pending}
                          className="button button-secondary"
                          onClick={() =>
                            request(`/runs/${encodeURIComponent(r.id)}/retry`, {
                              as_of: `${day}T${time}:00+08:00`,
                            })
                          }
                        >
                          Retry assessment
                        </button>
                      )}
                    </div>
                    <RunTriggers id={r.id} />
                  </details>
                ))}
              {runs.data?.length === 0 && (
                <p className="quiet">
                  No assessments recorded. Request one using the selected
                  service date.
                </p>
              )}
            </div>
          </section>
        )
      ) : audit.error ? (
        <ErrorNotice error={audit.error} retry={() => audit.refetch()} />
      ) : (
        <section className="panel">
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Recorded time</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Event reference</th>
                </tr>
              </thead>
              <tbody>
                {audit.data
                  ?.slice()
                  .reverse()
                  .map((a) => (
                    <tr key={a.id}>
                      <td>{singaporeTime(a.timestamp)}</td>
                      <td>{a.actor}</td>
                      <td>{humanize(a.action)}</td>
                      <td>
                        <small>{a.event_id}</small>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
function RunTriggers({ id }: { id: string }) {
  const q = useQuery({
    queryKey: ["triggers", id],
    queryFn: ({ signal }) =>
      api<{ event_id: string; effective_at: string }[]>(
        `/runs/${encodeURIComponent(id)}/triggers`,
        { signal },
      ),
  });
  return (
    <details>
      <summary>Trigger evidence</summary>
      {q.error ? (
        <ErrorNotice error={q.error} />
      ) : (
        q.data?.map((t) => (
          <p className="quiet" key={t.event_id}>
            {t.event_id} · {singaporeTime(t.effective_at)}
          </p>
        ))
      )}
    </details>
  );
}
