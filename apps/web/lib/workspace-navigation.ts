export const areas = [
  { id: "today", label: "Today", href: "/workspace/overview", description: "See what needs attention and choose your next action.", pages: [] },
  { id: "stock", label: "Stock & sales", href: "/workspace/inventory", description: "Check stock, report sales during service and submit counts at closing.", pages: [
    { label: "Inventory", href: "/workspace/inventory" },
    { label: "Sales", href: "/workspace/sales" },
    { label: "Closing update", href: "/workspace/daily" },
  ] },
  { id: "purchasing", label: "Purchasing", href: "/workspace/recommendations", description: "Review a recommendation, approve its version, then record purchases and receipts.", pages: [
    { label: "Recommendations", href: "/workspace/recommendations" },
    { label: "Purchases & deliveries", href: "/workspace/deliveries" },
  ] },
  { id: "activity", label: "Activity", href: "/workspace/activity", description: "Follow recorded changes and assessments. Open evidence when you need more detail.", pages: [] },
  { id: "settings", label: "Restaurant settings", href: "/workspace/suppliers", description: "Manage suppliers, promotions and ordering occasions; inspect menu and recipe reference data.", pages: [
    { label: "Suppliers & promotions", href: "/workspace/suppliers" },
    { label: "Menu & recipes", href: "/workspace/inventory?view=menu" },
    { label: "Ordering schedules", href: "/workspace/inventory?view=schedules" },
  ] },
] as const;

export function workspaceArea(path: string, view: string | null) {
  if (path === "/workspace/suppliers" || (path === "/workspace/inventory" && ["menu", "schedules"].includes(view ?? ""))) return areas[4];
  if (["/workspace/inventory", "/workspace/sales", "/workspace/daily"].includes(path)) return areas[1];
  if (["/workspace/recommendations", "/workspace/deliveries"].includes(path)) return areas[2];
  if (path.startsWith("/workspace/activity")) return areas[3];
  return areas[0];
}

export const areaGuides: Record<string, { title: string; description: string }[]> = {
  today: [
    { title: "Act next", description: "Start with the next-action banner. It points to the recommendation or assessment that needs attention." },
    { title: "Check readiness", description: "Use the summaries to check closing records, expected deliveries and expiring batches. Counts and estimates are different measures." },
    { title: "Explore details", description: "Open the linked work area to make a change. Today is a summary, not a replacement for the underlying records." },
  ],
  stock: [
    { title: "Check what you have · Inventory", description: "Physical counts show staff observations. Estimates account for known activity through a selected time; check their coverage warnings." },
    { title: "Report during service · Sales", description: "Inspect reported sales and ingredient usage, then open sales entry to record or correct a complete time interval." },
    { title: "Finish the day · Closing update", description: "Enter final dish sales and counted quantities for each batch. Save a draft first, then submit when service has finished." },
  ],
  purchasing: [
    { title: "Decide what to buy · Recommendations", description: "Review quantities, suppliers, arrivals and costs. Approval accepts only that exact recommendation version; it does not place an order." },
    { title: "Record what you arranged · Purchases", description: "Arrange the order outside ReStock, then record the actual purchase. Additional recommendations stay separate from existing commitments." },
    { title: "Add arrived stock · Deliveries", description: "Use Outstanding to find expected supply. Record a receipt after arrival, including partial quantities and batch expiry dates." },
  ],
  activity: [
    { title: "What changed · Timeline", description: "Read recorded sales, supplier and inventory changes in time order. Use this to reconstruct what happened." },
    { title: "What ReStock did · Assessments", description: "Request an assessment or follow its queued, running and completed states. Open a result to review its explanation and evidence." },
    { title: "Investigate a record · Audit details", description: "Check actors, times and technical references when investigating a change. These are records, not editable settings." },
  ],
  settings: [
    { title: "Changing conditions · Suppliers & promotions", description: "Update supplier terms or promotions. Ordering occasions record ordered/skipped decisions; holiday dates are reference context." },
    { title: "How dishes use stock · Menu & recipes", description: "Inspect ingredients required per portion. This is read-only recipe reference data, not a menu editor." },
    { title: "When to consider buying · Ordering schedules", description: "Read ingredient intervals and starting dates. A scheduled occasion is not an actual purchase and does not mean stock must be bought." },
  ],
};

