import { BOOTSTRAP_DEFERRED_GROUPS, baseModelNames, resolveExcludedModelGroups } from "../amplify/data/schema";

const [configured, environment] = process.argv.slice(2).map((argument) => JSON.parse(argument));
const excluded = resolveExcludedModelGroups(configured, environment);
console.log(JSON.stringify({
  excluded,
  known: BOOTSTRAP_DEFERRED_GROUPS,
  remaining: baseModelNames(excluded as never),
}));
