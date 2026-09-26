/** Frontend display models for review, NOT an agreed Backend wire contract. */
export type PreparedRead<T> =
  | { state: "not-connected" | "loading" | "empty" }
  | { state: "error"; message: string }
  | { state: "ready"; data: T };

export type ResultCapture = {
  artifactId: string; runId: string; version: string;
  asOf: string; knownAt: string; stateRevision: string;
  horizonStart: string; horizonEnd: string; complete: boolean;
  warnings: string[];
};
export type ForecastDisplay = ResultCapture & {
  method: string;
  rows: { start: string; end: string; dishId: string; dishName: string; portions: string | null; censored: boolean }[];
};
export type ProjectionDisplay = ResultCapture & {
  basis: "EXISTING_COMMITMENTS_ONLY" | "WITH_RECOMMENDATION";
  planVersionId: string | null;
  rows: { at: string; ingredientId: string; ingredientName: string; unit: string;
    usableBalance: string | null; expectedArrivals: string | null;
    projectedUsage: string | null; expiryQuantity: string | null;
    shortfall: string | null; coverage: "COMPLETE" | "INCOMPLETE" | "UNKNOWN" }[];
};
export type EconomicsDisplay = ResultCapture & {
  objective: string; planVersionId: string; currency: "SGD";
  scope: "NEW_PURCHASE_CASH_ONLY" | "FULL_HORIZON_ECONOMICS";
  certifiedOptimal: boolean;
  newPurchaseCash: string | null; purchase: string | null; shipmentFees: string | null;
  emergencyFees: string | null; expectedWaste: string | null;
  expectedStockout: string | null; expectedTotal: string | null;
};
