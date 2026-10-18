# Tenant-scoped ids rollout

Tenant-scoped ids (PR 327) change how records are keyed, so records written before the
change are not visible to a site until they are adopted into their tenant.

Order of operations for each site:

1. Release Papyrus and bump the site to the new version.
2. The site's Amplify build runs `npx ampx pipeline-deploy`, which deploys the backend
   schema with the new tenant fields.
3. Run the adopt-tenant-data migration in dry-run mode, review the report, then run it
   for real.

Until step 3 finishes, existing stories on a site appear missing even though they are
still stored.
