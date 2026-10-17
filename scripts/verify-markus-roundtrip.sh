#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 <content-dir> [--drafts-map drafts=articles]" >&2
  exit 2
}

[[ $# -ge 1 ]] || usage
content_dir="$(cd "$1" && pwd)"
shift
drafts_map=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --drafts-map) drafts_map="${2:?--drafts-map needs a value}"; shift 2 ;;
    *) usage ;;
  esac
done

papyrus_cmd="${PAPYRUS_CMD:-poetry run papyrus}"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
original_tree="$work_dir/original"
exported_tree="$work_dir/exported"

mkdir -p "$original_tree"
cp -R "$content_dir"/. "$original_tree"/
if [[ -n "$drafts_map" ]]; then
  rm -rf "$original_tree/${drafts_map%%=*}"
fi

import_args=(ops content import-markus --content-dir "$content_dir")
[[ -n "$drafts_map" ]] && import_args+=(--draft-dirs "$drafts_map")
$papyrus_cmd "${import_args[@]}"
$papyrus_cmd ops content export-published --out "$exported_tree" --clean

if [[ -d "$content_dir/assets" ]]; then
  mkdir -p "$exported_tree/assets"
  cp -Rn "$content_dir/assets"/. "$exported_tree/assets"/
  diff -r "$original_tree/assets" "$exported_tree/assets"
fi
diff -r -x assets -x _papyrus "$original_tree" "$exported_tree"

$papyrus_cmd renderers markus-build --content "$original_tree" --out "$work_dir/dist-original" --theme hackerman
$papyrus_cmd renderers markus-build --content "$exported_tree" --out "$work_dir/dist-exported" --theme hackerman

if diff -r "$work_dir/dist-original" "$work_dir/dist-exported"; then
  echo "ROUNDTRIP OK"
else
  exit 1
fi
