#!/usr/bin/env node

const assert = require("node:assert/strict");
const fs = require("node:fs");
const ts = require("typescript");

require.extensions[".ts"] = function loadTs(module, filename) {
  const source = fs.readFileSync(filename, "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      esModuleInterop: true,
      module: ts.ModuleKind.CommonJS,
      moduleResolution: ts.ModuleResolutionKind.Node10,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: filename,
  });
  module._compile(output.outputText, filename);
};

const {
  BLOG_DEFENSE_CORE_NODE_ID,
  BLOG_DEFENSE_NODES,
  BLOG_DEFENSE_EDGES,
  BLOG_DEFENSE_COMPROMISE_PATH,
  buildVisibleAttackPath,
  buildCompromiseSequenceFromPath,
} = require("../blog-defense/graph.ts");
const { layoutDefenseGraph } = require("../blog-defense/layout.ts");

const RIGHT_ARM_HALO_TARGET_IDS = new Set([
  "halo_e",
  "halo_se",
  "halo_s",
  "halo_sw",
]);
const LEFT_ARM_HALO_TARGET_IDS = new Set([
  "halo_nw",
  "halo_n",
  "halo_w",
]);
const REMOVED_RIGHT_ARM_EDGE_IDS = new Set([
  "right_cross_6",
  "right_attach_1",
  "right_attach_1b",
  "right_attach_2",
  "right_to_outer_1",
  "right_to_outer_2",
  "right_to_outer_3",
  "right_to_outer_4",
  "right_to_outer_5",
  "right_to_outer_6",
  "right_to_outer_7",
  "right_to_outer_8",
  "right_to_outer_9",
  "right_to_outer_10",
  "right_to_outer_11",
]);
const STATIC_LEFT_ARM_ATTACHMENT_EDGE_IDS = new Set([
  "left_to_outer_1",
  "left_to_outer_2",
  "left_to_outer_3",
  "left_to_outer_4",
  "left_to_outer_5",
  "left_to_outer_6",
  "left_to_outer_7",
  "left_to_outer_8",
  "left_to_outer_9",
  "left_to_outer_10",
  "left_to_outer_11",
  "left_to_outer_12",
]);
const LEFT_ARM_ROWS = [
  ["left_tail_4", "left_tail_3", "left_tail_2", "left_tail_1", "left_tip", "left_a3", "left_a2", "left_a1", "left_a0", "left_bridge_top"],
  ["left_b3", "left_b0", "left_attach_top"],
  ["left_c3", "left_c0", "left_attach_bottom"],
];
const RIGHT_ARM_ROWS = [
  ["right_c0", "right_b0", "right_a0"],
  ["right_attach_bottom", "right_c1", "right_b1", "right_a1"],
  ["right_c2", "right_b2", "right_a2"],
  ["right_c3", "right_b3", "right_a3"],
  ["right_c4", "right_b4", "right_a4"],
  ["right_c5", "right_b5", "right_a5"],
];

assert.equal(BLOG_DEFENSE_COMPROMISE_PATH[0], "corridor_6");
assert.equal(BLOG_DEFENSE_COMPROMISE_PATH.at(-1), BLOG_DEFENSE_CORE_NODE_ID);
assert.ok(!BLOG_DEFENSE_NODES.some((node) => node.id === "right_attach_top"));
assert.ok(!BLOG_DEFENSE_NODES.some((node) => node.id.startsWith("inner_")));
assert.ok(BLOG_DEFENSE_EDGES.every((edge) => !REMOVED_RIGHT_ARM_EDGE_IDS.has(edge.id)));
assert.ok(BLOG_DEFENSE_EDGES.every((edge) => !edge.id.startsWith("inner_") && !edge.id.startsWith("inner_core_") && !edge.id.startsWith("inner_to_mid_")));

