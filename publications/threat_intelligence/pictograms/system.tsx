"use client";

import { motion, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { PICTOGRAM_CYCLE_MS, PICTOGRAM_EDGE_WIDTH, PICTOGRAM_NODE_RADIUS } from "./registry";

export type PictogramPalette = {
  frame: string;
  edge: string;
  node: string;
  muted: string;
  accent: string;
  accentSoft: string;
  accentGlow: string;
  safe: string;
  warning: string;
  barrier: string;
};

export const PICTOGRAM_PALETTE: PictogramPalette = {
  frame: "var(--background)",
  edge: "var(--ti-pictogram-edge)",
  node: "var(--ti-pictogram-node)",
  muted: "var(--ti-pictogram-muted)",
  accent: "var(--ti-pictogram-compromised)",
  accentSoft: "var(--ti-pictogram-throb)",
  accentGlow: "var(--ti-pictogram-accent-glow)",
  safe: "var(--grass-8)",
  warning: "var(--amber-8)",
  barrier: "var(--sand-8)",
};

export type PictogramMotion = {
  cycleS: number;
  phase: number;
  prefersReducedMotion: boolean;
  delayS: (offsetMs?: number) => number;
};

export function usePictogramMotion(phaseOffsetMs: number): PictogramMotion {
  const prefersReducedMotion = useReducedMotion() ?? false;
  const [epochMs, setEpochMs] = useState(0);

  useEffect(() => {
    setEpochMs(Date.now() % PICTOGRAM_CYCLE_MS);
  }, []);

  return useMemo(() => {
    const cycleS = PICTOGRAM_CYCLE_MS / 1000;
    const phase = ((epochMs + phaseOffsetMs) % PICTOGRAM_CYCLE_MS) / PICTOGRAM_CYCLE_MS;
    return {
      cycleS,
      phase,
      prefersReducedMotion,
      delayS: (offsetMs = 0) =>
        prefersReducedMotion ? 0 : -(((epochMs + phaseOffsetMs + offsetMs) % PICTOGRAM_CYCLE_MS) / 1000),
    };
  }, [epochMs, phaseOffsetMs, prefersReducedMotion]);
}

export function PictogramFrame({
  aspectRatio = 1,
  children,
}: {
  aspectRatio?: number;
  children: ReactNode;
}) {
  return (
    <div className="pictogram-figure__frame" style={{ "--pictogram-aspect-ratio": String(aspectRatio) } as CSSProperties}>
      {children}
    </div>
  );
}

export function PictogramSvg({
  alt,
  children,
  viewBox = "0 0 320 220",
}: {
  alt: string;
  children: ReactNode;
  viewBox?: string;
}) {
  return (
    <svg aria-label={alt} className="pictogram-figure__svg" role="img" viewBox={viewBox}>
      <title>{alt}</title>
      {children}
    </svg>
  );
}

export function Line({
  d,
  palette,
  tone = "edge",
  width = PICTOGRAM_EDGE_WIDTH,
  opacity = 1,
  dashArray,
  dashOffset,
}: {
  d: string;
  palette: PictogramPalette;
  tone?: "edge" | "muted" | "accent" | "safe" | "warning" | "barrier";
  width?: number;
  opacity?: number;
  dashArray?: string;
  dashOffset?: number;
}) {
  return (
    <path
      d={d}
      fill="none"
      opacity={opacity}
      stroke={resolveTone(palette, tone)}
      strokeDasharray={dashArray}
      strokeDashoffset={dashOffset}
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={width}
    />
  );
}

export function MotionLine({
  animate,
  d,
  palette,
  tone = "edge",
  transition,
  width = PICTOGRAM_EDGE_WIDTH,
  opacity = 1,
  dashArray,
}: {
  animate: any;
  d: string;
  palette: PictogramPalette;
  tone?: "edge" | "muted" | "accent" | "safe" | "warning" | "barrier";
  transition: any;
  width?: number;
  opacity?: number;
  dashArray?: string;
}) {
  return (
    <motion.path
      animate={animate}
      d={d}
      fill="none"
      initial={false}
      opacity={opacity}
      stroke={resolveTone(palette, tone)}
      strokeDasharray={dashArray}
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={width}
      transition={transition}
    />
  );
}

export function Node({
  glow = false,
  palette,
  r = PICTOGRAM_NODE_RADIUS,
  tone = "node",
  x,
  y,
}: {
  glow?: boolean;
  palette: PictogramPalette;
  r?: number;
  tone?: "node" | "muted" | "accent" | "safe" | "warning";
  x: number;
  y: number;
}) {
  const fill = resolveNodeTone(palette, tone);
  return (
    <g>
      {glow ? <circle cx={x} cy={y} fill={palette.accentGlow} r={r * 2.4} /> : null}
      <circle cx={x} cy={y} fill={fill} r={r} />
    </g>
  );
}

export function MotionNode({
  animate,
  glow = false,
  palette,
  r = PICTOGRAM_NODE_RADIUS,
  tone = "node",
  transition,
  x,
  y,
}: {
  animate: any;
  glow?: boolean;
  palette: PictogramPalette;
  r?: number;
  tone?: "node" | "muted" | "accent" | "safe" | "warning";
  transition: any;
  x: number;
  y: number;
}) {
  const fill = resolveNodeTone(palette, tone);
  return (
    <g>
      {glow ? (
        <motion.circle animate={animate} cx={x} cy={y} fill={palette.accentGlow} initial={false} r={r * 2.4} transition={transition} />
      ) : null}
      <motion.circle animate={animate} cx={x} cy={y} fill={fill} initial={false} r={r} transition={transition} />
    </g>
  );
}

export function Box({
  fillOpacity = 0.08,
  height,
  palette,
  strokeTone = "edge",
  width,
  x,
  y,
}: {
  fillOpacity?: number;
  height: number;
  palette: PictogramPalette;
  strokeTone?: "edge" | "muted" | "accent" | "safe" | "warning" | "barrier";
  width: number;
  x: number;
  y: number;
}) {
  const stroke = resolveTone(palette, strokeTone);
  return (
    <rect
      fill={stroke}
      fillOpacity={fillOpacity}
      height={height}
      rx={14}
      stroke={stroke}
      strokeWidth={PICTOGRAM_EDGE_WIDTH}
      width={width}
      x={x}
      y={y}
    />
  );
}

export function arrowPath(x1: number, y1: number, x2: number, y2: number, arrowSize = 9): string {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const length = Math.sqrt(dx * dx + dy * dy) || 1;
  const ux = dx / length;
  const uy = dy / length;
  const px = -uy;
  const py = ux;
  const bx = x2 - ux * arrowSize;
  const by = y2 - uy * arrowSize;
  const leftX = bx + px * (arrowSize * 0.55);
  const leftY = by + py * (arrowSize * 0.55);
  const rightX = bx - px * (arrowSize * 0.55);
  const rightY = by - py * (arrowSize * 0.55);
  return `M ${x1} ${y1} L ${x2} ${y2} M ${leftX} ${leftY} L ${x2} ${y2} L ${rightX} ${rightY}`;
}

export function pointsPath(points: Array<[number, number]>): string {
  return points.map(([x, y], index) => `${index === 0 ? "M" : "L"} ${x} ${y}`).join(" ");
}

export function ringNodes(cx: number, cy: number, radius: number, count: number, startAngle = -90): Array<[number, number]> {
  return Array.from({ length: count }, (_, index) => {
    const angle = ((startAngle + (360 / count) * index) * Math.PI) / 180;
    return [cx + Math.cos(angle) * radius, cy + Math.sin(angle) * radius];
  });
}

function resolveTone(palette: PictogramPalette, tone: "edge" | "muted" | "accent" | "safe" | "warning" | "barrier"): string {
  switch (tone) {
    case "muted":
      return palette.muted;
    case "accent":
      return palette.accent;
    case "safe":
      return palette.safe;
    case "warning":
      return palette.warning;
    case "barrier":
      return palette.barrier;
    default:
      return palette.edge;
  }
}

function resolveNodeTone(palette: PictogramPalette, tone: "node" | "muted" | "accent" | "safe" | "warning"): string {
  switch (tone) {
    case "muted":
      return palette.muted;
    case "accent":
      return palette.accent;
    case "safe":
      return palette.safe;
    case "warning":
      return palette.warning;
    default:
      return palette.node;
  }
}
