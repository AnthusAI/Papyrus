export const BLOG_DEFENSE_VIEWBOX_WIDTH = 1000;
export const BLOG_DEFENSE_VIEWBOX_HEIGHT = 700;

export type BlogDefenseNodeRole = "core" | "attack" | "perimeter" | "interior";
export type BlogDefenseZone = "core" | "left_arm" | "right_arm" | "right_corridor";

export type BlogDefenseNode = {
  id: string;
  x: number;
  y: number;
  radius: number;
  role: BlogDefenseNodeRole;
  zone: BlogDefenseZone;
  protectedIngress?: boolean;
};

export type BlogDefenseEdge = {
  id: string;
  from: string;
  to: string;
};

export type VisibleAttackPathInput = {
  nodes: BlogDefenseNode[];
  edges: BlogDefenseEdge[];
  coreId?: string;
  stochastic?: boolean;
};

export type VisibleAttackPath = {
  nodeIds: string[];
  edgeIds: string[];
};

export const BLOG_DEFENSE_CORE_NODE_ID = "core";

export const BLOG_DEFENSE_NODES: BlogDefenseNode[] = [
  { id: "core", x: 770, y: 175, radius: 12, role: "core", zone: "core" },
  { id: "halo_n", x: 770, y: 32, radius: 7, role: "perimeter", zone: "core" },
  { id: "halo_ne", x: 913, y: 58, radius: 7, role: "perimeter", zone: "core" },
  { id: "halo_e", x: 913, y: 175, radius: 7, role: "perimeter", zone: "core" },
  { id: "halo_se", x: 878, y: 284, radius: 7, role: "perimeter", zone: "core" },
  { id: "halo_s", x: 770, y: 318, radius: 7, role: "perimeter", zone: "core" },
  { id: "halo_sw", x: 662, y: 284, radius: 7, role: "perimeter", zone: "core" },
  { id: "halo_w", x: 627, y: 175, radius: 7, role: "perimeter", zone: "core" },
  { id: "halo_nw", x: 662, y: 66, radius: 7, role: "perimeter", zone: "core" },
  { id: "outer_n", x: 770, y: 56, radius: 7, role: "perimeter", zone: "core" },
  { id: "outer_ne", x: 854, y: 91, radius: 7, role: "perimeter", zone: "core" },
  { id: "outer_e", x: 889, y: 175, radius: 7, role: "perimeter", zone: "core" },
  { id: "outer_se", x: 854, y: 259, radius: 7, role: "perimeter", zone: "core" },
  { id: "outer_s", x: 770, y: 294, radius: 7, role: "perimeter", zone: "core" },
  { id: "outer_sw", x: 686, y: 259, radius: 7, role: "perimeter", zone: "core" },
  { id: "outer_w", x: 651, y: 175, radius: 7, role: "perimeter", zone: "core" },
  { id: "outer_nw", x: 686, y: 91, radius: 7, role: "perimeter", zone: "core" },
  { id: "ring_n", x: 770, y: 84, radius: 7, role: "perimeter", zone: "core" },
  { id: "ring_ne", x: 833, y: 111, radius: 7, role: "perimeter", zone: "core" },
  { id: "ring_e", x: 858, y: 175, radius: 7, role: "perimeter", zone: "core" },
  { id: "ring_se", x: 833, y: 240, radius: 7, role: "perimeter", zone: "core" },
  { id: "ring_s", x: 770, y: 266, radius: 7, role: "perimeter", zone: "core" },
  { id: "ring_sw", x: 706, y: 240, radius: 7, role: "perimeter", zone: "core" },
  { id: "ring_w", x: 682, y: 175, radius: 7, role: "perimeter", zone: "core" },
  { id: "ring_nw", x: 706, y: 111, radius: 7, role: "perimeter", zone: "core" },

  { id: "mid_n", x: 770, y: 111, radius: 5, role: "interior", zone: "core" },
  { id: "mid_ne", x: 814, y: 130, radius: 5, role: "interior", zone: "core" },
  { id: "mid_e", x: 832, y: 175, radius: 5, role: "interior", zone: "core" },
  { id: "mid_se", x: 814, y: 220, radius: 5, role: "interior", zone: "core" },
  { id: "mid_s", x: 770, y: 239, radius: 5, role: "interior", zone: "core" },
  { id: "mid_sw", x: 726, y: 220, radius: 5, role: "interior", zone: "core" },
  { id: "mid_w", x: 708, y: 175, radius: 5, role: "interior", zone: "core" },
  { id: "mid_nw", x: 726, y: 130, radius: 5, role: "interior", zone: "core" },

  { id: "left_attach_top", x: 640, y: 42, radius: 6, role: "interior", zone: "left_arm" },
  { id: "left_attach_bottom", x: 626, y: 114, radius: 6, role: "interior", zone: "left_arm" },
  { id: "left_bridge_top", x: 678, y: 32, radius: 6, role: "perimeter", zone: "left_arm" },
  { id: "left_a0", x: 640, y: 32, radius: 6, role: "perimeter", zone: "left_arm" },
  { id: "left_a1", x: 600, y: 32, radius: 6, role: "perimeter", zone: "left_arm" },
  { id: "left_a2", x: 556, y: 32, radius: 6, role: "perimeter", zone: "left_arm" },
  { id: "left_a3", x: 514, y: 32, radius: 6, role: "perimeter", zone: "left_arm" },
  { id: "left_b0", x: 628, y: 72, radius: 6, role: "interior", zone: "left_arm" },
  { id: "left_b3", x: 534, y: 44, radius: 6, role: "interior", zone: "left_arm" },
  { id: "left_c0", x: 632, y: 120, radius: 6, role: "interior", zone: "left_arm" },
  { id: "left_c3", x: 548, y: 60, radius: 6, role: "interior", zone: "left_arm" },
  { id: "left_tip", x: 492, y: 32, radius: 5, role: "perimeter", zone: "left_arm" },
  { id: "left_tail_1", x: 450, y: 32, radius: 5, role: "perimeter", zone: "left_arm" },
  { id: "left_tail_2", x: 408, y: 32, radius: 5, role: "perimeter", zone: "left_arm" },
  { id: "left_tail_3", x: 366, y: 32, radius: 5, role: "perimeter", zone: "left_arm" },
  { id: "left_tail_4", x: 326, y: 32, radius: 5, role: "perimeter", zone: "left_arm" },

  { id: "right_attach_bottom", x: 820, y: 308, radius: 6, role: "interior", zone: "right_arm" },
  { id: "right_bridge_top", x: 905, y: 74, radius: 6, role: "perimeter", zone: "right_arm" },
  { id: "right_bridge_peak", x: 913, y: 42, radius: 6, role: "perimeter", zone: "right_arm" },
  { id: "right_a0", x: 906, y: 240, radius: 7, role: "perimeter", zone: "right_arm" },
  { id: "right_a1", x: 910, y: 316, radius: 7, role: "perimeter", zone: "right_arm" },
  { id: "right_a2", x: 912, y: 390, radius: 7, role: "perimeter", zone: "right_arm" },
  { id: "right_a3", x: 912, y: 470, radius: 7, role: "perimeter", zone: "right_arm" },
  { id: "right_a4", x: 912, y: 552, radius: 7, role: "perimeter", zone: "right_arm" },
  { id: "right_a5", x: 912, y: 632, radius: 7, role: "perimeter", zone: "right_arm" },
  { id: "right_b0", x: 834, y: 286, radius: 6, role: "interior", zone: "right_arm" },
  { id: "right_b1", x: 848, y: 350, radius: 6, role: "interior", zone: "right_arm" },
  { id: "right_b2", x: 872, y: 424, radius: 6, role: "interior", zone: "right_arm" },
  { id: "right_b3", x: 907, y: 502, radius: 6, role: "interior", zone: "right_arm" },
  { id: "right_b4", x: 910, y: 582, radius: 6, role: "interior", zone: "right_arm" },
  { id: "right_b5", x: 911, y: 654, radius: 6, role: "interior", zone: "right_arm" },
  { id: "right_c0", x: 790, y: 328, radius: 6, role: "interior", zone: "right_arm" },
  { id: "right_c1", x: 812, y: 366, radius: 6, role: "interior", zone: "right_arm" },
  { id: "right_c2", x: 836, y: 444, radius: 6, role: "interior", zone: "right_arm" },
  { id: "right_c3", x: 900, y: 528, radius: 6, role: "interior", zone: "right_arm" },
  { id: "right_c4", x: 908, y: 608, radius: 6, role: "interior", zone: "right_arm" },
  { id: "right_c5", x: 910, y: 676, radius: 6, role: "interior", zone: "right_arm" },

  { id: "corridor_0", x: 970, y: 260, radius: 7, role: "attack", zone: "right_corridor", protectedIngress: true },
  { id: "corridor_1", x: 972, y: 328, radius: 7, role: "attack", zone: "right_corridor", protectedIngress: true },
  { id: "corridor_2", x: 974, y: 398, radius: 7, role: "attack", zone: "right_corridor", protectedIngress: true },
  { id: "corridor_3", x: 976, y: 472, radius: 8, role: "attack", zone: "right_corridor", protectedIngress: true },
  { id: "corridor_4", x: 978, y: 548, radius: 8, role: "attack", zone: "right_corridor", protectedIngress: true },
  { id: "corridor_5", x: 980, y: 620, radius: 9, role: "attack", zone: "right_corridor", protectedIngress: true },
  { id: "corridor_6", x: 982, y: 684, radius: 10, role: "attack", zone: "right_corridor", protectedIngress: true },
];

