import { Ingredient, InventoryLot } from "@/lib/api";
import { sumDecimals } from "@/lib/decimal";
export function InventorySummary({
  lots,
  ingredients,
  estimated,
}: {
  lots: InventoryLot[];
  ingredients: Ingredient[];
  estimated: boolean;
}) {
  return (
    <section className="panel">
      <header className="panel-head">
        <h2>Ingredient totals</h2>
        <span className="quiet">
          {estimated ? "Estimated balances" : "Latest recorded counts"}
        </span>
      </header>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Ingredient</th>
              <th>Total recorded quantity</th>
              <th>Batches</th>
              <th>Observation basis</th>
            </tr>
          </thead>
          <tbody>
            {ingredients.map((i) => {
              const matching = lots.filter((l) => l.ingredient_id === i.id);
              return (
                <tr key={i.id}>
                  <td>{i.name}</td>
                  <td>
                    {matching.length
                      ? sumDecimals(matching.map((l) => l.quantity))
                      : "No observation"}{" "}
                    {matching.length ? i.unit : ""}
                  </td>
                  <td>{matching.length}</td>
                  <td>
                    {estimated
                      ? "Sales-derived estimate"
                      : "Latest count per batch"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="compact-note">Latest counts may include expired lots or different count times. Check batch details before using these totals.</p>
    </section>
  );
}
