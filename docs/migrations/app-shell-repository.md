# Connecting the Amplify apps to the site repository

A site can now ask the app shell to set the Amplify repository from `infra/site.json`.
Add `repositoryAccessTokenSecretArn` to the site configuration, pointing at a Secrets
Manager secret that holds a GitHub token. Both Amplify apps then use the site repository,
with the token read through a dynamic reference at deploy time.

Sites that omit the field are unchanged: their Amplify apps stay repository-less and keep
building through the GitHub App connection made in the console.