export const BLOG_DEFENSE_EDGES: BlogDefenseEdge[] = [
  { id: "halo_1", from: "halo_n", to: "halo_ne" },
  { id: "halo_2", from: "halo_ne", to: "halo_e" },
  { id: "halo_3", from: "halo_e", to: "halo_se" },
  { id: "halo_4", from: "halo_se", to: "halo_s" },
  { id: "halo_5", from: "halo_s", to: "halo_sw" },
  { id: "halo_6", from: "halo_sw", to: "halo_w" },
  { id: "halo_7", from: "halo_w", to: "halo_nw" },
  { id: "halo_8", from: "halo_nw", to: "halo_n" },
  { id: "halo_to_outer_n", from: "halo_n", to: "outer_n" },
  { id: "halo_to_outer_ne", from: "halo_ne", to: "outer_ne" },
  { id: "halo_to_outer_e", from: "halo_e", to: "outer_e" },
  { id: "halo_to_outer_se", from: "halo_se", to: "outer_se" },
  { id: "halo_to_outer_s", from: "halo_s", to: "outer_s" },
  { id: "halo_to_outer_sw", from: "halo_sw", to: "outer_sw" },
  { id: "halo_to_outer_w", from: "halo_w", to: "outer_w" },
  { id: "halo_to_outer_nw", from: "halo_nw", to: "outer_nw" },
  { id: "outer_1", from: "outer_n", to: "outer_ne" },
  { id: "outer_2", from: "outer_ne", to: "outer_e" },
  { id: "outer_3", from: "outer_e", to: "outer_se" },
  { id: "outer_4", from: "outer_se", to: "outer_s" },
  { id: "outer_5", from: "outer_s", to: "outer_sw" },
  { id: "outer_6", from: "outer_sw", to: "outer_w" },
  { id: "outer_7", from: "outer_w", to: "outer_nw" },
  { id: "outer_8", from: "outer_nw", to: "outer_n" },
  { id: "outer_to_ring_n", from: "outer_n", to: "ring_n" },
  { id: "outer_to_ring_ne", from: "outer_ne", to: "ring_ne" },
  { id: "outer_to_ring_e", from: "outer_e", to: "ring_e" },
  { id: "outer_to_ring_se", from: "outer_se", to: "ring_se" },
  { id: "outer_to_ring_s", from: "outer_s", to: "ring_s" },
  { id: "outer_to_ring_sw", from: "outer_sw", to: "ring_sw" },
  { id: "outer_to_ring_w", from: "outer_w", to: "ring_w" },
  { id: "outer_to_ring_nw", from: "outer_nw", to: "ring_nw" },
  { id: "ring_1", from: "ring_n", to: "ring_ne" },
  { id: "ring_2", from: "ring_ne", to: "ring_e" },
  { id: "ring_3", from: "ring_e", to: "ring_se" },
  { id: "ring_4", from: "ring_se", to: "ring_s" },
  { id: "ring_5", from: "ring_s", to: "ring_sw" },
  { id: "ring_6", from: "ring_sw", to: "ring_w" },
  { id: "ring_7", from: "ring_w", to: "ring_nw" },
  { id: "ring_8", from: "ring_nw", to: "ring_n" },
  { id: "spoke_n", from: "ring_n", to: "core" },
  { id: "spoke_e", from: "ring_e", to: "core" },
  { id: "spoke_s", from: "ring_s", to: "core" },
  { id: "spoke_w", from: "ring_w", to: "core" },
  { id: "mid_ring_1", from: "mid_n", to: "mid_ne" },
  { id: "mid_ring_2", from: "mid_ne", to: "mid_e" },
  { id: "mid_ring_3", from: "mid_e", to: "mid_se" },
  { id: "mid_ring_4", from: "mid_se", to: "mid_s" },
  { id: "mid_ring_5", from: "mid_s", to: "mid_sw" },
  { id: "mid_ring_6", from: "mid_sw", to: "mid_w" },
  { id: "mid_ring_7", from: "mid_w", to: "mid_nw" },
  { id: "mid_ring_8", from: "mid_nw", to: "mid_n" },
  { id: "mid_spoke_n", from: "mid_n", to: "core" },
  { id: "mid_spoke_e", from: "mid_e", to: "core" },
  { id: "mid_spoke_s", from: "mid_s", to: "core" },
  { id: "mid_spoke_w", from: "mid_w", to: "core" },
  { id: "mid_to_outer_n", from: "mid_n", to: "ring_n" },
  { id: "mid_to_outer_e", from: "mid_e", to: "ring_e" },
  { id: "mid_to_outer_s", from: "mid_s", to: "ring_s" },
  { id: "mid_to_outer_w", from: "mid_w", to: "ring_w" },
  { id: "left_a_chain_1", from: "left_a0", to: "left_a1" },
  { id: "left_a_chain_0", from: "left_bridge_top", to: "left_a0" },
  { id: "left_a_chain_2", from: "left_a1", to: "left_a2" },
  { id: "left_a_chain_3", from: "left_a2", to: "left_a3" },
  { id: "left_a_chain_4", from: "left_a3", to: "left_tip" },
  { id: "left_b_chain_1", from: "left_b0", to: "left_b3" },
  { id: "left_b_chain_4", from: "left_b3", to: "left_tip" },
  { id: "left_c_chain_1", from: "left_c0", to: "left_c3" },
  { id: "left_c_chain_4", from: "left_c3", to: "left_tip" },
  { id: "left_tail_chain_1", from: "left_tip", to: "left_tail_1" },
  { id: "left_tail_chain_2", from: "left_tail_1", to: "left_tail_2" },
  { id: "left_tail_chain_3", from: "left_tail_2", to: "left_tail_3" },
  { id: "left_tail_chain_4", from: "left_tail_3", to: "left_tail_4" },
  { id: "left_tri_1", from: "left_a0", to: "left_b0" },
  { id: "left_tri_2", from: "left_b0", to: "left_c0" },
  { id: "left_tri_7", from: "left_a3", to: "left_b3" },
  { id: "left_tri_8", from: "left_b3", to: "left_c3" },
  { id: "left_tri_9", from: "left_a3", to: "left_tip" },
  { id: "left_tri_10", from: "left_c3", to: "left_tip" },
  { id: "left_cross_1", from: "left_b0", to: "left_a1" },
  { id: "left_cross_7", from: "left_b3", to: "left_tip" },
  { id: "left_cross_8", from: "left_c3", to: "left_tip" },
  { id: "left_attach_1", from: "left_attach_top", to: "left_a0" },
  { id: "left_attach_1b", from: "left_attach_top", to: "left_bridge_top" },
  { id: "left_attach_2", from: "left_attach_top", to: "left_b0" },
  { id: "left_attach_3", from: "left_attach_bottom", to: "left_b0" },
  { id: "left_attach_4", from: "left_attach_bottom", to: "left_c0" },
  { id: "left_to_outer_1", from: "left_attach_top", to: "halo_nw" },
  { id: "left_to_outer_2", from: "left_attach_bottom", to: "halo_nw" },
  { id: "left_to_outer_3", from: "left_c0", to: "halo_w" },
  { id: "left_to_outer_4", from: "left_c0", to: "halo_nw" },
  { id: "left_to_outer_5", from: "left_a0", to: "halo_nw" },
  { id: "left_to_outer_11", from: "left_bridge_top", to: "halo_nw" },
  { id: "left_to_outer_12", from: "left_bridge_top", to: "halo_n" },
  { id: "left_to_outer_6", from: "left_b0", to: "halo_nw" },
  { id: "left_to_outer_10", from: "left_c3", to: "halo_nw" },

  { id: "right_a_chain_1", from: "right_a0", to: "right_a1" },
  { id: "right_a_chain_2", from: "right_a1", to: "right_a2" },
  { id: "right_a_chain_3", from: "right_a2", to: "right_a3" },
  { id: "right_a_chain_4", from: "right_a3", to: "right_a4" },
  { id: "right_a_chain_5", from: "right_a4", to: "right_a5" },
  { id: "right_b_chain_1", from: "right_b0", to: "right_b1" },
  { id: "right_b_chain_2", from: "right_b1", to: "right_b2" },
  { id: "right_b_chain_3", from: "right_b2", to: "right_b3" },
  { id: "right_b_chain_4", from: "right_b3", to: "right_b4" },
  { id: "right_b_chain_5", from: "right_b4", to: "right_b5" },
  { id: "right_c_chain_1", from: "right_c0", to: "right_c1" },
  { id: "right_c_chain_2", from: "right_c1", to: "right_c2" },
  { id: "right_c_chain_3", from: "right_c2", to: "right_c3" },
  { id: "right_c_chain_4", from: "right_c3", to: "right_c4" },
  { id: "right_c_chain_5", from: "right_c4", to: "right_c5" },
  { id: "right_tri_1", from: "right_a0", to: "right_b0" },
  { id: "right_tri_2", from: "right_a1", to: "right_b1" },
  { id: "right_tri_3", from: "right_a2", to: "right_b2" },
  { id: "right_tri_4", from: "right_a3", to: "right_b3" },
  { id: "right_tri_5", from: "right_a4", to: "right_b4" },
  { id: "right_tri_6", from: "right_a5", to: "right_b5" },
  { id: "right_thick_1", from: "right_b0", to: "right_c0" },
  { id: "right_thick_2", from: "right_b1", to: "right_c1" },
  { id: "right_thick_3", from: "right_b2", to: "right_c2" },
  { id: "right_thick_4", from: "right_b3", to: "right_c3" },
  { id: "right_thick_5", from: "right_b4", to: "right_c4" },
  { id: "right_thick_6", from: "right_b5", to: "right_c5" },
  { id: "right_cross_1", from: "right_b0", to: "right_a1" },
  { id: "right_cross_2", from: "right_b1", to: "right_a2" },
  { id: "right_cross_3", from: "right_b2", to: "right_a3" },
  { id: "right_cross_4", from: "right_b3", to: "right_a4" },
  { id: "right_cross_5", from: "right_b4", to: "right_a5" },
  { id: "right_cross_7", from: "right_c1", to: "right_b2" },
  { id: "right_cross_8", from: "right_c2", to: "right_b3" },
  { id: "right_cross_9", from: "right_c3", to: "right_b4" },
  { id: "right_cross_10", from: "right_c4", to: "right_b5" },
  { id: "right_attach_3", from: "right_attach_bottom", to: "right_b0" },
  { id: "right_attach_4", from: "right_attach_bottom", to: "right_c0" },
  { id: "right_to_outer_12", from: "right_bridge_top", to: "halo_ne" },
  { id: "right_to_outer_13", from: "right_bridge_top", to: "halo_e" },
  { id: "right_to_outer_14", from: "right_bridge_peak", to: "halo_ne" },
  { id: "right_to_outer_15", from: "right_bridge_peak", to: "halo_n" },
  { id: "right_bridge_chain_1", from: "right_bridge_top", to: "right_bridge_peak" },

  { id: "corridor_chain_1", from: "corridor_0", to: "corridor_1" },
  { id: "corridor_chain_2", from: "corridor_1", to: "corridor_2" },
  { id: "corridor_chain_3", from: "corridor_2", to: "corridor_3" },
  { id: "corridor_chain_4", from: "corridor_3", to: "corridor_4" },
  { id: "corridor_chain_5", from: "corridor_4", to: "corridor_5" },
  { id: "corridor_chain_6", from: "corridor_5", to: "corridor_6" },
  { id: "corridor_to_arm_1", from: "corridor_0", to: "right_c1" },
  { id: "corridor_to_arm_2", from: "corridor_1", to: "right_c2" },
  { id: "corridor_to_arm_3", from: "corridor_2", to: "right_c3" },
  { id: "corridor_to_arm_4", from: "corridor_3", to: "right_b2" },
  { id: "corridor_to_arm_5", from: "corridor_4", to: "right_b4" },
  { id: "corridor_to_arm_6", from: "corridor_5", to: "right_a5" },
  { id: "corridor_to_arm_7", from: "corridor_5", to: "right_c3" },
  { id: "corridor_to_arm_8", from: "corridor_5", to: "right_b2" },
];

