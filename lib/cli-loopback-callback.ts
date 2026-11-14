/**
 * The one fixed loopback callback the CLI binds when it signs in on a site's registered Prospectus federation client.
 * Cognito matches callback URLs exactly, so the port and path are fixed and unassigned; the CLI refuses to start a login
 * if the port is taken (docs/cli-login.md "Which client"). Kept free of imports so the backend and the site can share it.
 */
export const CLI_LOOPBACK_CALLBACK = "http://127.0.0.1:38947/cli/callback";
export const CLI_REMOTE_CALLBACK_PATH = "/cli/callback";
