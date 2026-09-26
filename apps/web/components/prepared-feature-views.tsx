"use client";
import { useState } from "react";
import type { ReactNode } from "react";
import type { EconomicsDisplay, ForecastDisplay, PreparedRead, ProjectionDisplay, ResultCapture } from "@/lib/prepared-results";

function Unready({ result }: { result: Exclude<PreparedRead<unknown>, { state: "ready" }> }) {
  if (result.state === "error") return <p className="notice notice-error" role="alert">Could not load this result: {result.message}</p>;
  if (result.state === "loading") return <p role="status">Loading stored result…</p>;
  return <div className="empty-state"><h3>{result.state === "empty" ? "No stored result for this selection." : "Waiting for an agreed manager data source."}</h3><p>{result.state === "empty" ? "No result is not a zero forecast or proof of sufficient stock." : "This display is prepared, but not connected. No illustrative data or browser calculation is being substituted."}</p></div>;
}
function Capture({ data }: { data: ResultCapture }) {
  return <>
    <p className="compact-note">Coverage: {data.horizonStart} → {data.horizonEnd} · Singapore time</p>
    {!data.complete && <p className="notice" role="alert">Incomplete result. Do not treat this as a certified forecast, safe stock balance or complete optimisation.</p>}
    {!!data.warnings.length && <ul aria-label="Result warnings">{data.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul>}
    <details className="record-details"><summary>Result provenance</summary><dl className="terms-facts">
      {Object.entries({ Artifact: data.artifactId, Assessment: data.runId, Version: data.version, "Operational cutoff": data.asOf, "Knowledge cutoff": data.knownAt, "Captured revision": data.stateRevision }).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}
    </dl></details>
  </>;
}
function Table({ headings, children }: { headings: string[]; children: ReactNode }) {
  return <div className="table-scroll"><table><thead><tr>{headings.map(heading => <th key={heading} scope="col">{heading}</th>)}</tr></thead><tbody>{children}</tbody></table></div>;
}
const quantity = (value: string | null) => value ?? "Unknown";
const cash = (value: string | null) => value === null ? "Unavailable" : `S$ ${value}`;

export function ForecastResultView({ result }: { result: PreparedRead<ForecastDisplay> }) {
  if (result.state !== "ready") return <Unready result={result} />;
  const data = result.data;
  return <section aria-label="Stored forecast result"><Capture data={data} /><p>Method: {data.method}. Predicted portions are not actual sales.</p>
    {!data.rows.length ? <p>No dish/bucket rows recorded. This does not establish zero demand.</p> : <Table headings={["Service interval", "Dish", "Forecast portions", "History censored"]}>{data.rows.map((row, i) => <tr key={i}><td>{row.start} → {row.end}</td><td>{row.dishName}</td><td>{quantity(row.portions)}</td><td>{row.censored ? "Yes" : "No"}</td></tr>)}</Table>}
  </section>;
}
export function ProjectionResultView({ result }: { result: PreparedRead<ProjectionDisplay> }) {
  if (result.state !== "ready") return <Unready result={result} />;
  const data = result.data;
  return <section aria-label="Stored stock projection"><Capture data={data} />
    <p>{data.basis === "EXISTING_COMMITMENTS_ONLY" ? "Existing commitments only; proposed purchases excluded." : `Includes recommendation ${data.planVersionId ?? "reference unavailable"}. Proposed arrivals are not received stock.`}</p>
    {!data.rows.length ? <p>No projection rows recorded. This does not establish sufficient stock.</p> : <Table headings={["Cutoff", "Ingredient / unit", "Usable balance", "Expected arrivals", "Projected use", "Expiry loss", "Shortfall", "Coverage"]}>{data.rows.map((row, i) => <tr key={i}><td>{row.at}</td><td>{row.ingredientName} · {row.unit}</td><td>{quantity(row.usableBalance)}</td><td>{quantity(row.expectedArrivals)}</td><td>{quantity(row.projectedUsage)}</td><td>{quantity(row.expiryQuantity)}</td><td>{quantity(row.shortfall)}</td><td>{row.coverage.toLowerCase()}</td></tr>)}</Table>}
    <p className="compact-note">Projected expiry loss is not measured staff-recorded waste. Quantities come from the stored result, not a browser inventory simulation.</p>
  </section>;
}
export function EconomicsResultView({ result }: { result: PreparedRead<EconomicsDisplay> }) {
  if (result.state !== "ready") return <Unready result={result} />;
  const data = result.data;
  const cashOnly = data.scope === "NEW_PURCHASE_CASH_ONLY";
  const costs = cashOnly ? [["New purchase cash only", data.newPurchaseCash]] : [["Purchases", data.purchase], ["Shipment fees", data.shipmentFees], ["Emergency fees", data.emergencyFees], ["Expected waste cost", data.expectedWaste], ["Expected stockout cost", data.expectedStockout], ["Expected economic total", data.expectedTotal]];
  return <section aria-label="Stored economic result"><Capture data={data} />
    <p>Objective: {data.objective} · Plan version: {data.planVersionId}</p>
    <p>{data.certifiedOptimal && data.complete ? "Stored result certifies optimality within its approved domain." : "No complete optimality certification recorded."}</p>
    {cashOnly && <p className="notice">Cash-slice result only. Full-horizon waste, stockout costs and economic total are unavailable—not zero.</p>}
    <Table headings={["Stored cost component", "SGD"]}>{costs.map(([label, value]) => <tr key={label}><td>{label}</td><td>{cash(value)}</td></tr>)}</Table>
    <p className="compact-note">Expected costs are model outputs, not actual spending or measured waste. No total is recomputed in the browser.</p>
  </section>;
}
export function WastePreparationForm() {
  const [quantityDraft, setQuantity] = useState("");
  return <section aria-label="Waste entry preparation">
    <p className="notice">Form preparation only. Recording is unavailable until the waste contract is agreed. Nothing here is saved, submitted or deducted from inventory.</p>
    <form onSubmit={event => event.preventDefault()}>
      <div className="form-grid">
        <label>Received batch<select disabled><option>Awaiting agreed batch eligibility</option></select></label>
        <label>Observed waste quantity<input inputMode="decimal" value={quantityDraft} onChange={event => setQuantity(event.target.value)} placeholder="Enter a quantity" /></label>
        <label>Unit<input disabled value="Derived from selected ingredient" readOnly /></label>
        <label>Observed at (Singapore)<input type="datetime-local" /></label>
        <label>Reason / note (optional)<textarea placeholder="Only record what staff actually observed" /></label>
      </div>
      <p className="compact-note">Draft fields are temporary and disappear when leaving this tab. Stock discrepancies and expired balances must not be auto-labelled waste.</p>
      <div className="form-actions"><button className="button button-primary" type="submit" disabled>Waste recording not connected</button><button className="button button-secondary" type="reset" onClick={() => setQuantity("")}>Clear draft</button></div>
    </form>
  </section>;
}