const templateCore = BLOG_DEFENSE_NODES.find((node) => node.id === BLOG_DEFENSE_CORE_NODE_ID);
const templateMidRing = BLOG_DEFENSE_NODES.filter((node) => node.id.startsWith("mid_"));
const templateOuterRing = BLOG_DEFENSE_NODES.filter((node) => node.id.startsWith("ring_"));
assert.ok(templateCore);
assert.ok(templateMidRing.length > 0);
assert.ok(templateOuterRing.length > 0);
const avgMidRadius = templateMidRing.reduce((sum, node) => (
  sum + Math.hypot(node.x - templateCore.x, node.y - templateCore.y)
), 0) / templateMidRing.length;
const avgOuterRingRadius = templateOuterRing.reduce((sum, node) => (
  sum + Math.hypot(node.x - templateCore.x, node.y - templateCore.y)
), 0) / templateOuterRing.length;
assert.ok(
  avgMidRadius >= avgOuterRingRadius * 0.66,
  `first core ring should not be too tight (${avgMidRadius} vs ${avgOuterRingRadius})`,
);

const zoneCounts = BLOG_DEFENSE_NODES.reduce((acc, node) => {
  acc[node.zone] = (acc[node.zone] ?? 0) + 1;
  return acc;
}, {});
assert.ok(zoneCounts.core >= 8);
assert.ok(zoneCounts.left_arm >= 6);
assert.ok(zoneCounts.right_arm >= 6);
assert.ok(zoneCounts.right_corridor >= 5);

const ingressProtected = BLOG_DEFENSE_NODES.filter((node) => node.zone === "right_corridor");
assert.ok(ingressProtected.every((node) => node.protectedIngress === true));

const desktopLayout = layoutDefenseGraph({ width: 720, height: 430 });
const tabletLayout = layoutDefenseGraph({ width: 520, height: 330 });
const mobileLayout = layoutDefenseGraph({ width: 280, height: 230 });
const namedLayouts = [
  { name: "desktop", width: 720, layout: desktopLayout },
  { name: "tablet", width: 520, layout: tabletLayout },
  { name: "mobile", width: 280, layout: mobileLayout },
];

