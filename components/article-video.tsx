"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ArticleVideoAsset } from "@/lib/articles";
import { resolveThemedVideoSrc } from "@/lib/themed-image";
import { useResolvedPapyrusTheme } from "@/components/use-resolved-papyrus-theme";
import { getSiteBrand } from "@/lib/site-brand";
import { normalizeDevPreviewDsl, type VideoScriptRef } from "@/lib/video-script";
import { resolveVideoMode, resolveVideoModeFromEnv, type VideoMode } from "@/lib/video-mode";

type ArticleVideoFigureProps = {
  video: ArticleVideoAsset;
  slug: string;
  figureClassName?: string;
  priority?: boolean;
  videoScript?: VideoScriptRef | null;
};

const PREVIEW_STORAGE_PREFIX = "papyrus-video-preview:";

export function ArticleVideoFigure({
  video,
  slug,
  figureClassName = "article-photo article-video",
  videoScript = null,
}: ArticleVideoFigureProps) {
  const theme = useResolvedPapyrusTheme();
  const [hasHydrated, setHasHydrated] = useState(false);
  const [videoMode, setVideoMode] = useState<VideoMode>(() => resolveVideoModeFromEnv());
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [previewReady, setPreviewReady] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    setHasHydrated(true);
    setVideoMode(resolveVideoMode());
  }, []);

  // Match SSR to the default dark MP4 in `video.src` until after hydration.
  const resolvedTheme = hasHydrated ? theme : "dark";
  const src = resolveThemedVideoSrc(video.src, video.themeVariants, resolvedTheme);
  const usePreview = videoMode === "preview" && Boolean(videoScript?.dsl);
  const previewDsl = videoScript?.dsl
    ? normalizeDevPreviewDsl(videoScript.dsl, getSiteBrand().video?.sceneComponents)
    : null;
  const previewSrc = `/videoml/preview.html?target=${encodeURIComponent(slug)}&theme=${resolvedTheme}${
    src ? `&audio=${encodeURIComponent(src)}` : ""
  }`;

  if (usePreview && previewDsl && typeof window !== "undefined") {
    sessionStorage.setItem(`${PREVIEW_STORAGE_PREFIX}${slug}`, previewDsl);
  }

  useEffect(() => {
    setPreviewReady(false);
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(0);
  }, [previewSrc, usePreview]);

  useEffect(() => {
    if (!usePreview || !previewReady) return;
    iframeRef.current?.contentWindow?.postMessage(
      { kind: "papyrus-video-refresh", target: slug, theme: resolvedTheme, audio: src || undefined },
      "*",
    );
  }, [previewReady, resolvedTheme, slug, src, usePreview]);

  useEffect(() => {
    if (!usePreview) return;
    const onMessage = (event: MessageEvent) => {
      const payload = event.data;
      if (!payload || typeof payload !== "object" || payload.kind !== "papyrus-video-time") return;
      if (typeof payload.currentTime === "number") setCurrentTime(payload.currentTime);
      if (typeof payload.duration === "number") setDuration(payload.duration);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [usePreview]);

  const togglePreviewPlayback = useCallback(() => {
    iframeRef.current?.contentWindow?.postMessage({ kind: isPlaying ? "papyrus-video-pause" : "papyrus-video-play" }, "*");
    setIsPlaying(!isPlaying);
  }, [isPlaying]);

  const seekPreview = useCallback((nextTime: number) => {
    const clamped = Math.max(0, Number.isFinite(nextTime) ? nextTime : 0);
    iframeRef.current?.contentWindow?.postMessage({ kind: "papyrus-video-seek", time: clamped }, "*");
    setCurrentTime(clamped);
  }, []);

  if (usePreview) {
    return (
      <figure
        className={`${figureClassName} article-video--preview`}
        data-media-type="videoml-preview"
        data-video-theme={resolvedTheme}
        data-video-mode={videoMode}
      >
        {hasHydrated ? (
          <iframe
            key={`${slug}-${resolvedTheme}-${src}`}
            ref={iframeRef}
            className="article-video__preview-frame"
            src={previewSrc}
            title={video.alt}
            onLoad={() => setPreviewReady(true)}
          />
        ) : null}
        <div className="article-video__preview-controls">
          <button type="button" onClick={togglePreviewPlayback} aria-pressed={isPlaying}>
            {isPlaying ? "Pause video" : "Play video"}
          </button>
          <input
            type="range"
            min={0}
            max={duration || 0}
            step={0.1}
            value={Math.min(currentTime, duration || 0)}
            onChange={(event) => seekPreview(Number(event.target.value))}
            aria-label="Seek video"
            disabled={!duration}
          />
        </div>
        {video.caption ? <figcaption>{video.caption}</figcaption> : null}
        {video.credit ? <p className="article-video__credit">{video.credit}</p> : null}
        <span className="sr-only" data-video-slug={slug}>
          {video.alt}
        </span>
      </figure>
    );
  }

  return (
    <figure className={figureClassName} data-media-type="video" data-video-theme={resolvedTheme} data-video-mode={videoMode}>
      <video
        controls
        playsInline
        preload="metadata"
        poster={video.posterSrc}
        aria-label={video.alt}
        className="article-video__player"
        key={hasHydrated ? src : "ssr"}
      >
        <source src={src} type="video/mp4" />
      </video>
      {video.caption ? <figcaption>{video.caption}</figcaption> : null}
      {video.credit ? <p className="article-video__credit">{video.credit}</p> : null}
      <span className="sr-only" data-video-slug={slug}>
        {video.alt}
      </span>
    </figure>
  );
}
