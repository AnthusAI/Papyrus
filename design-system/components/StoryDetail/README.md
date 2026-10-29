# StoryDetail

What an editor sees when they open a story on the newsroom board. Today that is
`NewsroomArticleEditor` rendered `embedded` inside Kanbus's `IssueDetailPanel`
(`components/newsroom-board-view.tsx`), with an *Open full page* link beside it.
It is the roughest surface in the newsroom, and this card is here to be argued
with.

## What it does today

A slug field and a back link; Type, Section and Status selects; a read-only
notice when an older version is open; a four-way toggle — *Preview · Edit ·
Messages · References*; the front matter as Title, Subtitle and Blurb fields;
an unlabelled *What changed?* input; the body in a markdown editor with an
insert-image control; a bordered preview column; and a validation list at the
bottom.

Everything is there. The trouble is that it is all there at once, in one flat
form, with no claim about what matters.

## What makes it read as a prototype

- **Three button idioms in one panel.** `organizer-header-button`,
  `newsroom-article-link-button` and the shared `ui/button` all appear, so the
  same visual weight means three different things.
- **The four-way toggle is hand-rolled** from buttons with `aria-pressed`,
  while `components/ui/tabs.tsx` exists and is used elsewhere. It also mixes
  two kinds of switch: *Preview / Edit* are views of the same text, while
  *Messages / References* are different subjects entirely.
- **A bordered preview** (`rounded-xl border border-border`) inside a newsroom
  surface that tells regions apart by tone. It is the only border in the pane.
- **Validation is far from what it judges.** Errors collect in a list at the
  bottom naming fields that are three scroll-lengths up.
- **The change note has no label** — an `aria-label` and a placeholder carrying
  the whole explanation, floating between the front matter and the body.
- **Image upload is gated by a hint**: *Save the draft once to enable image
  upload.* That is a state of the draft reported as advice.
- **Status appears twice.** A Status select here and the board column the card
  sits in are two controls for one truth.
- **Labels are bare spans** (`<label><span>Title</span><Input/></label>`) with
  no room for a description, a hint, or an error.

## The direction proposed here

Four zones, in the order the work happens, each answering one question:

| Zone | Answers |
| --- | --- |
| **Identity** | what is this story called, and how does it read in a list? Title, subtitle, blurb, slug, with the listing preview beside them and validation on the field itself |
| **Placement** | where does it go? Type, section, desk — and *not* status |
| **The story** | the body and its media, with Edit and Preview as one switch |
| **The record** | versions, what changed, messages, and the references it draws on |

Rules that follow from the newsroom registers:

- One button idiom: the shared `Button`, with `variant` carrying the weight.
- No borders inside the pane. Tone separates zones, as it does in the feed.
- Validation belongs to its field. A summary list may stay, but only as a
  second copy of what each field already says.
- Anything irreversible — publishing, deleting a version — belongs on the full
  page, not in a panel opened from a board.

## Open questions, deliberately unanswered

- Do Messages and References stay as tabs here, or move to the pane that
  already holds them for a reference, so one component covers both subjects?
- Should the embedded panel offer saving a new version at all, or is the board
  a place to read and retitle, with real editing on the full page?
- Status lives on the board column today. If it leaves this pane, does the
  editor lose anything they cannot get by dragging the card?

These change what the component is, not how it looks, so they are worth
settling before any of it is built.
