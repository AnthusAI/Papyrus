"use client";

import { motion } from "motion/react";
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";
import {
  BLOG_DEFENSE_CORE_NODE_ID,
  buildCompromiseSequenceFromPath,
  buildVisibleAttackPath,
  type BlogDefenseCompromiseStep,
} from "./graph";
import { layoutDefenseGraph, type LayoutDefenseNode } from "./layout";
import { SITE_BRAND } from "../../../lib/site-brand";
import { PICTOGRAM_CYCLE_MS } from "../pictograms/registry";
import { useResolvedPapyrusTheme } from "../../../components/use-resolved-papyrus-theme";

const THROB_MS = 190;
const COMPROMISE_MS = 120;
const STEP_GAP_MS = 36;
const START_DELAY_MS = 40;
const COMPROMISE_TRANSITION_S = COMPROMISE_MS / 1000;
const THROB_TRANSITION_S = 0.21;
const BREACH_RING_DELAYS_S = [0, 0.6, 1.2];
const BREACH_RING_DURATION_S = 2.4;

type PictogramColors = {
  edge: string;
  node: string;
  throb: string;
  coreGlow: string;
  compromised: string;
  compromisedStroke: string;
};

const FALLBACK_COLORS: Record<"light" | "dark", PictogramColors> = {
  light: {
    edge: "var(--slate-8)",
    node: "var(--slate-8)",
    throb: "var(--tomato-8)",
    coreGlow: "var(--ti-alarm-red)",
    compromised: "var(--tomato-11)",
    compromisedStroke: "var(--sand-1)",
  },
  dark: {
    edge: "var(--slate-6)",
    node: "var(--slate-5)",
    throb: "var(--tomato-8)",
    coreGlow: "var(--ti-alarm-red)",
    compromised: "var(--tomato-9)",
    compromisedStroke: "var(--sand-2)",
  },
};

type Size = {
  width: number;
  height: number;
};

type ObstacleRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

type BlogPageBackgroundProps = {
  pageRef: RefObject<HTMLElement | null>;
};

function intersectRect(source: DOMRect, bounds: DOMRect): ObstacleRect | null {
  const left = Math.max(source.left, bounds.left);
  const top = Math.max(source.top, bounds.top);
  const right = Math.min(source.right, bounds.right);
  const bottom = Math.min(source.bottom, bounds.bottom);
  const width = right - left;
  const height = bottom - top;
  if (width <= 0 || height <= 0) return null;
  return {
    x: left - bounds.left,
    y: top - bounds.top,
    width,
    height,
  };
}

function textFragmentRects(element: HTMLElement, bounds: DOMRect): ObstacleRect[] {
  const ownerDocument = element.ownerDocument;
  const elementRect = element.getBoundingClientRect();
  const computedStyle = ownerDocument.defaultView?.getComputedStyle(element);
  const context = ownerDocument.createElement("canvas").getContext("2d");
  if (context && computedStyle) {
    context.font = computedStyle.font;
  }
  const walker = ownerDocument.createTreeWalker(
    element,
    NodeFilter.SHOW_TEXT,
    {
      acceptNode(node) {
        return /\S/.test(node.textContent ?? "")
          ? NodeFilter.FILTER_ACCEPT
          : NodeFilter.FILTER_REJECT;
      },
    },
  );
  const range = ownerDocument.createRange();
  const rects: ObstacleRect[] = [];

  try {
    let node = walker.nextNode();
    while (node) {
      const text = node.textContent ?? "";
      const tokenPattern = /\S+/g;
      let match: RegExpExecArray | null;
      while ((match = tokenPattern.exec(text)) !== null) {
        range.setStart(node, match.index);
        range.setEnd(node, match.index + match[0].length);
        for (const fragmentRect of Array.from(range.getClientRects())) {
          const measuredWidth = context?.measureText(match[0]).width ?? 0;
          const textWidth = measuredWidth > 0 && measuredWidth < (fragmentRect.width * 0.98)
            ? measuredWidth
            : fragmentRect.width;
          const sourceRect = new DOMRect(
            fragmentRect.left,
            elementRect.top,
            textWidth,
            elementRect.height,
          );
          const rect = intersectRect(sourceRect, bounds);
          if (rect) rects.push(rect);
        }
      }
      node = walker.nextNode();
    }
  } finally {
    range.detach();
  }

  return rects;
}

