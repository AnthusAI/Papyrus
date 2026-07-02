"use client";

import { motion } from "motion/react";
import type { CSSProperties, ReactElement } from "react";
import type { ThreatIntelligencePictogramSlug } from "./registry";
import {
  Box,
  Line,
  Node,
  PictogramSvg,
  pointsPath,
  type PictogramMotion,
  type PictogramPalette,
} from "./system";

export type RegisteredPictogramProps = {
  alt: string;
  timing: PictogramMotion;
  palette: PictogramPalette;
};

export type PictogramRegistryEntry = {
  aspectRatio?: number;
  render: (props: RegisteredPictogramProps) => ReactElement;
};

function BalanceShiftPictogram({ alt, palette, timing }: RegisteredPictogramProps) {
  const scalePalette = {
    ...palette,
    edge: "var(--foreground-strong)",
    node: "var(--foreground-strong)",
    muted: "color-mix(in srgb, var(--foreground-strong) 54%, var(--background) 46%)",
  };
  const nodeTransition = timing.prefersReducedMotion
    ? { duration: 0 }
    : {
        duration: timing.cycleS,
        repeat: Infinity,
        ease: "easeInOut",
        times: [0, 0.24, 0.42, 0.62, 1],
        delay: timing.delayS(900),
      };
  const animationDelay = `${timing.delayS()}s`;
  const beamStyle = {
    animation: timing.prefersReducedMotion ? "none" : `ti-scale-beam ${timing.cycleS}s ease-in-out ${animationDelay} infinite`,
    transform: timing.prefersReducedMotion ? "rotate(7deg)" : undefined,
    transformBox: "view-box",
    transformOrigin: "160px 118px",
  } as CSSProperties;
  const leftPanStyle = {
    animation: timing.prefersReducedMotion ? "none" : `ti-scale-left-pan ${timing.cycleS}s ease-in-out ${animationDelay} infinite`,
    transform: timing.prefersReducedMotion ? "translateY(-10px)" : undefined,
  } as CSSProperties;
  const rightPanStyle = {
    animation: timing.prefersReducedMotion ? "none" : `ti-scale-right-pan ${timing.cycleS}s ease-in-out ${animationDelay} infinite`,
    transform: timing.prefersReducedMotion ? "translateY(12px)" : undefined,
  } as CSSProperties;

  return (
    <PictogramSvg alt={alt} viewBox="0 0 320 320">
      <style>
        {`
          @keyframes ti-scale-beam {
            0%, 16%, 100% { transform: rotate(0deg); }
            38%, 82% { transform: rotate(7deg); }
          }

          @keyframes ti-scale-left-pan {
            0%, 16%, 100% { transform: translateY(0); }
            38%, 82% { transform: translateY(-10px); }
          }

          @keyframes ti-scale-right-pan {
            0%, 16%, 100% { transform: translateY(0); }
            38%, 82% { transform: translateY(12px); }
          }
        `}
      </style>
      <g transform="translate(160 166) scale(1.14) translate(-160 -166)">
        <Line d="M 160 86 V 246" palette={scalePalette} width={8} />
        <Line d="M 124 246 H 196" palette={scalePalette} width={9} />
        <g>
          <g style={beamStyle}>
            <path
              d="M 72 118 L 248 118"
              fill="none"
              stroke={scalePalette.edge}
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={8}
            />
            <path
              d="M 160 118 L 248 118"
              fill="none"
              stroke={palette.accent}
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={8}
            />
          </g>
          <g style={leftPanStyle}>
            <path
              d="M 78 118 L 42 198 H 128 L 78 118 Z"
              fill="none"
              stroke={scalePalette.edge}
              strokeLinejoin="round"
              strokeWidth={6}
            />
            <circle cx={70} cy={180} fill={scalePalette.node} opacity={0.88} r={15} />
            <circle cx={92} cy={190} fill={scalePalette.muted} opacity={0.86} r={11} />
          </g>
          <g style={rightPanStyle}>
            <path
              d="M 246 118 L 190 212 H 288 L 246 118 Z"
              fill="none"
              stroke={palette.accent}
              strokeLinejoin="round"
              strokeWidth={7}
            />
            <motion.circle
              animate={timing.prefersReducedMotion ? { opacity: 0.78, scale: 1 } : { opacity: [0.42, 0.42, 0.62, 0.82, 0.82], scale: [1, 1, 1.02, 1.04, 1.04] }}
              cx={208}
              cy={198}
              fill={palette.accent}
              initial={false}
              opacity={0.78}
              r={13}
              transition={nodeTransition as any}
            />
            <motion.circle
              animate={timing.prefersReducedMotion ? { opacity: 0.9, scale: 1 } : { opacity: [0.5, 0.5, 0.76, 0.95, 0.95], scale: [1, 1, 1.03, 1.07, 1.07] }}
              cx={232}
              cy={188}
              fill={palette.accent}
              initial={false}
              opacity={0.9}
              r={14}
              transition={{ ...nodeTransition, delay: timing.delayS(1200) } as any}
            />
            <motion.circle
              animate={timing.prefersReducedMotion ? { opacity: 1, scale: 1 } : { opacity: [0.55, 0.55, 0.84, 1, 1], scale: [1, 1, 1.03, 1.1, 1.1] }}
              cx={254}
              cy={200}
              fill={palette.accent}
              initial={false}
              opacity={1}
              r={16}
              transition={{ ...nodeTransition, delay: timing.delayS(1550) } as any}
            />
            <motion.circle
              animate={timing.prefersReducedMotion ? { opacity: 0.82, scale: 1 } : { opacity: [0.38, 0.38, 0.68, 0.88, 0.88], scale: [1, 1, 1.02, 1.06, 1.06] }}
              cx={274}
              cy={189}
              fill={palette.accent}
              initial={false}
              opacity={0.82}
              r={12}
              transition={{ ...nodeTransition, delay: timing.delayS(1900) } as any}
            />
          </g>
        </g>
        <circle cx={160} cy={118} fill={palette.frame} r={23} stroke={scalePalette.edge} strokeWidth={7} />
      </g>
    </PictogramSvg>
  );
}

