/** Manager-only frozen outputs. Never infer missing quantities or recalculate results. */
type Evidence = [string, { reference: string; available_at: string; captured_revision: string }];
type Balance = { ingredient_id: string; unit: string; opening: string; admitted: string; required: string; allocated: string; unmet: string; expired: string; closing: string };
type Lot = { key: string; ingredient_id: string; unit: string; source: string; opening: string; admitted: string; allocated: string; expired: string; closing: string };
export type Projection = {
  as_of: string; known_at: string; horizon_end: string; captured_revision: string;
  complete: boolean; fixture_fefo: string; evidence: Evidence[];
  findings: { code: string; source: string }[];
  buckets: { start: string; end: string; ingredients: Balance[]; lots: Lot[] }[] | null;
  first_shortages: { ingredient_id: string; start: string; end: string }[] | null;
};
export type CalculationResult = {
  run_id: string; status: "AVAILABLE" | "NOT_RECORDED"; current_state_revision: string;
  stale: boolean | null; plan_version_id: string | null;
  artifact: null | { id: string; content_sha256: string; outputs: {
    schema_version: "MANAGER_CALCULATION_OUTPUTS_V1"; run_id: string;
    as_of: string; known_at: string; captured_state_revision: string;
    policy_id: string; policy_version: number; forecast_input_id: string; forecast_input_version: number;
    candidate_id: string; timezone: "Asia/Singapore"; bucket_boundary: "START_INCLUSIVE_END_EXCLUSIVE";
    forecast_method: string; portions_semantics: "FRACTIONAL_EXPECTATION"; censored_history_present: boolean;
    dishes: { id: string; name: string; baseline: { expected_portions: string | null; method: string; eligible_days: number; matching_weekdays: number; used_history: [string, number, string][]; coverage_flags: string[] } }[];
    forecast: { reference: string; base_reference: string; target_date: string; promotion_state: string; sources: Evidence[]; buckets: { start: string; end: string; expected_portions: Record<string, string | null> }[] };
    existing_commitments_projection: Projection; with_recommendation_projection: Projection;
    proposed_supply_ids: string[]; limitations: string[];
  } };
};

const fail = (): never => { throw new Error("Stored calculation response is incompatible. No substitute values have been displayed."); };
function object(v: unknown): Record<string, unknown> { if (!v || typeof v !== "object" || Array.isArray(v)) return fail(); return v as Record<string, unknown>; }
function list(v: unknown): unknown[] { return Array.isArray(v) ? v : fail(); }
function str(v: unknown): string { return typeof v === "string" ? v : fail(); }
function bool(v: unknown) { if (typeof v !== "boolean") fail(); }
function integer(v: unknown) { if (typeof v !== "number" || !Number.isInteger(v) || v < 0) fail(); }
function instant(v: unknown) { if (!/(Z|[+-]\d\d:\d\d)$/.test(str(v)) || !Number.isFinite(Date.parse(str(v)))) fail(); }
function decimal(v: unknown, nullable = false) { if (nullable && v === null) return; if (!/^[+-]?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?$/.test(str(v))) fail(); }
function strings(v: unknown) { list(v).forEach(str); }
function evidence(v: unknown) { list(v).forEach(row => { const pair = list(row); if (pair.length !== 2) fail(); str(pair[0]); const e = object(pair[1]); str(e.reference); instant(e.available_at); str(e.captured_revision); }); }
function interval(v: Record<string, unknown>) { instant(v.start); instant(v.end); if (Date.parse(str(v.start)) >= Date.parse(str(v.end))) fail(); }
function projection(v: unknown) {
  const p = object(v); bool(p.complete); [p.as_of, p.known_at, p.horizon_end].forEach(instant); str(p.captured_revision); str(p.fixture_fefo); evidence(p.evidence);
  list(p.findings).forEach(v => { const f = object(v); str(f.code); str(f.source); });
  if (p.buckets !== null) list(p.buckets).forEach(v => {
    const b = object(v); interval(b);
    list(b.ingredients).forEach(v => { const i = object(v); str(i.ingredient_id); str(i.unit); ["opening", "admitted", "required", "allocated", "unmet", "expired", "closing"].forEach(k => decimal(i[k])); });
    list(b.lots).forEach(v => { const l = object(v); ["key", "ingredient_id", "unit", "source"].forEach(k => str(l[k])); ["opening", "admitted", "allocated", "expired", "closing"].forEach(k => decimal(l[k])); });
  });
  if (p.first_shortages !== null) list(p.first_shortages).forEach(v => { const s = object(v); str(s.ingredient_id); interval(s); });
  if (p.complete && (p.buckets === null || p.first_shortages === null)) fail();
}

export function readCalculationResult(value: unknown, selectedRun: string): CalculationResult {
  const r = object(value); if (r.run_id !== selectedRun) fail(); str(r.current_state_revision);
  if (r.plan_version_id !== null) str(r.plan_version_id);
  if (r.status === "NOT_RECORDED") { if (r.artifact !== null || r.stale !== null) fail(); return value as CalculationResult; }
  if (r.status !== "AVAILABLE") fail(); bool(r.stale);
  const a = object(r.artifact), o = object(a.outputs); str(a.id); if (!/^[a-f0-9]{64}$/.test(str(a.content_sha256))) fail();
  if (o.schema_version !== "MANAGER_CALCULATION_OUTPUTS_V1" || o.run_id !== selectedRun || o.timezone !== "Asia/Singapore" || o.bucket_boundary !== "START_INCLUSIVE_END_EXCLUSIVE" || o.portions_semantics !== "FRACTIONAL_EXPECTATION" || o.forecast_method !== "SEASONAL_BASELINE_V1") fail();
  ["policy_id", "forecast_input_id", "candidate_id", "captured_state_revision"].forEach(k => str(o[k])); [o.as_of, o.known_at].forEach(instant); integer(o.policy_version); integer(o.forecast_input_version); bool(o.censored_history_present); strings(o.limitations); strings(o.proposed_supply_ids);
  if (r.stale !== (o.captured_state_revision !== r.current_state_revision)) fail();
  const ids = new Set<string>();
  list(o.dishes).forEach(v => { const d = object(v); const id = str(d.id); if (ids.has(id)) fail(); ids.add(id); str(d.name); const b = object(d.baseline); decimal(b.expected_portions, true); str(b.method); integer(b.eligible_days); integer(b.matching_weekdays); strings(b.coverage_flags); list(b.used_history).forEach(v => { const h = list(v); if (h.length !== 3) fail(); str(h[0]); integer(h[1]); instant(h[2]); }); });
  const f = object(o.forecast); ["reference", "base_reference", "target_date", "promotion_state"].forEach(k => str(f[k])); evidence(f.sources);
  list(f.buckets).forEach(v => { const b = object(v); interval(b); const quantities = object(b.expected_portions); if (Object.keys(quantities).length !== ids.size) fail(); ids.forEach(id => decimal(quantities[id], true)); });
  projection(o.existing_commitments_projection); projection(o.with_recommendation_projection);
  for (const value of [o.existing_commitments_projection, o.with_recommendation_projection]) {
    const p = object(value);
    if (p.captured_revision !== o.captured_state_revision || Date.parse(str(p.as_of)) !== Date.parse(str(o.as_of)) || Date.parse(str(p.known_at)) !== Date.parse(str(o.known_at))) fail();
  }
  return value as CalculationResult;
}
