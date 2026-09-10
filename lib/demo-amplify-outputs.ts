import { readAmplifyOutputsFile } from "./amplify-outputs-path";

const DEMO_MARKERS = [
  "demo-user-pool-client-id-not-a-secret",
  "da2-demoapikeynotasecret000000",
  "00000000-demo-4000-8000-000000000000",
] as const;

/** True when amplify_outputs.json is the offline demo stub (see amplify/fixtures/demo-amplify-outputs.json). */
export function isDemoAmplifyOutputs(): boolean {
  const outputs = readAmplifyOutputsFile();
  if (!outputs) return false;
  const serialized = JSON.stringify(outputs);
  return DEMO_MARKERS.some((marker) => serialized.includes(marker));
}
