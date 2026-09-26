"use client";
import { useState } from "react";
import Link from "next/link";
import type { CalculationResult, Projection } from "@/lib/calculation-results";
import { singaporeTime, humanize } from "@/lib/format";

const quantity = (v: string | null | undefined) => v ?? "Unknown";
const interval = (start: string, end: string) => `${singaporeTime(start)} → ${singaporeTime(end)}`;
type Outputs = NonNullable<CalculationResult["artifact"]>["outputs"];

function Forecast({ data }: { data: Outputs }) {
  const [dish, setDish] = useState(data.dishes[0]?.id ?? "");
  return <>
    <h2>Daily baseline</h2>
    <p>Expected portions before promotion adjustments. Fractional expectations are not actual sales or rounded orders.</p>
    {data.censored_history_present && <p className="notice">Censored observations were present in the frozen input. This does not mean they were used.</p>}
    <div className="table-scroll"><table><thead><tr>{["Dish", "Expected portions", "Method", "Eligible days", "Matching weekdays"].map(t => <th scope="col" key={t}>{t}</th>)}</tr></thead><tbody>{data.dishes.map(d => <tr key={d.id}><td>{d.name}</td><td>{quantity(d.baseline.expected_portions)}</td><td>{humanize(d.baseline.method)}</td><td>{d.baseline.eligible_days}</td><td>{d.baseline.matching_weekdays}</td></tr>)}</tbody></table></div>
    <details className="record-details"><summary>Historical eligibility and coverage</summary>{data.dishes.map(d => <div key={d.id}><h3>{d.name}</h3><p>{d.baseline.coverage_flags.join(" · ") || "No coverage flags recorded."}</p><ul>{d.baseline.used_history.map(([date, revision, at]) => <li key={`${date}-${revision}`}>{date} · revision {revision} · available {singaporeTime(at)}</li>)}</ul></div>)}</details>
    <hr /><h2>Selected service forecast</h2>
    <p>Service date: {data.forecast.target_date} · Promotion state: {humanize(data.forecast.promotion_state)}. These stored bucket values may differ from the daily baseline.</p>
    <label className="field-label">Dish<select value={dish} onChange={e => setDish(e.target.value)}>{data.dishes.map(d => <option value={d.id} key={d.id}>{d.name}</option>)}</select></label>
    {!data.forecast.buckets.length ? <p>No service buckets recorded. This is not evidence of zero demand.</p> : <div className="table-scroll"><table><thead><tr><th scope="col">Service interval · Singapore</th><th scope="col">Expected portions</th></tr></thead><tbody>{data.forecast.buckets.map(b => <tr key={b.start}><td>{interval(b.start, b.end)}</td><td>{quantity(b.expected_portions[dish])}</td></tr>)}</tbody></table></div>}
    <details className="record-details"><summary>Forecast source references</summary><p>Selected: {data.forecast.reference}</p><p>Baseline: {data.forecast.base_reference}</p><ul>{data.forecast.sources.map(([kind, s]) => <li key={kind}>{kind}: {s.reference} · revision {s.captured_revision} · available {singaporeTime(s.available_at)}</li>)}</ul></details>
  </>;
}

