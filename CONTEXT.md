# ReStock

ReStock helps a restaurant maintain purchasing recommendations as demand, inventory, and supplier conditions change.

## Language

**Purchase plan**:
A recommendation of which ingredients to buy, in what quantities, from which suppliers, and when. It is not an order placed with a supplier.
_Avoid_: Order, purchase order

**Plan version**:
A complete revision of a purchase recommendation for a planning horizon. Existing external commitments remain fixed inputs; purchase lines recommend only quantities not already committed. Approval belongs to the exact revision reviewed.

**Planning window**:
The period covered by a purchasing recommendation, determined by ordering opportunities and delivery timing. Ingredients can require different coverage periods.

**Ordering schedule**:
The restaurant's planned opportunities to order an ingredient, such as daily or every fourteen days. It does not imply that a purchase is needed on every opportunity.

**Stock count**:
A staff-reported quantity of an ingredient at a particular time. It is an observation, distinct from estimated stock remaining at a future time.

**Closing stock count**:
The authoritative staff-reported quantity remaining in each batch at the end of the day, including deliveries received that day. Dish sales are recorded separately and are not deducted again from this count.

**Order cycle**:
A scheduled purchasing occasion for an ingredient, recurring at its configured interval from a starting date. It can be marked ordered or skipped; late recording does not shift later occasions.

**Stock discrepancy**:
The difference between an estimated stock balance and a physical count. It does not establish how much was wasted or why the difference occurred.

**Approval**:
A manager's acceptance of a specific plan version. Every new version requires approval; acceptance does not place orders or add inventory.

**Event**:
A reported change in restaurant conditions, such as a promotion, supplier shortage, sales update, or inventory adjustment.

**Inventory lot**:
A received batch of an ingredient with its own expiry date and remaining quantity. Each batch is tracked separately, even when another batch contains the same ingredient.

**Expired batch**:
A retained inventory batch that has reached the agreed expiry boundary and is no longer usable. Its recorded counts remain historical observations, not proof of how much was discarded.

**Supplier offer**:
An approved supplier's purchasing terms and available quantity for a particular ingredient.

**Incoming delivery**:
A recorded ingredient shipment arranged outside ReStock, with a quantity and expected arrival date. It is distinct from a purchase recommendation and from stock already counted on hand.

**Emergency order**:
A purchase the owner arranges outside an ingredient's normal ordering schedule to address a shortage, potentially following an agent recommendation. Its expected delivery covers a projected shortage only if enough stock arrives in time.

**Daily update**:
The restaurant's submitted stock counts, sales, and known operational changes for a day. Completing the update requests assessment; promotions, supplier disruptions, and material changes detected from sales batches can also request assessment between daily updates.

**Estimated inventory**:
A derived stock balance starting from the latest physical count and accounting for known subsequent activity through a stated time. It remains an estimate and does not replace the physical observation.

**Sales batch**:
A timestamped report of dish quantities sold during a defined interval. Successive batches support ingredient-usage estimates between physical counts.

**Contingency recommendation**:
A proposed additional purchase addressing a disruption while accounting for purchases already arranged. It does not change existing external commitments.

**Procurement policy version**:
An immutable, dated set of rules that defines the purchasing objective, service coverage, safety stock, storage limits, budget, fee treatment, emergency mode and deterministic policy versions for one planning slice. A run uses the exact version frozen when it is claimed.

**Approved procurement domain**:
The complete set of frozen supplier-offer revisions and dated purchasing opportunities a procurement search may consider under a procurement policy version. It is distinct from the subset of lines eventually recommended.

**Procurement contract**:
The Backend-owned read artifact that combines a frozen procurement policy version, its approved procurement domain, the run's operational and knowledge cutoffs, and captured state revision. The agent passes it to deterministic tools; it does not create or alter it.

**Sales threshold policy version**:
An immutable, dated definition of when cumulative intraday sales deviation has enough exposure to be assessed as material. A run uses the exact Backend-selected version and revision-bound evidence; the agent does not supply fallback thresholds.

**Sales materiality assessment**:
The immutable, hashed engine request and result associated with one sales-triggered planning run. It records the frozen contract, issued forecast, catalogue, policy, evidence, and three-state materiality result without treating unknown as safe.

**Inventory adjustment assessment**:
The immutable, hashed deterministic result for one or more closing-count corrections attached to a planning run. It binds the canonical adjustment events, corrected inventory snapshot, plan reference, clocks, and state revision; only a complete non-material result can certify that the current plan remains unchanged.
