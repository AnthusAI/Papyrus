#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: prepare-web-video.sh <input-directory-of-mp4> <output-directory>" >&2
  exit 2
fi

input_directory="$1"
output_directory="$2"
audio_bitrate="${PAPYRUS_VIDEO_AUDIO_BITRATE:-96k}"
poster_second="${PAPYRUS_VIDEO_POSTER_SECOND:-1}"

mkdir -p "$output_directory"

total_before=0
total_after=0
for input_file in "$input_directory"/*.mp4; do
  base_name="$(basename "$input_file" .mp4)"
  output_file="$output_directory/$base_name.mp4"
  ffmpeg -v error -y -i "$input_file" -c:v copy -c:a aac -b:a "$audio_bitrate" -movflags +faststart "$output_file"
  ffmpeg -v error -y -ss "$poster_second" -i "$input_file" -frames:v 1 -vf scale=1280:-2 -c:v libwebp -quality 70 "$output_directory/$base_name.poster.webp"
  size_before="$(stat -f%z "$input_file" 2>/dev/null || stat -c%s "$input_file")"
  size_after="$(stat -f%z "$output_file" 2>/dev/null || stat -c%s "$output_file")"
  total_before=$((total_before + size_before))
  total_after=$((total_after + size_after))
  echo "$base_name before=$size_before after=$size_after"
done
echo "total before=$total_before after=$total_after"
