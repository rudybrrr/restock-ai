import { AssessmentDetail } from "@/components/assessment-detail";
export default async function AssessmentPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  return <AssessmentDetail id={runId} />;
}