for (const { name, width, layout } of namedLayouts) {
  assert.ok(layout.nodes.length > 0);
  assert.ok(layout.edges.length > 0);
  assert.ok(layout.nodes.every((node) => Number.isFinite(node.x) && Number.isFinite(node.y)));
  assert.ok(layout.edges.every((edge) => Number.isFinite(edge.x1) && Number.isFinite(edge.y1)));
  const nodeRadii = layout.nodes.map((node) => node.radius);
  const minRadius = Math.min(...nodeRadii);
  const maxRadius = Math.max(...nodeRadii);
  assert.ok(
    Math.abs(maxRadius - minRadius) <= 0.001,
    `${name} should render all node dots at a uniform radius`,
  );

  const coreNodes = layout.nodes.filter((node) => node.zone === "core");
  const leftArmNodes = layout.nodes.filter((node) => node.zone === "left_arm");
  const rightArmNodes = layout.nodes.filter((node) => node.zone === "right_arm");
  if (coreNodes.length && leftArmNodes.length) {
    const coreCenter = layout.nodes.find((node) => node.id === BLOG_DEFENSE_CORE_NODE_ID);
    assert.ok(coreCenter, `${name} should keep a core node`);

    const coreOuterRadius = coreNodes.reduce((maxRadius, node) => (
      Math.max(maxRadius, Math.hypot(node.x - coreCenter.x, node.y - coreCenter.y) + node.radius)
    ), 0);
    const leftRows = LEFT_ARM_ROWS
      .map((rowIds) => rowIds
        .map((id) => leftArmNodes.find((node) => node.id === id))
        .filter(Boolean)
        .sort((left, right) => left.x - right.x))
      .filter((rowNodes) => rowNodes.length > 0);

    assert.ok(
      !layout.edges.some((edge) => STATIC_LEFT_ARM_ATTACHMENT_EDGE_IDS.has(edge.id)),
      `${name} should not render stale left-arm static halo attachments`,
    );

    const topRow = leftRows[0];
    if (topRow && topRow.length >= 2) {
      const topYs = topRow.map((node) => node.y);
      const topYSpread = Math.max(...topYs) - Math.min(...topYs);
      assert.ok(topYSpread <= Math.max(4, width * 0.01), `${name} left-arm top rail should stay flat`);
    }

    if (leftRows.length >= 3) {
      const rowCenters = leftRows.map((rowNodes) => rowNodes.reduce((sum, node) => sum + node.y, 0) / rowNodes.length);
      const rowGaps = [];
      for (let index = 1; index < rowCenters.length; index += 1) {
        rowGaps.push(rowCenters[index] - rowCenters[index - 1]);
      }
      const avgRowGap = rowGaps.reduce((sum, gap) => sum + gap, 0) / rowGaps.length;
      const rowGapTolerance = Math.max(6, avgRowGap * 0.2);
      assert.ok(
        rowGaps.every((gap) => Math.abs(gap - avgRowGap) <= rowGapTolerance),
        `${name} left-arm rows should have near-uniform vertical spacing`,
      );
    }

    for (const rowNodes of leftRows) {
      if (rowNodes.length < 3) continue;
      const gaps = [];
      for (let index = 1; index < rowNodes.length; index += 1) {
        gaps.push(rowNodes[index].x - rowNodes[index - 1].x);
      }
      const avgGap = gaps.reduce((sum, gap) => sum + gap, 0) / gaps.length;
      const laneGapTolerance = Math.max(12, avgGap * 0.72);
      assert.ok(
        gaps.every((gap) => Math.abs(gap - avgGap) <= laneGapTolerance),
        `${name} left-arm row lane spacing should stay controlled without becoming perfectly even`,
      );
    }

    if (leftRows.length >= 3) {
      const rowLeftEdges = leftRows.map((rowNodes) => Math.min(...rowNodes.map((node) => node.x - node.radius)));
      assert.ok(
        rowLeftEdges[1] >= rowLeftEdges[0] && rowLeftEdges[2] >= rowLeftEdges[1],
        `${name} left-arm lower rows should taper inward from the top rail`,
      );
    }

    for (const node of leftArmNodes) {
      const distanceFromCore = Math.hypot(node.x - coreCenter.x, node.y - coreCenter.y);
      assert.ok(
        distanceFromCore + 0.001 >= coreOuterRadius + Math.min(3, node.radius * 0.5),
        `${name} left-arm nodes must remain outside the core envelope`,
      );
    }

    const dynamicAttachmentEdges = layout.edges.filter((edge) => edge.id.startsWith("left_dynamic_attach_"));
    assert.ok(dynamicAttachmentEdges.length >= 2, `${name} should keep rebuilt left-arm attachments`);
    assert.ok(
      dynamicAttachmentEdges.every((edge) => LEFT_ARM_HALO_TARGET_IDS.has(edge.to)),
      `${name} rebuilt left-arm attachments must target left halo perimeter nodes only`,
    );
    assert.ok(
      dynamicAttachmentEdges.every((edge) => !/^(outer_|ring_|mid_|inner_)/.test(edge.to) && edge.to !== BLOG_DEFENSE_CORE_NODE_ID),
      `${name} rebuilt left-arm attachments must not target inner core rings`,
    );

    const visibleLeftTargets = layout.nodes.filter((node) => LEFT_ARM_HALO_TARGET_IDS.has(node.id));
    const leftA0 = leftArmNodes.find((node) => node.id === "left_a0");
    const leftA0Attachment = dynamicAttachmentEdges.find((edge) => edge.from === "left_a0");
    if (leftA0 && leftA0Attachment && visibleLeftTargets.length) {
      const nearestTarget = visibleLeftTargets
        .slice()
        .sort((left, right) => {
          const leftDistance = Math.hypot(leftA0.x - left.x, leftA0.y - left.y);
          const rightDistance = Math.hypot(leftA0.x - right.x, leftA0.y - right.y);
          if (Math.abs(leftDistance - rightDistance) > 0.001) {
            return leftDistance - rightDistance;
          }
          return right.x - left.x;
        })[0];
      assert.equal(
        leftA0Attachment.to,
        nearestTarget.id,
        `${name} left_a0 should attach to the nearest visible left halo perimeter node`,
      );
    }
  }
  if (coreNodes.length && rightArmNodes.length) {
    const coreLeft = Math.min(...coreNodes.map((node) => node.x - node.radius));
    const coreRight = Math.max(...coreNodes.map((node) => node.x + node.radius));
    const coreWidth = coreRight - coreLeft;
    const rightArmRight = Math.max(...rightArmNodes.map((node) => node.x + node.radius));
    assert.ok(
      rightArmRight <= coreRight + 0.001,
      `right arm must not extend beyond core right edge (${rightArmRight} > ${coreRight})`,
    );

    const widthControlNodes = rightArmNodes.filter((node) => (
      /^right_[abc]\d/.test(node.id) || node.id === "right_attach_bottom"
    ));
    const armNodesForBands = widthControlNodes.length ? widthControlNodes : rightArmNodes;
    const armTop = Math.min(...armNodesForBands.map((node) => node.y));
    const armBottom = Math.max(...armNodesForBands.map((node) => node.y));
    const armSpan = Math.max(1, armBottom - armTop);
    const topBandLimit = armTop + armSpan * 0.28;
    const bottomBandFloor = armBottom - armSpan * 0.2;
    const topBandNodes = armNodesForBands.filter((node) => node.y <= topBandLimit);
    const bottomBandNodes = armNodesForBands.filter((node) => node.y >= bottomBandFloor);
    assert.ok(topBandNodes.length >= 1, `${name} should keep nodes in top arm band`);
    assert.ok(bottomBandNodes.length >= 1, `${name} should keep nodes in bottom arm band`);

    const topBandWidth = Math.max(...topBandNodes.map((node) => node.x + node.radius))
      - Math.min(...topBandNodes.map((node) => node.x - node.radius));
    const bottomBandWidth = Math.max(...bottomBandNodes.map((node) => node.x + node.radius))
      - Math.min(...bottomBandNodes.map((node) => node.x - node.radius));

    if (width >= 500 && topBandNodes.length >= 3) {
      assert.ok(
        topBandWidth >= coreWidth * 0.4,
        `${name} right-arm top width should be close to core width (${topBandWidth} vs ${coreWidth})`,
      );
    }
    if (topBandNodes.length >= 3 && bottomBandNodes.length >= 2) {
      assert.ok(
        bottomBandWidth < topBandWidth,
        `${name} right-arm should taper downward (${bottomBandWidth} !< ${topBandWidth})`,
      );
    }

    const armRows = RIGHT_ARM_ROWS
      .map((rowIds) => rowIds
        .map((id) => rightArmNodes.find((node) => node.id === id))
        .filter(Boolean)
        .sort((left, right) => left.x - right.x))
      .filter((rowNodes) => rowNodes.length > 0);
    if (armRows.length >= 3) {
      const rowCenters = armRows.map((rowNodes) => rowNodes.reduce((sum, node) => sum + node.y, 0) / rowNodes.length);
      const rowGaps = [];
      for (let index = 1; index < rowCenters.length; index += 1) {
        rowGaps.push(rowCenters[index] - rowCenters[index - 1]);
      }
      const spacingGaps = rowGaps.slice(1).length ? rowGaps.slice(1) : rowGaps;
      const avgRowGap = spacingGaps.reduce((sum, gap) => sum + gap, 0) / spacingGaps.length;
      const rowGapTolerance = Math.max(6, avgRowGap * 0.18);
      assert.ok(
        spacingGaps.every((gap) => Math.abs(gap - avgRowGap) <= rowGapTolerance),
        `${name} right-arm rows should have near-uniform vertical spacing`,
      );
    }

    for (const rowNodes of armRows) {
      if (rowNodes.length < 4) continue;
      const gaps = [];
      for (let index = 1; index < rowNodes.length; index += 1) {
        gaps.push(rowNodes[index].x - rowNodes[index - 1].x);
      }
      const avgGap = gaps.reduce((sum, gap) => sum + gap, 0) / gaps.length;
      const laneGapTolerance = Math.max(5, avgGap * 0.2);
      assert.ok(
        gaps.every((gap) => Math.abs(gap - avgGap) <= laneGapTolerance),
        `${name} right-arm row lane spacing should be approximately even`,
      );
    }

    assert.ok(!rightArmNodes.some((node) => node.id === "right_attach_top"), `${name} should not render right_attach_top`);
    assert.ok(!layout.edges.some((edge) => REMOVED_RIGHT_ARM_EDGE_IDS.has(edge.id)), `${name} should not render removed dense-cluster edges`);

    const dynamicAttachmentEdges = layout.edges.filter((edge) => edge.id.startsWith("right_dynamic_attach_"));
    assert.ok(dynamicAttachmentEdges.length >= 3, `${name} should keep multiple rebuilt arm attachments`);
    assert.ok(
      dynamicAttachmentEdges.every((edge) => RIGHT_ARM_HALO_TARGET_IDS.has(edge.to)),
      `${name} rebuilt arm attachments must target halo perimeter nodes only`,
    );

    const visibleCoreTargets = layout.nodes.filter((node) => RIGHT_ARM_HALO_TARGET_IDS.has(node.id));
    const rightC0 = rightArmNodes.find((node) => node.id === "right_c0");
    const rightC0Attachment = dynamicAttachmentEdges.find((edge) => edge.from === "right_c0");
    if (rightC0 && rightC0Attachment) {
      const nearestTarget = visibleCoreTargets
        .slice()
        .sort((left, right) => {
          const leftDistance = Math.hypot(rightC0.x - left.x, rightC0.y - left.y);
          const rightDistance = Math.hypot(rightC0.x - right.x, rightC0.y - right.y);
          if (Math.abs(leftDistance - rightDistance) > 0.001) {
            return leftDistance - rightDistance;
          }
          return left.x - right.x;
        })[0];
      assert.equal(
        rightC0Attachment.to,
        nearestTarget.id,
        `${name} right_c0 should attach to the nearest visible halo perimeter node`,
      );
    }

    assert.ok(
      dynamicAttachmentEdges.every((edge) => !/^(outer_|ring_|mid_|inner_)/.test(edge.to) && edge.to !== BLOG_DEFENSE_CORE_NODE_ID),
      `${name} rebuilt arm attachments must not target inner core rings`,
    );
  }
}

