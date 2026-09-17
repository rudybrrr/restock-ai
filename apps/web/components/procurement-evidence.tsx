"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { humanize, singaporeTime } from "@/lib/format";
import { ErrorNotice } from "./workspace";

type Policy = {
  id: string;
  policy_id: string;
  version: number;
  effective_at: string;
  recorded_at: string;
  payload: {
    objective_policy: string;
    target_date: string;
    new_order_budget_sgd: string;
    issue_time: string;
    horizon_end: string;
    timezone: string;
    bucket_minutes: number;
    service_profile: { start: string; end: string; weight: string }[];
    safety_stock: Record<string, string>;
    storage_limits: Record<string, string>;
    fee_policy: string;
    fee_grouping: string;
    emergency_mode: string;
    reliability_mode: string;
    fefo_policy: string;
    new_supply_expiry_policy: string;
    tie_break_policy: string;
    search_policy: string;
    approved_supplier_ids: string[];
    expected_offer_count: number;
    expected_opportunity_count: number;
    explicit_empty_post_count_activity: boolean;
    explicit_empty_outstanding_commitments: boolean;
  };
};
type Evidence = {
  policy: Policy;
  domain: {
    id: string;
    domain_id: string;
    version: number;
    source_revision: string;
    recorded_at: string;
    payload: {
      source_kind: string;
      source_description: string;
      opening_lot_ids: string[];
    };
    offers: {
      id: string;
      offer_id: string;
      supplier_id: string;
      ingredient_id: string;
      source_revision: string;
      offer: Record<string, unknown>;
    }[];
    opportunities: {
      id: string;
      opportunity_id: string;
      offer_id: string;
      ordered_at: string;
      arrival_at: string;
      kind: string;
      expiry_date: string;
      source_revision: string;
    }[];
  };
  forecast_input: {
    artifact_id: string;
    version: number;
    source_revision: string;
    effective_at: string;
    recorded_at: string;
    payload: {
      source_kind: string;
      forecast_method: string;
      target_date: string;
      menu_item_ids: string[];
      history: {
        service_date: string;
        available_at: string;
        revision: number;
        promotion: boolean;
        censored: boolean;
        portions: Record<string, number>;
      }[];
    };
  };
};

