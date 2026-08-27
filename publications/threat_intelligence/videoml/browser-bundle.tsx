import React from "react";
import { ThreatIntelligencePictogramVideo } from "./pictogram-video";

import "babulus-browser-bundle";

declare global {
  interface Window {
    Babulus?: {
      registerComponent: (name: string, component: React.ComponentType<Record<string, unknown>>) => void;
    };
  }
}

type TiTitleSlideProps = Record<string, unknown> & {
  pictogramSlug?: string;
  pictogramSize?: number;
  frame?: number;
  fps?: number;
  title?: string;
  subtitle?: string;
  eyebrow?: string;
  horizontalAlign?: "left" | "center";
  verticalAlign?: "top" | "center" | "bottom";
  titleSize?: number;
  subtitleSize?: number;
  titleColor?: string;
  titleWeight?: number;
  eyebrowWeight?: number;
  eyebrowLetterSpacing?: number;
  eyebrowSize?: number;
  eyebrowRule?: boolean;
  padding?: number;
  gap?: number;
};

const fontHeadline = "var(--font-headline, Helvetica Neue, Segoe UI, Helvetica, Arial, sans-serif)";
const fontSubhead = "var(--font-subhead, Helvetica Neue, Segoe UI, Helvetica, Arial, sans-serif)";
const fontEyebrow = "var(--font-eyebrow, Helvetica Neue, Segoe UI, Helvetica, Arial, sans-serif)";

function EyebrowWithRules({
  label,
  letterSpacing,
  weight,
  fontSize = 14,
}: {
  label: string;
  letterSpacing: number;
  weight: number;
  fontSize?: number;
}) {
  const ruleHeight = Math.round(fontSize);
  return (
    <div style={{ alignItems: "center", display: "flex", gap: 12, marginBottom: 14, width: "100%" }}>
      <div style={{ background: "var(--ti-alarm-red)", flex: 1, height: ruleHeight, minWidth: 24 }} />
      <span
        style={{
          background: "var(--background, #191918)",
          color: "var(--ti-headline-color, var(--foreground-strong, #eeeeec))",
          fontFamily: fontEyebrow,
          fontSize,
          fontWeight: weight,
          letterSpacing: `${letterSpacing}em`,
          lineHeight: 1,
          padding: "0 6px",
          textTransform: "uppercase",
          whiteSpace: "nowrap",
        }}
      >
        {label}
      </span>
      <div style={{ background: "var(--ti-alarm-red)", flex: 1, height: ruleHeight, minWidth: 24 }} />
    </div>
  );
}

function PlainEyebrow({
  label,
  letterSpacing,
  weight,
}: {
  label: string;
  letterSpacing: number;
  weight: number;
}) {
  return (
    <p
      style={{
        color: "var(--ti-headline-color, var(--foreground-strong, #eeeeec))",
        fontFamily: fontEyebrow,
        fontSize: 14,
        fontWeight: weight,
        letterSpacing: `${letterSpacing}em`,
        margin: "0 0 12px",
        textTransform: "uppercase",
      }}
    >
      {label}
    </p>
  );
}

function TiTitleSlide(props: TiTitleSlideProps) {
  const {
    pictogramSlug,
    pictogramSize = 400,
    frame = 0,
    fps = 30,
    title = "",
    subtitle,
    eyebrow,
    horizontalAlign = "left",
    verticalAlign = "center",
    titleSize = 56,
    subtitleSize = 26,
    titleColor,
    titleWeight = 900,
    eyebrowWeight = 900,
    eyebrowLetterSpacing = 0.09,
    eyebrowSize = 14,
    eyebrowRule = false,
    padding = 80,
    gap = 24,
  } = props;

  const resolvedTitleColor = titleColor || "var(--ti-headline-color, var(--foreground-strong, #eeeeec))";
  const resolvedSubtitleColor = "var(--ti-body-color, var(--color-text-muted, #b5b3ad))";

  const logo = pictogramSlug ? (
    <ThreatIntelligencePictogramVideo
      alt={typeof title === "string" ? title : String(pictogramSlug)}
      frame={Number(frame)}
      fps={Number(fps)}
      size={Number(pictogramSize)}
      slug={String(pictogramSlug)}
    />
  ) : null;

  const eyebrowNode =
    eyebrow && eyebrowRule ? (
      <EyebrowWithRules
        label={String(eyebrow)}
        letterSpacing={Number(eyebrowLetterSpacing)}
        weight={Number(eyebrowWeight)}
        fontSize={Number(eyebrowSize)}
      />
    ) : eyebrow ? (
      <PlainEyebrow label={String(eyebrow)} letterSpacing={Number(eyebrowLetterSpacing)} weight={Number(eyebrowWeight)} />
    ) : null;

  const textColumn = (
    <div style={{ display: "flex", flex: 1, flexDirection: "column", justifyContent: "center", minWidth: 0 }}>
      {eyebrowNode}
      <h1
        style={{
          color: resolvedTitleColor,
          fontFamily: fontHeadline,
          fontSize: Number(titleSize),
          fontWeight: Number(titleWeight),
          lineHeight: 1.1,
          margin: 0,
        }}
      >
        {title}
      </h1>
      {subtitle ? (
        <p
          style={{
            color: resolvedSubtitleColor,
            fontFamily: fontSubhead,
            fontSize: Number(subtitleSize),
            fontWeight: 400,
            lineHeight: 1.35,
            margin: `${gap}px 0 0`,
          }}
        >
          {subtitle}
        </p>
      ) : null}
    </div>
  );

  const justifyContent =
    verticalAlign === "top" ? "flex-start" : verticalAlign === "bottom" ? "flex-end" : "center";

  const outerStyle: React.CSSProperties = {
    alignItems: horizontalAlign === "left" && logo ? "center" : "stretch",
    boxSizing: "border-box",
    display: "flex",
    flexDirection: horizontalAlign === "left" && logo ? "row" : "column",
    gap: horizontalAlign === "left" && logo ? 48 : 0,
    height: "100%",
    justifyContent,
    padding,
    width: "100%",
  };

  if (horizontalAlign === "center") {
    return (
      <div style={{ ...outerStyle, alignItems: "center", textAlign: "center" }}>
        <div style={{ maxWidth: 960, width: "100%" }}>
          {eyebrowNode}
          <h1
            style={{
              color: resolvedTitleColor,
              fontFamily: fontHeadline,
              fontSize: Number(titleSize),
              fontWeight: Number(titleWeight),
              lineHeight: 1.1,
              margin: 0,
            }}
          >
            {title}
          </h1>
          {subtitle ? (
            <p
              style={{
                color: resolvedSubtitleColor,
                fontFamily: fontSubhead,
                fontSize: Number(subtitleSize),
                fontWeight: 400,
                lineHeight: 1.35,
                margin: `${gap}px auto 0`,
                maxWidth: 900,
              }}
            >
              {subtitle}
            </p>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div style={outerStyle}>
      {logo}
      {textColumn}
    </div>
  );
}

const babulus = window.Babulus;
if (!babulus?.registerComponent) {
  throw new Error("Babulus browser bundle did not initialize window.Babulus.registerComponent.");
}

babulus.registerComponent("TiTitleSlide", TiTitleSlide);
