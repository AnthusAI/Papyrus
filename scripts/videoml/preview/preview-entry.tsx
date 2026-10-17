import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ComposableRenderer, RendererProvider } from "@videoml/toolchain/renderer";
import { dslToScriptData } from "@videoml/toolchain/shared";
import { executeVomXml } from "@videoml/player";
import { advanceScriptPreviewTime, computePreviewPlaybackState } from "./preview-timing";
import { computePreviewStageFit } from "./preview-stage-fit";

type PreviewTheme = "dark" | "light";
type ScriptData = ReturnType<typeof dslToScriptData>;
type PreviewRetheme = (xml: string, theme: PreviewTheme) => string;

type PreviewMountOptions = {
  xml: string;
  theme?: PreviewTheme;
  autoPlay?: boolean;
  audioSrc?: string;
};

type PreviewPlayerProps = {
  script: ScriptData;
  width: number;
  height: number;
  autoPlay?: boolean;
  audioSrc?: string;
};

let rethemeXml: PreviewRetheme = (xml) => xml;

function registerPreviewRetheme(retheme: PreviewRetheme): void {
  rethemeXml = retheme;
}

function scriptDuration(script: ScriptData): number {
  const scenes = script.scenes ?? [];
  if (!scenes.length) return 10;
  const lastScene = scenes[scenes.length - 1];
  return typeof lastScene.endSec === "number" && lastScene.endSec > 0 ? lastScene.endSec : 10;
}

