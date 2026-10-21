# Pending Reference intake with an editorial session

`papyrus references create-from-catalog --status pending` uses the
`intakePendingReferences` AppSync action when normal user-session authentication
is selected. It does not attempt direct `updateKnowledgeCorpus`, Reference, or
import-run mutations, and it never falls back to IAM on failure. Explicit IAM
operator catalog imports keep their existing workflow.

The action reuses the Python content-actions Lambda and its existing managed
GraphQL and payload-upload access. The new custom mutation is restricted to the
existing editor/admin groups in both schema definitions. Generic knowledge model
authorization stays read-only. Its `PAPYRUS_USER_POOL_ISSUER` environment value is
derived from the backend's own Cognito pool at deployment, not caller input.
There are no new role policies, credentials, grants or bucket access rules.

## Operators without an editor session

`intakePendingReferences` refuses callers that are not a validated editor or admin of
the publication, and its error says so. The supported operator path is
`papyrus references create-from-catalog --status pending` with explicit IAM
credentials (`PAPYRUS_GRAPHQL_AUTH=iam`), followed by delegated curation of the
pending references. On a data-driven publication (no repo steering file) the command
resolves the publication from the backend's single canonical corpus, so
`--corpus-key` is optional (if given it must match), and catalog items without an
`item_id` get one computed from their source URL, as `references make-catalog` does.
A stored `papyrus login` session for another publication is not used for a different
endpoint; set `PAPYRUS_GRAPHQL_AUTH=iam` for that endpoint.

## Publication and actor boundary

AppSync validates the Cognito token. The handler additionally requires a subject,
matching identity/claim subject and deployed issuer, and an editor/admin group
claim. The request's `publicationEndpoint` must match the Lambda's deployed
`PAPYRUS_GRAPHQL_ENDPOINT`. Corpus existence is checked inside that same API.
The request cannot specify an actor, status, tenant, schema operation or endpoint
to which the server will connect. The immutable first version and provenance
record use the validated subject (`user:<sub>`), without supplied human labels.

This operation supports **one publication per backend**. Knowledge models do not
currently carry tenant-level authorization, so configured tenant environments
and tenant-bearing identities/requests are refused. Supporting shared-publication
knowledge data requires a separately reviewed tenancy design, not trusting a
caller-supplied publication or corpus field.

## Sources, deduplication and provenance

The request has `publicationEndpoint`, `corpusId` and 1–20 `items`. Each source
accepts `source_uri`, `title`, `media_type`, `ingestion_rationale` and the catalog's
optional `item_id`. Identity is derived from a SHA-256 of deployment endpoint,
corpus and canonical source URL; a supplied item id cannot control record ids.
Only pending intake is supported. Review and acceptance remain separate actions.

URL canonicalization lowercases scheme/host, normalizes default ports and empty
paths, and removes fragments. It preserves path case, query parameters, query
order and HTTP/HTTPS distinctions; redirects are not guessed. Non-HTTP(S) URLs,
credentials in URLs and whitespace are rejected. This action never fetches URLs.

Current legacy References participate in canonical-URL deduplication within the
corpus. Existing accepted/rejected References are returned without recuration.
Multiple current matching lineages produce an explicit conflict rather than an
arbitrary choice. Simultaneous requests through this action derive the same
Reference id and use generated AppSync conditional creates: the first writer
wins, and later writers read that record instead of updating it. Other legacy
import mechanisms do not acquire a global canonical-URL lock; do not run a
separate import of the same source concurrently.

Each new source has a deterministic KnowledgeImportRun and a private JSON
ModelAttachment (`reference`, role `metadata`, sort key `editorial-intake`, filename `editorial-intake.json`). The distinct
filename prevents collision with normal Reference metadata attachments. It
records publication endpoint, validated actor subject, canonical source URI,
title, rationale, timestamp and initial pending status. Existing upload/complete
operations validate payload hash and size. Corpus-wide counts are not overwritten
with this batch's size; corpus maintenance remains an operator workflow.

Reference, import run and S3 attachment writes are not a cross-service transaction.
The operation returns success only after provenance is complete. If interrupted,
repeat the same request: it repairs missing provenance from the immutable first
version and returns the same Reference. A response lost in transit has the same
recovery path. Full input validation occurs before writes; a later infrastructure
or legacy-duplicate conflict may leave earlier batch sources persisted. Rerun
canonical URL lookup after any uncertain result. The CLI prints each completed
batch's actual record/lineage ids for `stories link-reference`.

## Deployment and acceptance

Run the normal review/CI workflow into `develop`, then the authorized release
pipeline into `main`. Consumer publications must upgrade the released Papyrus
npm/Python bundle and deploy their backend through their normal pipeline. Updating
only a CLI cannot expose this mutation in an older backend. Do not grant generic
model writes or bypass the action while waiting for deployment.

The new server function environment and schema mutation require a backend deploy;
they do not require a new IAM policy or user-pool grant. Any unanticipated pipeline
permission expansion must be reviewed and explicitly approved rather than worked
around. The handler uses its existing Lambda IAM role internally; editorial
acceptance uses the Google/Keychain session with AWS credential sources disabled.

After deployment, run intake twice for a small pending-source catalog, verify the
same ids/provenance and no recuration, link returned record ids as consulted to an
existing unpublished Reporting story, then read versions, links, Messages, stage
and publication projection. Never claim local tests as live acceptance. Preserve
all prior story versions/Messages and do not create a replacement story.