function NewsroomFlowPictogram({ alt, palette, timing }: RegisteredPictogramProps) {
  const newsroomPalette = {
    ...palette,
    edge: "var(--foreground-strong)",
    node: "var(--foreground-strong)",
    muted: "color-mix(in srgb, var(--foreground-strong) 54%, var(--background) 46%)",
  };
  const animationDelay = `${timing.delayS()}s`;
  const wheelStyle = {
    animation: timing.prefersReducedMotion ? "none" : `ti-newsroom-wheel ${timing.cycleS}s ease-in-out ${animationDelay} infinite`,
    transform: timing.prefersReducedMotion ? "rotate(7deg)" : undefined,
    transformBox: "view-box",
    transformOrigin: "160px 70px",
  } as CSSProperties;
  const dotStyle = {
    animation: timing.prefersReducedMotion ? "none" : `ti-newsroom-dot ${timing.cycleS}s linear ${timing.delayS(1200)}s infinite`,
    transform: timing.prefersReducedMotion ? "translate(196px, 0)" : undefined,
  } as CSSProperties;
  const activeLineStyle = {
    animation: timing.prefersReducedMotion ? "none" : `ti-newsroom-flow ${timing.cycleS}s linear ${timing.delayS(1200)}s infinite`,
    opacity: timing.prefersReducedMotion ? 0.85 : undefined,
    strokeDashoffset: timing.prefersReducedMotion ? -224 : undefined,
  } as CSSProperties;
  const flowCenters = [
    [62, 214],
    [160, 160],
    [258, 214],
    [160, 264],
    [62, 214],
  ] as Array<[number, number]>;
  const flowPath = pointsPath(flowCenters);
  const states = [
    { cx: 62, cy: 214, r: 30, inner: "M 48 214 H 76" },
    { cx: 160, cy: 160, r: 32, inner: "M 146 152 H 174 M 146 168 H 174" },
    { cx: 258, cy: 214, r: 30, inner: "M 246 204 H 270 M 246 214 H 270 M 246 224 H 270" },
    { cx: 160, cy: 264, r: 30, inner: "M 148 256 L 160 268 L 176 250" },
  ];

  return (
    <PictogramSvg alt={alt} viewBox="0 0 320 320">
      <style>
        {`
          @keyframes ti-newsroom-wheel {
            0%, 16%, 100% { transform: rotate(-5deg); }
            34% { transform: rotate(8deg); }
            54% { transform: rotate(-3deg); }
            72% { transform: rotate(6deg); }
          }

          @keyframes ti-newsroom-dot {
            0%, 100% { transform: translate(0, 0); }
            18% { transform: translate(98px, -54px); }
            36% { transform: translate(196px, 0); }
            54% { transform: translate(98px, 50px); }
            72% { transform: translate(0, 0); }
          }

          @keyframes ti-newsroom-flow {
            0% { opacity: 0.2; stroke-dashoffset: 0; }
            18% { opacity: 0.95; stroke-dashoffset: -112; }
            36% { opacity: 0.95; stroke-dashoffset: -224; }
            54% { opacity: 0.95; stroke-dashoffset: -334; }
            72%, 100% { opacity: 0.2; stroke-dashoffset: -444; }
          }
        `}
      </style>
      <g transform="translate(160 172) scale(1.12) translate(-160 -172)">
        <g style={wheelStyle}>
          <circle cx={160} cy={70} fill="none" r={44} stroke={newsroomPalette.edge} strokeWidth={8} />
          <circle cx={160} cy={70} fill={palette.frame} r={8} stroke={newsroomPalette.edge} strokeWidth={5} />
          <Line d="M 160 70 V 28" palette={newsroomPalette} width={5} />
          <Line d="M 160 70 L 124 94" palette={newsroomPalette} width={5} />
          <Line d="M 160 70 L 196 94" palette={newsroomPalette} width={5} />
        </g>
        <Line d="M 160 116 V 128" opacity={0.7} palette={newsroomPalette} tone="muted" width={4} />
        <Line d={flowPath} opacity={0.42} palette={newsroomPalette} tone="muted" width={5} />
        <path
          d={flowPath}
          fill="none"
          stroke={palette.accent}
          strokeDasharray="44 440"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={5}
          style={activeLineStyle}
        />
        {states.map((state, index) => (
          <g key={`${state.cx}-${state.cy}`}>
            <circle cx={state.cx} cy={state.cy} fill={palette.frame} r={state.r} stroke={newsroomPalette.edge} strokeWidth={6} />
            <Line d={state.inner} opacity={index === 2 ? 0.9 : 0.72} palette={index === 2 ? palette : newsroomPalette} tone={index === 2 ? "accent" : "muted"} width={4} />
            <Node palette={index === 2 ? palette : newsroomPalette} tone={index === 2 ? "accent" : "node"} x={state.cx} y={state.cy} />
          </g>
        ))}
        <circle cx={62} cy={214} fill={palette.accent} r={7} style={dotStyle} />
      </g>
    </PictogramSvg>
  );
}