function PreviewPlayer({ script, width, height, autoPlay = false, audioSrc }: PreviewPlayerProps) {
  const [isPlaying, setIsPlaying] = useState(autoPlay);
  const [currentTime, setCurrentTime] = useState(0);
  const [audioDuration, setAudioDuration] = useState<number | null>(null);
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [audioProgressObserved, setAudioProgressObserved] = useState(false);
  const [viewportSize, setViewportSize] = useState({ width, height });
  const animationFrameRef = useRef<number | undefined>(undefined);
  const lastTimestampRef = useRef<number | undefined>(undefined);
  const currentTimeRef = useRef(0);
  const audioRef = useRef<HTMLAudioElement>(null);
  const lastAudioTimeRef = useRef(0);
  const viewportRef = useRef<HTMLDivElement>(null);
  const usedAudioClockRef = useRef(false);

  const fps = script.fps ?? 30;
  const scriptDerivedDuration = useMemo(() => scriptDuration(script), [script]);
  const playbackState = useMemo(
    () =>
      computePreviewPlaybackState({
        audioBlocked,
        audioDuration,
        audioProgressObserved,
        audioSrc,
        currentTime,
        isPlaying,
        scriptDerivedDuration,
      }),
    [audioBlocked, audioDuration, audioProgressObserved, audioSrc, currentTime, isPlaying, scriptDerivedDuration],
  );
  const { duration, hasAudioSource, useAudioClock, visualTime } = playbackState;

  const currentFrame = Math.floor(visualTime * fps);
  const sceneBackground = script.scenes?.[0]?.styles?.background;
  const backgroundColor = typeof sceneBackground === "string" ? sceneBackground : "#000";
  const fittedStage = useMemo(
    () =>
      computePreviewStageFit({
        containerHeight: viewportSize.height,
        containerWidth: viewportSize.width,
        stageHeight: height,
        stageWidth: width,
      }),
    [height, viewportSize.height, viewportSize.width, width],
  );

  const applyTime = useCallback(
    (nextTime: number) => {
      const clamped = Math.max(0, Math.min(nextTime, duration));
      currentTimeRef.current = clamped;
      setCurrentTime(clamped);
    },
    [duration],
  );

  const playAudio = useCallback(async () => {
    const audio = audioRef.current;
    if (!audio || !hasAudioSource) return true;
    try {
      await audio.play();
      setAudioBlocked(false);
      return true;
    } catch {
      setAudioBlocked(true);
      return false;
    }
  }, [hasAudioSource]);

  const pauseAudio = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || !hasAudioSource) return;
    audio.pause();
  }, [hasAudioSource]);

  const seekAudio = useCallback(
    (nextTime: number) => {
      const audio = audioRef.current;
      if (!audio || !hasAudioSource) return;
      try {
        audio.currentTime = nextTime;
      } catch {
        return;
      }
    },
    [hasAudioSource],
  );

  useEffect(() => {
    const audio = audioRef.current;
    setAudioDuration(null);
    setAudioProgressObserved(false);
    setAudioBlocked(false);
    lastAudioTimeRef.current = 0;
    if (!audio || !hasAudioSource) return;

    const onLoadedMetadata = () => {
      if (Number.isFinite(audio.duration) && audio.duration > 0) {
        setAudioDuration(audio.duration);
      }
    };
    const markAudioProgress = () => {
      if (!Number.isFinite(audio.currentTime)) return;
      if (audio.currentTime > 0 || audio.currentTime !== lastAudioTimeRef.current) {
        setAudioProgressObserved(true);
        setAudioBlocked(false);
      }
      lastAudioTimeRef.current = audio.currentTime;
    };
    const onEnded = () => setIsPlaying(false);
    const onError = () => {
      setAudioBlocked(true);
      setAudioProgressObserved(false);
    };

    audio.addEventListener("loadedmetadata", onLoadedMetadata);
    audio.addEventListener("timeupdate", markAudioProgress);
    audio.addEventListener("seeked", markAudioProgress);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("error", onError);
    if (audio.readyState >= 1) onLoadedMetadata();

    return () => {
      audio.removeEventListener("loadedmetadata", onLoadedMetadata);
      audio.removeEventListener("timeupdate", markAudioProgress);
      audio.removeEventListener("seeked", markAudioProgress);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("error", onError);
    };
  }, [audioSrc, hasAudioSource]);

  useEffect(() => {
    if (!autoPlay || !hasAudioSource) return;
    void playAudio();
  }, [audioSrc, autoPlay, hasAudioSource, playAudio]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || typeof ResizeObserver === "undefined") return;
    const updateViewport = () => {
      const rect = viewport.getBoundingClientRect();
      const nextWidth = Math.round(rect.width);
      const nextHeight = Math.round(rect.height);
      setViewportSize((current) => {
        if (current.width === nextWidth && current.height === nextHeight) return current;
        return { width: nextWidth > 0 ? nextWidth : width, height: nextHeight > 0 ? nextHeight : height };
      });
    };
    updateViewport();
    const observer = new ResizeObserver(updateViewport);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [height, width]);

  useEffect(() => {
    if (usedAudioClockRef.current && !useAudioClock) {
      currentTimeRef.current = visualTime;
      setCurrentTime(visualTime);
    }
    usedAudioClockRef.current = useAudioClock;
  }, [useAudioClock, visualTime]);

  useEffect(() => {
    if (!isPlaying) {
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
      pauseAudio();
      return;
    }
    if (hasAudioSource) void playAudio();

    const tick = (timestamp: number) => {
      if (!isPlaying) return;
      if (useAudioClock) {
        const audio = audioRef.current;
        if (audio && Number.isFinite(audio.currentTime)) {
          let nextTime = audio.currentTime;
          if (nextTime >= duration && duration > 0) {
            nextTime = 0;
            audio.currentTime = 0;
          }
          applyTime(nextTime);
        }
      } else if (lastTimestampRef.current !== undefined) {
        const delta = (timestamp - lastTimestampRef.current) / 1000;
        applyTime(advanceScriptPreviewTime(currentTimeRef.current, delta, duration));
      }
      lastTimestampRef.current = timestamp;
      animationFrameRef.current = requestAnimationFrame(tick);
    };

    lastTimestampRef.current = undefined;
    animationFrameRef.current = requestAnimationFrame(tick);
    return () => {
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
    };
  }, [applyTime, duration, hasAudioSource, isPlaying, pauseAudio, playAudio, useAudioClock]);

  const startPlayback = useCallback(async () => {
    if (hasAudioSource) await playAudio();
    setIsPlaying(true);
    lastTimestampRef.current = undefined;
  }, [hasAudioSource, playAudio]);

  const stopPlayback = useCallback(() => {
    setIsPlaying(false);
    lastTimestampRef.current = undefined;
  }, []);

  const handleSeek = useCallback(
    (nextTime: number) => {
      applyTime(nextTime);
      seekAudio(nextTime);
      lastTimestampRef.current = undefined;
    },
    [applyTime, seekAudio],
  );

  const lastBroadcastRef = useRef<{ currentTime: number; duration: number } | null>(null);
  useEffect(() => {
    if (typeof window === "undefined" || window.parent === window) return;
    const roundedTime = Math.round(currentTime * 10) / 10;
    const roundedDuration = Math.round(duration * 10) / 10;
    const previous = lastBroadcastRef.current;
    if (previous && previous.currentTime === roundedTime && previous.duration === roundedDuration) return;
    lastBroadcastRef.current = { currentTime: roundedTime, duration: roundedDuration };
    window.parent.postMessage({ kind: "papyrus-video-time", currentTime: roundedTime, duration: roundedDuration }, "*");
  }, [currentTime, duration]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const payload = event.data;
      if (!payload || typeof payload !== "object") return;
      if (payload.kind === "papyrus-video-play") {
        void startPlayback();
        return;
      }
      if (payload.kind === "papyrus-video-pause") {
        stopPlayback();
        return;
      }
      if (payload.kind === "papyrus-video-seek" && typeof payload.time === "number") {
        handleSeek(payload.time);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [handleSeek, startPlayback, stopPlayback]);

  return (
    <div style={{ background: "#000", height: "100%", overflow: "hidden", position: "relative", width: "100%" }}>
      {hasAudioSource ? <audio ref={audioRef} preload="auto" src={audioSrc} style={{ display: "none" }} /> : null}
      <div
        ref={viewportRef}
        style={{
          alignItems: "center",
          background: backgroundColor,
          display: "flex",
          inset: 0,
          justifyContent: "center",
          overflow: "hidden",
          position: "absolute",
        }}
      >
        <div
          style={{
            height,
            left: "50%",
            position: "absolute",
            top: "50%",
            transform: `translate(-50%, -50%) scale(${fittedStage.scale})`,
            transformOrigin: "center center",
            width,
          }}
        >
          <RendererProvider
            frame={currentFrame}
            config={{ fps, width, height, durationFrames: Math.max(1, Math.floor(duration * fps)) }}
          >
            <ComposableRenderer script={script} />
          </RendererProvider>
        </div>
      </div>
    </div>
  );
}

