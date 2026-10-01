"use client";

import type { RenderArticleProps, RenderEditionProps, RenderItemProps } from "../../lib/renderer";

/**
 * Markus renders exclusively via the Python static build
 * (`poetry run papyrus renderers markus-build` → `web/dist/`).
 * These components satisfy the Renderer interface but are not wired into
 * `app/*` routes and must not become a second render path.
 */
function StaticRendererNotice({ label }: { label: string }) {
  return (
    <main className="markus-static-notice">
      <p>
        <strong>{label}</strong> uses the Markus static build output only. Run{" "}
        <code>poetry run papyrus renderers markus-build</code>, then preview{" "}
        <code>web/dist/</code> with a plain static file server — not Next.js.
      </p>
    </main>
  );
}

export function MarkusEditionStub(_props: RenderEditionProps) {
  return <StaticRendererNotice label="Edition view" />;
}

export function MarkusArticleStub(_props: RenderArticleProps) {
  return <StaticRendererNotice label="Article view" />;
}

export function MarkusItemStub(_props: RenderItemProps) {
  return <StaticRendererNotice label="Item view" />;
}