function AwsDiscoveryPictogram({ alt, palette, timing }: RegisteredPictogramProps) {
  const awsPalette = {
    ...palette,
    edge: "var(--foreground-strong)",
    node: "var(--foreground-strong)",
    muted: "color-mix(in srgb, var(--foreground-strong) 54%, var(--background) 46%)",
  };
  const riskStyle = (offsetMs: number, resting = false) =>
    ({
      animation: timing.prefersReducedMotion ? "none" : `ti-aws-risk ${timing.cycleS}s ease-in-out ${timing.delayS(offsetMs)}s infinite`,
      opacity: timing.prefersReducedMotion && resting ? 1 : timing.prefersReducedMotion ? 0.86 : 0.18,
      transformBox: "fill-box",
      transformOrigin: "center",
    }) as CSSProperties;
  const buckets = [
    { x: 92, y: 74, risk: null },
    { x: 160, y: 74, risk: null },
    { x: 228, y: 74, risk: "warning", offset: 2200, markerDx: 15, markerDy: -20 },
    { x: 92, y: 150, risk: "warning", offset: 4200 },
    { x: 160, y: 150, risk: null },
    { x: 228, y: 150, risk: null },
    { x: 92, y: 226, risk: null },
    { x: 160, y: 226, risk: "accent", offset: 6200, markerDx: 24, markerDy: -16, markerR: 20 },
    { x: 228, y: 226, risk: "accent", offset: 8200, markerDx: 12, markerDy: -24 },
  ];

  return (
    <PictogramSvg alt={alt} viewBox="0 0 320 320">
      <style>
        {`
          @keyframes ti-aws-risk {
            0%, 18%, 100% { opacity: 0.18; transform: scale(0.9); }
            26% { opacity: 1; transform: scale(1.14); }
            34%, 78% { opacity: 1; transform: scale(1); }
            88% { opacity: 0.42; transform: scale(0.96); }
          }
        `}
      </style>
      <g transform="translate(160 160) scale(1.14) translate(-160 -150)">
        {buckets.map((bucket) => {
          const stroke = bucket.risk === "accent" ? palette.accent : bucket.risk === "warning" ? palette.warning : awsPalette.edge;
          const markerX = bucket.x + (bucket.markerDx ?? 20);
          const markerY = bucket.y + (bucket.markerDy ?? -19);
          const markerR = bucket.markerR ?? 10;
          return (
            <g key={`aws-bucket-${bucket.x}-${bucket.y}`}>
              <path
                d={`M ${bucket.x - 22} ${bucket.y - 16} C ${bucket.x - 22} ${bucket.y - 27}, ${bucket.x + 22} ${bucket.y - 27}, ${bucket.x + 22} ${bucket.y - 16} V ${bucket.y + 18} C ${bucket.x + 22} ${bucket.y + 29}, ${bucket.x - 22} ${bucket.y + 29}, ${bucket.x - 22} ${bucket.y + 18} Z`}
                fill={palette.frame}
                stroke={awsPalette.edge}
                strokeLinejoin="round"
                strokeWidth={5}
              />
              <path
                d={`M ${bucket.x - 22} ${bucket.y - 16} C ${bucket.x - 22} ${bucket.y - 5}, ${bucket.x + 22} ${bucket.y - 5}, ${bucket.x + 22} ${bucket.y - 16}`}
                fill="none"
                opacity={0.72}
                stroke={awsPalette.muted}
                strokeLinecap="round"
                strokeWidth={4}
              />
              <Node palette={awsPalette} x={bucket.x} y={bucket.y + 2} />
              {bucket.risk ? (
                <g style={riskStyle(bucket.offset ?? 0, bucket.risk === "accent")}>
                  <circle cx={markerX} cy={markerY} fill={stroke} r={markerR} />
                  <path d={`M ${markerX - markerR * 0.8} ${markerY} H ${markerX + markerR * 0.8} M ${markerX} ${markerY - markerR * 0.8} V ${markerY + markerR * 0.8}`} stroke={palette.frame} strokeLinecap="round" strokeWidth={markerR >= 16 ? 4.8 : 3.4} />
                </g>
              ) : null}
            </g>
          );
        })}
      </g>
    </PictogramSvg>
  );
}

