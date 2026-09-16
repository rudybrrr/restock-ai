export type Draft = {
  cutoff: string;
  counts: Record<string, string>;
  sales: Record<string, number>;
};
export type Reconciliation = {
  status: string;
  period_start: string;
  period_end: string;
  batch_ids: string[];
  dishes: {
    menu_item_id: string;
    daily_total: number;
    batch_total: number;
    difference: number | null;
  }[];
};
export type DailyRevision = Draft & {
  id: string;
  day: string;
  revision: number;
  recorded_at: string;
  actor: string;
  reconciliation: Reconciliation | null;
};
export type DailyHistory = { draft: Draft | null; revisions: DailyRevision[] };
export type SalesBatch = {
  id: string;
  source: string;
  batch_id: string;
  period_start: string;
  period_end: string;
  sales: Record<string, number>;
  revision: number;
  active: boolean;
  replaces_id: string | null;
};
export type EventRecord = {
  id: string;
  type: string;
  timestamp: string;
  source: string;
  payload: Record<string, unknown>;
};
export type Delivery = {
  id: string;
  supplier_id: string;
  ingredient_id: string;
  kind: "NORMAL" | "EMERGENCY";
  expected_quantity: string;
  received_quantity: string;
  cancelled_quantity: string;
  outstanding_quantity: string;
  expected_at: string;
  ordered_at: string;
  source_plan_line_id: string | null;
  source_validation: string;
  receipts: Receipt[];
};
export type Receipt = {
  id: string;
  lot_id: string;
  quantity: string;
  received_at: string;
  expiry_date: string;
  request_id: string;
  remainder: "EXPECTED" | "CANCELLED";
};
export type Offer = {
  id: string;
  supplier_id: string;
  ingredient_id: string;
  currency: string;
  unit_price: string | null;
  available_quantity: string | null;
  moq: string | null;
  pack_size: string | null;
  lead_time_minutes: number | null;
  order_cutoff: { kind: string; local_time?: string };
  feasible_delivery_at: string[] | null;
  current_status: string;
  recent_on_time_rate: string | null;
  shelf_life_days_on_arrival: number | null;
  delivery_fee_sgd: string | null;
  emergency_fee_sgd: string | null;
  observed_at: string;
};
export type Promotion = {
  id: string;
  revision: number;
  name: string;
  start_date: string;
  end_date: string;
  menu_item_ids: string[];
  demand_multiplier: string;
  active: boolean;
  effective_at: string;
};
export type OrderCycle = {
  ingredient_id: string;
  scheduled_date: string;
  status: "OPEN" | "ORDERED" | "SKIPPED";
  note: string | null;
  actor: string | null;
  effective_at: string | null;
};
