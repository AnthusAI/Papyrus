/**
 * Runs the deploy-time skill sync by hand (a site's Amplify build runs the same code through `papyrus-app alexa-sync`):
 *
 *   tsx scripts/alexa/ask-deploy.ts [--outputs amplify_outputs.json]
 *
 * It needs AWS credentials for the account that holds the site and the `/papyrus/alexa/*` parameters. Without those
 * parameters it skips with one log line.
 */
import { runCli } from "../../amplify/plugins/alexa/sync/cli";

void runCli(process.argv.slice(2)).then((code) => process.exit(code));