function AzureBlastRadiusPictogram({ alt, palette, timing }: RegisteredPictogramProps) {
  const azurePalette = {
    ...palette,
    edge: "var(--foreground-strong)",
    node: "var(--foreground-strong)",
    muted: "color-mix(in srgb, var(--foreground-strong) 54%, var(--background) 46%)",
  };
  const animationDelay = `${timing.delayS(1000)}s`;
  const pathStyle = {
    animation: timing.prefersReducedMotion ? "none" : `ti-azure-path ${timing.cycleS}s ease-in-out ${animationDelay} infinite`,
    opacity: timing.prefersReducedMotion ? 0.95 : undefined,
    strokeDashoffset: timing.prefersReducedMotion ? -270 : undefined,
  } as CSSProperties;
  const riskStyle = (offsetMs: number) =>
    ({
      animation: timing.prefersReducedMotion ? "none" : `ti-azure-risk ${timing.cycleS}s ease-in-out ${timing.delayS(offsetMs)}s infinite`,
      opacity: timing.prefersReducedMotion ? 0.95 : 0.18,
      transformBox: "fill-box",
      transformOrigin: "center",
    }) as CSSProperties;

  return (
    <PictogramSvg alt={alt} viewBox="0 0 320 320">
      <style>
        {`
          @keyframes ti-azure-path {
            0%, 16%, 100% { opacity: 0.18; stroke-dashoffset: 0; }
            34%, 66% { opacity: 0.95; stroke-dashoffset: -270; }
            78% { opacity: 0.28; stroke-dashoffset: -270; }
          }

          @keyframes ti-azure-risk {
            0%, 20%, 100% { opacity: 0.18; transform: scale(0.9); }
            32%, 70% { opacity: 1; transform: scale(1.08); }
            82% { opacity: 0.35; transform: scale(1); }
          }
        `}
      </style>
      <g transform="translate(160 160) scale(1.1) translate(-160 -160)">
        <rect fill={palette.frame} height={214} rx={12} stroke={azurePalette.edge} strokeWidth={7} width={222} x={49} y={54} />
        <Line d="M 82 88 H 238 M 82 232 H 238" opacity={0.38} palette={azurePalette} tone="muted" width={4} />
        <circle cx={104} cy={112} fill={palette.frame} r={34} stroke={azurePalette.edge} strokeWidth={6} />
        <Line d="M 92 118 C 94 102, 114 102, 116 118" palette={azurePalette} tone="muted" width={4} />
        <Node palette={azurePalette} x={104} y={104} />
        <rect fill={palette.frame} height={52} rx={8} stroke={azurePalette.edge} strokeWidth={6} width={74} x={184} y={86} />
        <rect fill={palette.frame} height={52} rx={8} stroke={azurePalette.edge} strokeWidth={6} width={74} x={184} y={154} />
        <rect fill={palette.frame} height={40} rx={8} stroke={azurePalette.edge} strokeWidth={6} width={64} x={96} y={196} />
        <Line d="M 198 112 H 244 M 198 180 H 244 M 108 216 H 148" opacity={0.72} palette={azurePalette} tone="muted" width={4} />
        <Line d={pointsPath([[138, 112], [184, 112], [184, 180], [160, 216]])} opacity={0.34} palette={azurePalette} tone="muted" width={4} />
        <path
          d={pointsPath([[104, 112], [142, 112], [184, 112], [222, 112], [222, 180], [160, 216]])}
          fill="none"
          stroke={palette.accent}
          strokeDasharray="44 270"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={6}
          style={pathStyle}
        />
        <Node palette={azurePalette} x={104} y={112} />
        <Node palette={azurePalette} x={222} y={112} />
        <Node palette={azurePalette} x={222} y={180} />
        <Node palette={azurePalette} x={160} y={216} />
        <g style={riskStyle(3400)}>
          <circle cx={222} cy={112} fill={palette.warning} r={12} />
          <path d="M 213 112 H 231 M 222 103 V 121" stroke={palette.frame} strokeLinecap="round" strokeWidth={4} />
        </g>
        <g style={riskStyle(6200)}>
          <circle cx={160} cy={216} fill={palette.accent} r={18} />
          <path d="M 146 216 H 174 M 160 202 V 230" stroke={palette.frame} strokeLinecap="round" strokeWidth={5} />
        </g>
      </g>
    </PictogramSvg>
  );
}

