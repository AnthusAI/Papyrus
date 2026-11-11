Feature: Every way tenant A could reach tenant B is a generated case, and a gap fails the build
  The shared stack serves many tenants from one set of tables. The adversarial suite (PPY-29f730) tries every way
  tenant A could see or change tenant B's data, and it is generated from the schema and the function list so that a new
  model, index, query, mutation or function cannot ship without a case. This first part (PPY-65e5a9) is the generator
  and the case table. It reads the GraphQL that Amplify generates from amplify/data/schema.ts (with every plugin's
  models), and the function directories, then writes features_backend/fixtures/tenant-isolation/cases.json and the
  generated scenarios below. It calls no AWS service.

  The generated scenarios are tagged @isolation-pending. They need the shared stack with two seeded tenants, so the
  behave run reports them as skipped, never as failed. A later part supplies the steps and removes the tag.

  The generator also lists the gaps it can already see in the schema, for example a tenantId that an editor can change
  and an index whose partition key is shared by every tenant (npx tsx scripts/generate-tenant-isolation-cases.ts
  --report). They are reported, not failed, until the group rules are removed (PPY-bdc4ee).

  Scenario: A model without a case fails the build
    Given a model is added to schema.ts
    When the generator check runs in CI
    Then it fails naming the model

  Scenario: An index without a case fails the build
    Given an index is added to a model in schema.ts
    When the generator check runs in CI
    Then it fails naming the index

  Scenario: A custom query or mutation without a case fails the build
    Given a custom mutation is added to schema.ts
    When the generator check runs in CI
    Then it fails naming the mutation

  Scenario: A function without a case fails the build
    Given a function directory is added under amplify/functions
    When the generator check runs in CI
    Then it fails naming the function

  Scenario: A case for something that no longer exists fails the build
    Given a model is removed from schema.ts but its cases remain
    When the generator check runs in CI
    Then it fails naming the model

  Scenario: A case table that is out of date fails the build and says how to regenerate it
    Given the committed case table differs from the schema
    When the generator check runs in CI
    Then it fails and names the command that regenerates it

  Scenario: The committed case table and feature match the schema
    When the generator check runs in CI
    Then it passes

  Scenario: Every model is covered for every operation it exposes
    When the case table is generated
    Then each tenant-owned model has get, list, create with a foreign tenantId, update to a foreign tenantId, update of a foreign row and delete of a foreign row
    And a model that disables an operation has no case for it
    And the global models UserProfile, UserIdentity and PublicHandleClaim are recorded as reviewed decisions

  Scenario: The report lists the known gaps without failing
    When the gap report runs
    Then it lists the models whose tenantId can be changed
    And it lists the indexes whose partition key is not tenant-prefixed
    And it exits successfully

  # BEGIN GENERATED CASES (scripts/generate-tenant-isolation-cases.ts; do not edit by hand)
  @isolation-pending
  Scenario Outline: Tenant A cannot reach tenant B through any model operation
    Given editor sessions for "alpha" and "beta" on the shared stack
    When the "alpha" session performs <operation> on a "beta" <model>
    Then it is denied or returns nothing of "beta"

    Examples: generated from the schema
      | model                    | operation                       | outcome                                                               |
      | Assignment               | get                             | denied, or returns nothing of "beta"                                  |
      | Assignment               | list                            | no row of "beta" is returned and pages are not short                  |
      | Assignment               | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | Assignment               | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | Assignment               | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | Assignment               | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | Assignment               | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | AssignmentEvent          | get                             | denied, or returns nothing of "beta"                                  |
      | AssignmentEvent          | list                            | no row of "beta" is returned and pages are not short                  |
      | AssignmentEvent          | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | AssignmentEvent          | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | AssignmentEvent          | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | AssignmentEvent          | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | AssignmentEvent          | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | Automation               | get                             | denied, or returns nothing of "beta"                                  |
      | Automation               | list                            | no row of "beta" is returned and pages are not short                  |
      | Automation               | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | Automation               | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | Automation               | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | Automation               | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | Automation               | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | Category                 | get                             | denied, or returns nothing of "beta"                                  |
      | Category                 | list                            | no row of "beta" is returned and pages are not short                  |
      | Category                 | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | Category                 | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | Category                 | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | Category                 | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | Category                 | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | CategoryKeyword          | get                             | denied, or returns nothing of "beta"                                  |
      | CategoryKeyword          | list                            | no row of "beta" is returned and pages are not short                  |
      | CategoryKeyword          | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | CategoryKeyword          | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | CategoryKeyword          | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | CategoryKeyword          | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | CategoryKeyword          | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | CategorySet              | get                             | denied, or returns nothing of "beta"                                  |
      | CategorySet              | list                            | no row of "beta" is returned and pages are not short                  |
      | CategorySet              | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | CategorySet              | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | CategorySet              | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | CategorySet              | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | CategorySet              | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | CurationDelegationRecord | get                             | denied, or returns nothing of "beta"                                  |
      | CurationDelegationRecord | list                            | no row of "beta" is returned and pages are not short                  |
      | CurationDelegationRecord | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | CurationDelegationRecord | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | CurationDelegationRecord | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | CurationDelegationRecord | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | CurationDelegationRecord | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | Edition                  | get                             | denied, or returns nothing of "beta"                                  |
      | Edition                  | list                            | no row of "beta" is returned and pages are not short                  |
      | Edition                  | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | Edition                  | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | Edition                  | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | Edition                  | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | Edition                  | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | EditionItem              | get                             | denied, or returns nothing of "beta"                                  |
      | EditionItem              | list                            | no row of "beta" is returned and pages are not short                  |
      | EditionItem              | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | EditionItem              | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | EditionItem              | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | EditionItem              | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | EditionItem              | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | EditorialCheckRun        | get                             | denied, or returns nothing of "beta"                                  |
      | EditorialCheckRun        | list                            | no row of "beta" is returned and pages are not short                  |
      | EditorialCheckRun        | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | EditorialCheckRun        | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | EditorialCheckRun        | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | EditorialCheckRun        | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | EditorialCheckRun        | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | EditorialCheckSettings   | get                             | denied, or returns nothing of "beta"                                  |
      | EditorialCheckSettings   | list                            | no row of "beta" is returned and pages are not short                  |
      | EditorialCheckSettings   | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | EditorialCheckSettings   | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | EditorialCheckSettings   | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | EditorialCheckSettings   | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | EditorialCheckSettings   | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | EditorialFeedback        | get                             | denied, or returns nothing of "beta"                                  |
      | EditorialFeedback        | list                            | no row of "beta" is returned and pages are not short                  |
      | EditorialFeedback        | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | EditorialFeedback        | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | EditorialFeedback        | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | EditorialFeedback        | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | EditorialFeedback        | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | EditorialPolicy          | get                             | denied, or returns nothing of "beta"                                  |
      | EditorialPolicy          | list                            | no row of "beta" is returned and pages are not short                  |
      | EditorialPolicy          | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | EditorialPolicy          | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | EditorialPolicy          | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | EditorialPolicy          | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | EditorialPolicy          | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | Item                     | get                             | denied, or returns nothing of "beta"                                  |
      | Item                     | list                            | no row of "beta" is returned and pages are not short                  |
      | Item                     | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | Item                     | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | Item                     | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | Item                     | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | Item                     | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ItemTag                  | get                             | denied, or returns nothing of "beta"                                  |
      | ItemTag                  | list                            | no row of "beta" is returned and pages are not short                  |
      | ItemTag                  | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | ItemTag                  | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | ItemTag                  | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | ItemTag                  | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ItemTag                  | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | KnowledgeArtifact        | get                             | denied, or returns nothing of "beta"                                  |
      | KnowledgeArtifact        | list                            | no row of "beta" is returned and pages are not short                  |
      | KnowledgeArtifact        | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | KnowledgeArtifact        | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | KnowledgeArtifact        | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | KnowledgeArtifact        | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | KnowledgeArtifact        | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | KnowledgeCorpus          | get                             | denied, or returns nothing of "beta"                                  |
      | KnowledgeCorpus          | list                            | no row of "beta" is returned and pages are not short                  |
      | KnowledgeCorpus          | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | KnowledgeCorpus          | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | KnowledgeCorpus          | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | KnowledgeCorpus          | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | KnowledgeCorpus          | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | KnowledgeImportRun       | get                             | denied, or returns nothing of "beta"                                  |
      | KnowledgeImportRun       | list                            | no row of "beta" is returned and pages are not short                  |
      | KnowledgeImportRun       | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | KnowledgeImportRun       | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | KnowledgeImportRun       | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | KnowledgeImportRun       | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | KnowledgeImportRun       | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | KnowledgeRawPayload      | get                             | denied, or returns nothing of "beta"                                  |
      | KnowledgeRawPayload      | list                            | no row of "beta" is returned and pages are not short                  |
      | KnowledgeRawPayload      | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | KnowledgeRawPayload      | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | KnowledgeRawPayload      | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | KnowledgeRawPayload      | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | KnowledgeRawPayload      | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | LexicalSteeringRule      | get                             | denied, or returns nothing of "beta"                                  |
      | LexicalSteeringRule      | list                            | no row of "beta" is returned and pages are not short                  |
      | LexicalSteeringRule      | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | LexicalSteeringRule      | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | LexicalSteeringRule      | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | LexicalSteeringRule      | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | LexicalSteeringRule      | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | MediaAsset               | get                             | denied, or returns nothing of "beta"                                  |
      | MediaAsset               | list                            | no row of "beta" is returned and pages are not short                  |
      | MediaAsset               | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | MediaAsset               | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | MediaAsset               | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | MediaAsset               | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | MediaAsset               | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | Message                  | get                             | denied, or returns nothing of "beta"                                  |
      | Message                  | list                            | no row of "beta" is returned and pages are not short                  |
      | Message                  | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | Message                  | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | Message                  | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | Message                  | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | Message                  | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | MessageThread            | get                             | denied, or returns nothing of "beta"                                  |
      | MessageThread            | list                            | no row of "beta" is returned and pages are not short                  |
      | MessageThread            | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | MessageThread            | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | MessageThread            | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | MessageThread            | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | MessageThread            | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ModelAttachment          | get                             | denied, or returns nothing of "beta"                                  |
      | ModelAttachment          | list                            | no row of "beta" is returned and pages are not short                  |
      | ModelAttachment          | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | ModelAttachment          | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | ModelAttachment          | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | ModelAttachment          | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ModelAttachment          | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ModerationAction         | get                             | denied, or returns nothing of "beta"                                  |
      | ModerationAction         | list                            | no row of "beta" is returned and pages are not short                  |
      | ModerationAction         | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | ModerationAction         | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | ModerationAction         | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | ModerationAction         | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ModerationAction         | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | NewsroomSection          | get                             | denied, or returns nothing of "beta"                                  |
      | NewsroomSection          | list                            | no row of "beta" is returned and pages are not short                  |
      | NewsroomSection          | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | NewsroomSection          | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | NewsroomSection          | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | NewsroomSection          | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | NewsroomSection          | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ProcedureDefinition      | get                             | denied, or returns nothing of "beta"                                  |
      | ProcedureDefinition      | list                            | no row of "beta" is returned and pages are not short                  |
      | ProcedureDefinition      | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | ProcedureDefinition      | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | ProcedureDefinition      | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | ProcedureDefinition      | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ProcedureDefinition      | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ProcedureRun             | get                             | denied, or returns nothing of "beta"                                  |
      | ProcedureRun             | list                            | no row of "beta" is returned and pages are not short                  |
      | ProcedureRun             | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | ProcedureRun             | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | ProcedureRun             | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | ProcedureRun             | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ProcedureRun             | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ProcedureVersion         | get                             | denied, or returns nothing of "beta"                                  |
      | ProcedureVersion         | list                            | no row of "beta" is returned and pages are not short                  |
      | ProcedureVersion         | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | ProcedureVersion         | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | ProcedureVersion         | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | ProcedureVersion         | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ProcedureVersion         | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | Proposal                 | get                             | denied, or returns nothing of "beta"                                  |
      | Proposal                 | list                            | no row of "beta" is returned and pages are not short                  |
      | Proposal                 | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | Proposal                 | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | Proposal                 | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | Proposal                 | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | Proposal                 | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | PublicHandleClaim        | get                             | reviewed: PublicHandleClaim is global and holds no tenant data        |
      | PublicHandleClaim        | list                            | reviewed: PublicHandleClaim is global and holds no tenant data        |
      | PublicHandleClaim        | create                          | reviewed: only the rule's own principals may create PublicHandleClaim |
      | PublicHandleClaim        | update                          | reviewed: only the rule's own principals may update PublicHandleClaim |
      | PublicHandleClaim        | delete                          | reviewed: only the rule's own principals may delete PublicHandleClaim |
      | PublishedCategory        | get                             | denied, or returns nothing of "beta"                                  |
      | PublishedCategory        | list                            | no row of "beta" is returned and pages are not short                  |
      | PublishedCategory        | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | PublishedCategory        | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | PublishedCategory        | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | PublishedCategory        | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | PublishedCategory        | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | PublishedCategorySet     | get                             | denied, or returns nothing of "beta"                                  |
      | PublishedCategorySet     | list                            | no row of "beta" is returned and pages are not short                  |
      | PublishedCategorySet     | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | PublishedCategorySet     | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | PublishedCategorySet     | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | PublishedCategorySet     | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | PublishedCategorySet     | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | PublishedEdition         | get                             | denied, or returns nothing of "beta"                                  |
      | PublishedEdition         | list                            | no row of "beta" is returned and pages are not short                  |
      | PublishedEdition         | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | PublishedEdition         | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | PublishedEdition         | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | PublishedEdition         | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | PublishedEdition         | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | PublishedEditionItem     | get                             | denied, or returns nothing of "beta"                                  |
      | PublishedEditionItem     | list                            | no row of "beta" is returned and pages are not short                  |
      | PublishedEditionItem     | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | PublishedEditionItem     | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | PublishedEditionItem     | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | PublishedEditionItem     | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | PublishedEditionItem     | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | PublishedItem            | get                             | denied, or returns nothing of "beta"                                  |
      | PublishedItem            | list                            | no row of "beta" is returned and pages are not short                  |
      | PublishedItem            | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | PublishedItem            | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | PublishedItem            | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | PublishedItem            | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | PublishedItem            | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | PublishedMediaAsset      | get                             | denied, or returns nothing of "beta"                                  |
      | PublishedMediaAsset      | list                            | no row of "beta" is returned and pages are not short                  |
      | PublishedMediaAsset      | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | PublishedMediaAsset      | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | PublishedMediaAsset      | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | PublishedMediaAsset      | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | PublishedMediaAsset      | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReaderComment            | get                             | denied, or returns nothing of "beta"                                  |
      | ReaderComment            | list                            | no row of "beta" is returned and pages are not short                  |
      | ReaderComment            | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | ReaderComment            | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | ReaderComment            | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | ReaderComment            | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReaderComment            | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReaderFlag               | get                             | denied, or returns nothing of "beta"                                  |
      | ReaderFlag               | list                            | no row of "beta" is returned and pages are not short                  |
      | ReaderFlag               | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | ReaderFlag               | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | ReaderFlag               | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | ReaderFlag               | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReaderFlag               | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReaderHandle             | get                             | denied, or returns nothing of "beta"                                  |
      | ReaderHandle             | list                            | no row of "beta" is returned and pages are not short                  |
      | ReaderHandle             | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | ReaderHandle             | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | ReaderHandle             | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | ReaderHandle             | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReaderHandle             | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReaderProfile            | get                             | denied, or returns nothing of "beta"                                  |
      | ReaderProfile            | list                            | no row of "beta" is returned and pages are not short                  |
      | ReaderProfile            | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | ReaderProfile            | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | ReaderProfile            | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | ReaderProfile            | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReaderProfile            | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReaderReport             | get                             | denied, or returns nothing of "beta"                                  |
      | ReaderReport             | list                            | no row of "beta" is returned and pages are not short                  |
      | ReaderReport             | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | ReaderReport             | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | ReaderReport             | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | ReaderReport             | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReaderReport             | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReaderSubmission         | get                             | denied, or returns nothing of "beta"                                  |
      | ReaderSubmission         | list                            | no row of "beta" is returned and pages are not short                  |
      | ReaderSubmission         | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | ReaderSubmission         | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | ReaderSubmission         | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | ReaderSubmission         | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReaderSubmission         | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReaderVote               | get                             | denied, or returns nothing of "beta"                                  |
      | ReaderVote               | list                            | no row of "beta" is returned and pages are not short                  |
      | ReaderVote               | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | ReaderVote               | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | ReaderVote               | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | ReaderVote               | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReaderVote               | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | Reference                | get                             | denied, or returns nothing of "beta"                                  |
      | Reference                | list                            | no row of "beta" is returned and pages are not short                  |
      | Reference                | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | Reference                | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | Reference                | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | Reference                | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | Reference                | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReferenceAttachment      | get                             | denied, or returns nothing of "beta"                                  |
      | ReferenceAttachment      | list                            | no row of "beta" is returned and pages are not short                  |
      | ReferenceAttachment      | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | ReferenceAttachment      | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | ReferenceAttachment      | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | ReferenceAttachment      | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReferenceAttachment      | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReviewReadMark           | get                             | denied, or returns nothing of "beta"                                  |
      | ReviewReadMark           | list                            | no row of "beta" is returned and pages are not short                  |
      | ReviewReadMark           | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | ReviewReadMark           | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | ReviewReadMark           | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | ReviewReadMark           | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReviewReadMark           | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReviewRecipientRule      | get                             | denied, or returns nothing of "beta"                                  |
      | ReviewRecipientRule      | list                            | no row of "beta" is returned and pages are not short                  |
      | ReviewRecipientRule      | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | ReviewRecipientRule      | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | ReviewRecipientRule      | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | ReviewRecipientRule      | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReviewRecipientRule      | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReviewRequest            | get                             | denied, or returns nothing of "beta"                                  |
      | ReviewRequest            | list                            | no row of "beta" is returned and pages are not short                  |
      | ReviewRequest            | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | ReviewRequest            | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | ReviewRequest            | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | ReviewRequest            | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | ReviewRequest            | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | SemanticNode             | get                             | denied, or returns nothing of "beta"                                  |
      | SemanticNode             | list                            | no row of "beta" is returned and pages are not short                  |
      | SemanticNode             | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | SemanticNode             | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | SemanticNode             | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | SemanticNode             | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | SemanticNode             | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | SemanticRelation         | get                             | denied, or returns nothing of "beta"                                  |
      | SemanticRelation         | list                            | no row of "beta" is returned and pages are not short                  |
      | SemanticRelation         | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | SemanticRelation         | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | SemanticRelation         | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | SemanticRelation         | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | SemanticRelation         | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | SemanticRelationType     | get                             | denied, or returns nothing of "beta"                                  |
      | SemanticRelationType     | list                            | no row of "beta" is returned and pages are not short                  |
      | SemanticRelationType     | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | SemanticRelationType     | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | SemanticRelationType     | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | SemanticRelationType     | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | SemanticRelationType     | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | SignupEntry              | get                             | denied, or returns nothing of "beta"                                  |
      | SignupEntry              | list                            | no row of "beta" is returned and pages are not short                  |
      | SignupEntry              | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | SignupEntry              | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | SignupEntry              | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | SignupEntry              | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | SignupEntry              | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | SteeringDecision         | get                             | denied, or returns nothing of "beta"                                  |
      | SteeringDecision         | list                            | no row of "beta" is returned and pages are not short                  |
      | SteeringDecision         | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | SteeringDecision         | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | SteeringDecision         | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | SteeringDecision         | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | SteeringDecision         | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | SteeringProposal         | get                             | denied, or returns nothing of "beta"                                  |
      | SteeringProposal         | list                            | no row of "beta" is returned and pages are not short                  |
      | SteeringProposal         | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | SteeringProposal         | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | SteeringProposal         | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | SteeringProposal         | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | SteeringProposal         | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | StoryVariation           | get                             | denied, or returns nothing of "beta"                                  |
      | StoryVariation           | list                            | no row of "beta" is returned and pages are not short                  |
      | StoryVariation           | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | StoryVariation           | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | StoryVariation           | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | StoryVariation           | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | StoryVariation           | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | Tag                      | get                             | denied, or returns nothing of "beta"                                  |
      | Tag                      | list                            | no row of "beta" is returned and pages are not short                  |
      | Tag                      | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | Tag                      | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | Tag                      | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | Tag                      | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | Tag                      | delete-foreign-row              | denied, or returns nothing of "beta"                                  |
      | UserIdentity             | get                             | reviewed: UserIdentity is global and holds no tenant data             |
      | UserIdentity             | list                            | reviewed: UserIdentity is global and holds no tenant data             |
      | UserIdentity             | create                          | reviewed: only the rule's own principals may create UserIdentity      |
      | UserIdentity             | update                          | reviewed: only the rule's own principals may update UserIdentity      |
      | UserIdentity             | delete                          | reviewed: only the rule's own principals may delete UserIdentity      |
      | UserProfile              | get                             | reviewed: UserProfile is global and holds no tenant data              |
      | UserProfile              | list                            | reviewed: UserProfile is global and holds no tenant data              |
      | UserProfile              | create                          | reviewed: only the rule's own principals may create UserProfile       |
      | UserProfile              | update                          | reviewed: only the rule's own principals may update UserProfile       |
      | UserProfile              | delete                          | reviewed: only the rule's own principals may delete UserProfile       |
      | UserRoleAssignment       | get                             | denied, or returns nothing of "beta"                                  |
      | UserRoleAssignment       | list                            | no row of "beta" is returned and pages are not short                  |
      | UserRoleAssignment       | list-filtered-to-foreign-tenant | denied, or returns nothing of "beta"                                  |
      | UserRoleAssignment       | create-with-foreign-tenantId    | denied, or returns nothing of "beta"                                  |
      | UserRoleAssignment       | update-to-foreign-tenantId      | denied, or returns nothing of "beta"                                  |
      | UserRoleAssignment       | update-foreign-row              | denied, or returns nothing of "beta"                                  |
      | UserRoleAssignment       | delete-foreign-row              | denied, or returns nothing of "beta"                                  |

  @isolation-pending
  Scenario Outline: Tenant A cannot read tenant B through any index
    Given editor sessions for "alpha" and "beta" on the shared stack
    When the "alpha" session calls <query> at one of "beta"'s keys
    Then it is denied or returns nothing of "beta"

    Examples: generated from the schema
      | query                                                | outcome                          |
      | listAssignmentsByTypeStatusAndCreatedAt              | returns nothing of "beta"        |
      | listAssignmentsByQueueStatusAndPriority              | returns nothing of "beta"        |
      | listAssignmentsByStatusAndUpdatedAt                  | returns nothing of "beta"        |
      | listAssignmentsByAssigneeStatusAndUpdatedAt          | returns nothing of "beta"        |
      | listAssignmentsBySectionAndCreatedAt                 | returns nothing of "beta"        |
      | listAssignmentsBySectionStatusAndPriority            | returns nothing of "beta"        |
      | listAssignmentsBySectionQueueStatusAndPriority       | returns nothing of "beta"        |
      | listAssignmentsByImportRunAndCreatedAt               | returns nothing of "beta"        |
      | listAssignmentsByNewsroomFeedAndCreatedAt            | returns nothing of "beta"        |
      | listAssignmentsByItemLineageAndCreatedAt             | returns nothing of "beta"        |
      | listAssignmentEventsByAssignmentAndCreatedAt         | returns nothing of "beta"        |
      | listAssignmentEventsByQueueAndCreatedAt              | returns nothing of "beta"        |
      | listAssignmentEventsByTypeAndCreatedAt               | returns nothing of "beta"        |
      | listCategoriesByLineageAndVersion                    | returns nothing of "beta"        |
      | listCategoriesBySetAndKey                            | returns nothing of "beta"        |
      | listCategoriesByCorpusAndName                        | returns nothing of "beta"        |
      | listCategoriesByParentAndRank                        | returns nothing of "beta"        |
      | listCategoriesByParentKeyAndRank                     | returns nothing of "beta"        |
      | listCategoriesByStatusAndName                        | returns nothing of "beta"        |
      | listCategoryKeywordsBySetKeyAndRank                  | returns nothing of "beta"        |
      | listCategoryKeywordsByCategoryKeyAndRank             | returns nothing of "beta"        |
      | listCategoryKeywordsByNormalizedKeywordAndSet        | returns nothing of "beta"        |
      | listCategoryKeywordsByImportRunAndRank               | returns nothing of "beta"        |
      | listCategorySetsByLineageAndVersion                  | returns nothing of "beta"        |
      | listCategorySetsByVersionStateAndGeneratedAt         | returns nothing of "beta"        |
      | listCategorySetsByCorpusAndClassifier                | returns nothing of "beta"        |
      | listCategorySetsByStatusAndName                      | returns nothing of "beta"        |
      | listCurationDelegationRecordsByGrantor               | returns nothing of "beta"        |
      | listEditionsByLineageAndVersion                      | returns nothing of "beta"        |
      | listEditionsByVersionStateAndPublishedAt             | returns nothing of "beta"        |
      | editionBySlug                                        | returns nothing of "beta"        |
      | listEditionsByStatusAndEditionDate                   | returns nothing of "beta"        |
      | listEditionsByStatusAndPublishedAt                   | returns nothing of "beta"        |
      | listEditionItemsByEditionAndSortKey                  | returns nothing of "beta"        |
      | listEditionItemsByItemAndEdition                     | returns nothing of "beta"        |
      | listEditorialCheckRunsByLineage                      | returns nothing of "beta"        |
      | listEditorialFeedbackByItem                          | returns nothing of "beta"        |
      | listItemsByLineageAndVersion                         | returns nothing of "beta"        |
      | listItemsByVersionStateAndUpdatedAt                  | returns nothing of "beta"        |
      | listItemsByStageAndUpdatedAt                         | returns nothing of "beta"        |
      | listItemsByTypeStatusAndPublishedAt                  | returns nothing of "beta"        |
      | itemBySlug                                           | returns nothing of "beta"        |
      | itemByTenantSlug                                     | returns nothing of "beta"        |
      | listItemsBySectionStatusAndPublishedAt               | returns nothing of "beta"        |
      | listItemsByParentAndOrder                            | returns nothing of "beta"        |
      | listItemsByHeadStageAndUpdatedAt                     | returns nothing of "beta"        |
      | listItemTagsByItemAndTag                             | returns nothing of "beta"        |
      | listItemTagsByTagAndPublishedAt                      | returns nothing of "beta"        |
      | listKnowledgeArtifactsByCorpusAndKind                | returns nothing of "beta"        |
      | listKnowledgeArtifactsByKindAndCreatedAt             | returns nothing of "beta"        |
      | listKnowledgeArtifactsByImportRunAndKind             | returns nothing of "beta"        |
      | listKnowledgeCorporaByRoleAndName                    | returns nothing of "beta"        |
      | listKnowledgeImportRunsByCorpusAndImportedAt         | returns nothing of "beta"        |
      | listKnowledgeImportRunsByKindAndImportedAt           | returns nothing of "beta"        |
      | listKnowledgeImportRunsByCorpusKindAndImportedAt     | returns nothing of "beta"        |
      | listKnowledgeRawPayloadsByOwnerAndKind               | returns nothing of "beta"        |
      | listKnowledgeRawPayloadsByImportRunAndOwner          | returns nothing of "beta"        |
      | listLexicalSteeringRulesByScopeAndTerm               | returns nothing of "beta"        |
      | listLexicalSteeringRulesByStatusAndTerm              | returns nothing of "beta"        |
      | listLexicalSteeringRulesByCorpusAndTerm              | returns nothing of "beta"        |
      | listLexicalSteeringRulesBySetAndTerm                 | returns nothing of "beta"        |
      | listMediaAssetsByItemAndSortKey                      | returns nothing of "beta"        |
      | listMediaAssetsByRoleAndItem                         | returns nothing of "beta"        |
      | listMessagesByKindAndCreatedAt                       | returns nothing of "beta"        |
      | listMessagesByDomainAndCreatedAt                     | returns nothing of "beta"        |
      | listMessagesByStatusAndCreatedAt                     | returns nothing of "beta"        |
      | listMessagesByImportRunAndCreatedAt                  | returns nothing of "beta"        |
      | listMessagesByAuthorSubAndCreatedAt                  | returns nothing of "beta"        |
      | listMessagesByAuthorProfileAndCreatedAt              | returns nothing of "beta"        |
      | listMessagesByThreadAndSequence                      | returns nothing of "beta"        |
      | listMessagesByThreadAndCreatedAt                     | returns nothing of "beta"        |
      | listMessagesBySemanticLayerAndCreatedAt              | returns nothing of "beta"        |
      | listMessagesBySearchVisibilityAndCreatedAt           | returns nothing of "beta"        |
      | listMessagesByResponseTargetStatusAndCreatedAt       | returns nothing of "beta"        |
      | listMessagesByNewsroomFeedAndCreatedAt               | returns nothing of "beta"        |
      | listMessageThreadsByKindAndUpdatedAt                 | returns nothing of "beta"        |
      | listMessageThreadsByStatusAndUpdatedAt               | returns nothing of "beta"        |
      | listMessageThreadsByAnchorAndUpdatedAt               | returns nothing of "beta"        |
      | listMessageThreadsByCreatorAndUpdatedAt              | returns nothing of "beta"        |
      | listMessageThreadsByNewsroomFeedAndUpdatedAt         | returns nothing of "beta"        |
      | listModelAttachmentsByOwnerRoleAndSortKey            | returns nothing of "beta"        |
      | listModelAttachmentsByOwnerVersionRoleAndSortKey     | returns nothing of "beta"        |
      | listModelAttachmentsByRoleStatusAndCreatedAt         | returns nothing of "beta"        |
      | modelAttachmentByStoragePath                         | returns nothing of "beta"        |
      | listModelAttachmentsByImportRunKindAndRole           | returns nothing of "beta"        |
      | listModerationActionsByTargetAndAt                   | returns nothing of "beta"        |
      | listNewsroomSectionsByTenantAndSortOrder             | returns nothing of "beta"        |
      | listNewsroomSectionsByTypeAndSortOrder               | returns nothing of "beta"        |
      | listNewsroomSectionsByEnabledStatusAndSortOrder      | returns nothing of "beta"        |
      | listNewsroomSectionsBySortOrder                      | returns nothing of "beta"        |
      | listProcedureDefinitionsByKeyAndUpdatedAt            | returns nothing of "beta"        |
      | listProcedureDefinitionsByEnabledAndUpdatedAt        | returns nothing of "beta"        |
      | listProcedureDefinitionsByFeedAndUpdatedAt           | returns nothing of "beta"        |
      | listProcedureRunsByProcedureAndRequestedAt           | returns nothing of "beta"        |
      | listProcedureRunsByAssignmentAndRequestedAt          | returns nothing of "beta"        |
      | listProcedureRunsByStatusAndRequestedAt              | returns nothing of "beta"        |
      | listProcedureRunsByFeedAndRequestedAt                | returns nothing of "beta"        |
      | listProcedureVersionsByProcedureAndVersion           | returns nothing of "beta"        |
      | listProcedureVersionsByProcedureAndCreatedAt         | returns nothing of "beta"        |
      | listProcedureVersionsByStatusAndUpdatedAt            | returns nothing of "beta"        |
      | listProposalsByStateAndCreatedAt                     | returns nothing of "beta"        |
      | listPublishedCategoriesBySetAndKey                   | returns nothing of "beta"        |
      | listPublishedCategoriesByKeyAndSet                   | returns nothing of "beta"        |
      | listPublishedCategoriesByParentAndRank               | returns nothing of "beta"        |
      | listPublishedCategoriesByParentKeyAndRank            | returns nothing of "beta"        |
      | listPublishedCategorySetsByLineageAndVersion         | returns nothing of "beta"        |
      | listPublishedCategorySetsByClassifierAndName         | returns nothing of "beta"        |
      | listPublishedCategorySetsByStatusAndName             | returns nothing of "beta"        |
      | listPublishedEditionsByLineageAndVersion             | returns nothing of "beta"        |
      | publishedEditionBySlug                               | returns nothing of "beta"        |
      | listPublishedEditionsByStatusAndEditionDate          | returns nothing of "beta"        |
      | listPublishedEditionsByStatusAndPublishedAt          | returns nothing of "beta"        |
      | listPublishedEditionItemsByEditionAndSortKey         | returns nothing of "beta"        |
      | listPublishedEditionItemsByItemAndEdition            | returns nothing of "beta"        |
      | listPublishedItemsByLineageAndVersion                | returns nothing of "beta"        |
      | listPublishedItemsByTypeStatusAndPublishedAt         | returns nothing of "beta"        |
      | publishedItemBySlug                                  | returns nothing of "beta"        |
      | publishedItemByTenantSlug                            | returns nothing of "beta"        |
      | listPublishedItemsBySectionStatusAndPublishedAt      | returns nothing of "beta"        |
      | listPublishedMediaAssetsByItemAndSortKey             | returns nothing of "beta"        |
      | listPublishedMediaAssetsByRoleAndItem                | returns nothing of "beta"        |
      | listReaderCommentsByModerationAndCreatedAt           | returns nothing of "beta"        |
      | listReaderProfilesByReader                           | returns nothing of "beta"        |
      | listReaderReportsByTargetAndCreatedAt                | returns nothing of "beta"        |
      | listReaderSubmissionsByDomainAndCreatedAt            | returns nothing of "beta"        |
      | listReaderSubmissionsByModerationAndCreatedAt        | returns nothing of "beta"        |
      | listReferencesByLineageAndVersion                    | returns nothing of "beta"        |
      | listReferencesByVersionStateAndUpdatedAt             | returns nothing of "beta"        |
      | listReferencesByCorpusAndExternalItem                | returns nothing of "beta"        |
      | listReferencesByImportRunAndExternalItem             | returns nothing of "beta"        |
      | listReferencesByCurationStatusAndUpdatedAt           | returns nothing of "beta"        |
      | listReferencesByCurationStatusKeyAndUpdatedAt        | returns nothing of "beta"        |
      | listReferencesByNewsroomFeedAndCreatedAt             | returns nothing of "beta"        |
      | listReferencesByNewsroomFeedAndImportedAt            | returns nothing of "beta"        |
      | listReferencesByReviewedFeedAndUpdatedAt             | returns nothing of "beta"        |
      | listReferencesByMonitorAndCreatedAt                  | returns nothing of "beta"        |
      | listReferencesByFeedStateAndPrediction               | returns nothing of "beta"        |
      | listReferencesByFeedStateAndArrival                  | returns nothing of "beta"        |
      | listReferencesByStarFeedAndArrival                   | returns nothing of "beta"        |
      | listReferencesByMediumFeedAndArrival                 | returns nothing of "beta"        |
      | listReferencesByContentNeededAndArrival              | returns nothing of "beta"        |
      | listReferenceAttachmentsByReferenceLineageAndSortKey | returns nothing of "beta"        |
      | listReferenceAttachmentsByReferenceVersionAndSortKey | returns nothing of "beta"        |
      | referenceAttachmentByStoragePath                     | returns nothing of "beta"        |
      | listReferenceAttachmentsByImportRunAndSortKey        | returns nothing of "beta"        |
      | listSemanticNodesByLineageAndVersion                 | returns nothing of "beta"        |
      | listSemanticNodesByVersionStateAndUpdatedAt          | returns nothing of "beta"        |
      | listSemanticNodesByNodeKeyAndVersion                 | returns nothing of "beta"        |
      | listSemanticNodesByCorpusAndNodeKey                  | returns nothing of "beta"        |
      | listSemanticNodesByImportRunAndNodeKey               | returns nothing of "beta"        |
      | listSemanticNodesByNewsroomFeedAndCreatedAt          | returns nothing of "beta"        |
      | listSemanticRelationsByTypeAndImportedAt             | returns nothing of "beta"        |
      | listSemanticRelationsByDomainAndImportedAt           | returns nothing of "beta"        |
      | listSemanticRelationsBySubjectState                  | returns nothing of "beta"        |
      | listSemanticRelationsByObjectState                   | returns nothing of "beta"        |
      | listSemanticRelationsByObjectSubjectStateAndScore    | returns nothing of "beta"        |
      | listSemanticRelationsByPredicateObjectStateAndScore  | returns nothing of "beta"        |
      | listSemanticRelationsBySubjectVersion                | returns nothing of "beta"        |
      | listSemanticRelationsByImportRunAndImportedAt        | returns nothing of "beta"        |
      | listSemanticRelationsByNewsroomFeedAndCreatedAt      | returns nothing of "beta"        |
      | semanticRelationTypeByKey                            | returns nothing of "beta"        |
      | listSemanticRelationTypesByDomainAndLabel            | returns nothing of "beta"        |
      | listSemanticRelationTypesByStatusAndLabel            | returns nothing of "beta"        |
      | listSignupEntriesByFormAndSubmittedAt                | returns nothing of "beta"        |
      | listSteeringDecisionsByProposalAndCreatedAt          | returns nothing of "beta"        |
      | listSteeringDecisionsBySetAndCreatedAt               | returns nothing of "beta"        |
      | listSteeringProposalsBySetAndStatus                  | returns nothing of "beta"        |
      | listSteeringProposalsByCorpusAndKind                 | returns nothing of "beta"        |
      | listSteeringProposalsByDomainAndStatus               | returns nothing of "beta"        |
      | listSteeringProposalsByStatusAndProposedAt           | returns nothing of "beta"        |
      | listStoryVariationsByStoryAndNumber                  | returns nothing of "beta"        |
      | tagBySlug                                            | returns nothing of "beta"        |
      | listTagsByTypeAndLabel                               | returns nothing of "beta"        |
      | listUserIdentitiesByProfileAndLinkedAt               | reviewed: UserIdentity is global |
      | userIdentityByCognitoSub                             | reviewed: UserIdentity is global |
      | listUserIdentitiesByEmailAndStatus                   | reviewed: UserIdentity is global |
      | userProfileByPublicHandle                            | reviewed: UserProfile is global  |
      | listUserRoleAssignmentsByProfileAndRole              | returns nothing of "beta"        |
      | listUserRoleAssignmentsByUserAndRole                 | returns nothing of "beta"        |
      | listUserRoleAssignmentsByRoleAndStatus               | returns nothing of "beta"        |

  @isolation-pending
  Scenario Outline: Tenant A receives no event of tenant B
    Given editor sessions for "alpha" and "beta" on the shared stack
    When the "alpha" session subscribes to <event> on <model> while "beta" writes
    Then it is denied or returns nothing of "beta"

    Examples: generated from the schema
      | model         | event    | outcome                           |
      | Message       | onCreate | alpha receives no event of "beta" |
      | Message       | onUpdate | alpha receives no event of "beta" |
      | Message       | onDelete | alpha receives no event of "beta" |
      | MessageThread | onCreate | alpha receives no event of "beta" |
      | MessageThread | onUpdate | alpha receives no event of "beta" |
      | MessageThread | onDelete | alpha receives no event of "beta" |
      | Reference     | onCreate | alpha receives no event of "beta" |
      | Reference     | onUpdate | alpha receives no event of "beta" |
      | Reference     | onDelete | alpha receives no event of "beta" |

  @isolation-pending
  Scenario Outline: Tenant A cannot use a custom query or mutation on tenant B
    Given editor sessions for "alpha" and "beta" on the shared stack
    When the "alpha" session calls <operation> with "beta"'s ids
    Then it is denied or returns nothing of "beta"

    Examples: generated from the schema
      | operation                            | outcome                              |
      | abortModelAttachmentUpload           | denied, or returns nothing of "beta" |
      | addStoryAgentNote                    | denied, or returns nothing of "beta" |
      | applyKnowledgeReview                 | denied, or returns nothing of "beta" |
      | approveCurationDelegation            | denied, or returns nothing of "beta" |
      | archiveDraftCategory                 | denied, or returns nothing of "beta" |
      | automationOverview                   | denied, or returns nothing of "beta" |
      | cancelAssignment                     | denied, or returns nothing of "beta" |
      | checkEditorial                       | denied, or returns nothing of "beta" |
      | checkItemVersion                     | denied, or returns nothing of "beta" |
      | claimAssignment                      | denied, or returns nothing of "beta" |
      | completeAssignment                   | denied, or returns nothing of "beta" |
      | completeModelAttachmentUpload        | denied, or returns nothing of "beta" |
      | correctReferenceCapture              | denied, or returns nothing of "beta" |
      | createCategorySetDraft               | denied, or returns nothing of "beta" |
      | createConceptLink                    | denied, or returns nothing of "beta" |
      | createCurationDelegation             | denied, or returns nothing of "beta" |
      | createDraftCategory                  | denied, or returns nothing of "beta" |
      | createEditorConcept                  | denied, or returns nothing of "beta" |
      | createModelAttachmentDownload        | denied, or returns nothing of "beta" |
      | createModelAttachmentUpload          | denied, or returns nothing of "beta" |
      | createReferenceLink                  | denied, or returns nothing of "beta" |
      | createStoryFromReference             | denied, or returns nothing of "beta" |
      | decideReferenceLink                  | denied, or returns nothing of "beta" |
      | deleteOwnMessage                     | denied, or returns nothing of "beta" |
      | denyCurationDelegation               | denied, or returns nothing of "beta" |
      | deriveMarkus                         | denied, or returns nothing of "beta" |
      | describeConcept                      | denied, or returns nothing of "beta" |
      | discardCategorySetDraft              | denied, or returns nothing of "beta" |
      | draftEditorialQuestions              | denied, or returns nothing of "beta" |
      | editMessage                          | denied, or returns nothing of "beta" |
      | editProposal                         | denied, or returns nothing of "beta" |
      | fileProposal                         | denied, or returns nothing of "beta" |
      | getAssignmentContext                 | denied, or returns nothing of "beta" |
      | getCurationDelegationStatus          | denied, or returns nothing of "beta" |
      | getEditorialContext                  | denied, or returns nothing of "beta" |
      | getNewsroomProcedureDefinition       | denied, or returns nothing of "beta" |
      | getNewsroomProcedureRun              | denied, or returns nothing of "beta" |
      | getNewsroomSummary                   | denied, or returns nothing of "beta" |
      | getReaderSettings                    | denied, or returns nothing of "beta" |
      | grantUserRole                        | denied, or returns nothing of "beta" |
      | guidelinesRead                       | denied, or returns nothing of "beta" |
      | guidelinesWrite                      | denied, or returns nothing of "beta" |
      | imageRead                            | denied, or returns nothing of "beta" |
      | imageWrite                           | denied, or returns nothing of "beta" |
      | importEditorialStarterPack           | denied, or returns nothing of "beta" |
      | intakeEmailSubmissionReferences      | denied, or returns nothing of "beta" |
      | intakePendingReferences              | denied, or returns nothing of "beta" |
      | knowledgeQuery                       | denied, or returns nothing of "beta" |
      | linkMessageHashtags                  | denied, or returns nothing of "beta" |
      | listAssignmentQueue                  | denied, or returns nothing of "beta" |
      | listAssignmentsForObject             | denied, or returns nothing of "beta" |
      | listCurationDelegations              | denied, or returns nothing of "beta" |
      | listEditorialStarterPacks            | denied, or returns nothing of "beta" |
      | listNewsroomProcedureDefinitions     | denied, or returns nothing of "beta" |
      | listNewsroomProcedureRunsByProcedure | denied, or returns nothing of "beta" |
      | listStoryDrafts                      | denied, or returns nothing of "beta" |
      | listUserDirectory                    | denied, or returns nothing of "beta" |
      | mergeUserProfiles                    | denied, or returns nothing of "beta" |
      | moderateMessage                      | denied, or returns nothing of "beta" |
      | moderateReader                       | denied, or returns nothing of "beta" |
      | monitoringDecideEmailSubmission      | denied, or returns nothing of "beta" |
      | monitoringEmailSubmission            | denied, or returns nothing of "beta" |
      | monitoringOverview                   | denied, or returns nothing of "beta" |
      | monitoringPage                       | denied, or returns nothing of "beta" |
      | monitoringQueueEmailReference        | denied, or returns nothing of "beta" |
      | monitoringQueueReferencePredictions  | denied, or returns nothing of "beta" |
      | monitoringResolveEmailArticleLink    | denied, or returns nothing of "beta" |
      | moveStoryStage                       | denied, or returns nothing of "beta" |
      | newsletterApproveIssue               | denied, or returns nothing of "beta" |
      | newsletterCancelIssue                | denied, or returns nothing of "beta" |
      | newsletterCreateDraft                | denied, or returns nothing of "beta" |
      | newsletterErase                      | denied, or returns nothing of "beta" |
      | newsletterExport                     | denied, or returns nothing of "beta" |
      | newsletterIssue                      | denied, or returns nothing of "beta" |
      | newsletterIssueDeliveries            | denied, or returns nothing of "beta" |
      | newsletterIssues                     | denied, or returns nothing of "beta" |
      | newsletterOverview                   | denied, or returns nothing of "beta" |
      | newsletterPreview                    | denied, or returns nothing of "beta" |
      | newsletterResume                     | denied, or returns nothing of "beta" |
      | newsletterStopIssue                  | denied, or returns nothing of "beta" |
      | newsletterSubscribers                | denied, or returns nothing of "beta" |
      | newsletterTestSend                   | denied, or returns nothing of "beta" |
      | postMessage                          | denied, or returns nothing of "beta" |
      | promoteCategorySetDraft              | denied, or returns nothing of "beta" |
      | publishItem                          | denied, or returns nothing of "beta" |
      | publishNewsroomProcedureVersion      | denied, or returns nothing of "beta" |
      | recalibrateEditorialPolicies         | denied, or returns nothing of "beta" |
      | recordDelegatedCuration              | denied, or returns nothing of "beta" |
      | recordDelegatedStars                 | denied, or returns nothing of "beta" |
      | refreshSitePages                     | denied, or returns nothing of "beta" |
      | releaseAssignment                    | denied, or returns nothing of "beta" |
      | renameThread                         | denied, or returns nothing of "beta" |
      | reopenAssignment                     | denied, or returns nothing of "beta" |
      | requestCurationDelegation            | denied, or returns nothing of "beta" |
      | requestStagingBuild                  | denied, or returns nothing of "beta" |
      | retryImmediateAssignment             | denied, or returns nothing of "beta" |
      | reviewReferenceCuration              | denied, or returns nothing of "beta" |
      | reviewReferenceTopicLabel            | denied, or returns nothing of "beta" |
      | reviewSteeringProposal               | denied, or returns nothing of "beta" |
      | revokeCurationDelegation             | denied, or returns nothing of "beta" |
      | revokeUserRole                       | denied, or returns nothing of "beta" |
      | runAutomation                        | denied, or returns nothing of "beta" |
      | saveItemDraft                        | denied, or returns nothing of "beta" |
      | saveNewsroomProcedureDefinition      | denied, or returns nothing of "beta" |
      | saveNewsroomProcedureVersionDraft    | denied, or returns nothing of "beta" |
      | searchReferences                     | denied, or returns nothing of "beta" |
      | setItemStars                         | denied, or returns nothing of "beta" |
      | setPublicHandle                      | denied, or returns nothing of "beta" |
      | setReferenceQualityRating            | denied, or returns nothing of "beta" |
      | setReferenceSection                  | denied, or returns nothing of "beta" |
      | setReferenceStars                    | denied, or returns nothing of "beta" |
      | setStoryReferenceRole                | denied, or returns nothing of "beta" |
      | setStoryStep                         | denied, or returns nothing of "beta" |
      | startNewsroomProcedureRun            | denied, or returns nothing of "beta" |
      | submitSignup                         | denied, or returns nothing of "beta" |
      | suggestEditorialRewrite              | denied, or returns nothing of "beta" |
      | suggestReferenceLinks                | denied, or returns nothing of "beta" |
      | transitionProposal                   | denied, or returns nothing of "beta" |
      | tryEditorialPolicy                   | denied, or returns nothing of "beta" |
      | unpublishItem                        | denied, or returns nothing of "beta" |
      | updateDraftCategory                  | denied, or returns nothing of "beta" |
      | updateNewsroomSummary                | denied, or returns nothing of "beta" |
      | updateReaderSettings                 | denied, or returns nothing of "beta" |

  @isolation-pending
  Scenario Outline: Tenant A cannot reach tenant B through any function
    Given editor sessions for "alpha" and "beta" on the shared stack
    When the "alpha" session reaches the <function> function with an event naming "beta"
    Then it is denied or returns nothing of "beta"

    Examples: generated from the schema
      | function                   | outcome                            |
      | alexa/function             | reads and writes nothing of "beta" |
      | assignment-action          | reads and writes nothing of "beta" |
      | automation-view            | reads and writes nothing of "beta" |
      | category-action            | reads and writes nothing of "beta" |
      | cli-login-pages            | reads and writes nothing of "beta" |
      | console-chat-responder     | reads and writes nothing of "beta" |
      | content-actions            | reads and writes nothing of "beta" |
      | editorial-checks           | reads and writes nothing of "beta" |
      | email-submission-processor | reads and writes nothing of "beta" |
      | home-page/function         | reads and writes nothing of "beta" |
      | image-service              | reads and writes nothing of "beta" |
      | knowledge-query            | reads and writes nothing of "beta" |
      | manage-user-role           | reads and writes nothing of "beta" |
      | model-attachment-upload    | reads and writes nothing of "beta" |
      | monitoring-view            | reads and writes nothing of "beta" |
      | newsletter/function        | reads and writes nothing of "beta" |
      | newsletter/ops             | reads and writes nothing of "beta" |
      | newsroom-summary           | reads and writes nothing of "beta" |
      | notifications/function     | reads and writes nothing of "beta" |
      | procedure-action           | reads and writes nothing of "beta" |
      | proposal-actions           | reads and writes nothing of "beta" |
      | public-forms               | reads and writes nothing of "beta" |
      | reader-settings            | reads and writes nothing of "beta" |
      | reader-steering/function   | reads and writes nothing of "beta" |
      | reference-word-index       | reads and writes nothing of "beta" |
      | renditions                 | reads and writes nothing of "beta" |
      | ses-inbound-receive        | reads and writes nothing of "beta" |
      | signup/function            | reads and writes nothing of "beta" |
      | slack-delivery             | reads and writes nothing of "beta" |
      | slack-events               | reads and writes nothing of "beta" |

  @isolation-pending
  Scenario Outline: Tenant A cannot reach tenant B outside the data API
    Given editor sessions for "alpha" and "beta" on the shared stack
    When the "alpha" session tries <surface>
    Then it is denied or returns nothing of "beta"

    Examples: generated from the schema
      | surface                 | outcome              |
      | s3-presign-foreign-key  | refused              |
      | s3-identity-pool-direct | denied               |
      | s3-rendition-paths      | refused              |
      | knowledge-search        | no hit of beta       |
      | projection-outputs      | no foreign rows      |
      | edge-host-spoofing      | never beta's content |
      | reader-api              | refused or empty     |
      | exports                 | nothing of beta      |
      | cli-foreign-tenant      | refused              |
  # END GENERATED CASES