export const BLOG_DEFENSE_COMPROMISE_PATH: string[] = [
  "corridor_6",
  "corridor_5",
  "corridor_4",
  "corridor_3",
  "right_b3",
  "right_b2",
  "right_b1",
  "right_b0",
  "ring_s",
  "mid_s",
  "core",
];

export type BlogDefenseCompromiseStep =
  | { kind: "node"; nodeId: string }
  | { kind: "edge"; from: string; to: string; edgeId: string };

function edgeKey(a: string, b: string): string {
  return a < b ? `${a}::${b}` : `${b}::${a}`;
}

function normalizeAngle(angle: number): number {
  while (angle > Math.PI) angle -= Math.PI * 2;
  while (angle < -Math.PI) angle += Math.PI * 2;
  return angle;
}

function buildGraphIndex(edges: BlogDefenseEdge[]): {
  adjacency: Map<string, string[]>;
  edgeByNodes: Map<string, BlogDefenseEdge>;
} {
  const adjacency = new Map<string, string[]>();
  const edgeByNodes = new Map<string, BlogDefenseEdge>();
  for (const edge of edges) {
    if (!adjacency.has(edge.from)) adjacency.set(edge.from, []);
    if (!adjacency.has(edge.to)) adjacency.set(edge.to, []);
    adjacency.get(edge.from)?.push(edge.to);
    adjacency.get(edge.to)?.push(edge.from);
    edgeByNodes.set(edgeKey(edge.from, edge.to), edge);
  }
  return { adjacency, edgeByNodes };
}

