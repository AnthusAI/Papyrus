# Preparing a publication with a shared central router

This is an **inactive preparation contract**, not hosted-site support or a
deployment configuration. The Python API validates supplied metadata and prepares
an immutable handoff. It does not create a site, account, grant, credentials,
engine, section, label or feedback record, and it does not call a model.

The plan preserves two stages:

1. The existing central Cyclotron routes a discovery to its matching publications.
   An owner grant permits a separate SaaS account to use a narrowly scoped output.
2. A matched publication uses its own internal Cyclotron to classify the discovery
   into that publication's sections.

The consumer's SaaS account must differ from the central owner's account. The
internal router belongs to the consuming publication's SaaS account and
publication, and has a distinct engine instance identity. Sharing the central
service does not make the consumer a member or administrator of the owner's
account. No duplicate central publication router is prepared.

## Artifact and identity boundaries

`docs/examples/dataparade-publication-plan.json` is deliberately inactive. Every
unverified identity, domain and editorial setting is `null`. The publication name
is the user's requested name; no Anthus account, existing local pod, default
policy, match label or section taxonomy is substituted.

`prepare_publication_routing_plan(mapping)` returns a frozen
`PreparedPublicationRoutingPlan` with `unresolved_fields`. Nulls are valid for
preparation and prevent `ready_for_review`. Missing keys, unknown keys, malformed
values and inconsistent router ownership are rejected. `ready_for_review=True`
means all fields were supplied and are structurally consistent. It does **not**
verify live identity, permissions or deployment and does **not** activate anything.
The contract accepts only `status: "inactive"`.

| Field group | Meaning |
| --- | --- |
| `consumer.accountId` | Canonical SaaS organization UUID; never an AWS account number. |
| `consumer.perspectiveSystem` and `perspectiveId` | Explicit metadata identifying what the user's “perspective” means once verified. They grant no authority and are not inferred to mean Prospectus or an AWS account. |
| `consumer.publicationId` and `domain` | Verified target publication and approved DNS name. The name alone establishes neither. |
| `centralRouter` | Existing service, owner SaaS account, engine instance, one output, immutable binding revision, explicit match label and reviewed grant/revision. |
| `centralRouter.billingAccountId` and `billingPolicy` | Current sharing contract is `owner-pays`, billed to the central owner. A different billing policy needs a separate contract change and approval. |
| `internalRouter` | Consumer account/publication, separate internal engine identity and versioned section-taxonomy reference. |
| `editorialPolicyRef` | Versioned reference only; private policy bodies are not carried by this artifact. |

References identify reviewed versions; the API does not retrieve or establish
them. Hosts must verify those references against current metadata. This module is
not wired into the existing runtime, schema, CLI or site configuration.

## Scoped match handoff

`prepare_section_handoff(plan, envelope, verify_match=host_verifier)` requires a
complete plan and an explicit host verifier. There is no default verifier and no
JSON `trusted` flag. The verifier must authenticate the receipt's transport or
signature and central issuer/service, audience and freshness, then verify the
current grant/revision, consumer entitlement, source/output scope and budget.
The verifier must return only a verified `cyclotron-sharing/v1` receipt.
Bind the verifier to the expected `plan.central_router.service_id`; service
identity comes from authenticated transport and is not a field in that receipt.

The preparation API revalidates the actual plan fields at every handoff, including
plans reconstructed with public dataclasses; a stale or forged completeness flag
cannot bypass the routing invariants. It validates the receipt's owner, consumer, publication, engine,
binding revision, grant/revision and owner billing against the plan. It accepts
exactly the configured output and only its configured match label. The sharing
contract uses the label supplied by that output; this module does not infer or
convert editorial labels. Confidence may be null, as in the sharing contract;
this module adds no editorial confidence threshold. Extra outputs, policy bodies, labels and feedback
payloads are refused. A negative match does not prepare an internal handoff.
Output versions retain Cyclotron's native positive integer version.

The frozen `SectionHandoff` retains source account/list/item/revision/content
hash; central service, owner, engine, binding, output label/confidence/version, request, decision,
receipt and grant; consumer publication; internal router and taxonomy reference;
editorial-policy reference; and billing attribution. It contains no source body
or permission to fetch one. It prepares the *input* to section classification and
does not claim that a section prediction has occurred.

Addressed delivery of an existing central decision retains its original source
account/publication and decision identity. The delivery receipt also retains
`delivery.id`, `delivery.centralReceiptId` and matching `billing.origin` provenance.
Its current `providerRequests` must be zero; the original measured count is retained
separately and is not charged again. Preparing this handoff never reruns central
inference. A logical `reservedRequests: 1` records the delivery operation and is
not provider-spend authorization.
Source identity uses the exact native account, `source.listId`, item `source.id`,
positive integer `source.revision` and content hash. Revisions are not stringified;
booleans and nonpositive revisions are refused. Identically named items in two
lists retain distinct identities.
For a source from a shared discovery pool, `source.publicationId` may explicitly
be null; this field is optional origin metadata, not a uniqueness key. The source
account/list/item/revision/content hash remain required and unchanged.
No originating publication is invented. The addressed consumer publication is
always required.

The receipt verifier is an integration boundary, not cryptographic verification
implemented here. A callback that trusts an arbitrary dictionary would violate
the contract. Hosting must authenticate the current principal and recheck the
live grant and publication access immediately before internal dispatch or any
other effect; prepared metadata is not an authorization lease. Replay protection
must bind the receipt/request and source revision in the host. Hosts must retain
the central-to-internal provenance in later section predictions and keep
publication feedback and human labels scoped to their own stage and tenant.

## Existing Data Parade resources and pending activation

Read-only inventory on 2026-10-20 established:

- An existing local Papyrus pod is not evidence of a hosted SaaS publication and
  will not be repurposed implicitly.
- Data Parade already has product and landing sites.
  Both `https://dataparade.io` and `https://app.dataparade.io` returned HTTP 200
  through CloudFront. Existing SAM configuration describes Lambda/CloudFront
  stacks; these resources must be preserved.
- The accessible DataParade-io repository inventory did not contain a separate
  hosted Papyrus publication repository. The inspected Papyrus production
  `us-east-1` Amplify inventory also contained no Data Parade application.
- Data Parade's own production AWS resource inventory was not verified because
  its existing SSO session had expired. This is an inventory gap, not evidence
  that a resource is absent.
- The actual consuming SaaS account, perspective meaning, publication identity,
  central owner/grant and internal section-router bindings remain unverified.

Domain and editorial criteria are pending the user's later choices. Do not
repurpose the existing local pod, invent a taxonomy, or create a hosted target
based on the absence of evidence. Verify the existing account and resources first,
then review exact site, grant, billing, source/output and infrastructure scopes
before any activation. No DNS, production infrastructure or security grant
changes are authorized by this artifact.

Tracking: PPY epic `PPY-9822fdeb-f07c-495a-a035-66f9e81f3d30`, preparation story
`PPY-b9c2ff5e-008c-45a0-9a41-88a85d15135f`, and activation dependency
`PPY-90711b3b-4684-4782-bb7e-9d788794a373`. Central priming proceeds independently.

## Offline verification

The tests use synthetic SaaS tenants, policy/taxonomy references and receipt
verifiers. No provider, cloud credential or production data is used.

```sh
python -m pytest procedures/newsroom/tests/test_publication_routing_plan.py -q
PYTHONPATH=src python -m behave features_backend/publication-routing-plan.feature
```

The full Behave step loader requires the repository's normal development
dependencies. Isolating this feature and its matching step file verifies this
contract without claiming the entire backend suite passed.
