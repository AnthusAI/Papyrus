import { NewsDeskClientProvider } from "./news-desk-client-provider";
import { createDemoCategorySteeringDashboard } from "../lib/category-repository";
import { resolveDevSandboxEditorAuth } from "../lib/dev-sandbox-editor-auth";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { withReferenceFeedFixture } from "../lib/local-preview-feed-fixture";
import { getBrandNewsroomSectionsConfigPath, resolveActiveSiteBrand } from "../lib/site-brand-tenant";

export function NewsroomClientShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const devSandboxEditorAuth = resolveDevSandboxEditorAuth();
  const activeBrand = resolveActiveSiteBrand();
  const localPreviewDashboard = isLocalPreviewEnabled()
    ? withReferenceFeedFixture(createDemoCategorySteeringDashboard(activeBrand.id, getBrandNewsroomSectionsConfigPath(activeBrand)))
    : null;

  return (
    <NewsDeskClientProvider devSandboxEditorAuth={devSandboxEditorAuth} localPreviewDashboard={localPreviewDashboard}>
      {children}
    </NewsDeskClientProvider>
  );
}
