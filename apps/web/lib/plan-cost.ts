export type PlanCostFields = {
  cost_scope: "LEGACY_FIELDS" | "NEW_PURCHASE_CASH_ONLY";
  total_expected_cost: string | null;
  new_purchase_cash_cost: string | null;
};

export function planCostSummary(plan: PlanCostFields) {
  return plan.cost_scope === "NEW_PURCHASE_CASH_ONLY"
    ? { label: "New purchase cash only", value: plan.new_purchase_cash_cost }
    : { label: "Total expected cost", value: plan.total_expected_cost };
}

export function moneyOrUnavailable(value: string | null) {
  return value === null ? "Unavailable" : `S$ ${value}`;
}
