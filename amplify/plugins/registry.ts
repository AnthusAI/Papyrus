import type { PapyrusPlugin, PluginRequest, PluginResolveOptions } from "./types";
import { homePagePlugin } from "./home-page/papyrus.plugin";
import { newsletterPlugin } from "./newsletter/papyrus.plugin";
import { readerSteeringPlugin } from "./reader-steering/papyrus.plugin";
import { signupPlugin } from "./signup/papyrus.plugin";

/** Plugins are packaged with Papyrus and pinned by its version: there is no registry to fetch from. */
export const KNOWN_PLUGINS: Record<string, PapyrusPlugin<any, any>> = {
  "home-page": homePagePlugin,
  newsletter: newsletterPlugin,
  "reader-steering": readerSteeringPlugin,
  signup: signupPlugin,
};

export type ResolvedPlugin = { plugin: PapyrusPlugin<any, any>; config: unknown };

export function resolvePlugins(requests: PluginRequest[] | undefined, options: PluginResolveOptions = {}): ResolvedPlugin[] {
  const resolved: ResolvedPlugin[] = [];
  for (const request of requests ?? []) {
    const name = typeof request === "string" ? request : request.name;
    const plugin = KNOWN_PLUGINS[name];
    if (plugin === undefined) {
      throw new Error(`Unknown plugin "${name}". Known plugins: ${Object.keys(KNOWN_PLUGINS).join(", ")}`);
    }
    if (resolved.some((entry) => entry.plugin.manifest.name === name)) throw new Error(`Plugin "${name}" is listed twice.`);
    resolved.push({ plugin, config: plugin.resolveConfig(request, options) });
  }
  return resolved;
}
