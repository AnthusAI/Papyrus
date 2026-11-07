---
name: image-work
description: Use when a Story or Reference needs a picture: finding stock images, generating options from the publication's visual style, choosing, applying or keeping the placeholder.
---

# Image work

This skill is for any agent that adds a picture to a Story or Reference, through the `papyrus images` commands or the `image_*` MCP tools. They are
the same operations, with the same input and the same JSON result.

Start from the publication's style. `image_profile_resolve` says which image types the publication has for a use (`availableTypes`, each with a plain description and its
allowed sources, best first), which one applies, and where every rule came from. Name an image type for anything inside the article; for a cover or social card you may leave it out
and the publication's default is used and said so. Write a brief about what the picture should show, never about its style: the style comes from the profile. A publication with no
profile gives a `profile_missing` warning, not an error: say so, and do not make up style rules. You may save profile changes with `image_profile_save`, but binding constraints
belong to a person who is an admin: an agent gets `human_required`.

The guidance on when to use stock, when to generate, how to choose, and how review works is written in a later build step. Until then, read the
reference below, and treat a picture you apply without a person as a suggestion: it is not approved.

<!-- generated:image-operations -->
<!-- Generated from src/papyrus_content/images/operations.py. Do not edit by hand; run scripts/generate-image-operations.py. -->

## Reference: the operations

Each operation is a command and a tool with the same input and the same JSON result. A person-only operation returns `human_required` to an agent.

| Operation (MCP tool) | Command | What it does | Agent may call | Errors it can return |
| --- | --- | --- | --- | --- |
| `image_profile_get` | `papyrus images profile get` | Read the publication's visual style profile, the current version or an older one. | yes | `not_found` |
| `image_profile_resolve` | `papyrus images profile resolve` | Show the style that would apply to a Story, section and use, with the layer every field came from. | yes | `constraint_conflict`, `image_type_required`, `image_type_unknown`, `not_found` |
| `image_profile_diff` | `papyrus images profile diff` | Show what saving a style document would change, without saving it. | yes | `constraint_conflict` |
| `image_profile_save` | `papyrus images profile save` | Save a style document as a new profile version. | yes | `human_required`, `stale_version`, `constraint_conflict` |
| `image_profile_history` | `papyrus images profile history` | List the profile's versions, newest first, with who changed it and why. | yes | only the common ones |
| `image_profile_example_add` | `papyrus images profile example add` | Add an example or an avoid-this picture to the profile, as a new version. | yes | `human_required`, `image_type_unknown`, `not_found`, `stale_version` |
| `image_profile_example_remove` | `papyrus images profile example remove` | Remove an example picture from the profile, as a new version. | yes | `not_found`, `stale_version` |
| `image_capabilities` | `papyrus images capabilities` | Say which image models this site can use and whether spending is approved. | yes | only the common ones |
| `image_brief_draft` | `papyrus images brief` | Work out a starting brief and stock search from a Story's title and deck. | yes | `image_type_required`, `not_found` |
| `image_prompt_preview` | `papyrus images prompt` | Show exactly what would be asked of the image model, and what it would cost, without making anything. | yes | `capability_unsupported`, `constraint_conflict`, `generation_not_configured`, `image_type_required`, `image_type_unknown`, `not_found`, `set_needs_person`, `source_not_allowed` |
| `image_search` | `papyrus images search` | Find stock pictures for a Story, four at a time. | yes | `image_type_required`, `image_type_unknown`, `not_found`, `source_not_allowed` |
| `image_generate` | `papyrus images generate` | Make pictures from a brief in the publication's style. The pictures arrive later. | yes | `capability_unsupported`, `constraint_conflict`, `generation_not_configured`, `image_type_required`, `image_type_unknown`, `not_found`, `provider_busy`, `set_needs_person`, `source_not_allowed` |
| `image_figure_add` | `papyrus images figure add` | Record a figure drawn with the publication's figure system as a picture to preview, review and apply. It draws and generates nothing. | yes | `checks_failed`, `image_type_unknown`, `not_found`, `source_not_allowed` |
| `image_round_get` | `papyrus images round` | Read a round of pictures and say whether they are all done. | yes | `not_found` |
| `image_candidate_get` | `papyrus images show` | Read one picture's full record, with a short-lived preview address. | yes | `not_found` |
| `image_list` | `papyrus images list` | List the rounds and pictures made for a Story or Reference, newest first. | yes | `not_found` |
| `image_retry` | `papyrus images retry` | Make a new picture to replace one that failed. The ones that worked stay. | yes | `candidate_closed`, `candidate_not_ready`, `capability_unsupported`, `generation_not_configured`, `not_found`, `provider_busy` |
| `image_iterate` | `papyrus images iterate` | Make new pictures from one you have, with an instruction such as 'less busy'. | yes | `candidate_closed`, `candidate_not_ready`, `capability_unsupported`, `constraint_conflict`, `generation_not_configured`, `not_found`, `provider_busy`, `set_needs_person` |
| `image_select` | `papyrus images select` | Record a picture as the pick. It changes no Story and is not approval. | yes | `candidate_closed`, `candidate_not_ready`, `not_found` |
| `image_unapply` | `papyrus images unapply` | Undo an applied picture: the Story gets a new version with the old cover or the placeholder back. | yes | `candidate_closed`, `not_found`, `stale_version` |
| `image_review` | `papyrus images review` | Keep or remove a picture that was added without a person looking at it. Only a person may. | no, a person only | `human_required`, `not_found`, `stale_version` |
| `image_review_queue` | `papyrus images review-queue` | List the pictures that were added without a person, oldest first. | yes | only the common ones |
| `image_apply` | `papyrus images apply` | Put a picture on a Story: copy it into the site's media and record where it came from. It never publishes. | yes | `candidate_closed`, `candidate_not_ready`, `checks_failed`, `image_type_unknown`, `not_found`, `source_not_allowed`, `stale_version` |
| `image_discard` | `papyrus images discard` | Reject a picture, or a whole round (which keeps the placeholder). The private file is deleted; the record stays. | yes | `candidate_closed`, `not_found` |

Every operation may also return: `invalid_input`, `not_authorized`, `service_unavailable`, `not_implemented`.

### Every result

Success: `{"ok": true, "op": "...", "publication": "...", "result": {...}, "warnings": []}`. Failure: `{"ok": false, "op": "...", "error": {"code": "...", "message": "...", "retryable": false, "details": {}}}`. The command prints this JSON; it exits 0 on success and 2 on any error.

### Errors

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
| `batch_expired` | The picture was not ready within the batch window (24 hours). Nothing was charged. | yes |  |
| `stale_version` | The Story has a newer version than the one you named. Read it again. | no |  |
| `candidate_not_ready` | The picture is still being made. | no |  |
| `candidate_closed` | The picture was already discarded, expired or applied. | no |  |
| `service_unavailable` | A permission or storage check could not be made. Nothing was changed. | yes |  |
<!-- /generated:image-operations -->