function ProjectionView({ data, proposed }: { data: Projection; proposed: string[] }) {
  const ids = [...new Set(data.buckets?.flatMap(b => b.ingredients.map(i => i.ingredient_id)) ?? [])];
  const [ingredient, setIngredient] = useState(ids[0] ?? "");
  return <>
    <p>Coverage: {interval(data.as_of, data.horizon_end)} · FEFO: {data.fixture_fefo}</p>
    {!data.complete && <p className="notice" role="alert">Incomplete projection. Recorded rows are bounded evidence, not proof of safe stock beyond their coverage.</p>}
    {!!data.findings.length && <ul aria-label="Projection findings">{data.findings.map((f, i) => <li key={i}>{f.code} · {f.source}</li>)}</ul>}
    {data.first_shortages === null ? <p>Shortage assessment unavailable—not zero.</p> : data.first_shortages.length ? <div className="notice"><h3>First projected shortages</h3><ul>{data.first_shortages.map(s => <li key={s.ingredient_id}>{humanize(s.ingredient_id.replaceAll("-", " "))}: {interval(s.start, s.end)}</li>)}</ul></div> : <p>{data.complete ? "No shortage intervals recorded within this projection’s coverage." : "No shortage intervals recorded; incomplete evidence does not establish sufficient stock."}</p>}
    {data.buckets === null ? <p>Balance calculations unavailable. Unknown stock is not zero.</p> : <>
      <label className="field-label">Ingredient<select value={ingredient} onChange={e => setIngredient(e.target.value)}>{ids.map(id => <option key={id} value={id}>{humanize(id.replaceAll("-", " "))}</option>)}</select></label>
      <p className="compact-note">Opening is usable stock after arrivals/expiry at interval start; closing is after allocated demand. Do not add arrivals to opening again.</p>
      <div className="table-scroll"><table><thead><tr>{["Service interval · Singapore", "Unit", "Opening", "Arrivals", "Required", "Allocated", "Unmet", "Expired", "Closing"].map(t => <th scope="col" key={t}>{t}</th>)}</tr></thead><tbody>{data.buckets.map(b => { const i = b.ingredients.find(i => i.ingredient_id === ingredient); return <tr key={b.start}><td>{interval(b.start, b.end)}</td><td>{i?.unit ?? "Unknown"}</td>{[i?.opening, i?.admitted, i?.required, i?.allocated, i?.unmet, i?.expired, i?.closing].map((v, n) => <td key={n}>{quantity(v)}</td>)}</tr>; })}</tbody></table></div>
      {!data.buckets.length && <p>No balance rows recorded—not proof of sufficient stock.</p>}
      <details className="record-details"><summary>Lot provenance for selected ingredient</summary><p>Source classifications and identifiers are frozen engine evidence, not newly received stock.</p><div className="table-scroll"><table><thead><tr><th>Interval</th><th>Lot key</th><th>Origin</th><th>Closing</th><th>Unit</th></tr></thead><tbody>{data.buckets.flatMap(b => b.lots.filter(l => l.ingredient_id === ingredient).map(l => <tr key={`${b.start}-${l.key}`}><td>{interval(b.start, b.end)}</td><td>{l.key}</td><td>{l.source}</td><td>{l.closing}</td><td>{l.unit}</td></tr>))}</tbody></table></div>{!!proposed.length && <><h3>Hypothetical supply identifiers</h3><ul>{proposed.map(id => <li key={id}>{id}</li>)}</ul></>}</details>
    </>}
    <details className="record-details"><summary>Projection source references</summary><ul>{data.evidence.map(([kind, s]) => <li key={kind}>{kind}: {s.reference} · revision {s.captured_revision} · available {singaporeTime(s.available_at)}</li>)}</ul></details>
    <p className="compact-note">Intervals include their start and exclude their end. Projected expiry is not observed or staff-recorded waste.</p>
  </>;
}

export function CalculationResults({ result }: { result: CalculationResult }) {
  const [tab, setTab] = useState("Forecast");
  const [basis, setBasis] = useState("existing");
  if (result.status === "NOT_RECORDED" || !result.artifact) return <div className="empty-state"><h2>No stored calculation output for this assessment.</h2><p>Queued, older, contingency and unsupported calculation paths may not record this artifact. This is not a zero forecast or a safe-stock result.</p></div>;
  const data = result.artifact.outputs;
  return <>
    {result.stale && <p className="notice" role="alert">Historical result: restaurant state has changed since this calculation. Read it as captured evidence, not a current recommendation.</p>}
    <p>Service: {data.forecast.target_date} · Stored first-slice calculation. This is not a general 21-day forecast or full economic assessment.</p>
    {!!data.limitations.length && <details className="record-details"><summary>Calculation limitations</summary><ul>{data.limitations.map((s, i) => <li key={i}>{s}</li>)}</ul></details>}
    <div className="tabs" role="tablist" aria-label="Calculation views">{["Forecast", "Stock projection"].map(t => <button key={t} role="tab" aria-selected={tab === t} id={`calculation-${t.replaceAll(" ", "-")}`} aria-controls="calculation-panel" onClick={() => setTab(t)}>{t}</button>)}</div>
    <section id="calculation-panel" role="tabpanel" aria-labelledby={`calculation-${tab.replaceAll(" ", "-")}`}>
      {tab === "Forecast" ? <Forecast data={data} /> : <>
        <label className="field-label">Projection basis<select value={basis} onChange={e => setBasis(e.target.value)}><option value="existing">Existing commitments only</option><option value="candidate">With this recommendation</option></select></label>
        <p>{basis === "existing" ? "Proposed purchases excluded. Recorded commitments remain fixed." : `Includes hypothetical candidate ${data.candidate_id}. These additions are not orders or received stock.`}</p>
        <p>Published plan version: {result.plan_version_id ?? "Not published"}. Calculation output does not establish approval.</p>
        <ProjectionView key={basis} data={basis === "existing" ? data.existing_commitments_projection : data.with_recommendation_projection} proposed={basis === "existing" ? [] : data.proposed_supply_ids} />
      </>}
    </section>
    <details className="record-details"><summary>Captured result identity</summary><dl className="terms-facts">{Object.entries({ Assessment: result.run_id, Artifact: result.artifact.id, SHA256: result.artifact.content_sha256, "Operational cutoff": singaporeTime(data.as_of), "Knowledge cutoff": singaporeTime(data.known_at), "Captured revision": data.captured_state_revision, "Current revision": result.current_state_revision, Policy: `${data.policy_id} · v${data.policy_version}`, "Forecast input": `${data.forecast_input_id} · v${data.forecast_input_version}` }).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl></details>
    <Link href={`/workspace/activity/${encodeURIComponent(result.run_id)}`}>Open assessment activity →</Link>
  </>;
}
