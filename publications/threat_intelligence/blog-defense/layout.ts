import {
  BLOG_DEFENSE_CORE_NODE_ID,
  BLOG_DEFENSE_EDGES,
  BLOG_DEFENSE_NODES,
  BLOG_DEFENSE_VIEWBOX_HEIGHT,
  BLOG_DEFENSE_VIEWBOX_WIDTH,
  type BlogDefenseEdge,
  type BlogDefenseNode,
} from "./graph";

export type LayoutRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type LayoutDefenseGraphInput = {
  width: number;
  height: number;
  obstacles?: LayoutRect[];
  padX?: number;
  padTop?: number;
  padBottom?: number;
};

export type LayoutDefenseNode = BlogDefenseNode;

export type LayoutDefenseEdge = {
  id: string;
  from: string;
  to: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

export type LayoutDefenseGraphResult = {
  nodes: LayoutDefenseNode[];
  edges: LayoutDefenseEdge[];
  scale: number;
};

function uniformNodeRadius(scale: number): number {
  return Math.max(4.4, scale * 6);
}

const RIGHT_ARM_BASE_CANDIDATE_IDS = ["right_attach_bottom", "right_c0"] as const;
const LEFT_ARM_ATTACH_CANDIDATE_IDS = [
  "left_bridge_top",
  "left_attach_top",
  "left_attach_bottom",
  "left_a0",
  "left_b0",
  "left_c0",
] as const;
const LEFT_ARM_CORE_TARGET_IDS = [
  "halo_nw",
  "halo_n",
  "halo_w",
] as const;
const LEFT_ARM_ROW_NODE_IDS = [
  ["left_tail_4", "left_tail_3", "left_tail_2", "left_tail_1", "left_tip", "left_a3", "left_a2", "left_a1", "left_a0", "left_bridge_top"],
  ["left_b3", "left_b0", "left_attach_top"],
  ["left_c3", "left_c0", "left_attach_bottom"],
] as const;
const RIGHT_ARM_CORE_TARGET_IDS = [
  "halo_e",
  "halo_se",
  "halo_s",
  "halo_sw",
] as const;
const RIGHT_ARM_ROW_NODE_IDS = [
  ["right_c0", "right_b0", "right_a0"],
  ["right_attach_bottom", "right_c1", "right_b1", "right_a1"],
  ["right_c2", "right_b2", "right_a2"],
  ["right_c3", "right_b3", "right_a3"],
  ["right_c4", "right_b4", "right_a4"],
  ["right_c5", "right_b5", "right_a5"],
] as const;

function pointInRect(x: number, y: number, rect: LayoutRect, inflate = 0): boolean {
  return x >= rect.x - inflate
    && x <= rect.x + rect.width + inflate
    && y >= rect.y - inflate
    && y <= rect.y + rect.height + inflate;
}

function orientation(ax: number, ay: number, bx: number, by: number, cx: number, cy: number): number {
  const value = (by - ay) * (cx - bx) - (bx - ax) * (cy - by);
  if (Math.abs(value) < 0.0001) return 0;
  return value > 0 ? 1 : 2;
}

function onSegment(ax: number, ay: number, bx: number, by: number, cx: number, cy: number): boolean {
  return bx <= Math.max(ax, cx) + 0.0001
    && bx + 0.0001 >= Math.min(ax, cx)
    && by <= Math.max(ay, cy) + 0.0001
    && by + 0.0001 >= Math.min(ay, cy);
}

function segmentsIntersect(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  x3: number,
  y3: number,
  x4: number,
  y4: number,
): boolean {
  const o1 = orientation(x1, y1, x2, y2, x3, y3);
  const o2 = orientation(x1, y1, x2, y2, x4, y4);
  const o3 = orientation(x3, y3, x4, y4, x1, y1);
  const o4 = orientation(x3, y3, x4, y4, x2, y2);
  if (o1 !== o2 && o3 !== o4) return true;
  if (o1 === 0 && onSegment(x1, y1, x3, y3, x2, y2)) return true;
  if (o2 === 0 && onSegment(x1, y1, x4, y4, x2, y2)) return true;
  if (o3 === 0 && onSegment(x3, y3, x1, y1, x4, y4)) return true;
  if (o4 === 0 && onSegment(x3, y3, x2, y2, x4, y4)) return true;
  return false;
}

function segmentIntersectsRect(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  rect: LayoutRect,
  inflate = 0,
): boolean {
  const inflated = {
    x: rect.x - inflate,
    y: rect.y - inflate,
    width: rect.width + inflate * 2,
    height: rect.height + inflate * 2,
  };
  if (pointInRect(x1, y1, inflated) || pointInRect(x2, y2, inflated)) return true;
  const left = inflated.x;
  const right = inflated.x + inflated.width;
  const top = inflated.y;
  const bottom = inflated.y + inflated.height;
  return segmentsIntersect(x1, y1, x2, y2, left, top, right, top)
    || segmentsIntersect(x1, y1, x2, y2, right, top, right, bottom)
    || segmentsIntersect(x1, y1, x2, y2, right, bottom, left, bottom)
    || segmentsIntersect(x1, y1, x2, y2, left, bottom, left, top);
}

function edgeIntersectsObstacles(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  obstacles: LayoutRect[],
): boolean {
  return obstacles.some((obstacle) => segmentIntersectsRect(x1, y1, x2, y2, obstacle, 2));
}

function nodeIntersectsObstacles(
  x: number,
  y: number,
  radius: number,
  obstacles: LayoutRect[],
): boolean {
  return obstacles.some((obstacle) => {
    const nearestX = Math.max(obstacle.x, Math.min(x, obstacle.x + obstacle.width));
    const nearestY = Math.max(obstacle.y, Math.min(y, obstacle.y + obstacle.height));
    const dx = x - nearestX;
    const dy = y - nearestY;
    return (dx * dx) + (dy * dy) <= (radius * radius);
  });
}

function coreAnchor(
  width: number,
  height: number,
  padX: number,
  scale: number,
  coreNode: BlogDefenseNode,
): { x: number; y: number } {
  const coreZoneNodes = BLOG_DEFENSE_NODES.filter((node) => node.zone === "core");
  const maxCoreDx = coreZoneNodes.reduce((maxDx, node) => Math.max(maxDx, node.x - coreNode.x), 0);
  const rightAlignedX = width - padX - maxCoreDx * scale;
  return {
    x: rightAlignedX,
    y: Math.max(76, Math.min(height * 0.24, 208)),
  };
}

function bestCoreAnchor(input: {
  width: number;
  height: number;
  padX: number;
  padTop: number;
  padBottom: number;
  scale: number;
  coreNode: BlogDefenseNode;
  nodeRadius: number;
  obstacles: LayoutRect[];
}): { x: number; y: number } {
  const {
    width,
    height,
    padX,
    padTop,
    padBottom,
    scale,
    coreNode,
    nodeRadius,
    obstacles,
  } = input;
  const base = coreAnchor(width, height, padX, scale, coreNode);
  if (!obstacles.length) return base;

  const coreZoneNodes = BLOG_DEFENSE_NODES.filter((node) => node.zone === "core");
  const maxAnchorX = width - padX - nodeRadius;
  const step = Math.max(4, Math.round(width * 0.012));
  let best = base;
  let bestScore = -Infinity;

  for (let x = base.x; x <= maxAnchorX + 0.001; x += step) {
    let score = 0;
    for (const node of coreZoneNodes) {
      const candidateX = x + (node.x - coreNode.x) * scale;
      const candidateY = base.y + (node.y - coreNode.y) * scale;
      const inBounds = candidateX > padX + nodeRadius
        && candidateX < width - padX - nodeRadius
        && candidateY > padTop + nodeRadius
        && candidateY < height - padBottom - nodeRadius;
      if (!inBounds) continue;
      if (nodeIntersectsObstacles(candidateX, candidateY, nodeRadius + 2, obstacles)) continue;
      score += node.id === BLOG_DEFENSE_CORE_NODE_ID ? 100 : 1;
    }

    const distancePenalty = Math.abs(x - base.x) / Math.max(1, width);
    const adjustedScore = score - distancePenalty;
    if (adjustedScore > bestScore) {
      bestScore = adjustedScore;
      best = { x, y: base.y };
    }
  }

  return best;
}

function bestCorridorX(
  width: number,
  height: number,
  padX: number,
  padTop: number,
  padBottom: number,
  scale: number,
  coreNode: BlogDefenseNode,
  anchor: { x: number; y: number },
  obstacles: LayoutRect[],
): number {
  const preferred = width - padX - Math.max(12, 22 * scale);
  const minX = Math.max(padX + 10, preferred - Math.max(40, width * 0.13));
  const maxX = preferred;
  const step = Math.max(6, Math.round(width * 0.01));
  let bestX = preferred;
  let bestScore = -1;

  for (let x = maxX; x >= minX; x -= step) {
    let clearCount = 0;
    for (const node of BLOG_DEFENSE_NODES) {
      if (node.zone !== "right_corridor") continue;
      const dy = node.y - coreNode.y;
      const y = Math.min(
        height - padBottom - node.radius * scale,
        Math.max(padTop + node.radius * scale, anchor.y + dy * scale),
      );
      const blocked = obstacles.some((obstacle) => pointInRect(x, y, obstacle, node.radius * scale + 2));
      if (!blocked) clearCount += 1;
    }
    if (clearCount > bestScore || (clearCount === bestScore && x > bestX)) {
      bestScore = clearCount;
      bestX = x;
    }
  }

  return bestX;
}

function templateNodeById(id: string): BlogDefenseNode | undefined {
  return BLOG_DEFENSE_NODES.find((node) => node.id === id);
}

function normalizeAngle(angle: number): number {
  while (angle > Math.PI) angle -= Math.PI * 2;
  while (angle < -Math.PI) angle += Math.PI * 2;
  return angle;
}

function buildEdgeRecord(from: LayoutDefenseNode, to: LayoutDefenseNode, id: string): LayoutDefenseEdge {
  return {
    id,
    from: from.id,
    to: to.id,
    x1: from.x,
    y1: from.y,
    x2: to.x,
    y2: to.y,
  };
}

function keepNodeOutsideCoreEnvelope(input: {
  nextX: number;
  nextY: number;
  node: LayoutDefenseNode;
  coreCenter?: LayoutDefenseNode;
  outerCoreRadius: number;
  preferredHorizontalDirection: -1 | 1;
}): { x: number; y: number } {
  const {
    nextX,
    nextY,
    node,
    coreCenter,
    outerCoreRadius,
    preferredHorizontalDirection,
  } = input;
  if (!coreCenter) {
    return { x: nextX, y: nextY };
  }

  const clearance = Math.max(4, node.radius * 0.5);
  const minDistanceFromCore = outerCoreRadius + node.radius + clearance;
  const dx = nextX - coreCenter.x;
  const dy = nextY - coreCenter.y;
  const distance = Math.hypot(dx, dy);
  if (distance >= minDistanceFromCore) {
    return { x: nextX, y: nextY };
  }

  const verticalDistance = Math.abs(dy);
  if (verticalDistance < minDistanceFromCore) {
    const horizontalDistance = Math.sqrt((minDistanceFromCore ** 2) - (verticalDistance ** 2));
    return {
      x: coreCenter.x + preferredHorizontalDirection * horizontalDistance,
      y: nextY,
    };
  }

  const ux = distance > 0.0001 ? dx / distance : preferredHorizontalDirection;
  const uy = distance > 0.0001 ? dy / distance : 0;
  return {
    x: coreCenter.x + ux * minDistanceFromCore,
    y: coreCenter.y + uy * minDistanceFromCore,
  };
}

function leftArmIrregularityOffset(nodeId: string, rowIndex: number, scale: number): number {
  if (rowIndex === 0) {
    const offsets: Record<string, number> = {
      left_tail_4: -24,
      left_tail_3: -18,
      left_tail_2: -12,
      left_tail_1: -7,
      left_tip: -2,
      left_a3: 1,
      left_a2: 2,
      left_a1: 5,
      left_a0: 1,
      left_bridge_top: 14,
    };
    return (offsets[nodeId] ?? 0) * scale;
  }

  if (rowIndex === 1) {
    const offsets: Record<string, number> = {
      left_b3: -10,
      left_b0: -4,
      left_attach_top: 12,
    };
    return (offsets[nodeId] ?? 0) * scale;
  }

  const offsets: Record<string, number> = {
    left_c3: -7,
    left_c0: -3,
    left_attach_bottom: 11,
  };
  return (offsets[nodeId] ?? 0) * scale;
}

function layoutLeftArmRows(input: {
  coreNodes: LayoutDefenseNode[];
  leftArmNodes: LayoutDefenseNode[];
  positionedNodes: Map<string, LayoutDefenseNode>;
  padX: number;
  padTop: number;
  scale: number;
  coreCenter?: LayoutDefenseNode;
}): void {
  const {
    coreNodes,
    leftArmNodes,
    positionedNodes,
    padX,
    padTop,
    scale,
    coreCenter,
  } = input;

  if (!leftArmNodes.length) return;

  const coreLeftEdge = coreNodes.reduce((min, node) => Math.min(min, node.x - node.radius), Infinity);
  const coreTopY = coreNodes.reduce((min, node) => Math.min(min, node.y), Infinity);
  const outerCoreRadius = coreCenter
    ? coreNodes.reduce((maxRadius, node) => (
      Math.max(maxRadius, Math.hypot(node.x - coreCenter.x, node.y - coreCenter.y) + node.radius)
    ), 0)
    : 0;

  const visibleRows = LEFT_ARM_ROW_NODE_IDS
    .map((rowIds, templateIndex) => ({
      templateIndex,
      nodes: rowIds
        .map((id) => positionedNodes.get(id))
        .filter((node): node is LayoutDefenseNode => Boolean(node)),
      fullIds: [...rowIds] as string[],
    }))
    .filter((row) => row.nodes.length > 0);
  if (!visibleRows.length) return;

  const topRow = visibleRows[0];
  const topRightNode = topRow.nodes
    .slice()
    .sort((left, right) => right.x - left.x)[0];
  const topRowY = Math.max(padTop + (topRightNode?.radius ?? 0), coreTopY);
  const rowGap = Math.max(20 * scale, Math.min(34 * scale, outerCoreRadius * 0.32));
  const topRowLeft = topRow.nodes.reduce((min, node) => Math.min(min, node.x), Infinity) - (62 * scale);
  const topRowRight = topRightNode?.x ?? coreLeftEdge - (10 * scale);
  const topRowWidth = Math.max(12 * scale, topRowRight - topRowLeft);

  for (let visibleIndex = 0; visibleIndex < visibleRows.length; visibleIndex += 1) {
    const row = visibleRows[visibleIndex];
    const rowY = topRowY + rowGap * visibleIndex;
    const slotCount = row.fullIds.length;
    const rawRowLeft = row.nodes.reduce((min, node) => Math.min(min, node.x), Infinity);
    const rawRowRight = row.nodes.reduce((max, node) => Math.max(max, node.x), -Infinity);
    const rawRowWidth = Math.max(1, rawRowRight - rawRowLeft);
    const rowRightNode = row.nodes
      .slice()
      .sort((left, right) => right.x - left.x)[0];
    const rowRightCenter = visibleIndex === 0
      ? topRowRight
      : Math.min(
        rowRightNode?.x ?? (coreLeftEdge - (10 * scale)),
        coreLeftEdge - Math.max(8 * scale, (rowRightNode?.radius ?? 0) + (4 * scale)),
      );
    const taperInset = visibleIndex === 0 ? 0 : topRowWidth * (0.16 + (visibleIndex - 1) * 0.07);
    const currentRowLeft = rawRowLeft;
    const monotonicLeft = topRowLeft + taperInset;
    const rowLeftCenter = Math.min(
      rowRightCenter - Math.max(10 * scale, row.nodes[0]?.radius ?? 0),
      Math.max(
        padX + (row.nodes[0]?.radius ?? 0),
        visibleIndex === 0
          ? Math.min(currentRowLeft - (10 * scale), monotonicLeft)
          : Math.max(currentRowLeft - (4 * scale), monotonicLeft),
      ),
    );
    const rowSpan = Math.max(1, rowRightCenter - rowLeftCenter);
    const templateBlend = visibleIndex === 0 ? 0.76 : visibleIndex === 1 ? 0.56 : 0.42;

    for (const node of row.nodes) {
      const slotIndex = row.fullIds.indexOf(node.id);
      if (slotIndex < 0) continue;
      const slotProgress = slotCount === 1 ? 1 : slotIndex / (slotCount - 1);
      const rawProgress = rawRowWidth <= 1 ? slotProgress : (node.x - rawRowLeft) / rawRowWidth;
      let blendedProgress = (slotProgress * (1 - templateBlend)) + (rawProgress * templateBlend);
      if (visibleIndex === 0) {
        if (slotProgress <= 0.45) blendedProgress -= 0.03;
        if (slotProgress >= 0.82) blendedProgress += 0.015;
      } else if (visibleIndex === 1) {
        if (slotProgress <= 0.3) blendedProgress -= 0.02;
        if (slotProgress >= 0.72) blendedProgress += 0.02;
      } else {
        if (slotProgress <= 0.35) blendedProgress -= 0.015;
      }
      blendedProgress = Math.max(0, Math.min(1, blendedProgress));
      let nextX = rowLeftCenter + rowSpan * blendedProgress + leftArmIrregularityOffset(node.id, visibleIndex, scale);
      let nextY = rowY;

      const outsideCore = keepNodeOutsideCoreEnvelope({
        nextX,
        nextY,
        node,
        coreCenter,
        outerCoreRadius,
        preferredHorizontalDirection: -1,
      });
      nextX = outsideCore.x;
      nextY = outsideCore.y;

      positionedNodes.set(node.id, {
        ...node,
        x: Math.max(padX + node.radius, nextX),
        y: Math.max(padTop + node.radius, nextY),
      });
    }
  }
}

function layoutRightArmRows(input: {
  coreNodes: LayoutDefenseNode[];
  rightArmNodes: LayoutDefenseNode[];
  positionedNodes: Map<string, LayoutDefenseNode>;
  padX: number;
  padTop: number;
  padBottom: number;
  height: number;
  scale: number;
  coreCenter?: LayoutDefenseNode;
}): void {
  const {
    coreNodes,
    rightArmNodes,
    positionedNodes,
    padX,
    padTop,
    padBottom,
    height,
    scale,
    coreCenter,
  } = input;
  const drawableNodes = rightArmNodes.filter((node) => !node.id.startsWith("right_bridge_"));
  if (!drawableNodes.length) return;

  const coreRightEdge = coreNodes.reduce((max, node) => Math.max(max, node.x + node.radius), -Infinity);
  const coreLeftEdge = coreNodes.reduce((min, node) => Math.min(min, node.x - node.radius), Infinity);
  const baseEnvelopeWidth = Math.max(16, (coreRightEdge - coreLeftEdge) * 0.82);
  const outerCoreRadius = coreCenter
    ? coreNodes.reduce((maxRadius, node) => (
      Math.max(maxRadius, Math.hypot(node.x - coreCenter.x, node.y - coreCenter.y) + node.radius)
    ), 0)
    : 0;
  const minRadius = drawableNodes.reduce((min, node) => Math.min(min, node.radius), Infinity);
  const tailWidthTarget = Math.max(2.2 * scale, minRadius * 2);

  const visibleRows = RIGHT_ARM_ROW_NODE_IDS
    .map((rowIds, templateIndex) => ({
      templateIndex,
      nodes: rowIds
        .map((id) => positionedNodes.get(id))
        .filter((node): node is LayoutDefenseNode => Boolean(node)),
      fullIds: [...rowIds] as string[],
    }))
    .filter((row) => row.nodes.length > 0);
  if (!visibleRows.length) return;

  const topY = visibleRows.reduce((min, row) => Math.min(min, ...row.nodes.map((node) => node.y)), Infinity);
  const bottomY = visibleRows.reduce((max, row) => Math.max(max, ...row.nodes.map((node) => node.y)), -Infinity);
  const rowSpan = Math.max(1, bottomY - topY);
  const rowGap = visibleRows.length === 1 ? 0 : rowSpan / (visibleRows.length - 1);
  const rowTilt = Math.min(Math.max(10 * scale, rowGap * 0.44), 24 * scale);

  for (let visibleIndex = 0; visibleIndex < visibleRows.length; visibleIndex += 1) {
    const row = visibleRows[visibleIndex];
    const rowProgress = visibleRows.length === 1 ? 0 : visibleIndex / (visibleRows.length - 1);
    const rowWidth = baseEnvelopeWidth - (baseEnvelopeWidth - tailWidthTarget) * rowProgress;
    const rowY = topY + rowSpan * rowProgress;
    const slotCount = row.fullIds.length;

    for (const node of row.nodes) {
      const slotIndex = row.fullIds.indexOf(node.id);
      if (slotIndex < 0) continue;
      const slotProgress = slotCount === 1 ? 1 : slotIndex / (slotCount - 1);
      const rowRightCenter = coreRightEdge - node.radius;
      const rowLeftCenter = Math.max(padX + node.radius, rowRightCenter - rowWidth);
      let nextX = rowLeftCenter + (rowRightCenter - rowLeftCenter) * slotProgress;
      const slotOffset = slotCount === 1 ? 0 : ((slotProgress - 0.5) * rowTilt);
      let nextY = rowY + slotOffset;

      if (node.id === "right_c0") {
        nextX += 112 * scale;
        nextY += 118 * scale;
      }

      if (coreCenter) {
        const clearance = Math.max(4 * scale, 3);
        const minDistanceFromCore = outerCoreRadius + node.radius + clearance;
        const dx = nextX - coreCenter.x;
        const dy = nextY - coreCenter.y;
        const distance = Math.hypot(dx, dy);
        if (distance < minDistanceFromCore) {
          const verticalDistance = Math.abs(dy);
          if (verticalDistance < minDistanceFromCore) {
            const horizontalDistance = Math.sqrt((minDistanceFromCore ** 2) - (verticalDistance ** 2));
            const direction = dx <= 0 ? -1 : 1;
            nextX = coreCenter.x + direction * horizontalDistance;
          } else {
            const ux = distance > 0.0001 ? dx / distance : 1;
            const uy = distance > 0.0001 ? dy / distance : 0;
            nextX = coreCenter.x + ux * minDistanceFromCore;
            nextY = coreCenter.y + uy * minDistanceFromCore;
          }
        }
      }

      nextX = Math.min(Math.max(nextX, padX + node.radius), coreRightEdge - node.radius);
      nextY = Math.min(height - padBottom - node.radius, Math.max(padTop + node.radius, nextY));
      positionedNodes.set(node.id, {
        ...node,
        x: nextX,
        y: nextY,
      });
    }
  }

  for (const node of rightArmNodes.filter((candidate) => candidate.id.startsWith("right_bridge_"))) {
    positionedNodes.set(node.id, {
      ...node,
      x: Math.min(node.x, coreRightEdge - node.radius),
    });
  }
}

type BuildRightArmAttachmentEdgesInput = {
  positionedNodes: Map<string, LayoutDefenseNode>;
  coreCenter: LayoutDefenseNode;
  obstacles: LayoutRect[];
  usedEdgeIds: Set<string>;
};

function buildRightArmAttachmentEdges(input: BuildRightArmAttachmentEdgesInput): LayoutDefenseEdge[] {
  const { positionedNodes, coreCenter, obstacles, usedEdgeIds } = input;
  const candidateNodes = RIGHT_ARM_BASE_CANDIDATE_IDS
    .map((id) => positionedNodes.get(id))
    .filter((node): node is LayoutDefenseNode => Boolean(node));
  const preferredExtraCandidateIds = RIGHT_ARM_ROW_NODE_IDS[1]
    .filter((id) => id !== "right_attach_bottom");
  const extraCandidate = preferredExtraCandidateIds
    .map((id) => positionedNodes.get(id))
    .filter((node): node is LayoutDefenseNode => Boolean(node))
    .sort((a, b) => b.x - a.x || a.y - b.y)[0]
    ?? Array.from(positionedNodes.values())
      .filter((node) => (
        node.zone === "right_arm"
        && !RIGHT_ARM_BASE_CANDIDATE_IDS.includes(node.id as (typeof RIGHT_ARM_BASE_CANDIDATE_IDS)[number])
        && !node.id.startsWith("right_bridge_")
      ))
      .sort((a, b) => a.y - b.y || b.x - a.x)[0];
  if (extraCandidate) {
    candidateNodes.push(extraCandidate);
  }

  const targets = RIGHT_ARM_CORE_TARGET_IDS
    .map((id) => positionedNodes.get(id))
    .filter((node): node is LayoutDefenseNode => Boolean(node));
  if (!candidateNodes.length || !targets.length) {
    return [];
  }

  const usedTargetIds = new Set<string>();
  const attachmentEdges: LayoutDefenseEdge[] = [];
  const orderedCandidates = candidateNodes
    .slice()
    .sort((a, b) => a.x - b.x || a.y - b.y);

  for (const candidate of orderedCandidates) {
    const candidateAngle = Math.atan2(candidate.y - coreCenter.y, candidate.x - coreCenter.x);
    const bestTarget = targets
      .filter((target) => candidate.id === "right_c0" || !usedTargetIds.has(target.id))
      .filter((target) => !edgeIntersectsObstacles(candidate.x, candidate.y, target.x, target.y, obstacles))
      .sort((left, right) => {
        const leftDistance = Math.hypot(candidate.x - left.x, candidate.y - left.y);
        const rightDistance = Math.hypot(candidate.x - right.x, candidate.y - right.y);
        if (Math.abs(leftDistance - rightDistance) > 0.001) {
          return leftDistance - rightDistance;
        }

        const leftAngleDelta = Math.abs(normalizeAngle(candidateAngle - Math.atan2(left.y - coreCenter.y, left.x - coreCenter.x)));
        const rightAngleDelta = Math.abs(normalizeAngle(candidateAngle - Math.atan2(right.y - coreCenter.y, right.x - coreCenter.x)));
        if (Math.abs(leftAngleDelta - rightAngleDelta) > 0.001) {
          return leftAngleDelta - rightAngleDelta;
        }

        return left.x - right.x;
      })[0];

    if (!bestTarget) continue;

    const edgeId = `right_dynamic_attach_${candidate.id}_${bestTarget.id}`;
    if (usedEdgeIds.has(edgeId)) continue;
    attachmentEdges.push(buildEdgeRecord(candidate, bestTarget, edgeId));
    usedEdgeIds.add(edgeId);
    usedTargetIds.add(bestTarget.id);
  }

  return attachmentEdges;
}

type BuildLeftArmAttachmentEdgesInput = {
  positionedNodes: Map<string, LayoutDefenseNode>;
  coreCenter: LayoutDefenseNode;
  obstacles: LayoutRect[];
  usedEdgeIds: Set<string>;
  scale: number;
};

function buildLeftArmAttachmentEdges(input: BuildLeftArmAttachmentEdgesInput): LayoutDefenseEdge[] {
  const {
    positionedNodes,
    coreCenter,
    obstacles,
    usedEdgeIds,
    scale,
  } = input;
  const candidateNodes = LEFT_ARM_ATTACH_CANDIDATE_IDS
    .map((id) => positionedNodes.get(id))
    .filter((node): node is LayoutDefenseNode => Boolean(node))
    .sort((a, b) => {
      const priority = ["left_a0", "left_b0", "left_c0", "left_attach_top", "left_attach_bottom", "left_bridge_top"];
      const aIndex = priority.indexOf(a.id);
      const bIndex = priority.indexOf(b.id);
      if (aIndex !== bIndex) return aIndex - bIndex;
      return a.y - b.y || b.x - a.x;
    });
  const targets = LEFT_ARM_CORE_TARGET_IDS
    .map((id) => positionedNodes.get(id))
    .filter((node): node is LayoutDefenseNode => Boolean(node));
  if (!candidateNodes.length || !targets.length) {
    return [];
  }

  const usedTargetIds = new Set<string>();
  const attachmentEdges: LayoutDefenseEdge[] = [];

  for (const candidate of candidateNodes) {
    const targetPool = targets.filter((target) => !edgeIntersectsObstacles(candidate.x, candidate.y, target.x, target.y, obstacles));
    if (!targetPool.length) continue;
    const preferredTargets = targetPool.filter((target) => !usedTargetIds.has(target.id));
    const shouldIgnoreDedupe = candidate.id === "left_a0" || candidate.id === "left_b0" || candidate.id === "left_c0";
    const availableTargets = shouldIgnoreDedupe || !preferredTargets.length ? targetPool : preferredTargets;
    const verticalBias = candidate.y <= coreCenter.y - (16 * scale)
      ? ["halo_n", "halo_nw", "halo_w"]
      : candidate.y >= coreCenter.y + (16 * scale)
        ? ["halo_w", "halo_nw", "halo_n"]
        : ["halo_nw", "halo_w", "halo_n"];

    const bestTarget = availableTargets
      .slice()
      .sort((left, right) => {
        const leftDistance = Math.hypot(candidate.x - left.x, candidate.y - left.y);
        const rightDistance = Math.hypot(candidate.x - right.x, candidate.y - right.y);
        if (Math.abs(leftDistance - rightDistance) > 0.001) {
          return leftDistance - rightDistance;
        }

        const leftPreference = verticalBias.indexOf(left.id);
        const rightPreference = verticalBias.indexOf(right.id);
        if (leftPreference !== rightPreference) {
          return leftPreference - rightPreference;
        }

        return right.x - left.x;
      })[0];

    if (!bestTarget) continue;

    const edgeId = `left_dynamic_attach_${candidate.id}_${bestTarget.id}`;
    if (usedEdgeIds.has(edgeId)) continue;
    attachmentEdges.push(buildEdgeRecord(candidate, bestTarget, edgeId));
    usedEdgeIds.add(edgeId);
    usedTargetIds.add(bestTarget.id);
  }

  return attachmentEdges;
}

export function layoutDefenseGraph(input: LayoutDefenseGraphInput): LayoutDefenseGraphResult {
  const width = Math.max(1, input.width);
  const height = Math.max(1, input.height);
  const padX = input.padX ?? 18;
  const padTop = input.padTop ?? 8;
  const padBottom = input.padBottom ?? 12;
  const obstacles = input.obstacles ?? [];
  const core = templateNodeById(BLOG_DEFENSE_CORE_NODE_ID) ?? BLOG_DEFENSE_NODES[0];
  const baseScale = Math.min(width / BLOG_DEFENSE_VIEWBOX_WIDTH, height / BLOG_DEFENSE_VIEWBOX_HEIGHT);
  const scaleBoost = width >= 720
    ? 1.08
    : width >= 520
      ? 1.05
      : 1.02;
  const scale = Math.max(0.48, Math.min(1.18, baseScale * scaleBoost));
  const nodeRadius = uniformNodeRadius(scale);
  const anchor = bestCoreAnchor({
    width,
    height,
    padX,
    padTop,
    padBottom,
    scale,
    coreNode: core,
    nodeRadius,
    obstacles,
  });
  const corridorX = bestCorridorX(width, height, padX, padTop, padBottom, scale, core, anchor, obstacles);

  const positionedNodes = new Map<string, LayoutDefenseNode>();
  for (const node of BLOG_DEFENSE_NODES) {
    const dx = node.x - core.x;
    const dy = node.y - core.y;
    let x = anchor.x + dx * scale;
    let y = anchor.y + dy * scale;
    const radius = nodeRadius;

    if (node.zone === "right_corridor") {
      x = corridorX;
      y = Math.min(height - padBottom - radius, Math.max(padTop + radius, y));
    }

    const inBounds = x > padX + radius
      && x < width - padX - radius
      && y > padTop + radius
      && y < height - padBottom - radius;
    if (!inBounds) continue;

    positionedNodes.set(node.id, {
      ...node,
      x,
      y,
      radius,
    });
  }

  const coreNodes = Array.from(positionedNodes.values()).filter((node) => node.zone === "core");
  const leftArmNodes = Array.from(positionedNodes.values()).filter((node) => node.zone === "left_arm");
  const rightArmNodes = Array.from(positionedNodes.values()).filter((node) => node.zone === "right_arm");
  if (coreNodes.length && leftArmNodes.length) {
    layoutLeftArmRows({
      coreNodes,
      leftArmNodes,
      positionedNodes,
      padX,
      padTop,
      scale,
      coreCenter: positionedNodes.get(BLOG_DEFENSE_CORE_NODE_ID),
    });
  }
  if (coreNodes.length && rightArmNodes.length) {
    layoutRightArmRows({
      coreNodes,
      rightArmNodes,
      positionedNodes,
      padX,
      padTop,
      padBottom,
      height,
      scale,
      coreCenter: positionedNodes.get(BLOG_DEFENSE_CORE_NODE_ID),
    });
  }

  for (const [nodeId, node] of positionedNodes.entries()) {
    if (nodeIntersectsObstacles(node.x, node.y, node.radius + 2, obstacles)) {
      positionedNodes.delete(nodeId);
    }
  }

  const phaseAEdges: LayoutDefenseEdge[] = [];
  const usedEdgeIds = new Set<string>();
  for (const edge of BLOG_DEFENSE_EDGES) {
    if (edge.id.startsWith("left_to_outer_")) continue;
    const from = positionedNodes.get(edge.from);
    const to = positionedNodes.get(edge.to);
    if (!from || !to) continue;
    if (edgeIntersectsObstacles(from.x, from.y, to.x, to.y, obstacles)) continue;
    phaseAEdges.push(buildEdgeRecord(from, to, edge.id));
    usedEdgeIds.add(edge.id);
  }

  const coreCenter = positionedNodes.get(BLOG_DEFENSE_CORE_NODE_ID);
  if (coreCenter) {
    phaseAEdges.push(...buildLeftArmAttachmentEdges({
      positionedNodes,
      coreCenter,
      obstacles,
      usedEdgeIds,
      scale,
    }));
    phaseAEdges.push(...buildRightArmAttachmentEdges({
      positionedNodes,
      coreCenter,
      obstacles,
      usedEdgeIds,
    }));
  }

  const corridorNodes = Array.from(positionedNodes.values())
    .filter((node) => node.zone === "right_corridor")
    .sort((a, b) => a.y - b.y);

  const phaseBEdges = [...phaseAEdges];
  for (let index = 0; index < corridorNodes.length - 1; index += 1) {
    const from = corridorNodes[index];
    const to = corridorNodes[index + 1];
    if (edgeIntersectsObstacles(from.x, from.y, to.x, to.y, obstacles)) continue;
    const templateEdge = BLOG_DEFENSE_EDGES.find((edge) => (
      (edge.from === from.id && edge.to === to.id) || (edge.from === to.id && edge.to === from.id)
    ));
    const id = templateEdge ? templateEdge.id : `corridor_relink_${from.id}_${to.id}`;
    if (usedEdgeIds.has(id)) continue;
    phaseBEdges.push(buildEdgeRecord(from, to, id));
    usedEdgeIds.add(id);
  }

  const corridorCoreTargets = corridorNodes
    .slice()
    .sort((a, b) => Math.abs(a.y - anchor.y) - Math.abs(b.y - anchor.y))
    .slice(0, 2);
  const rightArmCandidates = Array.from(positionedNodes.values())
    .filter((node) => node.zone === "right_arm")
    .sort((a, b) => Math.abs(a.y - anchor.y) - Math.abs(b.y - anchor.y));
  for (let index = 0; index < Math.min(corridorCoreTargets.length, rightArmCandidates.length); index += 1) {
    const from = corridorCoreTargets[index];
    const to = rightArmCandidates[index];
    if (edgeIntersectsObstacles(from.x, from.y, to.x, to.y, obstacles)) continue;
    const id = `corridor_bridge_${from.id}_${to.id}`;
    if (usedEdgeIds.has(id)) continue;
    phaseBEdges.push(buildEdgeRecord(from, to, id));
    usedEdgeIds.add(id);
  }

  return {
    nodes: Array.from(positionedNodes.values()),
    edges: phaseBEdges,
    scale,
  };
}
