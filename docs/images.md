# Images

Every image action is one operation in one table, `src/papyrus_content/images/operations.py`. The `papyrus images` commands, the `image_*` MCP tools, the newsroom's TypeScript types,
the `image-work` skill's reference and this page are generated from it, so they cannot disagree. The design is in `project/wiki/image-toolchain.md`.

**Adding or changing an operation:** edit the table, then run `python scripts/generate-image-operations.py`. A test fails when a generated file is out of date.

Operations are built one step at a time. The five style profile operations (`image_profile_get`, `image_profile_resolve`, `image_profile_diff`, `image_profile_save`, `image_profile_history`) are built:
they read and save the publication's visual style profile and resolve it for a Story ([image style profiles](image-style-profiles.md)). The rest still answer `not_implemented`; later build steps fill them in.
Example add and remove are step 3. The newsroom and MCP reach the same operations through the `imageRead` and `imageWrite` fields of the `image-service` function; see [image style profiles](image-style-profiles.md#the-door-the-image-service-function).

On the command line the profile operations run on the signed-in lane (`papyrus login`): each call acts as the person who signed in, so the backend applies their own rights.
An agent (`PAPYRUS_ACTOR_KIND=agent`) may save a style document but not change a binding constraint, which needs a person who is an admin.

<!-- generated:image-operations -->
<!-- Generated from src/papyrus_content/images/operations.py. Do not edit by hand; run scripts/generate-image-operations.py. -->

## Operations

| Operation (MCP tool) | Command | Effect | What it does |
| --- | --- | --- | --- |
| [`image_profile_get`](#image-profile-get) | `papyrus images profile get` | read | Read the publication's visual style profile, the current version or an older one. |
| [`image_profile_resolve`](#image-profile-resolve) | `papyrus images profile resolve` | read | Show the style that would apply to a Story, section and use, with the layer every field came from. |
| [`image_profile_diff`](#image-profile-diff) | `papyrus images profile diff` | read | Show what saving a style document would change, without saving it. |
| [`image_profile_save`](#image-profile-save) | `papyrus images profile save` | write | Save a style document as a new profile version. |
| [`image_profile_history`](#image-profile-history) | `papyrus images profile history` | read | List the profile's versions, newest first, with who changed it and why. |
| [`image_profile_init`](#image-profile-init) | `papyrus images profile init` | read | Draft a starting style document from the site's brand, for an editor to correct and save. Saves nothing. |
| [`image_profile_example_add`](#image-profile-example-add) | `papyrus images profile example add` | write | Add an example or an avoid-this picture to the profile, as a new version. |
| [`image_profile_example_remove`](#image-profile-example-remove) | `papyrus images profile example remove` | write | Remove an example picture from the profile, as a new version. |
| [`image_capabilities`](#image-capabilities) | `papyrus images capabilities` | read | Say which image models this site can use and whether spending is approved. |
| [`image_brief_draft`](#image-brief-draft) | `papyrus images brief` | read | Work out a starting brief and stock search from a Story's title and deck. |
| [`image_prompt_preview`](#image-prompt-preview) | `papyrus images prompt` | read | Show exactly what would be asked of the image model, and what it would cost, without making anything. |
| [`image_search`](#image-search) | `papyrus images search` | read | Find stock pictures for a Story, four at a time. |
| [`image_generate`](#image-generate) | `papyrus images generate` | spend | Make pictures from a brief in the publication's style. The pictures arrive later. |
| [`image_figure_add`](#image-figure-add) | `papyrus images figure add` | write | Record a figure drawn with the publication's figure system as a picture to preview, review and apply. It draws and generates nothing. |
| [`image_round_get`](#image-round-get) | `papyrus images round` | read | Read a round of pictures and say whether they are all done. |
| [`image_candidate_get`](#image-candidate-get) | `papyrus images show` | read | Read one picture's full record, with a short-lived preview address. |
| [`image_list`](#image-list) | `papyrus images list` | read | List the rounds and pictures made for a Story or Reference, newest first. |
| [`image_retry`](#image-retry) | `papyrus images retry` | spend | Make a new picture to replace one that failed. The ones that worked stay. |
| [`image_iterate`](#image-iterate) | `papyrus images iterate` | spend | Make new pictures from one you have, with an instruction such as 'less busy'. |
| [`image_select`](#image-select) | `papyrus images select` | write | Record a picture as the pick. It changes no Story and is not approval. |
| [`image_unapply`](#image-unapply) | `papyrus images unapply` | write | Undo an applied picture: the Story gets a new version with the old cover or the placeholder back. |
| [`image_review`](#image-review) | `papyrus images review` | write | Keep or remove a picture that was added without a person looking at it. Only a person may. |
| [`image_review_queue`](#image-review-queue) | `papyrus images review-queue` | read | List the pictures that were added without a person, oldest first. |
| [`image_apply`](#image-apply) | `papyrus images apply` | write | Put a picture on a Story: copy it into the site's media and record where it came from. It never publishes. |
| [`image_discard`](#image-discard) | `papyrus images discard` | write | Reject a picture, or a whole round (which keeps the placeholder). The private file is deleted; the record stays. |

Effect: `read` changes nothing; `write` changes records; `spend` asks an image provider to make something, which costs money and only works when the site's image generation is configured and approved. Every operation needs an editor or admin of the site; readers get none.

## Results and errors

Every call returns one envelope. Success: `{"ok": true, "op", "publication", "result", "warnings"}`. Failure: `{"ok": false, "op", "error": {"code", "message", "retryable", "details"}}`.

The commands print the envelope as JSON and exit 0 on success and 2 on any error. `--dry-run` on a write or spend command checks the input and prints it back as `{"dryRun": true, "input": ...}` in the result without calling anything. `--input-file PATH` gives the whole input as JSON; flags override it. A command is run as a person unless `PAPYRUS_ACTOR_KIND=agent` is set; an agent may not call person-only operations and gets one picture, not a set.

Every operation may return `invalid_input`, `not_authorized`, `service_unavailable`, `not_implemented`.

| Code | Meaning | Retry? | Details |
| --- | --- | --- | --- |
| `invalid_input` | The request does not fit the operation's input. | no | path names the field |
| `unknown_operation` | There is no image operation by that name. | no | operation, or command for the CLI |
| `not_implemented` | This operation is described but not built yet. | no | operation |
| `not_authorized` | You are not an editor or admin of this site, or the grant lacks the permission. | no |  |
| `human_required` | A person has to do this one; an agent may not. | no |  |
| `set_needs_person` | A set of several pictures is for a person choosing. Unattended work gets one picture. | no |  |
| `not_found` | No such Story, Reference, round or picture in this publication. | no |  |
| `constraint_conflict` | The request asks for something one of the publication's rules forbids. | no | the constraint |
| `image_type_required` | This request has to name an image type: an inline picture, or a use with no default, did not. | no | choices lists the publication's image types for that use, with their descriptions |
| `image_type_unknown` | There is no such image type in this publication's profile, or it has been retired. | no | choices lists the publication's image types for that use, with their descriptions |
| `source_not_allowed` | This image type does not allow that way of getting a picture. | no | allowed lists the type's sources in order, and where their rules live |
| `checks_failed` | A check failed, so the picture cannot be applied. | no | checks lists which |
| `generation_not_configured` | No approved image model is set up for this site, so nothing was made. | no | how to configure it |
| `capability_unsupported` | The configured model cannot do what was asked. | no | alternatives lists fallbacks the caller may opt into |
| `provider_failed` | The image provider refused or failed. | yes | providerMessage, retryable |
| `provider_busy` | The image provider is busy. Try again shortly. | yes | retryAfterSeconds |
| `spend_ceiling_exceeded` | The site's spending ceiling for a round or a day is reached, so this picture was not made. | no | the ceiling |
| `batch_expired` | The picture was not ready within the batch window (24 hours). Nothing was charged. | yes |  |
| `stale_version` | The Story has a newer version than the one you named. Read it again. | no |  |
| `candidate_not_ready` | The picture is still being made. | no |  |
| `candidate_closed` | The picture was already discarded, expired or applied. | no |  |
| `unknown_kind` | There is no such kind of guidelines. | no | kinds lists the kinds this site knows |
| `resolver_not_available` | This kind of guidelines is resolved by its own command, not this one. | no | use names the command |
| `document_hash_mismatch` | The stored guideline document does not match its recorded hash, so it was not used. | no | itemId |
| `service_unavailable` | A permission or storage check could not be made. Nothing was changed. | yes |  |

## image_profile_get

Read the publication's visual style profile, the current version or an older one.

- Command: `papyrus images profile get`
- MCP tool: `image_profile_get`
- Effect: read
- Agent may call: yes

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `version` | integer | no | A version number; the current version when left out. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `profile` | object | yes | The visual style document: a full or partial profile (design section 5.2). |
| `itemId` | string | yes |  |
| `versionNumber` | integer | yes |  |
| `updatedAt` | string | no |  |
| `updatedBy` | string | no |  |
| `contentHash` | string | yes |  |

Errors: `not_found`.

Example input:

```json
{}
```

Example result:

```json
{
  "profile": {
    "schemaVersion": 1,
    "identity": {
      "summary": "Flat, calm editorial illustration."
    }
  },
  "itemId": "item-editorial-doctrine-visual-style-v3",
  "versionNumber": 3,
  "updatedAt": "2026-11-07T17:51:39Z",
  "updatedBy": "account-1",
  "contentHash": "sha256:0f3a"
}
```

## image_profile_resolve

Show the style that would apply to a Story, section and use, with the layer every field came from.

- Command: `papyrus images profile resolve`
- MCP tool: `image_profile_resolve`
- Effect: read
- Agent may call: yes

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `target` | object | no | What the picture is for: a Story or a Reference. |
| `sectionId` | string | no | A section id; worked out from the Story when left out. |
| `use` | string | yes | Where the picture goes: the cover, inline in the body, or a social card. One of: `cover`, `inline`, `social`. |
| `imageType` | string | no | A key from the profile's imageTypes, such as cover-illustration. Omit for a cover or social card to get the publication's default; inside the article you must name one. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `resolutionHash` | string | yes |  |
| `profile` | object/null | yes | Which profile version; null when the publication has none. |
| `layers` | array | yes |  |
| `effective` | object | yes |  |
| `fieldSources` | object | yes |  |
| `imageType` | string | yes |  |
| `imageTypeChosenBy` | string | yes | Whether the caller named the image type or the use's default supplied it. One of: `request`, `default-for-use`. |
| `availableTypes` | array | yes |  |
| `constraints` | array | yes |  |
| `warnings` | array | yes |  |

Errors: `constraint_conflict`, `image_type_required`, `image_type_unknown`, `not_found`.

Example input:

```json
{
  "target": {
    "kind": "story",
    "lineageId": "story-containment-note"
  },
  "use": "cover",
  "imageType": "cover-illustration"
}
```

Example result:

```json
{
  "resolutionHash": "sha256:91bc",
  "profile": {
    "itemId": "item-editorial-doctrine-visual-style-v3",
    "versionNumber": 3,
    "contentHash": "sha256:0f3a"
  },
  "layers": [
    {
      "layer": "publication"
    },
    {
      "layer": "use"
    },
    {
      "layer": "image-type"
    }
  ],
  "effective": {
    "aspectRatio": "16:9"
  },
  "fieldSources": {
    "aspectRatio": "use:cover"
  },
  "imageType": "cover-illustration",
  "imageTypeChosenBy": "request",
  "availableTypes": [
    {
      "key": "cover-illustration",
      "label": "Cover illustration",
      "description": "A calm editorial illustration for the cover.",
      "sources": [
        "generated",
        "stock"
      ]
    }
  ],
  "constraints": [],
  "warnings": []
}
```

## image_profile_diff

Show what saving a style document would change, without saving it.

- Command: `papyrus images profile diff`
- MCP tool: `image_profile_diff`
- Effect: read
- Agent may call: yes

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `document` | object | yes | The visual style document: a full or partial profile (design section 5.2). |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `changes` | array | yes |  |
| `constraintChanges` | array | yes |  |
| `wouldCreateVersion` | integer | yes |  |

Errors: `constraint_conflict`.

Example input:

```json
{
  "document": {
    "identity": {
      "mood": [
        "calm"
      ]
    }
  }
}
```

Example result:

```json
{
  "changes": [
    {
      "path": "identity.mood",
      "from": [
        "calm",
        "precise"
      ],
      "to": [
        "calm"
      ]
    }
  ],
  "constraintChanges": [],
  "wouldCreateVersion": 4
}
```

## image_profile_save

Save a style document as a new profile version.

- Command: `papyrus images profile save`
- MCP tool: `image_profile_save`
- Effect: write
- Agent may call: yes
- Note: Adding, changing or removing a binding constraint needs an admin who is a person; an agent gets human_required. The document is laid over the current profile (objects merge, lists replace, null removes a key). For the very first profile pass none as expectedCurrentVersionId. Saving a document that changes nothing makes no version.

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `document` | object | yes | The visual style document: a full or partial profile (design section 5.2). |
| `reason` | string | yes | Why, in plain words. It is recorded with who and when. |
| `expectedCurrentVersionId` | string | yes | The profile's current version id when you read it. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `itemId` | string | yes |  |
| `versionNumber` | integer | yes |  |
| `contentHash` | string | yes |  |

Errors: `human_required`, `stale_version`, `constraint_conflict`.

Example input:

```json
{
  "document": {
    "identity": {
      "mood": [
        "calm"
      ]
    }
  },
  "reason": "Dropped one mood word.",
  "expectedCurrentVersionId": "item-editorial-doctrine-visual-style-v3"
}
```

Example result:

```json
{
  "itemId": "item-editorial-doctrine-visual-style-v4",
  "versionNumber": 4,
  "contentHash": "sha256:7d21"
}
```

## image_profile_history

List the profile's versions, newest first, with who changed it and why.

- Command: `papyrus images profile history`
- MCP tool: `image_profile_history`
- Effect: read
- Agent may call: yes

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `limit` | integer | no | How many versions to return. |
| `nextToken` | string | no | Pass this to get the next page. Absent when there is no more. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `versions` | array | yes |  |
| `nextToken` | string | no | Pass this to get the next page. Absent when there is no more. |

Errors: only the common ones.

Example input:

```json
{
  "limit": 2
}
```

Example result:

```json
{
  "versions": [
    {
      "versionNumber": 3,
      "at": "2026-11-07T17:51:39Z",
      "by": "account-1",
      "byKind": "human",
      "reason": "First profile.",
      "contentHash": "sha256:0f3a"
    }
  ]
}
```

## image_profile_init

Draft a starting style document from the site's brand, for an editor to correct and save. Saves nothing.

- Command: `papyrus images profile init`
- MCP tool: `image_profile_init`
- Effect: read
- Agent may call: yes
- Note: The draft holds the shape of a profile and the colours the brand names, and no style wording: an editor writes that. Nothing is saved; save the draft with image_profile_save after correcting it.

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `brand` | object | no | What the site's brand files say. Everything in it is optional. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `document` | object | yes | The visual style document: a full or partial profile (design section 5.2). |
| `expectedCurrentVersionId` | string | yes | Pass this to image_profile_save when saving the draft. |
| `notes` | array | yes | What an editor still has to write. |
| `profileExists` | boolean | yes |  |

Errors: only the common ones.

Example input:

```json
{
  "brand": {
    "name": "Example Daily",
    "palette": [
      {
        "name": "Ink blue",
        "hex": "#1f2a44",
        "token": "brand"
      }
    ]
  }
}
```

Example result:

```json
{
  "document": {
    "schemaVersion": 2,
    "identity": {
      "palette": [
        {
          "name": "Ink blue",
          "hex": "#1f2a44",
          "token": "brand"
        }
      ]
    }
  },
  "expectedCurrentVersionId": "none",
  "notes": [
    "Write identity.summary and identity.masterPrompt."
  ],
  "profileExists": false
}
```

## image_profile_example_add

Add an example or an avoid-this picture to the profile, as a new version.

- Command: `papyrus images profile example add`
- MCP tool: `image_profile_example_add`
- Effect: write
- Agent may call: yes
- Note: From the command line, --file PICTURE uploads the picture first (the same three steps the newsroom takes) and fills in attachmentId. Only a person may set sendToProvider: an agent asking for it gets human_required, because the service cannot tell whether a picture shows identifiable people or logos. An example belongs to one image type; a child type does not inherit its parent's examples.

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `attachmentId` | string | yes | The id of a picture already uploaded through the newsroom's upload step (PNG, JPEG or WebP, at most 10 MB). |
| `kind` | string | yes | One of: `exemplar`, `negative`. |
| `note` | string | yes | Why this picture is a good example, or what to avoid. |
| `imageType` | string | yes | The image type this example belongs to, or identity for a brand-wide example. |
| `sendToProvider` | boolean | no | Send it to the image model as a style reference. Default false. |
| `reason` | string | yes | Why, in plain words. It is recorded with who and when. |
| `expectedCurrentVersionId` | string | yes | The profile's current version id when you read it. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `attachmentId` | string | yes |  |
| `sha256` | string | yes |  |
| `versionNumber` | integer | yes |  |
| `imageType` | string | no |  |

Errors: `human_required`, `image_type_unknown`, `not_found`, `stale_version`.

Example input:

```json
{
  "attachmentId": "model-attachment-1",
  "imageType": "cover-illustration",
  "kind": "exemplar",
  "note": "The calm we want.",
  "reason": "Cover from the containment Story.",
  "expectedCurrentVersionId": "item-editorial-doctrine-visual-style-v3"
}
```

Example result:

```json
{
  "attachmentId": "model-attachment-1",
  "sha256": "sha256:aa10",
  "versionNumber": 4,
  "imageType": "cover-illustration"
}
```

## image_profile_example_remove

Remove an example picture from the profile, as a new version.

- Command: `papyrus images profile example remove`
- MCP tool: `image_profile_example_remove`
- Effect: write
- Agent may call: yes
- Note: The file stays for older profile versions, so a picture made from an older version keeps the examples it was made with.

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `attachmentId` | string | yes |  |
| `imageType` | string | no | Remove it from this image type only (or identity). Left out, it is removed from every list that has it. |
| `reason` | string | yes | Why, in plain words. It is recorded with who and when. |
| `expectedCurrentVersionId` | string | yes | The profile's current version id when you read it. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `versionNumber` | integer | yes |  |
| `removedFrom` | array | no | The image types (or identity) it was removed from. |

Errors: `not_found`, `stale_version`.

Example input:

```json
{
  "attachmentId": "model-attachment-1",
  "reason": "Too photographic.",
  "expectedCurrentVersionId": "item-editorial-doctrine-visual-style-v4"
}
```

Example result:

```json
{
  "versionNumber": 5,
  "removedFrom": [
    "cover-illustration"
  ]
}
```

## image_capabilities

Say which image models this site can use and whether spending is approved.

- Command: `papyrus images capabilities`
- MCP tool: `image_capabilities`
- Effect: read
- Agent may call: yes

Input:

None.

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `configured` | boolean | yes |  |
| `models` | array | yes |  |
| `approvedForSpend` | boolean | yes |  |
| `unreviewedMayPublish` | boolean | no |  |
| `spendCeilings` | object | no |  |
| `spentTodayUsd` | number | no |  |

Errors: only the common ones.

Example input:

```json
{}
```

Example result:

```json
{
  "configured": false,
  "models": [],
  "approvedForSpend": false
}
```

## image_brief_draft

Work out a starting brief and stock search from a Story's title and deck.

- Command: `papyrus images brief`
- MCP tool: `image_brief_draft`
- Effect: read
- Agent may call: yes

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `target` | object | yes | What the picture is for: a Story or a Reference. |
| `use` | string | yes | Where the picture goes: the cover, inline in the body, or a social card. One of: `cover`, `inline`, `social`. |
| `imageType` | string | no | A key from the profile's imageTypes, such as cover-illustration. Omit for a cover or social card to get the publication's default; inside the article you must name one. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `brief` | string | yes |  |
| `searchTarget` | string | yes |  |
| `imageType` | string | no |  |
| `imageTypeChosenBy` | string | no | Whether the caller named the image type or the use's default supplied it. One of: `request`, `default-for-use`. |
| `typeChoices` | array | no |  |
| `derivedFrom` | array | yes |  |
| `workedOut` | boolean | yes |  |

Errors: `image_type_required`, `not_found`.

Example input:

```json
{
  "target": {
    "kind": "story",
    "lineageId": "story-containment-note"
  },
  "use": "cover",
  "imageType": "cover-illustration"
}
```

Example result:

```json
{
  "brief": "A locked filing cabinet with one drawer ajar",
  "searchTarget": "filing cabinet",
  "imageType": "cover-illustration",
  "imageTypeChosenBy": "request",
  "typeChoices": [
    {
      "key": "cover-illustration",
      "label": "Cover illustration",
      "description": "A calm editorial illustration for the cover.",
      "sources": [
        "generated",
        "stock"
      ]
    }
  ],
  "derivedFrom": [
    "title",
    "deck"
  ],
  "workedOut": true
}
```

## image_prompt_preview

Show exactly what would be asked of the image model, and what it would cost, without making anything.

- Command: `papyrus images prompt`
- MCP tool: `image_prompt_preview`
- Effect: read
- Agent may call: yes

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `target` | object | no | What the picture is for: a Story or a Reference. |
| `sectionId` | string | no | A section id; worked out from the Story when left out. With no target it is the only place the section layer comes from. |
| `use` | string | yes | Where the picture goes: the cover, inline in the body, or a social card. One of: `cover`, `inline`, `social`. |
| `imageType` | string | no | A key from the profile's imageTypes, such as cover-illustration. Omit for a cover or social card to get the publication's default; inside the article you must name one. |
| `brief` | string | yes | What the picture should show. The publication's style rules are added by the service, never written here. |
| `count` | integer | no | How many to make (default 1). More than 1 is for a person choosing; an agent asking for more gets set_needs_person. |
| `spread` | string | no | Four takes of one image type, or one take of each type the use allows that can be generated. One of: `variations`, `types`. |
| `imageTypes` | array | no | Image types to spread across, from the profile. |
| `model` | string | no | A configured, approved model. Recorded as requested and never swapped. |
| `acceptFallback` | string | no | Id of a fallback offered in a capability_unsupported error, to use instead. |
| `references` | array | no | Example ids of the chosen image type to send as style references. Nothing else is accepted. |
| `speed` | string | no | Which lane: auto picks by who is asking (a person standard, an agent batch at half price). One of: `auto`, `standard`, `batch`. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `plans` | array | yes |  |
| `estimate` | object | yes | What it would cost; spends nothing. |
| `capabilityCheck` | object | yes |  |

Errors: `capability_unsupported`, `constraint_conflict`, `generation_not_configured`, `image_type_required`, `image_type_unknown`, `not_found`, `set_needs_person`, `source_not_allowed`.

Example input:

```json
{
  "target": {
    "kind": "story",
    "lineageId": "story-containment-note"
  },
  "use": "cover",
  "imageType": "cover-illustration",
  "brief": "A locked filing cabinet with one drawer ajar"
}
```

Example result:

```json
{
  "plans": [
    {
      "planVersion": "image-prompt/v2",
      "imageType": "cover-illustration",
      "segments": [],
      "avoid": []
    }
  ],
  "estimate": {
    "priced": false
  },
  "capabilityCheck": {
    "ok": true
  }
}
```

## image_search

Find stock pictures for a Story, four at a time.

- Command: `papyrus images search`
- MCP tool: `image_search`
- Effect: read
- Agent may call: yes
- Note: Nothing is stored until a picture is selected or applied.

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `target` | object | yes | What the picture is for: a Story or a Reference. |
| `use` | string | no | Where the picture goes: the cover, inline in the body, or a social card. One of: `cover`, `inline`, `social`. |
| `imageType` | string | no | A key from the profile's imageTypes, such as cover-illustration. Omit for a cover or social card to get the publication's default; inside the article you must name one. |
| `query` | string | no | Search words; worked out from the Story when left out. |
| `source` | string | no | A stock source, for example wikimedia-commons. |
| `cursor` | string | no | The nextCursor of the previous page. |
| `exclude` | array | no | Candidate ids already shown, which never come back. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `imageType` | string | no |  |
| `imageTypeChosenBy` | string | no | Whether the caller named the image type or the use's default supplied it. One of: `request`, `default-for-use`. |
| `candidates` | array | yes |  |
| `nextCursor` | string/null | yes |  |
| `searched` | string | yes |  |
| `searchedFromStory` | boolean | yes |  |

Errors: `image_type_required`, `image_type_unknown`, `not_found`, `source_not_allowed`.

Example input:

```json
{
  "target": {
    "kind": "story",
    "lineageId": "story-containment-note"
  },
  "use": "cover",
  "imageType": "cover-illustration"
}
```

Example result:

```json
{
  "imageType": "cover-illustration",
  "imageTypeChosenBy": "request",
  "candidates": [],
  "nextCursor": null,
  "searched": "filing cabinet",
  "searchedFromStory": true
}
```

## image_generate

Make pictures from a brief in the publication's style. The pictures arrive later.

- Command: `papyrus images generate`
- MCP tool: `image_generate`
- Effect: spend
- Agent may call: yes
- Note: Spends only when the site's image generation is configured and approved.

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `target` | object | no | What the picture is for: a Story or a Reference. |
| `sectionId` | string | no | A section id; worked out from the Story when left out. With no target it is the only place the section layer comes from. |
| `use` | string | yes | Where the picture goes: the cover, inline in the body, or a social card. One of: `cover`, `inline`, `social`. |
| `imageType` | string | no | A key from the profile's imageTypes, such as cover-illustration. Omit for a cover or social card to get the publication's default; inside the article you must name one. |
| `brief` | string | yes | What the picture should show. The publication's style rules are added by the service, never written here. |
| `count` | integer | no | How many to make (default 1). More than 1 is for a person choosing; an agent asking for more gets set_needs_person. |
| `spread` | string | no | Four takes of one image type, or one take of each type the use allows that can be generated. One of: `variations`, `types`. |
| `imageTypes` | array | no | Image types to spread across, from the profile. |
| `model` | string | no | A configured, approved model. Recorded as requested and never swapped. |
| `acceptFallback` | string | no | Id of a fallback offered in a capability_unsupported error, to use instead. |
| `references` | array | no | Example ids of the chosen image type to send as style references. Nothing else is accepted. |
| `speed` | string | no | Which lane: auto picks by who is asking (a person standard, an agent batch at half price). One of: `auto`, `standard`, `batch`. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `roundId` | string | yes |  |
| `imageType` | string | no |  |
| `imageTypeChosenBy` | string | no | Whether the caller named the image type or the use's default supplied it. One of: `request`, `default-for-use`. |
| `candidates` | array | yes |  |
| `estimate` | object | no | What it would cost; spends nothing. |

Errors: `capability_unsupported`, `constraint_conflict`, `generation_not_configured`, `image_type_required`, `image_type_unknown`, `not_found`, `provider_busy`, `set_needs_person`, `source_not_allowed`, `spend_ceiling_exceeded`.

Example input:

```json
{
  "target": {
    "kind": "story",
    "lineageId": "story-containment-note"
  },
  "use": "cover",
  "imageType": "cover-illustration",
  "brief": "A locked filing cabinet with one drawer ajar"
}
```

Example result:

```json
{
  "roundId": "round-1",
  "imageType": "cover-illustration",
  "imageTypeChosenBy": "request",
  "candidates": [
    {
      "id": "candidate-1",
      "position": 0,
      "status": "queued",
      "imageType": "cover-illustration",
      "origin": "generated",
      "lane": "batch"
    }
  ],
  "estimate": {
    "priced": false
  }
}
```

## image_figure_add

Record a figure drawn with the publication's figure system as a picture to preview, review and apply. It draws and generates nothing.

- Command: `papyrus images figure add`
- MCP tool: `image_figure_add`
- Effect: write
- Agent may call: yes
- Note: Needs an image type whose sources include figure-system. The figure is drawn and rendered elsewhere; this only records it. The CLI reads the figure.json acceptance fields from --file and takes uploadIds through --input-file.

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `target` | object | yes | What the picture is for: a Story or a Reference. |
| `imageType` | string | yes | The image type the figure is for, such as cover-diagram. It must allow the figure-system source. |
| `uploadIds` | object | no | Pictures already uploaded through the newsroom's upload step. |
| `figureId` | string | no | The id of the figure record, once the backend stores figures (PPY-cd4585). |
| `figure` | object | yes | The figure.json acceptance fields. |

Give exactly one of: `uploadIds`, `figureId`.

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `candidateId` | string | yes |  |
| `origin` | string | yes | One of: `figure`. |
| `checks` | array | yes |  |

Errors: `checks_failed`, `image_type_unknown`, `not_found`, `source_not_allowed`.

Example input:

```json
{
  "target": {
    "kind": "story",
    "lineageId": "story-containment-note"
  },
  "imageType": "cover-diagram",
  "uploadIds": {
    "light": "upload-2",
    "dark": "upload-3"
  },
  "figure": {
    "audience": "Editors deciding what to publish.",
    "shows": "Which checks run before a picture is applied.",
    "complements": "The paragraph on review."
  }
}
```

Example result:

```json
{
  "candidateId": "candidate-7",
  "origin": "figure",
  "checks": [
    {
      "name": "alt-text",
      "passed": true
    }
  ]
}
```

## image_round_get

Read a round of pictures and say whether they are all done.

- Command: `papyrus images round`
- MCP tool: `image_round_get`
- Effect: read
- Agent may call: yes

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `roundId` | string | yes |  |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `roundId` | string | yes |  |
| `target` | object | no | What the picture is for: a Story or a Reference. |
| `use` | string | yes | Where the picture goes: the cover, inline in the body, or a social card. One of: `cover`, `inline`, `social`. |
| `imageType` | string | no |  |
| `brief` | string | no |  |
| `candidates` | array | yes |  |
| `done` | boolean | yes |  |

Errors: `not_found`.

Example input:

```json
{
  "roundId": "round-1"
}
```

Example result:

```json
{
  "roundId": "round-1",
  "target": {
    "kind": "story",
    "lineageId": "story-containment-note"
  },
  "use": "cover",
  "imageType": "cover-illustration",
  "brief": "A locked filing cabinet with one drawer ajar",
  "candidates": [
    {
      "id": "candidate-1",
      "position": 0,
      "status": "ready",
      "treatment": "editorial-illustration",
      "imageType": "cover-illustration",
      "origin": "generated",
      "lane": "standard",
      "reviewStatus": "unreviewed"
    }
  ],
  "done": true
}
```

## image_candidate_get

Read one picture's full record, with a short-lived preview address.

- Command: `papyrus images show`
- MCP tool: `image_candidate_get`
- Effect: read
- Agent may call: yes

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `candidateId` | string | yes |  |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `candidate` | object | yes | The full ImageCandidate record. |
| `previewUrl` | string | no |  |

Errors: `not_found`.

Example input:

```json
{
  "candidateId": "candidate-1"
}
```

Example result:

```json
{
  "candidate": {
    "id": "candidate-1",
    "position": 0,
    "status": "ready",
    "treatment": "editorial-illustration",
    "imageType": "cover-illustration",
    "origin": "generated",
    "lane": "standard",
    "reviewStatus": "unreviewed"
  },
  "previewUrl": "https://example.invalid/preview/candidate-1"
}
```

## image_list

List the rounds and pictures made for a Story or Reference, newest first.

- Command: `papyrus images list`
- MCP tool: `image_list`
- Effect: read
- Agent may call: yes

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `target` | object | yes | What the picture is for: a Story or a Reference. |
| `status` | string | no | One of: `queued`, `pending`, `running`, `ready`, `failed`, `rejected`, `applied`, `unapplied`, `expired`. |
| `nextToken` | string | no | Pass this to get the next page. Absent when there is no more. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `rounds` | array | yes |  |
| `nextToken` | string | no | Pass this to get the next page. Absent when there is no more. |

Errors: `not_found`.

Example input:

```json
{
  "target": {
    "kind": "story",
    "lineageId": "story-containment-note"
  }
}
```

Example result:

```json
{
  "rounds": [
    {
      "roundId": "round-1",
      "use": "cover",
      "imageType": "cover-illustration",
      "brief": "A locked filing cabinet",
      "createdAt": "2026-11-07T18:00:00Z",
      "candidates": [
        {
          "id": "candidate-1",
          "position": 0,
          "status": "ready",
          "treatment": "editorial-illustration",
          "imageType": "cover-illustration",
          "origin": "generated",
          "lane": "standard",
          "reviewStatus": "unreviewed"
        }
      ]
    }
  ]
}
```

## image_retry

Make a new picture to replace one that failed. The ones that worked stay.

- Command: `papyrus images retry`
- MCP tool: `image_retry`
- Effect: spend
- Agent may call: yes
- Note: The design lists only candidateId; speed is added because it says a retry can choose standard (section 7.4).

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `candidateId` | string | yes | A failed picture. |
| `speed` | string | no | Lane for the new picture; a batch failure retries as batch by default. One of: `auto`, `standard`, `batch`. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `roundId` | string | yes |  |
| `candidate` | object | yes |  |
| `estimate` | object | no | What it would cost; spends nothing. |

Errors: `candidate_closed`, `candidate_not_ready`, `capability_unsupported`, `generation_not_configured`, `not_found`, `provider_busy`.

Example input:

```json
{
  "candidateId": "candidate-3"
}
```

Example result:

```json
{
  "roundId": "round-1",
  "candidate": {
    "id": "candidate-5",
    "position": 4,
    "status": "queued",
    "retryOf": "candidate-3"
  },
  "estimate": {
    "priced": false
  }
}
```

## image_iterate

Make new pictures from one you have, with an instruction such as 'less busy'.

- Command: `papyrus images iterate`
- MCP tool: `image_iterate`
- Effect: spend
- Agent may call: yes
- Note: The profile and its rules are resolved again and put back into the request; an instruction cannot remove them.

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `candidateId` | string | yes |  |
| `instruction` | string | yes | What to change, in plain words. |
| `count` | integer | no | How many to make (default 1). More than 1 is for a person choosing. |
| `useAsReference` | boolean | no | Send the picture to the model as a reference. Default true when the model can edit. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `roundId` | string | yes |  |
| `imageType` | string | no |  |
| `imageTypeChosenBy` | string | no | Whether the caller named the image type or the use's default supplied it. One of: `request`, `default-for-use`. |
| `candidates` | array | yes |  |
| `estimate` | object | no | What it would cost; spends nothing. |

Errors: `candidate_closed`, `candidate_not_ready`, `capability_unsupported`, `constraint_conflict`, `generation_not_configured`, `not_found`, `provider_busy`, `set_needs_person`.

Example input:

```json
{
  "candidateId": "candidate-1",
  "instruction": "less busy, subject lower"
}
```

Example result:

```json
{
  "roundId": "round-2",
  "candidates": [
    {
      "id": "candidate-6",
      "position": 0,
      "status": "queued",
      "lane": "batch"
    }
  ],
  "estimate": {
    "priced": false
  }
}
```

## image_select

Record a picture as the pick. It changes no Story and is not approval.

- Command: `papyrus images select`
- MCP tool: `image_select`
- Effect: write
- Agent may call: yes

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `candidateId` | string | no |  |
| `candidateRef` | string | no | A stock picture's reference from image_search. |
| `reason` | string | yes | Why, in plain words. It is recorded with who and when. |

Give exactly one of: `candidateId`, `candidateRef`.

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `candidateId` | string | yes |  |
| `selection` | object | yes |  |

Errors: `candidate_closed`, `candidate_not_ready`, `not_found`.

Example input:

```json
{
  "candidateId": "candidate-1",
  "reason": "Calmest of the four."
}
```

Example result:

```json
{
  "candidateId": "candidate-1",
  "selection": {
    "by": "account-1",
    "byKind": "agent",
    "at": "2026-11-07T18:05:00Z",
    "reason": "Calmest of the four."
  }
}
```

## image_unapply

Undo an applied picture: the Story gets a new version with the old cover or the placeholder back.

- Command: `papyrus images unapply`
- MCP tool: `image_unapply`
- Effect: write
- Agent may call: yes
- Note: The media asset and its record stay. Any editor or agent may unapply.

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `target` | object | yes | What the picture is for: a Story or a Reference. |
| `mediaAssetId` | string | yes |  |
| `expectedCurrentVersionId` | string | yes | The Story's current version id when you read it. The write is refused with stale_version if the Story has moved on. |
| `reason` | string | yes | Why, in plain words. It is recorded with who and when. |
| `save` | boolean | no | Make the new Story version now (default true). The newsroom editor passes false and saves itself. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `patch` | object | yes |  |
| `restored` | string | yes | One of: `previous-cover`, `placeholder`. |
| `savedVersion` | object | no |  |

Errors: `candidate_closed`, `not_found`, `stale_version`.

Example input:

```json
{
  "target": {
    "kind": "story",
    "lineageId": "story-containment-note"
  },
  "mediaAssetId": "media-asset-1",
  "expectedCurrentVersionId": "item-story-containment-note-v7",
  "reason": "Looks like a photograph."
}
```

Example result:

```json
{
  "patch": {
    "frontMatter": {
      "image": null
    }
  },
  "restored": "placeholder",
  "savedVersion": {
    "versionId": "item-story-containment-note-v8",
    "versionNumber": 8
  }
}
```

## image_review

Keep or remove a picture that was added without a person looking at it. Only a person may.

- Command: `papyrus images review`
- MCP tool: `image_review`
- Effect: write
- Agent may call: no, a person only
- Note: Keep marks the picture human-verified with who and when. Remove runs image_unapply. Either answers the linked review request.

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `mediaAssetId` | string | yes |  |
| `decision` | string | yes | One of: `keep`, `remove`. |
| `note` | string | no |  |
| `expectedCurrentVersionId` | string | no | Needed to remove: the Story's current version id when you read it. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `mediaAssetId` | string | yes |  |
| `decision` | string | yes | One of: `keep`, `remove`. |
| `reviewStatus` | string | yes | One of: `unreviewed`, `human-verified`. |
| `savedVersion` | object | no |  |

Errors: `human_required`, `not_found`, `stale_version`.

Example input:

```json
{
  "mediaAssetId": "media-asset-1",
  "decision": "keep"
}
```

Example result:

```json
{
  "mediaAssetId": "media-asset-1",
  "decision": "keep",
  "reviewStatus": "human-verified"
}
```

## image_review_queue

List the pictures that were added without a person, oldest first.

- Command: `papyrus images review-queue`
- MCP tool: `image_review_queue`
- Effect: read
- Agent may call: yes

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `nextToken` | string | no | Pass this to get the next page. Absent when there is no more. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `items` | array | yes |  |
| `nextToken` | string | no | Pass this to get the next page. Absent when there is no more. |

Errors: only the common ones.

Example input:

```json
{}
```

Example result:

```json
{
  "items": [
    {
      "mediaAssetId": "media-asset-1",
      "target": {
        "kind": "story",
        "lineageId": "story-containment-note"
      },
      "candidateId": "candidate-1",
      "appliedAt": "2026-11-07T18:10:00Z",
      "appliedBy": "account-1",
      "reviewRequestId": "review-1"
    }
  ]
}
```

## image_apply

Put a picture on a Story: copy it into the site's media and record where it came from. It never publishes.

- Command: `papyrus images apply`
- MCP tool: `image_apply`
- Effect: write
- Agent may call: yes
- Note: A person applying from a set they looked at makes it human-verified. Anyone else makes it unreviewed and opens a review request.

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `candidateId` | string | no |  |
| `candidateRef` | string | no | A stock picture's reference from image_search. |
| `target` | object | yes | What the picture is for: a Story or a Reference. |
| `use` | string | yes | Where the picture goes: the cover, inline in the body, or a social card. One of: `cover`, `inline`, `social`. |
| `imageType` | string | no | A key from the profile's imageTypes, such as cover-illustration. Omit for a cover or social card to get the publication's default; inside the article you must name one. |
| `alt` | string | no | Alt text; the picture's own draft when left out. |
| `caption` | string | no |  |
| `expectedCurrentVersionId` | string | yes | The Story's current version id when you read it. The write is refused with stale_version if the Story has moved on. |
| `save` | boolean | no | Make the new Story version now (default true). The newsroom editor passes false and saves itself. |

Give exactly one of: `candidateId`, `candidateRef`.

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `patch` | object | yes |  |
| `mediaAsset` | object | yes |  |
| `imageType` | string | no |  |
| `reviewStatus` | string | yes | One of: `unreviewed`, `human-verified`. |
| `reviewRequestId` | string | no |  |
| `savedVersion` | object | no |  |

Errors: `candidate_closed`, `candidate_not_ready`, `checks_failed`, `image_type_unknown`, `not_found`, `source_not_allowed`, `stale_version`.

Example input:

```json
{
  "candidateId": "candidate-1",
  "target": {
    "kind": "story",
    "lineageId": "story-containment-note"
  },
  "use": "cover",
  "imageType": "cover-illustration",
  "expectedCurrentVersionId": "item-story-containment-note-v7"
}
```

Example result:

```json
{
  "patch": {
    "bodyDirective": "::image{src=\"assets/containment/cover.png\"}",
    "frontMatter": {
      "image": "assets/containment/cover.png"
    }
  },
  "mediaAsset": {
    "id": "media-asset-1"
  },
  "imageType": "cover-illustration",
  "reviewStatus": "unreviewed",
  "reviewRequestId": "review-1",
  "savedVersion": {
    "versionId": "item-story-containment-note-v8",
    "versionNumber": 8
  }
}
```

## image_discard

Reject a picture, or a whole round (which keeps the placeholder). The private file is deleted; the record stays.

- Command: `papyrus images discard`
- MCP tool: `image_discard`
- Effect: write
- Agent may call: yes

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `candidateId` | string | no |  |
| `roundId` | string | no |  |
| `reason` | string | yes | Why, in plain words. It is recorded with who and when. |

Give exactly one of: `candidateId`, `roundId`.

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `discarded` | array | yes | The ids of the pictures that were discarded. |

Errors: `candidate_closed`, `not_found`.

Example input:

```json
{
  "roundId": "round-1",
  "reason": "Kept the placeholder."
}
```

Example result:

```json
{
  "discarded": [
    "candidate-1",
    "candidate-2"
  ]
}
```
<!-- /generated:image-operations -->
