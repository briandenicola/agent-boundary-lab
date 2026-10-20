#!/bin/sh
# Immutable image tags, sourced by the build/deploy Taskfiles:  . scripts/image-tag.sh
#
#   image_tag_new REPO OVERRIDE      Print the tag to build (override, else git-derived).
#   image_tag_record REPO TAG        Persist TAG for REPO after a successful build.
#   image_tag_read REPO OVERRIDE HINT  Print the tag to deploy (override, else recorded).
#
# Git-derived tag: `git rev-parse --short=7 HEAD`, plus `-dirty-<UTC YYYYMMDDHHMMSS>` when the
# working tree has changes. A dirty timestamp differs on every call, which is why the tag is
# recorded at build time (one file per repository) and read back by deploy tasks.
# There is no `latest` fallback anywhere: a missing record is an error naming the build task.

IMAGE_TAG_DIR="${IMAGE_TAG_DIR:-.task/image-tags}"

_image_tag_check() {
  case "$1" in
    latest) echo "Image tag 'latest' is mutable and not allowed. Unset it, or use an immutable tag." >&2; return 1 ;;
  esac
  printf '%s' "$1" | grep -qE '^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$' || {
    echo "Invalid image tag '$1'." >&2; return 1; }
}

image_tag_new() {
  if [ -n "${2:-}" ]; then
    _image_tag_check "$2" || return 1
    printf '%s\n' "$2"
    return 0
  fi
  _sha=$(git rev-parse --short=7 HEAD) || { echo "Cannot derive an image tag: git rev-parse failed." >&2; return 1; }
  if [ -n "$(git status --porcelain)" ]; then
    _sha="${_sha}-dirty-$(date -u +%Y%m%d%H%M%S)"
  fi
  printf '%s\n' "$_sha"
}

image_tag_record() {
  mkdir -p "$IMAGE_TAG_DIR"
  printf '%s\n' "$2" > "$IMAGE_TAG_DIR/$1"
}

image_tag_read() {
  if [ -n "${2:-}" ]; then
    _image_tag_check "$2" || return 1
    printf '%s\n' "$2"
    return 0
  fi
  _file="$IMAGE_TAG_DIR/$1"
  if [ ! -s "$_file" ]; then
    echo "No recorded image tag for $1 and no tag override set. Run '${3:-the matching task build:...}' first." >&2
    return 1
  fi
  _tag=$(head -n1 "$_file")
  _image_tag_check "$_tag" || { echo "Recorded tag in $_file is unusable; rebuild with '${3:-task build:...}'." >&2; return 1; }
  printf '%s\n' "$_tag"
}
