/** Fixture identity overrides can never replace production authorization. */
export function testEditorOverrideAllowed(runtime: string | undefined, flag: string | undefined): boolean {
  return runtime === "test" || (runtime === "development" && flag === "true");
}
