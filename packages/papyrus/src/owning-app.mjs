export const OWNING_APP_ID_VARIABLE = "PAPYRUS_AMPLIFY_APP_ID";

/**
 * The Amplify app that owns a stack, for the `deploy` and `deploy-edge` guards.
 *
 * - `PAPYRUS_AMPLIFY_APP_ID`, when set, is the owning app (so the id need not be written in a site repository).
 * - Otherwise `--only-app-id ID` is used, exactly as before.
 * - A site that passes `--only-app-id` has opted in to the guard. If no value is left (the flag has an empty value,
 *   which is what `--only-app-id "$PAPYRUS_AMPLIFY_APP_ID"` gives when the variable is unset) this throws, so the
 *   build fails closed instead of deploying from whichever app happens to run it.
 * - With neither the flag nor the variable there is no guard, as before.
 */
export function resolveOwningAppId({ args, environment = process.env }) {
  const fromEnvironment = String(environment[OWNING_APP_ID_VARIABLE] ?? "").trim();
  if (fromEnvironment) return fromEnvironment;
  const index = args.indexOf("--only-app-id");
  if (index < 0) return undefined;
  const value = String(args[index + 1] ?? "").trim();
  if (!value || value.startsWith("--")) {
    throw new Error(`--only-app-id has no value and ${OWNING_APP_ID_VARIABLE} is not set: set ${OWNING_APP_ID_VARIABLE} on this Amplify branch to the id of the app that owns the stack. Nothing was deployed`);
  }
  return value;
}