const desktopCore = desktopLayout.nodes.find((node) => node.id === BLOG_DEFENSE_CORE_NODE_ID);
assert.ok(desktopCore);
assert.ok(desktopCore.x > 470, "core should remain in the top-right region");
assert.ok(desktopCore.y < 210, "core should remain near top area");

const corridorVisible = desktopLayout.nodes
  .filter((node) => node.zone === "right_corridor")
  .sort((a, b) => b.y - a.y);
assert.ok(corridorVisible.length >= 1, "at least one right-corridor node should survive");
assert.ok(corridorVisible[0].x > 640, "corridor should stay in right margin");

const blockedLayout = layoutDefenseGraph({
  width: 720,
  height: 430,
  obstacles: [
    { x: 635, y: 210, width: 85, height: 130 },
  ],
});
const blockedCorridor = blockedLayout.nodes.filter((node) => node.zone === "right_corridor");
assert.ok(blockedCorridor.length >= 1, "corridor should still have visible points after culling");
assert.ok(
  blockedLayout.edges.every((edge) => (
    blockedLayout.nodes.some((node) => node.id === edge.from)
    && blockedLayout.nodes.some((node) => node.id === edge.to)
  )),
  "all visible edges must reference surviving visible nodes",
);

const collisionProbe = desktopLayout.nodes.find((node) => node.id === "left_attach_bottom");
assert.ok(collisionProbe, "expected a stable left-arm shoulder node for collision regression");
const collisionLayout = layoutDefenseGraph({
  width: 720,
  height: 430,
  obstacles: [
    { x: collisionProbe.x - 6, y: collisionProbe.y - 6, width: 12, height: 12 },
  ],
});
assert.ok(
  !collisionLayout.nodes.some((node) => node.id === "left_attach_bottom"),
  "a node whose rendered circle overlaps an obstacle should be fully removed",
);
assert.ok(
  collisionLayout.nodes.some((node) => node.id === "left_c3"),
  "an adjacent node outside the obstacle should remain visible",
);
assert.ok(
  collisionLayout.edges.every((edge) => edge.from !== "left_attach_bottom" && edge.to !== "left_attach_bottom"),
  "edges referencing a removed node should also be removed",
);

