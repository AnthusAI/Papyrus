import type { CliLoginDocument } from "./cli-login-discovery";

/** The Python package that installs the `papyrus` command (docs/cli-login.md, "Install the CLI"). */
export const CLI_INSTALL_COMMAND = "pipx install papyrus-newsroom";
export const CLI_INSTALL_ALTERNATIVE = "uv tool install papyrus-newsroom";
/** Where the console page lives, under the settings area. */
export const CONNECT_CLI_PATH = "/newsroom/settings/connect";

export type CliConnectPlan = {
  /** The site as the CLI wants it: the host of the `publication` the discovery file names, so a console on its own host is right. */
  site: string;
  install: string;
  browserCommand: string;
  /** Null unless the site's discovery values name a broker (cliRemoteLogin on). */
  remoteCommand: string | null;
  checkCommand: string;
};

/** The commands for one site, built only from the values `/.well-known/papyrus-cli.json` publishes. Null when it publishes none. */
export function cliConnectPlan(document: CliLoginDocument | null): CliConnectPlan | null {
  if (!document) return null;
  let site: string;
  try {
    site = new URL(document.publication).host;
  } catch {
    return null;
  }
  return {
    site,
    install: CLI_INSTALL_COMMAND,
    browserCommand: `papyrus login ${site}`,
    remoteCommand: document.broker_endpoint ? `papyrus login --remote ${site}` : null,
    checkCommand: `papyrus whoami ${site}`,
  };
}
