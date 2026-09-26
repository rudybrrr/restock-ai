"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, Run } from "@/lib/api";
import { singaporeTime } from "@/lib/format";
import { ErrorNotice } from "./workspace";

// Whitelist only operational fields from the existing manager-accessible run.
export function PurchaseContext({ runId }: { runId: string }) {
  const query = useQuery({ queryKey: ["run", runId], queryFn: ({ signal }) => api<Run>(`/runs/${encodeURIComponent(runId)}`, { signal }) });
  const captured = query.data?.snapshot;
  return (
    <section className="purchase-context" aria-label="Existing purchases">
      <h3>Already arranged · not new purchases</h3>
      <p className="compact-note">Captured purchases, not live delivery status. Received stock is not outstanding supply.</p>
      {query.data && <details className="reading-note"><summary>Capture times</summary><p>Operational cutoff: {singaporeTime(query.data.as_of)} · Knowledge cutoff: {captured?.known_at ? singaporeTime(captured.known_at) : "Not recorded"}.</p></details>}
      <p className="mobile-table-hint">Scroll sideways for outstanding quantities and arrival times →</p>
      {query.error ? <ErrorNotice error={query.error} retry={() => query.refetch()} />
        : query.isPending ? <p role="status">Loading captured purchases…</p>
          : !Array.isArray(captured?.commitments) ? <p>Existing-purchase records were not captured for this assessment. Do not assume the list is empty.</p>
            : captured.commitments.length === 0 ? <p>No purchases were present in this assessment’s captured commitment list.</p>
              : <div className="table-scroll"><table><thead><tr><th>Ingredient / supplier</th><th>Unit</th><th>Ordered</th><th>Received</th><th>Cancelled</th><th>Outstanding</th><th>Expected arrival</th></tr></thead><tbody>
                {captured.commitments.map(d => <tr key={d.id}><td>{captured.ingredients?.find(i => i.id === d.ingredient_id)?.name ?? d.ingredient_id}<small>{captured.suppliers?.find(s => s.id === d.supplier_id)?.name ?? d.supplier_id}</small></td><td>{captured.ingredients?.find(i => i.id === d.ingredient_id)?.unit ?? "Not recorded"}</td><td>{d.expected_quantity}</td><td>{d.received_quantity}</td><td>{d.cancelled_quantity ?? "Not recorded"}</td><td>{d.outstanding_quantity}</td><td>{singaporeTime(d.expected_at)}</td></tr>)}
              </tbody></table></div>}
      <Link href="/workspace/deliveries">Review current delivery records →</Link>
    </section>
  );
}
