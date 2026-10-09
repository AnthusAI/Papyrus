function collectEntryTargets(value, targets) {
  if (typeof value === "string") targets.push(value);
  else if (Array.isArray(value)) for (const item of value) collectEntryTargets(item, targets);
  else if (value && typeof value === "object") for (const item of Object.values(value)) collectEntryTargets(item, targets);
}

const TYPESCRIPT_SOURCE_TARGET = /\.(ts|tsx|mts|cts)$/;
const DECLARATION_TARGET = /\.d\.(ts|mts|cts)$/;

export function packageShipsTypeScriptSourceEntries(packageJson) {
  const targets = [];
  for (const field of ["exports", "main", "module"]) collectEntryTargets(packageJson[field], targets);
  return targets.some((target) => TYPESCRIPT_SOURCE_TARGET.test(target) && !DECLARATION_TARGET.test(target));
}
