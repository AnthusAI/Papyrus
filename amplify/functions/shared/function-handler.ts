import { a } from "@aws-amplify/backend";

/**
 * One AppSync Lambda data source per Lambda, not one per field.
 *
 * `a.handler.function(fn)` names every field's function `Fn<FieldName>`, and the @function transformer creates a data
 * source, an IAM role, an IAM policy and two function configurations for each distinct name, all in one nested stack
 * (`FunctionDirectiveStack`). CloudFormation allows 500 resources in a stack, and that stack grows by six resources per
 * Lambda-backed field. Giving every field that calls the same Lambda the same name makes them share one data source,
 * role, policy and function configuration, so each extra field costs only its resolver. The Lambda receives the same
 * event as before (`typeName`, `fieldName`, `arguments`, `identity`), so no handler changes.
 *
 * Every function used this way is registered here and handed to `defineData({ functions })`, which is how Amplify
 * resolves a handler given by name.
 */
/** What `a.handler.function` accepts, and what `defineData({ functions })` takes by name. */
type HandlerFunction = Exclude<Parameters<typeof a.handler.function>[0], string>;

const registered = new Map<string, HandlerFunction>();

/** The shared name for a Lambda: stable, alphanumeric, unique per function. */
export function sharedFunctionName(name: string): string {
  return `Fn${name.charAt(0).toUpperCase()}${name.slice(1)}`;
}

/** A schema handler for `fn` that shares one data source with every other field handled by `fn`. */
export function functionHandler(name: string, fn: HandlerFunction) {
  const shared = sharedFunctionName(name);
  const existing = registered.get(shared);
  if (existing !== undefined && existing !== fn) {
    throw new Error(`Two different functions are registered as "${shared}"`);
  }
  registered.set(shared, fn);
  return a.handler.function(shared);
}

/** Every function that a schema handler refers to by shared name, for `defineData({ functions })`. */
export function sharedFunctions(): Record<string, HandlerFunction> {
  return Object.fromEntries(registered);
}
