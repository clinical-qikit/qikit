#!/usr/bin/env bash
# Print one version's section of CHANGELOG.md, without its heading; fail if it is absent
# or empty. The release workflow uses it for the GitHub Release notes.
#
#   scripts/changelog_section.sh 1.4.0
set -euo pipefail

version=${1:?usage: changelog_section.sh VERSION}
changelog="$(dirname "$0")/../CHANGELOG.md"

section=$(awk -v v="$version" '
  /^## / { on = ($2 == v); next }
  on
' "$changelog" | sed -e '/./,$!d')

if [ -z "$section" ]; then
  echo "CHANGELOG.md has no section for $version" >&2
  exit 1
fi
printf '%s\n' "$section"