export function getBlogDefensePathEdge(from: string, to: string): BlogDefenseEdge | undefined {
  return BLOG_DEFENSE_EDGES.find(
    (edge) => (edge.from === from && edge.to === to) || (edge.from === to && edge.to === from),
  );
}

export function buildCompromiseSequenceFromPath(nodeIds: string[], edges: BlogDefenseEdge[]): BlogDefenseCompromiseStep[] {
  const steps: BlogDefenseCompromiseStep[] = [];
  if (!nodeIds.length) return steps;
  const { edgeByNodes } = buildGraphIndex(edges);
  steps.push({ kind: "node", nodeId: nodeIds[0] });
  for (let index = 0; index < nodeIds.length - 1; index += 1) {
    const from = nodeIds[index];
    const to = nodeIds[index + 1];
    const edge = edgeByNodes.get(edgeKey(from, to));
    if (!edge) continue;
    steps.push({ kind: "edge", from, to, edgeId: edge.id });
    steps.push({ kind: "node", nodeId: to });
  }
  return steps;
}

function shortestPathWithTieBreak(
  startId: string,
  targetId: string,
  nodeById: Map<string, BlogDefenseNode>,
  adjacency: Map<string, string[]>,
  blockedNodeIds: Set<string> = new Set(),
): string[] {
  const queue: string[] = [startId];
  const visited = new Set<string>([startId]);
  const prev = new Map<string, string>();
  const targetNode = nodeById.get(targetId);
  while (queue.length) {
    const current = queue.shift();
    if (!current) break;
    if (current === targetId) break;
    const neighbors = [...(adjacency.get(current) ?? [])];
    neighbors.sort((a, b) => {
      const aNode = nodeById.get(a);
      const bNode = nodeById.get(b);
      if (!aNode || !bNode || !targetNode) return 0;
      const aDist = Math.hypot(aNode.x - targetNode.x, aNode.y - targetNode.y);
      const bDist = Math.hypot(bNode.x - targetNode.x, bNode.y - targetNode.y);
      return aDist - bDist;
    });
    for (const neighbor of neighbors) {
      if (neighbor !== targetId && blockedNodeIds.has(neighbor)) continue;
      if (visited.has(neighbor)) continue;
      visited.add(neighbor);
      prev.set(neighbor, current);
      queue.push(neighbor);
    }
  }

  if (!visited.has(targetId)) return [];
  const path: string[] = [targetId];
  let current = targetId;
  while (current !== startId) {
    const parent = prev.get(current);
    if (!parent) return [];
    path.unshift(parent);
    current = parent;
  }
  return path;
}

