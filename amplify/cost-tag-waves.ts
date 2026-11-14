import { Aspects, CfnOutput, CfnResource, Lazy, Stack, TagManager, type IAspect } from "aws-cdk-lib";
import type { IConstruct } from "constructs";
import { writeFileSync } from "node:fs";
import { COSTED_RESOURCE_TYPES } from "./vendor/anthus-cost-accounting/tags";

/**
 * Cost tags reach a site backend in waves, one CloudFormation operation per wave.
 *
 * CloudFormation refuses a stack operation, nested stacks included, that involves more than 2,500 resources. A site
 * backend has more than that (2,918 on Machines on Machines), and adding a tag updates every stack that holds a tagged
 * resource, so tagging everything at once updated 61 of 62 stacks and rolled back (Papyrus 5.99.0). The backend
 * therefore splits its stacks into waves of at most WAVE_RESOURCE_BUDGET resources. A wave's cost counts every
 * resource of each stack it tags and of each parent stack above them, which CloudFormation updates as well. Wave W
 * tags the stacks of waves 1 to W; `papyrus-infra backend-deploy` runs one `ampx pipeline-deploy` per wave inside one
 * Amplify build and reads how far it got from the root stack output PapyrusCostTagWave.
 *
 * Nested stack resources (AWS::CloudFormation::Stack) are never tagged: CloudFormation copies a stack's tags to every
 * resource in it, which would update a whole child stack in its parent's wave.
 */

/** Set by `papyrus-infra backend-deploy`: a wave number from 1, or "all". Unset, the backend has no cost tags. */
export const COST_TAG_WAVE_VARIABLE = "PAPYRUS_COST_TAG_WAVE";
/** The root stack output that records the wave a deploy reached: "W/N", or "complete". */
export const COST_TAG_WAVE_OUTPUT = "PapyrusCostTagWave";
export const COST_TAG_WAVES_COMPLETE = "complete";
/** CloudFormation's limit on resources in one stack operation, nested stacks included. */
export const STACK_OPERATION_RESOURCE_LIMIT = 2500;
/** A wave pass carries only tags (backend-deploy deploys the release in a pass of its own); 700 resources of margin. */
export const WAVE_RESOURCE_BUDGET = 1800;
/** Tests set this to a file path to read the plan a synth used. */
export const COST_TAG_PLAN_FILE_VARIABLE = "PAPYRUS_COST_TAG_PLAN_FILE";

/** The wave a build asks for: null (no cost tags), a wave number, or Infinity for "all". */
export function costTagWave(env: Record<string, string | undefined> = process.env): number | null {
  const value = env[COST_TAG_WAVE_VARIABLE];
  if (value === undefined || value === "") return null;
  if (value === "all") return Number.POSITIVE_INFINITY;
  if (/^[1-9][0-9]{0,2}$/.test(value)) return Number(value);
  throw new Error(`${COST_TAG_WAVE_VARIABLE} must be a wave number from 1 or "all", not ${JSON.stringify(value)}.`);
}

/** One stack (root or nested) and the resources directly in its template. */
export interface CostTagUnit {
  id: string;
  parentId: string | null;
  resources: number;
  /** Units that change in wave 1 anyway (the usage senders' stacks) go first. */
  first?: boolean;
}

export interface CostTagWavePlan {
  waves: string[][];
  /** Resources in the stacks each wave's operation updates: its own stacks and their parents. */
  costs: number[];
}

/**
 * Packs units into waves, in a stable order (first units, then by id), so that no wave's operation goes over the budget.
 * A unit too big for the budget gets a wave of its own, and the plan fails only past CloudFormation's own limit.
 */
