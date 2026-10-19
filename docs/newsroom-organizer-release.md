# Organizer CMS release — PPY-ca252a

This is a presentation and read-only Board release around the existing CMS,
not a replacement backend. The organizer is the only newsroom shell: the former
`newsroomLayout` SiteBrand option and the legacy ops shell (top bar, fixed sidebar,
bottom tabs) are removed, so there is nothing to opt into. Publications that set
`newsroomLayout: "organizer"` must delete that field. The Overview page remains
the `/newsroom` landing page, reached from the brand link; Search is the header
search box; Topic proposals sit under Taxonomy.

## Implemented

- Full viewport shell, internally scrolling workspace, collapsible desktop
  sidebar, grouped mobile More menu and concise bottom navigation.
- Original NewsDeskClientProvider access lifecycle and ReaderAuthControl
  signin/signout. Account menu uses its actual session snapshot; Settings uses
  the original local/cloud preference implementation.
- Native CMS Articles, Assignments, References/curation, Messages (including notes),
  Taxonomy, Topic proposals, Concepts, Knowledge search, Policies, Sections,
  Procedures and Users/identity merging remain original components/commands.
  Existing server permissions remain authoritative. Desks routing opens the
  original taxonomy editor for every publication; the retired Users and Doctrine
  aliases redirect to Administration.
- Board uses released @kanbus/ui 0.2.0 IssueCollection and IssueDetailPanel. It
  projects native Item rows, current Reference revisions and Assignment rows,
  preserving identities/statuses and linking to their original mutation UI.
  Unknown statuses remain visible; no Story linkage, stage mutation, publishing
  by dragging, or fake issue hierarchy is inferred. References and Assignments
  paginate in batches of 50 with explicit Load more. Refresh reads the backend.
- Board waits for real editor access before reads; access transitions clear
  records, pending responses cannot repopulate a discarded session. Shared
  columns own collapse/persistence, keyboard behavior and motion. Existing
  theme/motion settings apply; fonts are licensed self-hosted assets. The host
  retains its publication tokens: shared kanban geometry is combined with a
  Papyrus-scoped newsprint theme. The optional CRM retro preset and global
  Kanbus font/palette tokens are not imported.
- Test editor override is refused in production even when the public test flag
  is set. No local gateway, fixture store, credential or synthetic classifier is
  a production dependency.

Shared release: `ui-v0.2.0`, source merge
`19ac9211b46f6a92d11d9cbc6afa44792adb455e` (PR402). Immutable artifact:
https://github.com/AnthusAI/Kanbus/releases/download/ui-v0.2.0/kanbus-ui-0.2.0.tgz
SHA-256 `e174dbbb7864c76eb02bb840b7e6f28ea653491593ec7539bfb061d7b2c82acf`.
The dedicated UI release pipeline succeeded; no CLI release or deployment was
performed by that tag. Shared 33-scenario/186-step component suite and canonical
console parity passed; PR402's full remote checks, including wiki retry and
Beads interoperability, passed before merge.

## Gates still to verify

- Product branch TypeScript/package smoke checks and an actual packed-package
  consumer/Amplify build, followed by each consumer upgrading.
- Responsive browser layout, deep links, manual/system themes, low/reduced
  motion, keyboard navigation and unchanged signed-out gates in the production
  host. Physical iPad/Safari is not claimed by automated Chromium checks.
- Reuse an existing authorized browser session for read-only signed-in acceptance
  if one is available. Current browser/screen inspection failed; no credentials
  or tokens are extracted. Fresh login, expired sessions and real editor/admin/
  ordinary-user matrix cannot be established just by reaching Google sign-in.
- Real mutations require an approved test corpus/nonproduction records. Existing
  staging frontends point at the production backend: no destructive tests there.
  Unit/transport fixtures test behavior but do not prove a live cloud mutation.

## Transitional boundaries

Original CMS handlers retain their existing data/authorization contracts. No new
schema or auth migration is required for this shell and native record Board.
Existing limitations of taxonomy destructive apply, semantic graph merge and
unconfigured procedure execution remain explicit. Optional Cyclotron integration
is separate and does not block this release; the original curator is retained.
There is no production schema-browser CRUD or LAN synthetic intake/gateway.

Pilobolus's existing domain now routes to the unchanged CMS through separate
CloudFront stack `papyrus-edge-pilobol-us-cms`; PR208 is merged at `3902b81`.
The original failed backend build attempted a Cognito domain update. This UI
rollout must preserve the deployed backend/auth domain rather than rerun that
unresolved migration. Use the existing DevOps frontend path with generated main
backend outputs. Never upload a manual ZIP or replace the S3 reader. Release
order: Pilobolus, p.apyr.us, Threat Intelligence; exclude Anth.us entirely.
