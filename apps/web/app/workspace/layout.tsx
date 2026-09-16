import { Providers } from "@/components/providers";
import { Workspace } from "@/components/workspace";
export default function WorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <Providers>
      <Workspace>{children}</Workspace>
    </Providers>
  );
}
