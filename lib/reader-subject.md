# Reader subject

`readerSubject(session)` in `reader-subject.ts` is the only place a reader's identity for the reader API is
decided. It returns the per-site pairwise `siteSubject` (`ss1_` plus 43 base64url characters) that Prospectus
puts on `person.siteSubject`, or `null`.

## Production

Only the `siteSubject` the sealed session cookie carries counts. While Prospectus does not return one, the
accessor returns `null`, every reader route answers `503 reader_identity_unavailable`, and the reader features
stay off. There is no other flag. The global Prospectus person id is never used as a reader key.

## Development and test only

When `SITE_ENV` is `development` or `test`, `NODE_ENV` is not `production` and `PAPYRUS_READER_DEV_SECRET`
holds at least 16 characters, a session without a `siteSubject` gets the interim value
`ssdev_` plus `base64url(HMAC-SHA-256(devSecret, personId))`.

That path never runs in production. No remap from `ssdev_` values to `ss1_` values is ever needed: production
reader writes stay closed until `siteSubject` is live, so no production row is ever keyed on an interim value.
The `reader-actions` function also refuses `ssdev_` subjects unless the site was synthesized with a
development or test `SITE_ENV`.

## Staff

`readerIsStaff(session)` reads the `cognito:groups` claim from the access token inside the sealed session
cookie (`editor` or `admin`). The cookie is written by the site's own callback route, so the token is trusted
the way the rest of the session is. The reader API passes the result to the function as `isStaff`; clients never
send it.
