import Link from "next/link";
import { Plan } from "@/lib/api";

export function PurchasingSteps({ plan, receiving = false }: { plan?: Plan; receiving?: boolean }) {
  const versionLink = plan ? `/workspace/recommendations?version=${encodeURIComponent(plan.id)}` : "/workspace/recommendations";
  const current = !plan ? receiving ? 4 : 3 : plan.status === "APPROVED" ? 3 : ["PENDING_APPROVAL"].includes(plan.status) ? 1 : null;
  const steps = [
    { label: "Review", detail: "Check quantities, suppliers and cash.", href: versionLink },
    { label: "Approve", detail: plan?.status === "APPROVED" ? `Version ${plan.version} approved. No order placed.` : "Approve the exact version. No order is placed.", href: `${versionLink}#plan-decision` },
    { label: "Record purchase", detail: "Arrange with the supplier, then record what you ordered.", href: plan ? `${versionLink}#purchase-lines` : "/workspace/deliveries?manual=1" },
    { label: "Receive", detail: "Record arrived stock, including partial receipts.", href: "/workspace/deliveries?view=receive" },
  ];
  return <nav className="purchasing-steps" aria-label="Purchasing workflow"><ol>{steps.map((step, i) => <li key={step.label} aria-current={current === i + 1 ? "step" : undefined}><span className="step-number">0{i + 1}</span><div><Link href={step.href}>{step.label}</Link><p>{step.detail}</p></div></li>)}</ol></nav>;
}