export function planCostTagWaves(units: CostTagUnit[], budget = WAVE_RESOURCE_BUDGET): CostTagWavePlan {
  const byId = new Map(units.map((unit) => [unit.id, unit]));
  const ancestors = (unit: CostTagUnit): CostTagUnit[] => {
    const chain: CostTagUnit[] = [];
    for (let parent = unit.parentId ? byId.get(unit.parentId) : undefined; parent; parent = parent.parentId ? byId.get(parent.parentId) : undefined) chain.push(parent);
    return chain;
  };
  const ordered = [...units].sort((a, b) => Number(Boolean(b.first)) - Number(Boolean(a.first)) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const waves: string[][] = [];
  const costs: number[] = [];
  let wave: string[] = [];
  let touched = new Set<string>();
  let cost = 0;
  const added = (unit: CostTagUnit, seen: Set<string>) => [unit, ...ancestors(unit)].filter((u) => !seen.has(u.id)).reduce((sum, u) => sum + u.resources, 0);
  for (const unit of ordered) {
    let extra = added(unit, touched);
    if (wave.length && cost + extra > budget) {
      waves.push(wave);
      costs.push(cost);
      wave = [];
      touched = new Set();
      cost = 0;
      extra = added(unit, touched);
    }
    if (extra > STACK_OPERATION_RESOURCE_LIMIT) {
      throw new Error(`Stack ${unit.id} and its parents hold ${extra} resources, over CloudFormation's ${STACK_OPERATION_RESOURCE_LIMIT} per operation.`);
    }
    wave.push(unit.id);
    for (const u of [unit, ...ancestors(unit)]) touched.add(u.id);
    cost += extra;
  }
  if (wave.length) {
    waves.push(wave);
    costs.push(cost);
  }
  return { waves, costs };
}

const isNestedStackResource = (node: CfnResource) => node.cfnResourceType === "AWS::CloudFormation::Stack";

/** The units of a construct tree: every stack under the scope, sized by the resources its template will hold. */
export function costTagUnits(scope: Stack, first: Stack[] = []): CostTagUnit[] {
  const stacks = scope.node.findAll().filter((node): node is Stack => Stack.isStack(node));
  const counts = new Map<Stack, number>(stacks.map((stack) => [stack, 1])); // each template also gets AWS::CDK::Metadata
  for (const node of scope.node.findAll()) {
    if (CfnResource.isCfnResource(node)) counts.set(Stack.of(node), (counts.get(Stack.of(node)) ?? 0) + 1);
  }
  const firstPaths = new Set(first.map((stack) => stack.node.path));
  return stacks.map((stack) => {
    const parent = stack === scope ? undefined : stack.nestedStackParent;
    return {
      id: stack.node.path,
      parentId: parent ? parent.node.path : null,
      resources: counts.get(stack) ?? 1,
      ...(firstPaths.has(stack.node.path) ? { first: true } : {}),
    };
  });
}

/**
 * Tags the stacks of waves 1 to `wave` of the backend under `scope`, and records the wave reached in the root stack
 * output. Untaggable costed resources (raw CfnResources CDK writes, such as the bucket auto-delete provider) get the
 * tags written as a property.
 */
export function applyCostTagWaves(scope: Stack, tags: Record<string, string>, wave: number, first: Stack[] = []): void {
  let status = "";
  new CfnOutput(scope, COST_TAG_WAVE_OUTPUT, {
    value: Lazy.string({ produce: () => status }),
    description: "The Prospectus cost tag wave this deploy reached (papyrus-infra backend-deploy).",
  });
  Aspects.of(scope).add(
    new (class implements IAspect {
      visit(node: IConstruct): void {
        if (node !== scope) return;
        const plan = planCostTagWaves(costTagUnits(scope, first));
        const reached = Math.min(wave, plan.waves.length);
        status = reached >= plan.waves.length ? COST_TAG_WAVES_COMPLETE : `${reached}/${plan.waves.length}`;
        const tagged = new Set(plan.waves.slice(0, reached).flat());
        for (const resource of scope.node.findAll()) {
          if (!CfnResource.isCfnResource(resource) || isNestedStackResource(resource) || !tagged.has(Stack.of(resource).node.path)) continue;
          if (TagManager.isTaggable(resource)) {
            for (const [key, value] of Object.entries(tags)) resource.tags.setTag(key, value, 100, true);
          } else if ((COSTED_RESOURCE_TYPES as readonly string[]).includes(resource.cfnResourceType)) {
            resource.addPropertyOverride("Tags", Object.entries(tags).map(([Key, Value]) => ({ Key, Value })));
          }
        }
        const planFile = process.env[COST_TAG_PLAN_FILE_VARIABLE];
        if (planFile) {
          const templates = Object.fromEntries(scope.node.findAll().filter((node): node is Stack => Stack.isStack(node)).map((stack) => [stack.node.path, stack.templateFile]));
          writeFileSync(planFile, JSON.stringify({ ...plan, reached, status, templates }, null, 2));
        }
      }
    })(),
  );
}