function OpenAIInfraPictogram({ alt, palette, timing }: RegisteredPictogramProps) {
  const aiPalette = {
    ...palette,
    edge: "var(--foreground-strong)",
    node: "var(--foreground-strong)",
    muted: "color-mix(in srgb, var(--foreground-strong) 54%, var(--background) 46%)",
  };
  const animationDelay = `${timing.delayS(1400)}s`;
  const pathStyle = {
    animation: timing.prefersReducedMotion ? "none" : `ti-ai-path ${timing.cycleS}s ease-in-out ${animationDelay} infinite`,
    opacity: timing.prefersReducedMotion ? 0.95 : undefined,
    strokeDashoffset: timing.prefersReducedMotion ? -280 : undefined,
  } as CSSProperties;
  const riskStyle = (offsetMs: number) =>
    ({
      animation: timing.prefersReducedMotion ? "none" : `ti-ai-risk ${timing.cycleS}s ease-in-out ${timing.delayS(offsetMs)}s infinite`,
      opacity: timing.prefersReducedMotion ? 0.95 : 0.16,
      transformBox: "fill-box",
      transformOrigin: "center",
    }) as CSSProperties;

  return (
    <PictogramSvg alt={alt} viewBox="0 0 320 320">
      <style>
        {`
          @keyframes ti-ai-path {
            0%, 16%, 100% { opacity: 0.16; stroke-dashoffset: 0; }
            34%, 68% { opacity: 0.95; stroke-dashoffset: -280; }
            82% { opacity: 0.28; stroke-dashoffset: -280; }
          }

          @keyframes ti-ai-risk {
            0%, 20%, 100% { opacity: 0.16; transform: scale(0.9); }
            30%, 72% { opacity: 1; transform: scale(1.08); }
            84% { opacity: 0.34; transform: scale(1); }
          }
        `}
      </style>
      <g transform="translate(160 160) scale(1.1) translate(-160 -160)">
        <rect fill={palette.frame} height={72} rx={12} stroke={aiPalette.edge} strokeWidth={7} width={94} x={113} y={44} />
        <Line d="M 130 68 H 190 M 130 92 H 190" opacity={0.72} palette={aiPalette} tone="muted" width={4} />
        <Node palette={aiPalette} x={160} y={80} />
        <rect fill={palette.frame} height={54} rx={9} stroke={aiPalette.edge} strokeWidth={6} width={78} x={44} y={154} />
        <rect fill={palette.frame} height={54} rx={9} stroke={aiPalette.edge} strokeWidth={6} width={78} x={198} y={154} />
        <rect fill={palette.frame} height={48} rx={9} stroke={aiPalette.edge} strokeWidth={6} width={72} x={124} y={226} />
        <Line d={pointsPath([[160, 116], [83, 154], [83, 181], [160, 226]])} opacity={0.32} palette={aiPalette} tone="muted" width={4} />
        <Line d={pointsPath([[160, 116], [237, 154], [237, 181], [160, 226]])} opacity={0.32} palette={aiPalette} tone="muted" width={4} />
        <path
          d={pointsPath([[83, 181], [120, 142], [160, 80], [200, 142], [237, 181], [160, 250]])}
          fill="none"
          stroke={palette.accent}
          strokeDasharray="44 280"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={6}
          style={pathStyle}
        />
        <Line d="M 58 181 H 108 M 212 181 H 262 M 140 250 H 180" opacity={0.72} palette={aiPalette} tone="muted" width={4} />
        <Node palette={aiPalette} x={83} y={181} />
        <Node palette={aiPalette} x={237} y={181} />
        <Node palette={aiPalette} x={160} y={250} />
        <g style={riskStyle(2600)}>
          <circle cx={83} cy={181} fill={palette.warning} r={12} />
          <path d="M 74 181 H 92 M 83 172 V 190" stroke={palette.frame} strokeLinecap="round" strokeWidth={4} />
        </g>
        <g style={riskStyle(5600)}>
          <circle cx={237} cy={181} fill={palette.accent} r={14} />
          <path d="M 226 181 H 248 M 237 170 V 192" stroke={palette.frame} strokeLinecap="round" strokeWidth={4.5} />
        </g>
        <g style={riskStyle(8200)}>
          <circle cx={160} cy={250} fill={palette.accent} r={18} />
          <path d="M 146 250 H 174 M 160 236 V 264" stroke={palette.frame} strokeLinecap="round" strokeWidth={5} />
        </g>
      </g>
    </PictogramSvg>
  );
}

