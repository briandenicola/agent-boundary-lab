#!/usr/bin/env bash
# Fails if the Azure CLI is invoked from anything that ships.
#
# Deployment is Terraform or SDK only, because that is what the client uses.
# Read-only `az` is fine for ad-hoc diagnosis at a terminal, but it must never
# land in a committed artifact that runs as part of the demo.
#
# Comments are stripped before matching, so prose explaining an az command is
# allowed. docs/ is not scanned at all: it documents az commands on purpose.
set -euo pipefail

SELF="$(basename "${BASH_SOURCE[0]}")"
DIRS=(src services infra tests scripts samples)

EXISTING=()
for d in "${DIRS[@]}"; do
  [ -d "$d" ] && EXISTING+=("$d")
done

if [ ${#EXISTING[@]} -eq 0 ]; then
  echo "no directories to scan"
  exit 0
fi

# grep -n emits `path:line:content`. Stripping from the first '#' to end of
# line drops both whole-line and trailing comments while leaving the
# path:line prefix intact, so reported line numbers stay correct.
HITS=$(grep -rn \
  --include='*.py' \
  --include='*.tf' \
  --include='*.yml' \
  --include='*.yaml' \
  --include='*.sh' \
  --include='Dockerfile*' \
  --exclude="$SELF" \
  -E '(^|[^[:alnum:]_.-])az[[:space:]]+[a-z]' \
  "${EXISTING[@]}" 2>/dev/null | sed 's/#.*$//' |
  grep -E '(^|[^[:alnum:]_.-])az[[:space:]]+[a-z]' || true)

if [ -n "$HITS" ]; then
  echo "Azure CLI invoked from shipped code:"
  echo
  echo "$HITS"
  echo
  echo "Deployment is Terraform or SDK only. If this is prose, move it into a"
  echo "comment. If it is a real invocation, replace it with the SDK."
  exit 1
fi

echo "no az CLI invocations in shipped code"
