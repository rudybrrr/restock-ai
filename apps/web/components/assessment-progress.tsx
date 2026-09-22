import { Run } from "@/lib/api";

const progress: Record<Run["status"], { title: string; detail: string }> = {
  QUEUED: {
    title: "Waiting to be processed",
    detail:
      "Your request is saved. Processing starts when an assessment worker picks it up; refreshing this page does not start the worker.",
  },
  RUNNING: {
    title: "Assessment in progress",
    detail:
      "The assessment has been claimed. Recorded progress refreshes automatically; no purchasing conclusion is available yet.",
  },
  SUCCEEDED: {
    title: "Assessment finished",
    detail:
      "Processing finished. Check the decision below: a finished assessment may still require information or manager review.",
  },
  FAILED: {
    title: "Assessment could not finish",
    detail:
      "No successful conclusion was recorded. Review the failure details before retrying; existing purchases remain unchanged.",
  },
};

export function AssessmentProgress({ status }: { status: Run["status"] }) {
  const value = progress[status];
  return (
    <section className="notice" aria-label="Assessment progress" role="status">
      <strong>{value.title}</strong>
      <p>{value.detail}</p>
    </section>
  );
}
