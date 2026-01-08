#!/usr/bin/env bash
set -euo pipefail

# Bumps VERSION file in repo root.
# Format: MAJOR.MINOR (e.g., 1.2 -> 1.3)

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version_file="$root_dir/VERSION"

if [[ ! -f "$version_file" ]]; then
  echo "VERSION file not found at $version_file" >&2
  exit 1
fi

current="$(tr -d ' \t\r\n' < "$version_file")"
if [[ ! "$current" =~ ^([0-9]+)\.([0-9]+)$ ]]; then
  echo "Invalid VERSION format: '$current' (expected MAJOR.MINOR)" >&2
  exit 1
fi

major="${BASH_REMATCH[1]}"
minor="${BASH_REMATCH[2]}"
minor=$((minor + 1))
next="${major}.${minor}"

echo "$next" > "$version_file"
echo "$next"