const edgeProbeStart = desktopLayout.nodes.find((node) => node.id === "left_c3");
const edgeProbeEnd = desktopLayout.nodes.find((node) => node.id === "left_c0");
assert.ok(edgeProbeStart && edgeProbeEnd, "expected stable left-arm nodes for edge collision regression");
const edgeMidX = (edgeProbeStart.x + edgeProbeEnd.x) / 2;
const edgeMidY = (edgeProbeStart.y + edgeProbeEnd.y) / 2;
const edgeCollisionLayout = layoutDefenseGraph({
  width: 720,
  height: 430,
  obstacles: [
    { x: edgeMidX - 2, y: edgeMidY - 2, width: 4, height: 4 },
  ],
});
assert.ok(
  edgeCollisionLayout.nodes.some((node) => node.id === "left_c3")
  && edgeCollisionLayout.nodes.some((node) => node.id === "left_c0"),
  "nodes adjacent to an edge-only obstacle should survive when not overlapped",
);
assert.ok(
  !edgeCollisionLayout.edges.some((edge) => (
    (edge.from === "left_c3" && edge.to === "left_c0")
    || (edge.from === "left_c0" && edge.to === "left_c3")
  )),
  "an edge intersecting an obstacle should be removed even when both endpoint nodes survive",
);

