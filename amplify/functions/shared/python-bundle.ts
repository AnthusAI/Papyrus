import { AssetHashType, DockerImage } from "aws-cdk-lib";
import { Code, Runtime } from "aws-cdk-lib/aws-lambda";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

/**
 * Python Lambda bundling that works both in a Papyrus checkout and when
 * `@anthusai/papyrus` is installed from npm into a publication repo.
 *
 * - Checkout mode (`src/` exists next to `amplify/`, default in the Papyrus
 *   repo): copy `src/<module>` into the asset, as before.
 * - Package mode (no `src/`, or PAPYRUS_BUNDLE_FROM_PIP=1): the asset is
 *   `pip install papyrus-newsroom==<this package's version>` plus the
 *   function's requirements, targeted at the Lambda platform (linux aarch64,
 *   CPython 3.12, binary wheels only); the handler is copied from this package.
 *
 * PAPYRUS_PIP_EXTRA_ARGS lets a site point pip at a private index or a local
 * wheel directory (e.g. `--find-links ./vendor`).
 */
const here = path.dirname(fileURLToPath(import.meta.url));
export const packageRoot = path.resolve(here, "../../..");

export function isPackageMode(): boolean {
  if (process.env.PAPYRUS_BUNDLE_FROM_PIP === "1") return true;
  return !fs.existsSync(path.join(packageRoot, "src", "papyrus_content"));
}

/** Lockstep version: the npm package's own version is the Python pin. */
export function papyrusVersion(): string {
  const pkg = JSON.parse(fs.readFileSync(path.join(packageRoot, "package.json"), "utf8")) as { version: string };
  return pkg.version;
}

/**
 * semver -> PEP 440. `1.2.0-next.3` is not a valid Python version; Semantic
 * Release prereleases (`-next.N`) map to dev releases (`1.2.0.dev3`), which sort
 * before the final release exactly like semver prereleases do.
 */
export function toPep440(version: string): string {
  const m = /^(\d+\.\d+\.\d+)(?:-[0-9A-Za-z-]+\.(\d+))?$/.exec(version);
  if (!m) throw new Error(`Cannot map ${version} to a PEP 440 version`);
  return m[2] === undefined ? m[1] : `${m[1]}.dev${m[2]}`;
}

export type PythonBundleOptions = {
  /** Directory under `amplify/functions/` holding `handler.py`. */
  functionDir: string;
  /** `src/` modules to copy in checkout mode. */
  modules: string[];
  /** Run extra checkout-mode steps (e.g. copy corpora, pip install -r). */
  checkoutExtras?: (outputDir: string) => void;
  /** Extra pip requirements in package mode, beyond `papyrus-newsroom`. */
  requirements?: string[];
  /** Copy `<cwd>/corpora/*.yml` into the asset (publication-owned steering config). */
  corpora?: boolean;
};

function pipSpec(): string {
  return (process.env.PAPYRUS_PIP_SPEC ?? "").trim() || `papyrus-newsroom==${toPep440(papyrusVersion())}`;
}

function bundleFromPip(outputDir: string, options: PythonBundleOptions): void {
  const extra = (process.env.PAPYRUS_PIP_EXTRA_ARGS ?? "").trim().split(/\s+/).filter(Boolean);
  const python = (process.env.PAPYRUS_PIP_PYTHON ?? "python3").trim();
  execFileSync(
    python,
    [
      "-m", "pip", "install",
      "--target", outputDir,
      "--no-cache-dir",
      "--platform", "manylinux2014_aarch64",
      "--implementation", "cp",
      "--python-version", "3.12",
      "--only-binary=:all:",
      // Older pip (e.g. a Python 3.9 build image) checks Requires-Python against the host interpreter, not --python-version.
      "--ignore-requires-python",
      ...extra,
      pipSpec(),
      ...(options.requirements ?? []),
    ],
    { stdio: "inherit" },
  );
  fs.copyFileSync(
    path.join(packageRoot, "amplify/functions", options.functionDir, "handler.py"),
    path.join(outputDir, "handler.py"),
  );
  if (options.corpora) {
    const corporaDir = path.join(outputDir, "corpora");
    fs.mkdirSync(corporaDir, { recursive: true });
    const sourceDir = path.join(process.cwd(), "corpora");
    if (fs.existsSync(sourceDir)) {
      for (const entry of fs.readdirSync(sourceDir)) {
        if (entry.endsWith(".yml")) fs.copyFileSync(path.join(sourceDir, entry), path.join(corporaDir, entry));
      }
    }
  }
}

function bundleFromCheckout(outputDir: string, options: PythonBundleOptions): void {
  fs.copyFileSync(
    path.join(packageRoot, "amplify/functions", options.functionDir, "handler.py"),
    path.join(outputDir, "handler.py"),
  );
  for (const module of options.modules) {
    fs.mkdirSync(path.join(outputDir, module), { recursive: true });
    fs.cpSync(path.join(packageRoot, "src", module), path.join(outputDir, module), { recursive: true });
  }
  options.checkoutExtras?.(outputDir);
}

/**
 * CDK Code for a Python Lambda. In package mode the asset hash is derived
 * from the pinned version and pip spec instead of hashing the package root.
 */
export function pythonLambdaCode(options: PythonBundleOptions, dockerCommand: string[]): Code {
  const packageMode = isPackageMode();
  return Code.fromAsset(packageRoot, {
    ...(packageMode
      ? {
          assetHashType: AssetHashType.CUSTOM,
          assetHash: `${options.functionDir}:${pipSpec()}:${(options.requirements ?? []).join(",")}`
            .replace(/[^a-zA-Z0-9._:=,-]/g, "_"),
        }
      : {}),
    bundling: {
      image: Runtime.PYTHON_3_12.bundlingImage ?? DockerImage.fromRegistry("public.ecr.aws/sam/build-python3.12"),
      local: {
        tryBundle(outputDir: string): boolean {
          if (packageMode) bundleFromPip(outputDir, options);
          else bundleFromCheckout(outputDir, options);
          return true;
        },
      },
      command: packageMode
        ? ["bash", "-c", "echo 'Package-mode Python bundling runs locally (pip on the build host).' >&2; exit 1"]
        : dockerCommand,
    },
  });
}