function nodeApproachPriority(node: BlogDefenseNode): number {
  if (node.id.startsWith("mid_")) return 0;
  if (node.id.startsWith("ring_")) return 1;
  if (node.id.startsWith("outer_")) return 2;
  if (node.id.startsWith("halo_")) return 3;
  return 4;
}

function resolveCoreApproachCandidates(
  startId: string,
  coreId: string,
  nodeById: Map<string, BlogDefenseNode>,
  adjacency: Map<string, string[]>,
): string[] {
  const coreNode = nodeById.get(coreId);
  const startNode = nodeById.get(startId);
  if (!coreNode || !startNode) return [];

  const startAngle = Math.atan2(startNode.y - coreNode.y, startNode.x - coreNode.x);
  return [...(adjacency.get(coreId) ?? [])]
    .map((id) => nodeById.get(id))
    .filter((node): node is BlogDefenseNode => Boolean(node))
    .sort((left, right) => {
      const leftPriority = nodeApproachPriority(left);
      const rightPriority = nodeApproachPriority(right);
      if (leftPriority !== rightPriority) return leftPriority - rightPriority;

      const leftAngle = Math.atan2(left.y - coreNode.y, left.x - coreNode.x);
      const rightAngle = Math.atan2(right.y - coreNode.y, right.x - coreNode.x);
      const leftDelta = Math.abs(normalizeAngle(leftAngle - startAngle));
      const rightDelta = Math.abs(normalizeAngle(rightAngle - startAngle));
      if (Math.abs(leftDelta - rightDelta) > 0.001) return leftDelta - rightDelta;

      const leftDistance = Math.hypot(startNode.x - left.x, startNode.y - left.y);
      const rightDistance = Math.hypot(startNode.x - right.x, startNode.y - right.y);
      return leftDistance - rightDistance;
    })
    .map((node) => node.id);
}