const visiblePath = buildVisibleAttackPath({
  nodes: desktopLayout.nodes,
  edges: desktopLayout.edges.map((edge) => ({ id: edge.id, from: edge.from, to: edge.to })),
  coreId: BLOG_DEFENSE_CORE_NODE_ID,
});
assert.ok(visiblePath.nodeIds.length >= 2);
assert.equal(visiblePath.nodeIds.at(-1), BLOG_DEFENSE_CORE_NODE_ID);
assert.equal(visiblePath.nodeIds.at(-2), "mid_s", "final node before core should be the south mid approach");
assert.ok(visiblePath.nodeIds.includes("mid_s"), "visible path should include the south mid approach node");
assert.ok(visiblePath.edgeIds.includes("mid_to_outer_s"), "visible path should include the south outer-to-mid edge");
assert.ok(visiblePath.edgeIds.includes("mid_spoke_s"), "visible path should include the south mid-to-core edge");
const startNode = desktopLayout.nodes.find((node) => node.id === visiblePath.nodeIds[0]);
assert.ok(startNode);
assert.equal(startNode.zone, "right_corridor");

const sequence = buildCompromiseSequenceFromPath(
  visiblePath.nodeIds,
  desktopLayout.edges.map((edge) => ({ id: edge.id, from: edge.from, to: edge.to })),
);
assert.ok(sequence.length >= 3);
assert.equal(sequence[0].kind, "node");
assert.equal(sequence.at(-1).kind, "node");
assert.equal(sequence.at(-1).nodeId, BLOG_DEFENSE_CORE_NODE_ID);

const pathEdgeIds = new Set(visiblePath.edgeIds);
for (const edgeId of pathEdgeIds) {
  assert.ok(desktopLayout.edges.some((edge) => edge.id === edgeId), "visible path must use visible edges only");
}

console.log("blog-defense graph/layout tests passed");
