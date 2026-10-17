import { NestedStack } from "aws-cdk-lib";
import type { IConstruct } from "constructs";

export const DEFAULT_RESOLVER_WAVE_SIZE = 12;

export function planResolverWaves<T>(items: T[], waveSize: number): T[][] {
  if (!Number.isInteger(waveSize) || waveSize < 1) {
    return [];
  }
  const waves: T[][] = [];
  for (let start = 0; start < items.length; start += waveSize) {
    waves.push(items.slice(start, start + waveSize));
  }
  return waves;
}

export function orderModelStacksInWaves(
  graphqlApi: IConstruct,
  modelNames: string[],
  waveSize: number,
): number {
  const modelStacks = modelNames
    .map((modelName) => graphqlApi.node.tryFindChild(modelName))
    .filter((child): child is NestedStack => child instanceof NestedStack);
  const waves = planResolverWaves(modelStacks, waveSize);
  for (let waveIndex = 1; waveIndex < waves.length; waveIndex += 1) {
    for (const stack of waves[waveIndex]) {
      for (const previousStack of waves[waveIndex - 1]) {
        stack.addDependency(previousStack);
      }
    }
  }
  return waves.length;
}