function parsePreviewScript(xml: string): ScriptData {
  const result = executeVomXml(xml);
  const composition = Array.isArray(result?.compositions) && result.compositions[0] ? result.compositions[0] : result;
  const script = dslToScriptData(composition, { type: "cue-count", secondsPerCue: 3 });

  const timeline: unknown[] = [];
  const scenes = script.scenes ?? [];
  let sceneIndex = 0;

  const doc = new DOMParser().parseFromString(xml, "text/xml");
  for (const element of Array.from(doc.documentElement.children)) {
    if (element.tagName === "scene") {
      const scene = scenes[sceneIndex];
      if (scene) {
        timeline.push(scene);
        sceneIndex += 1;
      }
    } else if (element.tagName === "transition") {
      const previousScene = sceneIndex > 0 ? scenes[sceneIndex - 1] : null;
      const nextScene = sceneIndex < scenes.length ? scenes[sceneIndex] : null;
      const durationAttribute = element.getAttribute("duration");
      const durationFrames = durationAttribute ? parseFloat(durationAttribute.replace("f", "")) : 16;
      const startSec = nextScene ? (nextScene.startSec ?? 0) : 0;
      const propsAttribute = element.getAttribute("props");
      timeline.push({
        kind: "transition",
        id: element.getAttribute("id") || `trans-${sceneIndex}`,
        effect: element.getAttribute("effect") || "push",
        durationFrames,
        ease: element.getAttribute("ease"),
        props: propsAttribute ? JSON.parse(propsAttribute) : undefined,
        startSec,
        endSec: startSec + durationFrames / (script.fps ?? 30),
        fromSceneId: previousScene?.id,
        toSceneId: nextScene?.id,
      });
    }
  }

  (script as { timeline?: unknown[] }).timeline = timeline;
  return script;
}

function mountPreview(container: HTMLElement, options: PreviewMountOptions): () => void {
  const theme = options.theme ?? "light";
  const script = parsePreviewScript(rethemeXml(options.xml, theme));
  const width = script.meta?.width && script.meta.width > 0 ? script.meta.width : 1280;
  const height = script.meta?.height && script.meta.height > 0 ? script.meta.height : 720;
  const root = (window as unknown as { ReactDOM: { createRoot: (el: HTMLElement) => { render: (node: React.ReactNode) => void; unmount: () => void } } }).ReactDOM.createRoot(container);
  root.render(
    <PreviewPlayer audioSrc={options.audioSrc} autoPlay={options.autoPlay ?? false} height={height} script={script} width={width} />,
  );
  return () => root.unmount();
}

(window as unknown as Record<string, unknown>).PapyrusVideo = { registerPreviewRetheme };
(window as unknown as Record<string, unknown>).mountPapyrusVideoPreview = mountPreview;