function buildPathToCoreWithPreferredApproach(
  startId: string,
  coreId: string,
  nodeById: Map<string, BlogDefenseNode>,
  adjacency: Map<string, string[]>,
): string[] {
  const approachCandidates = resolveCoreApproachCandidates(startId, coreId, nodeById, adjacency);
  for (const approachId of approachCandidates) {
    const approachPath = shortestPathWithTieBreak(startId, approachId, nodeById, adjacency, new Set([coreId]));
    if (!approachPath.length) continue;
    if (!(adjacency.get(approachId) ?? []).includes(coreId)) continue;
    return [...approachPath, coreId];
  }

  return shortestPathWithTieBreak(startId, coreId, nodeById, adjacency);
}

function hopDistanceToCore(
  coreId: string,
  adjacency: Map<string, string[]>,
  blockedNodeIds: Set<string> = new Set(),
): Map<string, number> {
  const distances = new Map<string, number>();
  const queue: string[] = [coreId];
  distances.set(coreId, 0);

  while (queue.length) {
    const current = queue.shift();
    if (!current) break;
    const currentDistance = distances.get(current) ?? 0;
    for (const neighbor of adjacency.get(current) ?? []) {
      if (neighbor !== coreId && blockedNodeIds.has(neighbor)) continue;
      if (distances.has(neighbor)) continue;
      distances.set(neighbor, currentDistance + 1);
      queue.push(neighbor);
    }
  }

  return distances;
}

