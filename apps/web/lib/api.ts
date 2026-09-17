export const API_BASE = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Manager-session requests only. Decimal values remain strings in response types. */
export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/v1${path}`, {
      method: options.method ?? "GET",
      credentials: "include",
      cache: "no-store",
      headers:
        options.body === undefined
          ? undefined
          : { "Content-Type": "application/json" },
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new ApiError(
      0,
      "CONNECTION_ERROR",
      "Cannot reach ReStock. Check the API connection and try again.",
    );
  }
  if (!response.ok) {
    if (
      response.status === 401 &&
      path !== "/auth/login" &&
      typeof window !== "undefined"
    ) {
      window.dispatchEvent(new Event("restock:session-expired"));
    }
    const payload = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      payload?.error?.code ?? "REQUEST_FAILED",
      payload?.error?.message ?? `Request failed (${response.status}).`,
      payload?.error?.details ?? payload?.detail,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export type Identity = { role: "manager" | "agent"; username: string };
export type NamedRecord = { id: string; name: string };
export type Ingredient = NamedRecord & {
  unit: "kg" | "litres" | "pieces";
  interval_days: number;
  starting_date: string;
};
export type InventoryLot = {
  id: string;
  ingredient_id: string;
  unit: string;
  quantity: string;
  initial_quantity: string;
  received_at: string;
  counted_at: string;
  expiry_date: string;
  provenance: "PHYSICAL" | "ESTIMATED";
  as_of?: string;
  coverage_complete?: boolean;
  unallocated_consumption?: string;
  status?: "ACTIVE" | "EXPIRED";
};
export type PlanLine = {
  ingredient_id: string;
  supplier_id: string;
  quantity: string;
  unit_price: string;
  arrival_at: string;
};
export type Plan = {
  id: string;
  plan_id: string;
  version: number;
  status:
    | "PENDING_APPROVAL"
    | "APPROVED"
    | "REJECTED"
    | "INVALIDATED"
    | "SUPERSEDED";
  calculation_mode: "DEVELOPMENT_FIXTURE" | "ENGINE";
  lines: PlanLine[];
  total_purchase_cost: string;
  delivery_cost: string;
  total_expected_cost: string;
  expected_waste_cost: string;
  expected_stockout_cost: string;
  emergency_penalty: string;
  forecast_id: string;
  inventory_snapshot_id: string;
  run_id: string;
  created_at: string;
};
export type Run = {
  input_revision?: number;
  claimed_at?: string | null;
  completed_at?: string | null;
  snapshot?: {
    known_at?: string;
    missing_offer_history?: string[];
    procurement_contract_unavailable_reason?: string;
    procurement_contract?: { captured_state_revision: string };
  };
  id: string;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  trigger: string;
  as_of: string;
  created_at: string;
  outcome: string | null;
  escalation_reason: string | null;
  failure_reason: string | null;
  plan_version_id: string | null;
};