function elementObstacleRects(element: HTMLElement, bounds: DOMRect): ObstacleRect[] {
  const fragments = textFragmentRects(element, bounds);
  if (fragments.length > 0) return fragments;
  return Array.from(element.getClientRects())
    .map((lineRect) => intersectRect(lineRect, bounds))
    .filter((rect): rect is ObstacleRect => Boolean(rect));
}

function readPictogramColors(container: HTMLElement): PictogramColors {
  const style = getComputedStyle(container);
  return {
    edge: style.getPropertyValue("--ti-pictogram-edge").trim() || FALLBACK_COLORS.light.edge,
    node: style.getPropertyValue("--ti-pictogram-node").trim() || FALLBACK_COLORS.light.node,
    throb: style.getPropertyValue("--ti-pictogram-throb").trim() || FALLBACK_COLORS.light.throb,
    coreGlow: style.getPropertyValue("--ti-pictogram-core-glow").trim() || FALLBACK_COLORS.light.coreGlow,
    compromised: style.getPropertyValue("--ti-pictogram-compromised").trim() || FALLBACK_COLORS.light.compromised,
    compromisedStroke: style.getPropertyValue("--ti-pictogram-compromised-stroke").trim() || FALLBACK_COLORS.light.compromisedStroke,
  };
}

function stepDurationMs(): number {
  return THROB_MS + COMPROMISE_MS + STEP_GAP_MS;
}

function isSameThrobStep(a: BlogDefenseCompromiseStep | null, b: BlogDefenseCompromiseStep | null): boolean {
  if (!a || !b || a.kind !== b.kind) return false;
  if (a.kind === "node" && b.kind === "node") return a.nodeId === b.nodeId;
  if (a.kind === "edge" && b.kind === "edge") return a.edgeId === b.edgeId;
  return false;
}

function CoreBreachEffect({
  coreNode,
  colors,
  filterId,
  prefersReducedMotion,
  scale,
  layer,
}: {
  coreNode: LayoutDefenseNode;
  colors: PictogramColors;
  filterId: string;
  prefersReducedMotion: boolean;
  scale: number;
  layer: "rings" | "halo";
}) {
  const ringStartRadius = coreNode.radius * 1.2;
  const ringEndRadius = coreNode.radius * 3;
  const haloRadius = coreNode.radius * 1.85;

  if (layer === "rings") {
    return (
      <g className="blog-page-background__breach-rings" style={{ color: colors.coreGlow }}>
        {BREACH_RING_DELAYS_S.map((delay) => (
          <motion.circle
            animate={
              prefersReducedMotion
                ? { fillOpacity: 0.22, r: ringEndRadius * 0.75 }
                : {
                    fillOpacity: [0.45, 0],
                    r: [ringStartRadius, ringEndRadius],
                  }
            }
            cx={coreNode.x}
            cy={coreNode.y}
            fill="currentColor"
            initial={false}
            key={`breach-ring-${delay}`}
            transition={
              prefersReducedMotion
                ? { duration: 0 }
                : {
                    delay,
                    duration: BREACH_RING_DURATION_S,
                    ease: "easeOut",
                    repeat: Infinity,
                  }
            }
          />
        ))}
      </g>
    );
  }

  const blurStdDeviation = Math.max(5, scale * 0.45);
  return (
    <g className="blog-page-background__breach-halo" style={{ color: colors.coreGlow }}>
      <motion.circle
        animate={
          prefersReducedMotion
            ? { fillOpacity: 0.42, r: haloRadius }
            : {
                fillOpacity: [0.35, 0.7, 0.35],
                r: haloRadius,
              }
        }
        cx={coreNode.x}
        cy={coreNode.y}
        fill="currentColor"
        filter={`url(#${filterId})`}
        initial={false}
        transition={
          prefersReducedMotion
            ? { duration: 0 }
            : {
                duration: BREACH_RING_DURATION_S,
                ease: "easeInOut",
                repeat: Infinity,
              }
        }
      />
      <defs>
        <filter height="300%" id={filterId} width="300%" x="-100%" y="-100%">
          <feGaussianBlur result="blur" stdDeviation={blurStdDeviation} />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
    </g>
  );
}

