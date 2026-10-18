export function isLocalPreviewEnabled(): boolean {
  return process.env.NEXT_PUBLIC_PAPYRUS_LOCAL_PREVIEW === "1";
}
