import type { SalesBatch } from "./operations-types";

/** Corrected reports replace, rather than add to, the original interval. */
export function activeBatches(batches: SalesBatch[]): SalesBatch[] {
  const replaced = new Set(
    batches.map((batch) => batch.replaces_id).filter(Boolean),
  );
  const unique = new Map(batches.map((batch) => [batch.id, batch]));
  return [...unique.values()].filter(
    (batch) => batch.active && !replaced.has(batch.id),
  );
}

/** Never prorate a report that crosses a requested boundary. */
export function intervalSummary(
  batches: SalesBatch[],
  start: string,
  end: string,
) {
  const from = Date.parse(start),
    until = Date.parse(end);
  const active = activeBatches(batches);
  const included = active
    .filter(
      (b) =>
        Date.parse(b.period_start) >= from && Date.parse(b.period_end) <= until,
    )
    .sort((a, b) => Date.parse(a.period_start) - Date.parse(b.period_start));
  const totals: Record<string, number> = {};
  const gaps: { start: string; end: string }[] = [];
  let cursor = from;
  let overlaps = false;
  for (const batch of included) {
    const first = Date.parse(batch.period_start),
      last = Date.parse(batch.period_end);
    if (first > cursor)
      gaps.push({
        start: new Date(cursor).toISOString(),
        end: batch.period_start,
      });
    if (first < cursor) overlaps = true;
    cursor = Math.max(cursor, last);
    for (const [dish, quantity] of Object.entries(batch.sales))
      totals[dish] = (totals[dish] ?? 0) + quantity;
  }
  if (cursor < until) gaps.push({ start: new Date(cursor).toISOString(), end });
  const crossing = active.filter(
    (b) =>
      Date.parse(b.period_start) < until &&
      Date.parse(b.period_end) > from &&
      !included.includes(b),
  );
  return { included, totals, gaps, crossing, overlaps };
}

/** Exact recipe quantity × integer portions, without floating-point stock arithmetic. */
export function recipeUsage(quantity: string, portions: number): string {
  if (
    !/^\d+(\.\d+)?$/.test(quantity) ||
    !Number.isSafeInteger(portions) ||
    portions < 0
  )
    return "Unavailable";
  const [whole, fraction = ""] = quantity.split(".");
  const result = (BigInt(whole + fraction) * BigInt(portions))
    .toString()
    .padStart(fraction.length + 1, "0");
  return fraction.length
    ? `${result.slice(0, -fraction.length)}.${result.slice(-fraction.length)}`
    : result;
}
