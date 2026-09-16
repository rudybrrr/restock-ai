"use client";
import { useSearchParams } from "next/navigation";
export function SessionNotice() {
  const params = useSearchParams();
  return params.get("expired") === "1" ? (
    <p className="notice" role="status">
      Your session expired. Sign in again to return to your workspace.
    </p>
  ) : null;
}
