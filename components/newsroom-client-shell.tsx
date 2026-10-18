import realSections from "../lib/real-preview-sections.json";
import realSeed from "../lib/real-preview-seed.json";
import { NewsDeskClientProvider } from "./news-desk-client-provider";
import { createDemoCategorySteeringDashboard } from "../lib/category-repository";
import { resolveDevSandboxEditorAuth } from "../lib/dev-sandbox-editor-auth";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { getBrandNewsroomSectionsConfigPath, resolveActiveSiteBrand } from "../lib/site-brand-tenant";

export function NewsroomClientShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const devSandboxEditorAuth = resolveDevSandboxEditorAuth();
  const activeBrand = resolveActiveSiteBrand();
  const previewDashboard = isLocalPreviewEnabled() ? createDemoCategorySteeringDashboard(activeBrand.id, getBrandNewsroomSectionsConfigPath(activeBrand)) : null;
  const localPreviewDashboard = previewDashboard
    ? { ...previewDashboard, newsroomSections: (realSections as unknown[]).length ? (realSections as never) : previewDashboard.newsroomSections, assignments: realSeed.assignments as never, references: [], messages: [] }
    : null;

  return (
    <NewsDeskClientProvider devSandboxEditorAuth={devSandboxEditorAuth} localPreviewDashboard={localPreviewDashboard}>
      {children}
    </NewsDeskClientProvider>
  );
}
