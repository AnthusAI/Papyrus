export type PreviewPlaybackStateInput = {
  audioBlocked: boolean;
  audioDuration: number | null;
  audioProgressObserved: boolean;
  audioSrc?: string | null;
  currentTime: number;
  isPlaying: boolean;
  scriptDerivedDuration: number;
};

export type PreviewPlaybackState = {
  audioReady: boolean;
  controlLabel: string;
  duration: number;
  hasAudioSource: boolean;
  useAudioClock: boolean;
  visualTime: number;
};

export function computePreviewPlaybackState(input: PreviewPlaybackStateInput): PreviewPlaybackState {
  const hasAudioSource = Boolean(input.audioSrc);
  const audioReady =
    input.audioDuration != null && Number.isFinite(input.audioDuration) && input.audioDuration > 0;
  const useAudioClock = hasAudioSource && audioReady && input.audioProgressObserved && !input.audioBlocked;
  const duration = useAudioClock && input.audioDuration != null ? input.audioDuration : input.scriptDerivedDuration;
  const visualTime =
    useAudioClock && duration > 0 && input.scriptDerivedDuration > 0
      ? (input.currentTime / duration) * input.scriptDerivedDuration
      : input.currentTime;
  const controlLabel = input.isPlaying ? "Pause" : hasAudioSource && input.audioBlocked ? "Play (audio)" : "Play";

  return { audioReady, controlLabel, duration, hasAudioSource, useAudioClock, visualTime };
}

export function advanceScriptPreviewTime(currentTime: number, deltaSeconds: number, duration: number): number {
  if (!(duration > 0)) return 0;
  let nextTime = currentTime + Math.max(0, deltaSeconds);
  if (nextTime >= duration) {
    nextTime = 0;
  }
  return Math.max(0, Math.min(nextTime, duration));
}
