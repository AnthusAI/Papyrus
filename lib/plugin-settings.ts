export type PluginOutputs = { custom?: { papyrusPlugins?: Record<string, Record<string, unknown>> } };

/** The settings a deployed plugin published in `amplify_outputs.json`, or null when the site did not enable it. */
export function pluginSettings(outputs: PluginOutputs | null | undefined, name: string): Record<string, unknown> | null {
  return outputs?.custom?.papyrusPlugins?.[name] ?? null;
}

export function signupForms(outputs: PluginOutputs | null | undefined): string[] {
  const forms = pluginSettings(outputs, "signup")?.forms;
  return Array.isArray(forms) ? forms.filter((form): form is string => typeof form === "string") : [];
}