export function ProcurementEvidence({
  runId,
  historyOnly = false,
}: {
  runId?: string;
  historyOnly?: boolean;
}) {
  const [selected, setSelected] = useState("");
  const policies = useQuery({
    queryKey: ["manager-policies"],
    queryFn: ({ signal }) =>
      api<Policy[]>("/manager/procurement-policies", { signal }),
    enabled: !runId,
  });
  const policy =
    policies.data?.find((item) => item.id === selected) ?? policies.data?.[0];
  const path = runId
    ? `/manager/runs/${encodeURIComponent(runId)}/procurement-evidence`
    : policy
      ? `/manager/procurement-policies/${encodeURIComponent(policy.policy_id)}/versions/${policy.version}`
      : "";
  const evidence = useQuery({
    queryKey: ["procurement-evidence", path],
    queryFn: ({ signal }) => api<Evidence>(path, { signal }),
    enabled: !!path,
  });
  const data = evidence.data;
  const payload = data?.policy.payload;
  const forecast = data?.forecast_input;
  return (
    <section className="panel evidence-display">
      <header className="panel-head">
        <h2>
          {historyOnly
            ? "Historical forecast inputs"
            : runId
              ? "Frozen run policy & domain"
              : "Persisted procurement policies"}
        </h2>
      </header>
      <div className="panel-body">
        <p className="quiet">
          {runId
            ? "Evidence frozen for this assessment—not the latest supplier terms."
            : "Browse immutable versions. A listed policy is not automatically applicable to the selected service day or every assessment."}
        </p>
        {!runId && policies.error && (
          <ErrorNotice
            error={policies.error}
            retry={() => policies.refetch()}
          />
        )}
        {!runId && policies.isPending && (
          <p role="status">Loading policy versions…</p>
        )}
        {!runId && policies.data?.length === 0 && (
          <p>
            No persisted policy versions. Backend migrations and fixture setup
            may be required.
          </p>
        )}
        {!runId && policy && (
          <label>
            Policy version
            <select
              value={policy.id}
              onChange={(event) => setSelected(event.target.value)}
            >
              {policies.data?.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.policy_id} · version {item.version} ·{" "}
                  {item.payload.target_date}
                </option>
              ))}
            </select>
          </label>
        )}
        {!!path && evidence.isPending && (
          <p role="status">Loading canonical evidence…</p>
        )}
        {evidence.error && (
          <ErrorNotice
            error={evidence.error}
            retry={() => evidence.refetch()}
          />
        )}
        {data && payload && (
          <>
            {!historyOnly && (
              <>
                <h3>
                  {data.policy.policy_id} · version {data.policy.version}
                </h3>
                <p>
                  Effective {singaporeTime(data.policy.effective_at)} · recorded{" "}
                  {singaporeTime(data.policy.recorded_at)}
                </p>
                <dl>
                  <dt>Objective / service date</dt>
                  <dd>
                    {payload.objective_policy} · {payload.target_date}
                  </dd>
                  <dt>New purchasing budget</dt>
                  <dd>S${payload.new_order_budget_sgd}</dd>
                  <dt>Issue time / horizon end</dt>
                  <dd>
                    {singaporeTime(payload.issue_time)} →{" "}
                    {singaporeTime(payload.horizon_end)}
                  </dd>
                  <dt>Service resolution</dt>
                  <dd>
                    {payload.bucket_minutes} minutes · {payload.timezone}
                  </dd>
                  <dt>Emergency / reliability</dt>
                  <dd>
                    {humanize(payload.emergency_mode)} /{" "}
                    {humanize(payload.reliability_mode)}
                  </dd>
                  <dt>Shipment fees</dt>
                  <dd>
                    {payload.fee_policy} · {payload.fee_grouping}
                  </dd>
                  <dt>FEFO / supply expiry</dt>
                  <dd>
                    {payload.fefo_policy} / {payload.new_supply_expiry_policy}
                  </dd>
                  <dt>Search / tie-break rules</dt>
                  <dd>
                    {payload.search_policy} / {payload.tie_break_policy}
                  </dd>
                  <dt>
                    Fixture requires empty post-count activity / commitments
                  </dt>
                  <dd>
                    {String(payload.explicit_empty_post_count_activity)} /{" "}
                    {String(payload.explicit_empty_outstanding_commitments)}
                  </dd>
                </dl>
                <p>
                  Service coverage is limited to the recorded horizon; this is
                  not a next-cycle guarantee. Policy search tags specify
                  requirements, not proof that a search completed.
                </p>
                <h3>Service periods</h3>
                {payload.service_profile.map((period) => (
                  <p key={period.start}>
                    {singaporeTime(period.start)} – {singaporeTime(period.end)}{" "}
                    · demand weight {period.weight}
                  </p>
                ))}
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Ingredient</th>
                        <th>Safety stock</th>
                        <th>Storage limit</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(payload.storage_limits).map(
                        ([ingredient, limit]) => (
                          <tr key={ingredient}>
                            <td>{ingredient}</td>
                            <td>
                              {payload.safety_stock[ingredient] ??
                                "Not recorded"}
                            </td>
                            <td>{limit}</td>
                          </tr>
                        ),
                      )}
                    </tbody>
                  </table>
                </div>
                <p className="quiet">
                  Quantities use each ingredient’s catalogue unit.
                </p>
                <h3>Approved supplier and opportunity domain</h3>
                <p>
                  {data.domain.domain_id} · version {data.domain.version} ·
                  source revision {data.domain.source_revision}
                </p>
                <p>
                  {data.domain.payload.source_kind}:{" "}
                  {data.domain.payload.source_description}
                </p>
                <p>
                  {data.domain.offers.length}/{payload.expected_offer_count}{" "}
                  offers · {data.domain.opportunities.length}/
                  {payload.expected_opportunity_count} opportunities ·
                  suppliers: {payload.approved_supplier_ids.join(", ")}
                </p>
                <details>
                  <summary>Opening lot provenance</summary>
                  <p>{data.domain.payload.opening_lot_ids.join(", ")}</p>
                </details>
                {data.domain.offers.map((offer) => (
                  <details className="record-details" key={offer.id}>
                    <summary>
                      {offer.supplier_id} · {offer.ingredient_id} ·{" "}
                      {offer.offer_id}
                    </summary>
                    <p>
                      Frozen revision {offer.id} · source{" "}
                      {offer.source_revision}
                    </p>
                    <dl>
                      {Object.entries(offer.offer).map(([key, value]) => (
                        <div key={key}>
                          <dt>{humanize(key)}</dt>
                          <dd>
                            {value === null
                              ? "Not recorded"
                              : typeof value === "object"
                                ? JSON.stringify(value)
                                : String(value)}
                          </dd>
                        </div>
                      ))}
                    </dl>
                    {data.domain.opportunities
                      .filter(
                        (opportunity) =>
                          opportunity.offer_id === offer.offer_id,
                      )
                      .map((opportunity) => (
                        <p key={opportunity.id}>
                          {opportunity.opportunity_id} · {opportunity.kind} ·
                          order {singaporeTime(opportunity.ordered_at)} ·
                          arrives {singaporeTime(opportunity.arrival_at)} ·
                          expiry {opportunity.expiry_date} · source{" "}
                          {opportunity.source_revision}
                        </p>
                      ))}
                  </details>
                ))}
              </>
            )}
            {forecast && (
              <>
                <h3>Forecast inputs—not forecast results</h3>
                <p>
                  {forecast.artifact_id} · version {forecast.version} · source
                  revision {forecast.source_revision}
                </p>
                <p>
                  {forecast.payload.source_kind} · method{" "}
                  {forecast.payload.forecast_method} · target{" "}
                  {forecast.payload.target_date}
                </p>
                <p>
                  Effective {singaporeTime(forecast.effective_at)} · recorded{" "}
                  {singaporeTime(forecast.recorded_at)}
                </p>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Service date</th>
                        <th>Revision</th>
                        <th>Available at</th>
                        <th>Promotion / censored</th>
                        {forecast.payload.menu_item_ids.map((dish) => (
                          <th key={dish}>{dish}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {forecast.payload.history.map((row) => (
                        <tr key={`${row.service_date}-${row.revision}`}>
                          <td>{row.service_date}</td>
                          <td>{row.revision}</td>
                          <td>{singaporeTime(row.available_at)}</td>
                          <td>
                            {String(row.promotion)} / {String(row.censored)}
                          </td>
                          {forecast.payload.menu_item_ids.map((dish) => (
                            <td key={dish}>
                              {row.portions[dish] ?? "Missing"}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </section>
  );
}
