import { NewsDeskClientProvider } from "../../components/news-desk-client-provider";
import { resolveDevSandboxEditorAuth } from "../../lib/dev-sandbox-editor-auth";

export default function NewsroomLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const devSandboxEditorAuth = resolveDevSandboxEditorAuth();

  return (
    <NewsDeskClientProvider devSandboxEditorAuth={devSandboxEditorAuth}>
      {children}
    </NewsDeskClientProvider>
  );
}
