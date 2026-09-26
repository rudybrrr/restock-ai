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
      "Review the recorded decision below.",
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
    <section className={`notice ${status === "SUCCEEDED" ? "processing-complete" : ""}`} aria-label="Assessment progress" role="status">
      <strong>{value.title}</strong>
      <p>{value.detail}</p>
      <ol className="progress-track" aria-label="Recorded processing stages">
        <li data-state="done">Request saved</li>
        <li data-state={status === "QUEUED" ? "waiting" : status === "RUNNING" ? "current" : "done"}>Worker processing</li>
        <li data-state={status === "SUCCEEDED" ? "done" : status === "FAILED" ? "failed" : "waiting"}>{status === "FAILED" ? "Processing failed" : "Result recorded"}</li>
      </ol>
    </section>
  );
}