export function BlogPageBackground({ pageRef }: BlogPageBackgroundProps) {
  const svgId = useId().replace(/:/g, "-");
  const coreBreachFilterId = `${svgId}-core-breach-glow`;
  const containerRef = useRef<HTMLDivElement | null>(null);
  const resolvedTheme = useResolvedPapyrusTheme();
  const [colors, setColors] = useState<PictogramColors>(FALLBACK_COLORS[resolvedTheme]);
  const [size, setSize] = useState<Size>({ width: 0, height: 0 });
  const [obstacles, setObstacles] = useState<ObstacleRect[]>([]);
  const [enableStochasticPath, setEnableStochasticPath] = useState(false);
  const [attackCycle, setAttackCycle] = useState(0);
  const [compromisedNodes, setCompromisedNodes] = useState<Set<string>>(() => new Set());
  const [compromisedEdges, setCompromisedEdges] = useState<Set<string>>(() => new Set());
  const [throbbingStep, setThrobbingStep] = useState<BlogDefenseCompromiseStep | null>(null);
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const update = () => {
      const rect = container.getBoundingClientRect();
      const width = Math.ceil(rect.width);
      const height = Math.ceil(rect.height);
      if (width > 0 && height > 0) {
        setSize((current) => (current.width === width && current.height === height ? current : { width, height }));
      }
    };

    update();
    const observer = new ResizeObserver(update);
    observer.observe(container);
    window.addEventListener("resize", update);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", update);
    };
  }, []);

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let page = pageRef.current ?? container.closest<HTMLElement>("main.presentation-page--blog");
    let raf = 0;
    let tries = 0;

    const update = () => {
      if (!page) {
        page = pageRef.current ?? container.closest<HTMLElement>("main.presentation-page--blog");
      }
      if (!page) return false;

      const containerRect = container.getBoundingClientRect();
      const padding = containerRect.width < 420 ? 6 : containerRect.width < 780 ? 9 : 12;
      const selectors = [
        ".presentation-header h1 span",
        ".presentation-header__meta",
        ".presentation-header__subtitle",
        ".presentation-header__date",
        ".presentation-header__tagline",
        ".presentation-section-nav a",
      ];
      const next: ObstacleRect[] = [];
      for (const selector of selectors) {
        const elements = Array.from(page.querySelectorAll<HTMLElement>(selector));
        for (const element of elements) {
          for (const rect of elementObstacleRects(element, containerRect)) {
            next.push({
              x: Math.max(0, rect.x - padding),
              y: Math.max(0, rect.y - padding),
              width: rect.width + padding * 2,
              height: rect.height + padding * 2,
            });
          }
        }
      }
      const unique = next.filter((candidate, index) => {
        return !next.slice(0, index).some((existing) => (
          Math.abs(existing.x - candidate.x) < 1
          && Math.abs(existing.y - candidate.y) < 1
          && Math.abs(existing.width - candidate.width) < 1
          && Math.abs(existing.height - candidate.height) < 1
        ));
      });
      setObstacles(unique);
      return unique.length > 0;
    };

    const ensureInitial = () => {
      const found = update();
      tries += 1;
      if (!found && tries < 30) {
        raf = window.requestAnimationFrame(ensureInitial);
      }
    };
    ensureInitial();

    const observer = new ResizeObserver(() => {
      void update();
    });
    observer.observe(container);
    if (page) observer.observe(page);
    window.addEventListener("resize", update);
    void document.fonts?.ready.then(() => {
      void update();
    });

    return () => {
      if (raf) window.cancelAnimationFrame(raf);
      observer.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [pageRef]);

  useEffect(() => {
    setEnableStochasticPath(true);
  }, []);

  useEffect(() => {
    if (!enableStochasticPath) return;
    const interval = window.setInterval(() => {
      setAttackCycle((current) => current + 1);
    }, PICTOGRAM_CYCLE_MS);
    return () => {
      window.clearInterval(interval);
    };
  }, [enableStochasticPath]);

  const graphLayout = useMemo(() => {
    if (!size.width || !size.height) return null;
    return layoutDefenseGraph({
      width: size.width,
      height: size.height,
      obstacles,
    });
  }, [obstacles, size.height, size.width]);

  const animationLayoutKey = `${size.width}:${size.height}`;
  const compromiseSequence = useMemo(() => {
    void attackCycle; // force recompute on attack cycle change
    if (!graphLayout) return [];
    const visiblePath = buildVisibleAttackPath({
      nodes: graphLayout.nodes,
      edges: graphLayout.edges,
      coreId: BLOG_DEFENSE_CORE_NODE_ID,
      stochastic: enableStochasticPath,
    });
    return buildCompromiseSequenceFromPath(visiblePath.nodeIds, graphLayout.edges);
  }, [attackCycle, enableStochasticPath, graphLayout]);
  const coreNode = useMemo(
    () => graphLayout?.nodes.find((node) => node.id === BLOG_DEFENSE_CORE_NODE_ID),
    [graphLayout?.nodes],
  );
  const coreBreached = compromisedNodes.has(BLOG_DEFENSE_CORE_NODE_ID);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    setColors(readPictogramColors(container));
  }, [resolvedTheme, animationLayoutKey]);

  useEffect(() => {
    if (!graphLayout || compromiseSequence.length === 0) return;

    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    setPrefersReducedMotion(motionQuery.matches);
    setCompromisedNodes(new Set());
    setCompromisedEdges(new Set());
    setThrobbingStep(null);

    if (motionQuery.matches) {
      const nodes = new Set<string>();
      const edges = new Set<string>();
      for (const step of compromiseSequence) {
        if (step.kind === "node") nodes.add(step.nodeId);
        else edges.add(step.edgeId);
      }
      setCompromisedNodes(nodes);
      setCompromisedEdges(edges);
      return;
    }

    const timeouts: number[] = [];
    const perStepMs = stepDurationMs();
    compromiseSequence.forEach((step, index) => {
      const stepStartMs = START_DELAY_MS + index * perStepMs;
      const compromiseAtMs = stepStartMs + THROB_MS;

      timeouts.push(window.setTimeout(() => {
        setThrobbingStep(step);
      }, stepStartMs));

      timeouts.push(window.setTimeout(() => {
        setThrobbingStep((current) => (isSameThrobStep(current, step) ? null : current));
        if (step.kind === "node") {
          setCompromisedNodes((current) => new Set([...current, step.nodeId]));
        } else {
          setCompromisedEdges((current) => new Set([...current, step.edgeId]));
        }
      }, compromiseAtMs));
    });

    return () => {
      timeouts.forEach((timeout) => window.clearTimeout(timeout));
    };
  }, [animationLayoutKey, attackCycle, compromiseSequence, graphLayout]);

  if (SITE_BRAND.id !== "threat-intelligence") return null;

  return (
    <div
      aria-hidden="true"
      className="blog-page-background"
      data-blog-page-background="true"
      data-blog-page-background-obstacles={JSON.stringify(obstacles)}
      ref={containerRef}
    >
      {graphLayout ? (
        <svg
          className="blog-page-background__svg"
          preserveAspectRatio="xMaxYMin meet"
          viewBox={`0 0 ${size.width} ${size.height}`}
        >
          <g className="blog-page-background__edges">
            {graphLayout.edges.map((edge) => {
              const isCompromised = compromisedEdges.has(edge.id);
              const isThrobbing = throbbingStep?.kind === "edge" && throbbingStep.edgeId === edge.id;
              const baseStrokeWidth = Math.max(1.4, graphLayout.scale * 1.2);
              return (
                <motion.line
                  animate={{
                    stroke: isCompromised
                      ? colors.compromised
                      : isThrobbing
                        ? [colors.edge, colors.throb, colors.edge]
                        : colors.edge,
                    strokeWidth: baseStrokeWidth,
                  }}
                  data-blog-edge-id={edge.id}
                  initial={false}
                  key={edge.id}
                  stroke={isCompromised ? colors.compromised : colors.edge}
                  strokeLinecap="round"
                  strokeWidth={baseStrokeWidth}
                  transition={
                    isThrobbing
                      ? { duration: THROB_TRANSITION_S, ease: "easeInOut", repeat: 1 }
                      : { duration: COMPROMISE_TRANSITION_S, ease: "easeOut" }
                  }
                  x1={edge.x1}
                  x2={edge.x2}
                  y1={edge.y1}
                  y2={edge.y2}
                />
              );
            })}
          </g>
          {coreBreached && coreNode ? (
            <CoreBreachEffect
              colors={colors}
              coreNode={coreNode}
              filterId={coreBreachFilterId}
              layer="rings"
              prefersReducedMotion={prefersReducedMotion}
              scale={graphLayout.scale}
            />
          ) : null}
          <g className="blog-page-background__nodes">
            {graphLayout.nodes.map((node) => {
              const isCompromised = compromisedNodes.has(node.id);
              const isThrobbing = throbbingStep?.kind === "node" && throbbingStep.nodeId === node.id;
              const isCore = node.role === "core";
              const coreBreachedNode = isCore && coreBreached;
              const coreStrokeWidth = isCore ? Math.max(4, graphLayout.scale * 1.5) : 0;
              const breachedCoreStrokeWidth = isCore
                ? Math.max(coreStrokeWidth * 1.35, graphLayout.scale * 2)
                : 0;
              return (
                <motion.circle
                  animate={{
                    fill: isCompromised
                      ? colors.compromised
                      : isThrobbing
                        ? [colors.node, colors.throb, colors.node]
                        : colors.node,
                    r: node.radius,
                    stroke: coreBreachedNode || (isCompromised && isCore)
                      ? colors.compromisedStroke
                      : "transparent",
                    strokeWidth: coreBreachedNode
                      ? breachedCoreStrokeWidth
                      : isCompromised && isCore
                        ? coreStrokeWidth
                        : 0,
                  }}
                  cx={node.x}
                  cy={node.y}
                  data-blog-node-id={node.id}
                  fill={isCompromised ? colors.compromised : colors.node}
                  initial={false}
                  key={node.id}
                  r={node.radius}
                  transition={
                    isThrobbing
                      ? { duration: THROB_TRANSITION_S, ease: "easeInOut", repeat: 1 }
                      : { duration: COMPROMISE_TRANSITION_S, ease: "easeOut" }
                  }
                />
              );
            })}
          </g>
          {coreBreached && coreNode ? (
            <CoreBreachEffect
              colors={colors}
              coreNode={coreNode}
              filterId={coreBreachFilterId}
              layer="halo"
              prefersReducedMotion={prefersReducedMotion}
              scale={graphLayout.scale}
            />
          ) : null}
        </svg>
      ) : null}
    </div>
  );
}
