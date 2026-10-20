import type { PapyrusPlugin, PluginRequest } from "./types";
import { signupPlugin } from "./signup/papyrus.plugin";

/** Plugins are packaged with Papyrus and pinned by its version: there is no registry to fetch from. */
export const KNOWN_PLUGINS: Record<string, PapyrusPlugin<any, any>> = {
  signup: signupPlugin,
};

export type ResolvedPlugin = { plugin: PapyrusPlugin<any, any>; config: unknown };

export function resolvePlugins(requests: PluginRequest[] | undefined): ResolvedPlugin[] {
  const resolved: ResolvedPlugin[] = [];
  for (const request of requests ?? []) {
    const name = typeof request === "string" ? request : request.name;
    const plugin = KNOWN_PLUGINS[name];
    if (plugin === undefined) {
      throw new Error(`Unknown plugin "${name}". Known plugins: ${Object.keys(KNOWN_PLUGINS).join(", ")}`);
    }
    if (resolved.some((entry) => entry.plugin.manifest.name === name)) throw new Error(`Plugin "${name}" is listed twice.`);
    resolved.push({ plugin, config: plugin.resolveConfig(request) });
  }
  return resolved;
}