function GamingIsolationPictogram({ alt, palette, timing }: RegisteredPictogramProps) {
  const gamingPalette = {
    ...palette,
    edge: "var(--foreground-strong)",
    node: "var(--foreground-strong)",
    muted: "color-mix(in srgb, var(--foreground-strong) 54%, var(--background) 46%)",
  };
  const animationDelay = `${timing.delayS(1200)}s`;
  const attemptStyle = {
    animation: timing.prefersReducedMotion ? "none" : `ti-gaming-attempt ${timing.cycleS}s ease-in-out ${animationDelay} infinite`,
    opacity: timing.prefersReducedMotion ? 0.86 : undefined,
  } as CSSProperties;
  const barrierStyle = {
    animation: timing.prefersReducedMotion ? "none" : `ti-gaming-barrier ${timing.cycleS}s ease-in-out ${animationDelay} infinite`,
  } as CSSProperties;
  const blockedDotStyle = {
    animation: timing.prefersReducedMotion ? "none" : `ti-gaming-blocked-dot ${timing.cycleS}s ease-in-out ${animationDelay} infinite`,
    opacity: timing.prefersReducedMotion ? 1 : undefined,
  } as CSSProperties;

  return (
    <PictogramSvg alt={alt} viewBox="0 0 320 320">
      <style>
        {`
          @keyframes ti-gaming-attempt {
            0%, 16%, 100% { opacity: 0.18; }
            34%, 58% { opacity: 0.95; }
            72% { opacity: 0.3; }
          }

          @keyframes ti-gaming-barrier {
            0%, 20%, 100% { opacity: 0.62; }
            38%, 62% { opacity: 1; }
          }

          @keyframes ti-gaming-blocked-dot {
            0%, 24%, 100% { opacity: 0; }
            38%, 64% { opacity: 1; }
            76% { opacity: 0.24; }
          }
        `}
      </style>
      <g transform="translate(160 160) scale(1.12) translate(-160 -160)">
        <rect fill={palette.frame} height={152} rx={10} stroke={gamingPalette.edge} strokeWidth={7} width={92} x={202} y={84} />
        <Line d="M 160 58 V 262" opacity={0.72} palette={gamingPalette} tone="muted" width={5} />
        <path
          d="M 160 58 V 262"
          fill="none"
          stroke={palette.accent}
          strokeDasharray="10 13"
          strokeLinecap="round"
          strokeWidth={5}
          style={barrierStyle}
        />

        <g transform="translate(34 67) scale(0.47)">
          <path
            d="M 24 170 C 31 136, 58 122, 88 128 C 98 130, 101 135, 106 135 H 114 C 119 135, 122 130, 132 128 C 162 122, 189 136, 196 170 L 207 200 C 216 228, 194 246, 170 236 C 154 230, 142 214, 132 198 L 125 187 H 95 L 88 198 C 78 214, 66 230, 50 236 C 26 246, 4 228, 13 200 Z"
            fill={palette.frame}
            stroke={gamingPalette.edge}
            strokeLinejoin="round"
            strokeWidth={7}
          />
          <Line d="M 52 176 H 86 M 69 159 V 193" opacity={0.9} palette={gamingPalette} tone="muted" width={7} />
          <circle cx={151} cy={166} fill={gamingPalette.node} r={8} />
          <circle cx={173} cy={184} fill={gamingPalette.muted} r={8} />
          <circle cx={173} cy={148} fill={gamingPalette.muted} r={8} />
        </g>
        <Node palette={palette} tone="warning" x={102} y={136} />

        <path
          d={pointsPath([
            [102, 136],
            [124, 150],
            [142, 160],
            [151, 160],
          ])}
          fill="none"
          stroke={palette.accent}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={6}
          style={attemptStyle}
        />
        <g style={blockedDotStyle}>
          <Line d="M 151 151 L 169 169 M 169 151 L 151 169" palette={palette} tone="accent" width={5} />
        </g>

        <Box fillOpacity={0.04} height={34} palette={gamingPalette} strokeTone="edge" width={50} x={224} y={110} />
        <Box fillOpacity={0.04} height={34} palette={gamingPalette} strokeTone="edge" width={50} x={224} y={156} />
        <Box fillOpacity={0.04} height={34} palette={gamingPalette} strokeTone="edge" width={50} x={224} y={202} />
        <Line d="M 236 127 H 262 M 236 173 H 262 M 236 219 H 262" opacity={0.72} palette={gamingPalette} tone="muted" width={4} />
        <Node palette={gamingPalette} x={249} y={127} />
        <Node palette={gamingPalette} x={249} y={173} />
        <Node palette={gamingPalette} x={249} y={219} />
      </g>
    </PictogramSvg>
  );
}

export const THREAT_INTELLIGENCE_PICTOGRAM_REGISTRY: Record<ThreatIntelligencePictogramSlug, PictogramRegistryEntry> = {
  "the-balance-of-power-is-shifting": { aspectRatio: 1, render: BalanceShiftPictogram },
  "how-our-newsroom-learns": { aspectRatio: 1, render: NewsroomFlowPictogram },
  "audit-aws-exposure-before-attackers-do": { aspectRatio: 1, render: AwsDiscoveryPictogram },
  "audit-azure-blast-radius-before-attackers-do": { aspectRatio: 1, render: AzureBlastRadiusPictogram },
  "treat-openai-accounts-like-production-infrastructure": { aspectRatio: 1, render: OpenAIInfraPictogram },
  "how-to-play-games-securely": { aspectRatio: 1, render: GamingIsolationPictogram },
};

export function getPictogramRegistryEntry(slug: ThreatIntelligencePictogramSlug): PictogramRegistryEntry {
  return THREAT_INTELLIGENCE_PICTOGRAM_REGISTRY[slug];
}
