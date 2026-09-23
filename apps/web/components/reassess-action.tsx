"use client";
import { useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { api, Run } from "@/lib/api";
import { localSingapore, timestamp } from "@/lib/format";
import { ErrorNotice } from "./workspace";

export function ReassessAction({ runId, at }: { runId: string; at: string }) {
  const cache = useQueryClient();
  const [time, setTime] = useState(localSingapore(at));
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<Run | null>(null);
  const [error, setError] = useState<Error | null>(null);
  return (
    <section className="notice">
      <h3>Request a new assessment</h3>
      <p>
        This creates an assessment linked to the previous plan. It does not
        approve a recommendation or change purchases already arranged.
      </p>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          if (pending || result) return;
          setPending(true);
          setError(null);
          try {
            setResult(
              await api<Run>(`/runs/${encodeURIComponent(runId)}/retry`, {
                method: "POST",
                body: { as_of: timestamp(time) },
              }),
            );
            await cache.invalidateQueries();
          } catch (error) {
            setError(
              error instanceof Error
                ? error
                : new Error("Assessment request failed"),
            );
          } finally {
            setPending(false);
          }
        }}
      >
        <label className="field-label">
          Assess through (Singapore time)
          <input
            type="datetime-local"
            required
            value={time}
            onChange={(e) => setTime(e.target.value)}
            disabled={pending || !!result}
          />
        </label>
        <button
          className="button button-secondary"
          disabled={pending || !!result}
        >
          {pending
            ? "Requesting…"
            : result
              ? "Assessment requested"
              : "Confirm reassessment"}
        </button>
      </form>
      {error && <ErrorNotice error={error} />}
      {result && (
        <p role="status">
          Request saved.{" "}
          <Link href={`/workspace/activity/${encodeURIComponent(result.id)}`}>
            Open new assessment →
          </Link>
        </p>
      )}
    </section>
  );
}