function chooseWeightedIndex(weights: number[]): number {
  const total = weights.reduce((sum, weight) => sum + (weight > 0 ? weight : 0), 0);
  if (total <= 0) return 0;
  let roll = Math.random() * total;
  for (let index = 0; index < weights.length; index += 1) {
    roll -= Math.max(0, weights[index]);
    if (roll <= 0) return index;
  }
  return Math.max(0, weights.length - 1);
}

function buildStochasticInwardPath(
  startId: string,
  coreId: string,
  nodeById: Map<string, BlogDefenseNode>,
  adjacency: Map<string, string[]>,
): string[] {
  const approachCandidates = resolveCoreApproachCandidates(startId, coreId, nodeById, adjacency);
  const preferredApproachId = approachCandidates[0];
  if (!preferredApproachId) {
    return shortestPathWithTieBreak(startId, coreId, nodeById, adjacency);
  }

  const distances = hopDistanceToCore(preferredApproachId, adjacency, new Set([coreId]));
  if (!distances.has(startId)) return [];
  if (startId === preferredApproachId) return [preferredApproachId, coreId];

  const maxSteps = Math.max(10, Math.min(40, nodeById.size + 6));
  const path = [startId];
  const visitCounts = new Map<string, number>([[startId, 1]]);
  let current = startId;

  for (let step = 0; step < maxSteps && current !== preferredApproachId; step += 1) {
    const neighbors = (adjacency.get(current) ?? []).filter((neighbor) => distances.has(neighbor));
    if (!neighbors.length) break;

    const currentHop = distances.get(current) ?? Number.POSITIVE_INFINITY;
    const improving = neighbors.filter((neighbor) => (distances.get(neighbor) ?? Number.POSITIVE_INFINITY) < currentHop);
    const candidatePool = improving.length && Math.random() < 0.82 ? improving : neighbors;

    const weights = candidatePool.map((neighbor) => {
      const neighborHop = distances.get(neighbor) ?? Number.POSITIVE_INFINITY;
      const hopDelta = currentHop - neighborHop;
      const revisitPenalty = 1 / (1 + (visitCounts.get(neighbor) ?? 0) * 1.8);
      const core = nodeById.get(preferredApproachId);
      const neighborNode = nodeById.get(neighbor);
      const euclideanBias = core && neighborNode
        ? 1 / (1 + Math.hypot(neighborNode.x - core.x, neighborNode.y - core.y) * 0.015)
        : 1;

      let bias = 1;
      if (hopDelta > 0) bias = 5 + hopDelta * 1.8;
      else if (hopDelta === 0) bias = 0.9;
      else bias = 0.18;
      if (neighbor === preferredApproachId) bias *= 4;

      return Math.max(0.01, bias * revisitPenalty * euclideanBias);
    });

    const next = candidatePool[chooseWeightedIndex(weights)];
    path.push(next);
    visitCounts.set(next, (visitCounts.get(next) ?? 0) + 1);
    current = next;

    if (current === preferredApproachId) return [...path, coreId];
  }

  if (current !== preferredApproachId) {
    const completion = shortestPathWithTieBreak(current, preferredApproachId, nodeById, adjacency, new Set([coreId]));
    if (completion.length > 1) path.push(...completion.slice(1));
  }

  return path[path.length - 1] === preferredApproachId ? [...path, coreId] : [];
}

