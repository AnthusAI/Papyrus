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

## Images

Add an image by uploading it in the newsroom. The system prepares the smaller sizes and modern formats it needs in the first seconds after the upload. You can save an article that uses the image straight away; if the sizes are not ready yet, that first save takes a little longer but still works.

Image files are cached by browsers for a long time. If you replace a picture, upload it under a new file name. Re-uploading under the same name can keep showing the old picture to people who saw it before.

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
