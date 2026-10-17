import React from "react";
import { createRoot } from "react-dom/client";
import {
  ComposableRenderer,
  RendererProvider,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "@videoml/toolchain/renderer";
import { getComponent, listComponents, registerComponent } from "@videoml/toolchain/renderer/components/registry";

type RenderFrameRequest = {
  script: unknown;
  frame: number;
  config: { fps: number; width: number; height: number; durationFrames: number };
  inputProps?: Record<string, unknown>;
};

const root = document.getElementById("root");
let reactRoot: ReturnType<typeof createRoot> | null = null;

const videoApi = {
  registerComponent,
  getComponent,
  listComponents,
  ComposableRenderer,
  RendererProvider,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
};

(window as unknown as { Babulus: typeof videoApi }).Babulus = videoApi;

(window as unknown as { renderFrame: (request: RenderFrameRequest) => Promise<void> }).renderFrame = (request) => {
  if (!root) throw new Error("VideoML render shell has no #root element.");
  reactRoot ??= createRoot(root);
  reactRoot.render(
    <RendererProvider frame={request.frame} config={request.config}>
      <ComposableRenderer script={request.script as never} {...(request.inputProps ?? {})} />
    </RendererProvider>,
  );
  return new Promise((resolve) => setTimeout(resolve, 100));
};