export const tabGuides: Record<string, { task: string; note: string }> = {
  "Summary": { task: "Follow the next action, review the current recommendation and check recent assessments.", note: "Use Daily operations for closing/delivery summaries, or Stock overview for counts and estimates." },
  "Daily operations": { task: "Check closing status, ordering occasions, expected deliveries, promotions and recent changes.", note: "These are summaries. Open the linked work area to record a change." },
  "Stock overview": { task: "Choose a cutoff and compare recorded counts with usable estimates.", note: "Check coverage warnings. Neither a count nor an estimate is a forecast of future demand." },
  "Reported sales": { task: "Choose a window and inspect included dish sales, gaps and report revisions.", note: "Overlapping reports withhold totals. Use Record or correct sales to submit facts." },
  "Ingredient usage": { task: "Inspect the ingredient quantities implied by reported portions and recipes.", note: "Calculated usage is not measured depletion or a physical stock count." },
  "Stock estimates": { task: "Inspect backend balances at the start, latest report and end of your selected window.", note: "Incomplete sales coverage stays visible. These are historical estimates, not future projections." },
  "Sales assessment": { task: "Review the latest sales-triggered assessment and its materiality or escalation findings.", note: "Unsupported or incomplete results do not mean that stock is safe." },
  "Physical counts": { task: "Find an ingredient, inspect its batches and check when each was counted.", note: "Read-only observations. Enter new closing counts in Closing update; record arrived stock through a receipt." },
  "Estimates": { task: "Select the time you want to inspect, then check quantities and sales coverage.", note: "An estimate is not a new physical count. Incomplete coverage means the balance may be incomplete." },
  "Closing update": { task: "Enter final dish sales and each batch’s counted quantity. Save a draft, then submit.", note: "Closing counts already include received stock. Do not subtract the day’s sales from them again." },
  "Sales intervals": { task: "Choose the interval, enter all dish quantities and submit. Use correction for an earlier report.", note: "This records sales facts, not a closing count. Report complete intervals; omitted dishes mean zero sales." },
  "Purchase plans": { task: "Choose a version, review its lines and evidence, then approve or reject if a decision is available.", note: "Approval is not an order. Arrange the purchase yourself and record it separately; never re-buy existing commitments." },
  "Policy": { task: "Open the stored policy, domain or input history to understand the calculation’s scope.", note: "Read-only captured rules. This view does not let you change the budget or certify an incomplete calculation." },
  "All": { task: "Find a recorded purchase and inspect its quantities, receipt history or available actions.", note: "Expected supply is not stock on hand. Only recording an arrived receipt adds inventory." },
  "Outstanding": { task: "Find what is still expected. Record an arrival, or update a delay, shortfall or cancellation.", note: "Receive only what actually arrived. Partial receipts leave the remaining quantity outstanding." },
  "Closed": { task: "Look up a purchase with no outstanding remainder and review its receipt/change history.", note: "Closed does not necessarily mean fully received: cancellations can also close the remainder." },
  "Supplier offers": { task: "Filter by ingredient, compare current offers and open View terms before recording a supplier update.", note: "An offer is availability and terms, not a purchase already placed or a guaranteed delivery." },
  "Promotions": { task: "Create or revise a promotion’s dates, affected dishes, multiplier and active state.", note: "The multiplier is a configured input, not a proven forecast. Check Activity for resulting assessments." },
  "Ordering occasions": { task: "For the selected service date, record whether each occasion was ordered or skipped.", note: "Marking an occasion does not place or record a purchase. Record actual quantities under Purchasing." },
  "Holidays": { task: "Look up Singapore public holidays and their source references.", note: "Read-only calendar context. A holiday does not automatically close the restaurant or change demand." },
  "Timeline": { task: "Browse recorded changes and open their linked records to see the surrounding facts.", note: "The timeline shows what was recorded; it is not a live external POS connection." },
  "Assessments": { task: "Request an assessment when needed, follow progress and open the completed result.", note: "A completed assessment may keep a plan or escalate an issue without publishing a new recommendation." },
  "Audit details": { task: "Inspect actors, timestamps and record references when investigating a specific action.", note: "Technical read-only history. Operational decisions belong in the relevant sales, stock or purchasing screen." },
};

export const tabDescriptions: Record<string, string> = {
  "Summary": "Your next action, current purchase recommendation and recent assessments.",
  "Daily operations": "Closing records, ordering occasions, incoming deliveries and changing conditions.",
  "Stock overview": "Compare staff-counted stock with sales-based estimates at a chosen cutoff.",
  "Reported sales": "Dish quantities, reporting gaps and included revisions for the selected window.",
  "Ingredient usage": "Ingredient use calculated from reported portions and current recipes.",
  "Stock estimates": "Backend stock balances at key times in your selected reporting window.",
  "Sales assessment": "The latest persisted sales assessment, including material changes and safe escalations.",
  "Physical counts": "Staff-counted stock by batch. Check count times and expiry before using totals.",
  "Estimates": "Stock estimated from counts, receipts and reported sales through your selected time.",
  "Closing update": "Enter final sales and physical counts. Submit when service is finished; corrections keep the original cutoff.",
  "Sales intervals": "Report all sales for an interval, or correct an earlier report. Omitted dishes count as zero.",
  "Purchase plans": "Review quantities and costs. Approve only the exact version you have checked.",
  "Policy": "Read the frozen rules and supplier opportunities behind a calculation. These are reference data, not editable settings.",
  "All": "All recorded purchases, including outstanding, received and cancelled quantities.",
  "Outstanding": "Purchases with stock still expected. Record a receipt only after it arrives.",
  "Closed": "Purchases with no outstanding remainder. Open their receipt and change history below.",
  "Supplier offers": "Compare prices and availability. View terms or record a supplier change.",
  "Promotions": "Add or revise promotions and the dishes they affect. Changes can request an assessment.",
  "Ordering occasions": "Mark each scheduled purchasing occasion as ordered or skipped; this does not place an order.",
  "Holidays": "Singapore public holiday reference dates. A holiday does not automatically mean closure or higher demand.",
  "Timeline": "Browse operational changes and manager decisions in time order.",
  "Assessments": "Track queued, running and completed assessments, then open their findings.",
  "Audit details": "Inspect technical records, actors and references when investigating a change.",
};
