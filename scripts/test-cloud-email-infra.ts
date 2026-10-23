// Keep the CDK harness within the app-shell package so App, Stack and Template
// resolve the same installed CDK version when that package has its own dependencies.
import { runCloudEmailTests } from "../infra/amplify-app-shell/lib/cloud-email.test";

runCloudEmailTests(process.argv[2]);
