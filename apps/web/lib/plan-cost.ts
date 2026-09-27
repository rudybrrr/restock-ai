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

export function moneyOrUnavailable(value: string | null | undefined) {
  if (value == null) return "Unavailable";
  const parts = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value);
  if (!parts) return "Unavailable";
  // Display cents without floating-point rounding; retain significant sub-cent precision.
  const whole = parts[2].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const fraction = (parts[3] ?? "").replace(/0+$/, "").padEnd(2, "0");
  return `S$ ${parts[1]}${whole}.${fraction}`;
}
