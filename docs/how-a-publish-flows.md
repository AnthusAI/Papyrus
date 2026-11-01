# How a publish flows

This page is for editors. It explains what happens when you press a button in the newsroom, and what to do when something looks wrong.

## Save is live

On a Markus site (for example pilobol.us or anth.us), saving a live article puts the change on the website within a few seconds. There is no Republish button and nothing to wait for in the background. When Save finishes, the notice says the item is live and shows its address. Open that address to check it.

What the system does for you on a save:

1. It stores your change.
2. It rewrites the article's page, and only the other pages that show the article: the home page, the lists of articles, tag pages and the sitemap.
3. It tells the website's cache to forget exactly those pages, so visitors get the new version.

If the change is not visible after about a minute, see "If something looks stale" below.

## Drafts, publishing and unpublishing

- **Draft.** A new article starts as a draft. A draft is private. It is not on the website and nobody outside the newsroom can read it. The buttons are **Save draft** and **Publish**.
- **Publish.** Publish makes the article live. The page appears on the site and in the lists, tag pages and sitemap.
- **Save on a live article.** The main button becomes **Save**. It stores your edit and updates the live page in one step.
- **Unpublish.** The page leaves the website and the lists, and its address stops working (visitors see the "not found" page). The article and all its versions stay in the newsroom, and you can publish it again.
- **Changing the address (slug).** The old address redirects to the new one.

## A site can require a person's approval to publish

Each site has a **publish approval** setting, stored as site data in its backend (not in a repository and not in an environment variable). It has two values:

- `not_required` (the default, and what a site has when nothing is stored): publishing works as described above.
- `required`: nothing publishes unless a person approved that version of the article.

When it is `required`:

- **You, publishing from the newsroom, are the approval.** Pressing **Publish**, or **Save** on a live article, is a person's decision, so your own gate never blocks you. If a request for that same version was already waiting in the Notification Center, your publish answers it as approved.
- **Everything else is held for a person.** A publish from the command line (`papyrus ops content publish`), from an automation or procedure, from an import, or from the content-actions function without a signed-in editor does not publish. It raises one **hard gate** review request about that version of the article ("Approve publishing: ...") and stops with the code `approval-required`. Trying again reuses the same request.
- **Approving the request lets the next publish through; it does not publish by itself.** After a person approves it in the Notification Center, the caller publishes the next time it runs (re-run the command or the automation), or an editor presses Publish. Approval covers the words that were approved: if the text changes, the next publish asks again. A rejected version stays unpublished (`approval-rejected`) until its text changes.
- **Unpublishing is never held.** Taking a page off the site needs no approval.
- Changing an address (`papyrus stories set-slug`) republishes the article, so on a `required` site do it in the newsroom.

The operator reads and sets the setting. Writing needs an admin or operator credential, and a dry run writes nothing:

```bash
papyrus ops content publish-gate show [--json]
papyrus ops content publish-gate set --approval required --dry-run
papyrus ops content publish-gate set --approval required        # or not_required
```

It is stored on the `EditorialCheckSettings` row with the id `publish-gate` (editors can read it, only admins write it), so changing it needs no deploy. Review requests are described in [review-requests.md](review-requests.md#the-publish-gate).

## Images

Add an image by uploading it in the newsroom. The system prepares the smaller sizes and modern formats it needs in the first seconds after the upload. You can save an article that uses the image straight away; if the sizes are not ready yet, that first save takes a little longer but still works.

Image files are cached by browsers for a long time. If you replace a picture, upload it under a new file name. Re-uploading under the same name can keep showing the old picture to people who saw it before.

### Dark-mode pictures

To give a picture a dark version, upload it as a second image whose name is the light picture's name with `.dark` before the extension: `figure.png` and `figure.dark.png`. Insert the light image first; uploading a `.dark` file does not add anything to the story, it just sits next to the light file. The page then shows the dark picture to readers in dark mode, following the site's own light/dark switch and, if the reader has not chosen, their device setting. The two files must have the same proportions, or the page build stops with an error naming the image. For a dark file with any other name, write `srcDark="…"` on the image line. See [markus-content-markup.md](markus-content-markup.md#light-and-dark-pictures).

## Some sites work differently

A Pretext site (a newspaper-style site rendered on request, such as p.apyr.us) also updates when you publish, but a page can take up to about two minutes to change for visitors.

## If something looks stale

Try these, in order:

1. Reload the page with a hard refresh (Shift and the reload button; on a phone, open it in a private tab). Your own browser is the most common cause.
2. Open the article in the newsroom and check its state: is it still a draft, or was it unpublished? Save did not run if the page showed an error.
3. Wait two minutes and look again.
4. Save the article again. This is safe: saving the same content again redoes the update.
5. Still wrong? Ask the site's operator (the person who runs the site's AWS account and deployment; for Anth.us sites, Ryan). Tell them the page address, the time you saved, and what you saw. They have two repair commands: one fixes a single missed page, and one re-checks the whole site against the newsroom and repairs anything that is out of date. Neither one changes your content.

If Save says the update did not go live, your change is still saved. The system retries by itself once, and the operator's repair command catches anything it misses.
