export function StagingBanner() {
  return (
    <div
      data-staging-banner
      role="status"
      className="sticky top-0 z-50 bg-amber-300 px-3 py-1 text-center text-xs font-semibold uppercase tracking-wide text-black"
    >
      STAGING: drafts shown as published
    </div>
  );
}