export function buildVisibleAttackPath(input: VisibleAttackPathInput): VisibleAttackPath {
  const coreId = input.coreId ?? BLOG_DEFENSE_CORE_NODE_ID;
  const nodeById = new Map(input.nodes.map((node) => [node.id, node]));
  const visibleEdges = input.edges.filter((edge) => nodeById.has(edge.from) && nodeById.has(edge.to));
  const { adjacency, edgeByNodes } = buildGraphIndex(visibleEdges);

  const corridorCandidates = input.nodes
    .filter((node) => node.zone === "right_corridor")
    .sort((a, b) => {
      if (b.y !== a.y) return b.y - a.y;
      return b.x - a.x;
    });

  const starts = corridorCandidates.length
    ? corridorCandidates
    : input.nodes.slice().sort((a, b) => {
        if (b.y !== a.y) return b.y - a.y;
        return b.x - a.x;
      });

  if (input.stochastic && starts.length) {
    const stochasticStartWeights = starts.map((node, index) => {
      const yBias = Math.max(1, node.y);
      const rankBias = Math.max(0.35, 1 - index * 0.06);
      return yBias * rankBias;
    });
    const stochasticStart = starts[chooseWeightedIndex(stochasticStartWeights)];
    const stochasticPath = buildStochasticInwardPath(stochasticStart.id, coreId, nodeById, adjacency);
    if (stochasticPath.length) {
      const sequence = buildCompromiseSequenceFromPath(stochasticPath, visibleEdges);
      return {
        nodeIds: sequence.filter((step) => step.kind === "node").map((step) => step.nodeId),
        edgeIds: sequence.filter((step) => step.kind === "edge").map((step) => step.edgeId),
      };
    }
  }

  for (const start of starts) {
    const path = buildPathToCoreWithPreferredApproach(start.id, coreId, nodeById, adjacency);
    if (!path.length) continue;
    const sequence = buildCompromiseSequenceFromPath(path, visibleEdges);
    return {
      nodeIds: sequence.filter((step) => step.kind === "node").map((step) => step.nodeId),
      edgeIds: sequence.filter((step) => step.kind === "edge").map((step) => step.edgeId),
    };
  }

  const fallback = input.nodes
    .filter((node) => node.id !== coreId)
    .sort((a, b) => {
      const core = nodeById.get(coreId);
      if (!core) return 0;
      const aDist = Math.hypot(a.x - core.x, a.y - core.y);
      const bDist = Math.hypot(b.x - core.x, b.y - core.y);
      return bDist - aDist;
    });
  for (const start of fallback) {
    const path = buildPathToCoreWithPreferredApproach(start.id, coreId, nodeById, adjacency);
    if (!path.length) continue;
    const sequence = buildCompromiseSequenceFromPath(path, visibleEdges);
    return {
      nodeIds: sequence.filter((step) => step.kind === "node").map((step) => step.nodeId),
      edgeIds: sequence.filter((step) => step.kind === "edge").map((step) => step.edgeId),
    };
  }

  return {
    nodeIds: nodeById.has(coreId) ? [coreId] : [],
    edgeIds: [],
  };
}

export function buildBlogDefenseCompromiseSequence(): BlogDefenseCompromiseStep[] {
  return buildCompromiseSequenceFromPath(BLOG_DEFENSE_COMPROMISE_PATH, BLOG_DEFENSE_EDGES);
}

export function isBlogDefenseAttackEdge(from: string, to: string): boolean {
  for (let index = 0; index < BLOG_DEFENSE_COMPROMISE_PATH.length - 1; index += 1) {
    const a = BLOG_DEFENSE_COMPROMISE_PATH[index];
    const b = BLOG_DEFENSE_COMPROMISE_PATH[index + 1];
    if ((from === a && to === b) || (from === b && to === a)) return true;
  }
  return false;
}

export function edgeIdForNodes(from: string, to: string, edges: BlogDefenseEdge[]): string | null {
  const edge = edges.find((entry) => (
    (entry.from === from && entry.to === to) || (entry.from === to && entry.to === from)
  ));
  return edge ? edge.id : null;
}
