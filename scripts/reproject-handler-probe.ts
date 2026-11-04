// Runs the post-deploy render handler of the site backend against an event and a fake content-actions function.
// Usage: tsx scripts/reproject-handler-probe.ts '<json: {event, functionError?, payload?}>'  Prints {ok, result|error, invoked}.
import vm from "node:vm";
import { DEPLOY_RENDER_HANDLER_SOURCE } from "../amplify/publication/reproject-on-deploy";

const input = JSON.parse(process.argv[2] ?? "{}");
let invoked = 0;
class LambdaClient {
  async send() {
    invoked += 1;
    return { FunctionError: input.functionError, Payload: Buffer.from(JSON.stringify(input.payload ?? { ok: true })) };
  }
}
class InvokeCommand {}
const module = { exports: {} as Record<string, any> };
const sandbox = {
  module,
  exports: module.exports,
  console: { log() {} },
  Buffer,
  require: (name: string) => {
    if (name === "@aws-sdk/client-lambda") return { LambdaClient, InvokeCommand };
    throw new Error(name);
  },
};
vm.runInNewContext(DEPLOY_RENDER_HANDLER_SOURCE, sandbox);
(async () => {
  try {
    const result = await module.exports.handler(input.event);
    console.log(JSON.stringify({ ok: true, result, invoked }));
  } catch (error) {
    console.log(JSON.stringify({ ok: false, error: String((error as Error).message), invoked }));
  }
})();
