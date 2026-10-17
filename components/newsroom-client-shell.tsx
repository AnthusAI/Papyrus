import { NewsDeskClientProvider } from "./news-desk-client-provider";
import { resolveDevSandboxEditorAuth } from "../lib/dev-sandbox-editor-auth";

export function NewsroomClientShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const devSandboxEditorAuth = resolveDevSandboxEditorAuth();

  return (
    <NewsDeskClientProvider devSandboxEditorAuth={devSandboxEditorAuth}>
      {children}
    </NewsDeskClientProvider>
  );
}
