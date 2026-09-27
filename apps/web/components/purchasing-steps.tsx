import { Plan } from "@/lib/api";

export function PurchasingSteps({ plan, receiving = false }: { plan?: Plan; receiving?: boolean }) {
  const current = !plan ? receiving ? 4 : 3 : plan.status === "APPROVED" ? 3 : ["PENDING_APPROVAL"].includes(plan.status) ? 1 : null;
  const steps = [
    { label: "Review", detail: "Check quantities, suppliers and cash." },
    { label: "Approve", detail: plan?.status === "APPROVED" ? `Version ${plan.version} approved. No order placed.` : "Approve the exact version. No order is placed." },
    { label: "Record purchase", detail: "Arrange with the supplier, then record what you ordered." },
    { label: "Receive", detail: "Record arrived stock, including partial receipts." },
  ];
  return <section className="purchasing-steps" aria-label="Purchasing workflow"><ol>{steps.map((step, i) => <li key={step.label} aria-current={current === i + 1 ? "step" : undefined}><span className="step-number">0{i + 1}</span><div><strong>{step.label}</strong><p>{step.detail}</p></div></li>)}</ol><p className="quiet workflow-note">Stages explain the workflow; they do not place orders or certify that a purchase was recorded. Use the relevant action below when its prerequisites are satisfied.</p></section>;
}
