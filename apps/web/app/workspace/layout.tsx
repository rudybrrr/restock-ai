import { Providers } from "@/components/providers";
import { Workspace } from "@/components/workspace";
import { Suspense } from "react";
export default function WorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <Providers>
      <Suspense fallback={<p role="status">Opening workspace…</p>}><Workspace>{children}</Workspace></Suspense>
    </Providers>
  );
}
